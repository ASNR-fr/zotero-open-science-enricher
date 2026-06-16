"""
Script d'enrichissement automatique des notices Zotero.
Interroge HAL, OpenAlex et Crossref pour compléter les métadonnées telle 
qu'elles apparaissent dans Zotero.
Les champs mis à jour dans Zotero sont listés ci-dessous dans l'ordre
Zotero ; l'ordre d'exécution du script est décrit dans la STRUCTURE :
- callNumber      : APC en $ (champ Zotero détourné, prévu à l'origine
                    pour la cote de bibliothèque — utilisé ici faute de
                    champ natif dédié au coût de publication)
- rights          : statut Open Access
- archive         : "HAL" si la notice est dans HAL, "absent de HAL" sinon
- archiveLocation : identifiant HAL court (hal-xxxxxxx), "absent de HAL" sinon
- extra           : citations ; éditeur ; financement ;
                    auteur correspondant ; URL HAL ou "absent de HAL" ; URL OpenAlex
                    (champ reconstruit entièrement à chaque exécution)
- tags            : taxonomie disciplinaire + concepts clés

──────────────────────────────────────────────────────────────────────
STRUCTURE DU SCRIPT
──────────────────────────────────────────────────────────────────────
 1. IMPORTS & CONFIGURATION
 2. UTILITAIRES ZOTERO          (outils d'écriture utilisés par le bloc 6 :
                                 concaténation dans extra, envoi avec retry)
 3. HAL                         (recherche par DOI puis par titre)
 4. OPENALEX                    (taxonomie, tags, funding, auteur corr.)
 5. CROSSREF                    (fallback funding uniquement)
 6. TRAITEMENT D'UNE NOTICE     (orchestre HAL + OpenAlex + Crossref,
                                 puis écrit le résultat dans Zotero)
 7. POINT D'ENTRÉE              (main)
──────────────────────────────────────────────────────────────────────
"""

# ══════════════════════════════════════════════════════════════════════
# 1. IMPORTS & CONFIGURATION
# ══════════════════════════════════════════════════════════════════════

import time
import urllib.parse

import requests
from pyzotero import zotero

ZOTERO_LIBRARY_ID   = 'xxxx'   # Votre ID Zotero
ZOTERO_LIBRARY_TYPE = 'group'      # 'group' ou 'user'
ZOTERO_API_KEY      = 'xxxx'   # Votre clé API personnelle
COLLECTION_KEY      = 'xxxx'       # Clé de la collection cible

# Séquence vide retournée par get_openalex_data en cas d'échec
# (oa_status, apc, tags, publisher, funding, corresponding, cited_by, openalex_url)
_OPENALEX_EMPTY = (None, None, [], None, [], None, None, None)


# ══════════════════════════════════════════════════════════════════════
# 2. UTILITAIRES ZOTERO
#    Outils d'écriture utilisés par le bloc 6 :
#    - add_to_extra      : concatène une entrée dans le champ "extra"
#                          en le réinitialisant au besoin. Cela se fait
#                          dans _build_extra (bloc 6)
#    - update_with_retry : envoie la notice enrichie à Zotero
#                          avec backoff exponentiel si rate limit (429)
# ══════════════════════════════════════════════════════════════════════

def add_to_extra(current_extra, new_entry):
    """Concatène une entrée dans le champ extra si elle n'y est pas déjà."""
    if new_entry in current_extra:
        return current_extra
    return f"{current_extra} ; {new_entry}" if current_extra else new_entry


def update_with_retry(zot_client, zotero_item, max_retries=5):
    """Envoie la mise à jour à Zotero avec backoff exponentiel si rate limit (429)."""
    for attempt in range(max_retries):
        try:
            zot_client.update_item(zotero_item)
            return True
        except requests.exceptions.HTTPError as err:
            if err.response is not None and err.response.status_code == 429:
                wait = 2 ** attempt
                print(f"  ⏳ Rate limit Zotero (tentative {attempt + 1}/{max_retries}),"
                      f" attente {wait}s...")
                time.sleep(wait)
            else:
                print(f"  ❌ Erreur HTTP inattendue : {err}")
                return False
        except Exception as err:  # pylint: disable=broad-except
            print(f"  ❌ Erreur inattendue lors de la mise à jour : {err}")
            return False
    print("  ❌ Échec après toutes les tentatives (rate limit persistant)")
    return False


# ══════════════════════════════════════════════════════════════════════
# 3. HAL
#    Méthode : on cherche d'abord par DOI (plus fiable),
#    puis par titre si le DOI ne donne rien.
#    Les deux fonctions retournent (hal_id, hal_url) ou (None, None).
# ══════════════════════════════════════════════════════════════════════

def search_hal_by_doi(article_doi):
    """Cherche une notice dans HAL via son DOI. Retourne (hal_id, hal_url) ou (None, None)."""
    url = (
        f'https://api.archives-ouvertes.fr/search/'
        f'?q=doiId_s:"{article_doi}"&fl=uri_s,halId_i&wt=json'
    )
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        docs = response.json().get('response', {}).get('docs', [])
        if docs:
            uri      = docs[0]['uri_s']
            found_id = docs[0].get('halId_i') or uri.split('/')[-1]
            return found_id, uri
    except requests.exceptions.RequestException as err:
        print(f"  Erreur HAL : DOI introuvable {article_doi}: {err}")
    return None, None


def search_hal_by_title(article_title):
    """Cherche une notice dans HAL via son titre. Retourne (hal_id, hal_url) ou (None, None)."""
    if not article_title:
        return None, None
    escaped = urllib.parse.quote(article_title)
    url = (
        f'https://api.archives-ouvertes.fr/search/'
        f'?q=title_t:"{escaped}"&fl=uri_s,halId_i&wt=json'
    )
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        docs = response.json().get('response', {}).get('docs', [])
        if docs:
            uri      = docs[0]['uri_s']
            found_id = docs[0].get('halId_i') or uri.split('/')[-1]
            return found_id, uri
    except requests.exceptions.RequestException as err:
        print(f"  Erreur HAL : titre introuvable '{article_title}': {err}")
    return None, None


# ══════════════════════════════════════════════════════════════════════
# 4. OPENALEX
#    Hiérarchie des fonctions :
#      extract_openalex_taxonomy   → niveau disciplinaire (Domain→Topic)
#      extract_openalex_tags       → taxonomy + concepts libres (appelle taxonomy)
#      extract_funding_openalex    → financements déclarés dans le champ
#                                    grants d'OpenAlex (source indépendante
#                                    de Crossref — voir bloc 5 pour le fallback)
#      extract_corresponding_author→ auteur correspondant avec idORCID quand il existe
#      get_openalex_data           → point d'entrée : appelle tout ce qui précède
#                                    et retourne un tuple de 8 valeurs
# ══════════════════════════════════════════════════════════════════════

def extract_openalex_taxonomy(work):
    """
    Extrait la hiérarchie disciplinaire d'OpenAlex : Domain → Field → Subfield → Topic.
    L'ordre est préservé pour maintenir la cohérence hiérarchique.
    """
    tags = []
    primary_topic = work.get("primary_topic") or {}
    for level in ['domain', 'field', 'subfield', 'topic']:
        name = (primary_topic.get(level) or {}).get('display_name')
        if name and name not in tags:
            tags.append(name)
    return tags


def extract_openalex_tags(work):
    """Fusionne taxonomie disciplinaire et concepts clés OpenAlex sans doublon."""
    tags = extract_openalex_taxonomy(work)
    seen = set(tags)
    for concept in work.get("concepts", [])[:5]:
        name = concept.get('display_name')
        if name and concept.get('score', 0) > 0.5 and name not in seen:
            tags.append(name)
            seen.add(name)
    return tags


def extract_funding_openalex(work):
    """
    Extrait les informations de financement depuis OpenAlex (champ grants).
    Retourne une liste de chaînes formatées, ou liste vide si rien trouvé.
    """
    funding_lines = []
    for award in work.get("grants", []):
        funder   = award.get("funder_display_name") or award.get("funder", "")
        award_id = award.get("award_id") or ""
        if funder:
            line = f"Funding: {funder}"
            if award_id:
                line += f" (Grant: {award_id})"
            funding_lines.append(line)
    return funding_lines


def extract_corresponding_author(work):
    """
    Extrait l'auteur correspondant depuis OpenAlex (champ is_corresponding).
    Retourne une chaîne formatée ou None si non disponible.
    """
    for authorship in work.get("authorships", []):
        if authorship.get("is_corresponding"):
            author = authorship.get("author", {})
            name   = author.get("display_name", "")
            orcid  = author.get("orcid", "")
            if name:
                return (f"Corresponding Author: {name} ({orcid})"
                        if orcid else f"Corresponding Author: {name}")
    return None


def get_openalex_data(article_doi=None, article_title=None):
    """
    Point d'entrée OpenAlex. Récupère :
    statut OA, APC, tags, éditeur, funding, auteur correspondant,
    nombre de citations et URL OpenAlex.
    Recherche par DOI en priorité, par titre en fallback.
    Retourne _OPENALEX_EMPTY en cas d'échec.
    """
    if article_doi:
        url = f"https://api.openalex.org/works/https://doi.org/{article_doi}"
    elif article_title:
        escaped = urllib.parse.quote(article_title)
        url = f"https://api.openalex.org/works?filter=title.search:{escaped}"
    else:
        return _OPENALEX_EMPTY

    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return _OPENALEX_EMPTY

        results = response.json()
        work    = results if article_doi else (results.get("results") or [None])[0]
        if not work:
            return _OPENALEX_EMPTY

        found_oa     = work.get("open_access", {}).get("oa_status")
        apc_paid     = work.get("apc_paid")
        found_apc    = apc_paid.get("value_usd") if isinstance(apc_paid, dict) else None
        publisher    = ((work.get("primary_location") or {})
                        .get("source") or {}).get("host_organization_name")
        cited_by     = work.get("cited_by_count")
        openalex_url = work.get("id")  # URL canonique OpenAlex

        return (found_oa, found_apc, extract_openalex_tags(work),
                publisher, extract_funding_openalex(work),
                extract_corresponding_author(work),
                cited_by, openalex_url)

    except requests.exceptions.RequestException as err:
        print(f"  Erreur OpenAlex : {err}")

    return _OPENALEX_EMPTY


# ══════════════════════════════════════════════════════════════════════
# 5. CROSSREF  (fallback funding uniquement)
#    Interrogé seulement si OpenAlex ne retourne aucun financement.
#    Produit le même format de sortie qu'extract_funding_openalex
#    pour rester interchangeable dans _apply_funding.
# ══════════════════════════════════════════════════════════════════════

def extract_funding_crossref(article_doi):
    """
    Interroge Crossref pour récupérer les informations de financement.
    Utilisé en fallback si OpenAlex ne retourne rien.
    Retourne une liste de chaînes formatées, ou liste vide si rien trouvé.
    """
    if not article_doi:
        return []
    url = f"https://api.crossref.org/works/{urllib.parse.quote(article_doi)}"
    try:
        response = requests.get(url, timeout=10,
                                headers={"User-Agent": "ZoteroEnrichScript/1.0"})
        if response.status_code != 200:
            return []
        funders       = response.json().get("message", {}).get("funder", [])
        funding_lines = []
        for funder in funders:
            name   = funder.get("name", "")
            awards = funder.get("award", [])
            if name:
                if awards:
                    for award in awards:
                        funding_lines.append(f"Funding: {name} (Grant: {award})")
                else:
                    funding_lines.append(f"Funding: {name}")
        return funding_lines
    except requests.exceptions.RequestException as err:
        print(f"  Erreur Crossref : funding introuvable : {err}")
    return []


# ══════════════════════════════════════════════════════════════════════
# 6. TRAITEMENT D'UNE NOTICE
#    process_item orchestre les étapes dans l'ordre, puis écrit dans Zotero :
#      _apply_hal          → champs archive / archiveLocation
#      get_openalex_data   → statut OA, APC, tags, éditeur…
#      _apply_tags         → ajout des tags dans la notice
#      _build_oa_data      → mise en forme du dict intermédiaire
#      _build_extra        → reconstruction complète du champ "extra"
#                            (Citations ; Publisher ; Funding ;
#                             Corresponding ; URLs)
#        └─ _apply_funding      (OpenAlex → Crossref fallback)
#        └─ _apply_corresponding
#      update_with_retry   → envoi final de la notice enrichie à Zotero
# ══════════════════════════════════════════════════════════════════════

def _apply_hal(item_data, doi, title):
    """
    Recherche HAL et met à jour :
    - archive         = "HAL" si trouvé, "absent de HAL" sinon
    - archiveLocation = identifiant HAL court (hal-xxxxxxx) si trouvé,
                        "absent de HAL" sinon
    Retourne (hal_id, hal_url) si trouvé, (None, None) sinon.
    """
    hal_id, hal_url = None, None
    if doi:
        hal_id, hal_url = search_hal_by_doi(doi)
    if not hal_id and title:
        hal_id, hal_url = search_hal_by_title(title)
    if hal_id:
        item_data['archive']         = 'HAL'
        item_data['archiveLocation'] = str(hal_id)
        print(f"  📎 HAL → archive: HAL | ID: {hal_id}")
        return hal_id, hal_url
    item_data['archive']         = 'absent de HAL'
    item_data['archiveLocation'] = 'absent de HAL'
    print("  📎 HAL → absent de HAL")
    return None, None


def _apply_tags(item_data, openalex_tags):
    """Ajoute les nouveaux tags OpenAlex sans doublon. Retourne True si ajout effectué."""
    current_tags = {tag['tag'] for tag in item_data.get('tags', [])}
    new_tags     = [t for t in openalex_tags if t not in current_tags]
    if new_tags:
        item_data.setdefault('tags', []).extend({'tag': t} for t in new_tags)
        print(f"  🏷️  Tags : {', '.join(new_tags)}")
        return True
    return False


def _apply_funding(extra, funding_lines, doi):
    """Résout le funding (OpenAlex → Crossref fallback) et l'écrit dans extra."""
    if not funding_lines and doi:
        print("  🔄 Funding absent dans OpenAlex, tentative Crossref...")
        funding_lines = extract_funding_crossref(doi)
    if funding_lines:
        for line in funding_lines:
            extra = add_to_extra(extra, line)
        print(f"  💶 Funding : {' | '.join(funding_lines)}")
    else:
        extra = add_to_extra(extra, "Funding: non disponible")
        print("  💶 Funding : non disponible")
    return extra


def _apply_corresponding(extra, corresponding):
    """Écrit l'auteur correspondant dans extra."""
    if corresponding:
        print(f"  ✍️  {corresponding}")
        return add_to_extra(extra, corresponding)
    print("  ✍️  Corresponding Author : non disponible")
    return add_to_extra(extra, "Corresponding Author: non disponible")


def _build_oa_data(doi, hal_url, oa_tuple):
    """Assemble le dict oa_data depuis le tuple OpenAlex et les données HAL."""
    _, _, _, publisher, funding_lines, corresponding, cited_by, openalex_url = oa_tuple
    return {
        'publisher': publisher, 'funding_lines': funding_lines,
        'corresponding': corresponding, 'hal_url': hal_url,
        'openalex_url': openalex_url, 'cited_by': cited_by, 'doi': doi,
    }


def _build_extra(oa_data):
    """
    Reconstruit le champ extra entièrement à chaque exécution (extra = '').
    Les entrées sont concaténées par add_to_extra dans l'ordre suivant :
    Citations ; Publisher ; Funding ; Corresponding Author ; URL HAL ; URL OpenAlex
    Séparateur " ; " pour export Excel (Données → Convertir → Délimité → point-virgule).
    oa_data est un dict avec les clés : publisher, funding_lines, corresponding,
    hal_url, openalex_url, cited_by, doi.
    """
    extra = ''  # Réinitialisation complète

    # 1. Citations
    if oa_data['cited_by'] is not None:
        extra = add_to_extra(extra, f"Citations: {oa_data['cited_by']}")
        print(f"  📊 Citations : {oa_data['cited_by']}")

    # 2. Éditeur
    if oa_data['publisher']:
        extra = add_to_extra(extra, f"Publisher: {oa_data['publisher']}")
        print(f"  🏢 Éditeur : {oa_data['publisher']}")

    # 3. Funding (OpenAlex → Crossref fallback)
    extra = _apply_funding(extra, oa_data['funding_lines'], oa_data['doi'])

    # 4. Auteur correspondant
    extra = _apply_corresponding(extra, oa_data['corresponding'])

    # 5. URL HAL
    if oa_data['hal_url']:
        extra = add_to_extra(extra, f"HAL URL: {oa_data['hal_url']}")
        print(f"  🔗 URL HAL : {oa_data['hal_url']}")
    else:
        extra = add_to_extra(extra, "HAL URL: absent de HAL")
        print("  🔗 URL HAL : absent de HAL")

    # 6. URL OpenAlex
    if oa_data['openalex_url']:
        extra = add_to_extra(extra, f"OpenAlex URL: {oa_data['openalex_url']}")
        print(f"  🔗 URL OpenAlex : {oa_data['openalex_url']}")

    return extra


def process_item(zot_client, zotero_item):
    """Enrichit une notice Zotero via HAL, OpenAlex et Crossref."""
    item_data = zotero_item['data']
    title     = item_data.get('title') or None
    doi       = item_data.get('DOI')   or None

    # --- 1. HAL ---
    hal_id, hal_url = _apply_hal(item_data, doi, title)

    # --- 2. OpenAlex ---
    oa_tuple  = get_openalex_data(doi, title)
    oa_status, value_usd, openalex_tags = oa_tuple[0], oa_tuple[1], oa_tuple[2]
    oa_data   = _build_oa_data(doi, hal_url, oa_tuple)

    if oa_status:
        item_data['rights'] = oa_status
        print(f"  🔓 Statut OA : {oa_status}")

    if value_usd is not None:
        item_data['callNumber'] = f"{value_usd}$"
        print(f"  💰 APC : {value_usd}$")
    else:
        item_data['callNumber'] = "APC non disponible"
        print("  💰 APC : non disponible")

    _apply_tags(item_data, openalex_tags)

    # --- 3. Construction du champ extra ---
    item_data['extra'] = _build_extra(oa_data)

    # --- 4. Envoi à Zotero (tous les champs sont réécrits) ---
    if update_with_retry(zot_client, zotero_item):
        print("  ✅ Mis à jour dans Zotero")
        enriched = bool(hal_id) or bool(oa_status) or bool(openalex_tags) or (value_usd is not None)
    return enriched



# ══════════════════════════════════════════════════════════════════════
# 7. POINT D'ENTRÉE
# ══════════════════════════════════════════════════════════════════════

def main():
    """Point d'entrée : récupère les notices et lance l'enrichissement."""
    zot_client = zotero.Zotero(ZOTERO_LIBRARY_ID, ZOTERO_LIBRARY_TYPE, ZOTERO_API_KEY)

    print("📥 Récupération de toutes les notices...")
    # Mode collection (défaut) — traite uniquement la collection définie par COLLECTION_KEY :
    all_items = zot_client.everything(zot_client.collection_items(COLLECTION_KEY))
    # Mode bibliothèque complète — traite toutes les notices sans filtre (décommenter si besoin) :
    # all_items = zot_client.everything(zot_client.items())
    total     = len(all_items)
    print(f"📚 {total} notices chargées.\n")
    # ⚠️  Le total affiché peut sembler supérieur au nombre d'articles visibles
    # dans Zotero. C'est normal : l'API Zotero retourne aussi les pièces jointes
    # (PDFs, snapshots) et les notes attachées à chaque notice. Par exemple,
    # 12 articles avec chacun un PDF et un snapshot représentent déjà 36 éléments.
    # Ces éléments sont ignorés automatiquement ci-dessous — seules les notices
    # articles sont enrichies, d'où l'écart entre "traitées" et "enrichies"
    # dans le bilan final.

    updated_count = 0

    for index, zotero_item in enumerate(all_items, start=1):
        item_data = zotero_item['data']

        if item_data.get('itemType') in {'attachment', 'note'}:
            print(f"[{index}/{total}] Ignoré ({item_data.get('itemType')}) :"
                  f" {item_data.get('title', '[sans titre]')}")
            continue

        label = item_data.get('title') or item_data.get('DOI') or '[sans titre ni DOI]'
        print(f"\n[{index}/{total}] {label}")

        if process_item(zot_client, zotero_item):
            updated_count += 1

        time.sleep(1)

    print(f"\n✅ Terminé — {updated_count} notices enrichies sur {total} traitées.")


if __name__ == "__main__":
    main()
