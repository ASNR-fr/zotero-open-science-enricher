
Enrichissement automatique des notices Zotero via HAL, OpenAlex et Crossref
================================================================================

Auteur       : Justine Ounnough, (https://orcid.org/0009-0001-9815-8206), ASNR/USNR/SEARCH

Approbateur  : Vincent Louison, ASNR/DNUM/SPN/BCN

Organisation : ASNR (Autorité de Sûreté Nucléaire et de Radioprotection)

Version      : 7.4

Date         : 2026-06-16

--------------------------------------------------------------------------------
DESCRIPTION
--------------------------------------------------------------------------------

Ce script Python enrichit automatiquement les notices d'une collection Zotero
en interrogeant trois API externes complémentaires :

  1. HAL (Hyper Articles en Ligne) : archive ouverte française du CNRS.
     Permet de retrouver l'identifiant HAL et l'URL de dépôt de chaque article.

  2. OpenAlex : base bibliographique ouverte et internationale.
     Fournit le statut Open Access, le coût APC, une classification
     disciplinaire hiérarchique, l'éditeur, le financement, l'auteur
     correspondant, le nombre de citations et l'URL OpenAlex.

  3. Crossref : registre officiel des DOI.
     Utilisé en fallback automatique si OpenAlex ne retourne pas
     d'information de financement.

Pour chaque notice, la recherche s'effectue par DOI en priorité,
puis par titre en fallback si aucun DOI n'est disponible.

Les métadonnées ajoutées ou mises à jour dans Zotero pour chaque notice sont :

  - callNumber      Champ cote de Zotero :Coût APC en USD (ex : 2500$) ou "APC non disponible"
  - rights          Statut Open Access (gold, green, closed, hybrid…)
  - archive         Nom de l'archive : "HAL" si la notice y est déposée,
                    "absent de HAL" sinon
  - archiveLocation Identifiant HAL court (ex : hal-00123456),
                    "absent de HAL" si la notice n'est pas dans HAL
  - extra           Citations ; éditeur ; financement ; auteur correspondant ;
                    URL HAL ou "absent de HAL" ; URL OpenAlex  (voir format ci-dessous)
  - tags            Tags disciplinaires OpenAlex (taxonomie + concepts clés)

Les pièces jointes (type attachment) et les notes (type note) sont ignorées
automatiquement.

Tous les champs sont réécrits intégralement à chaque exécution. Si une
information est mise à jour dans OpenAlex ou Crossref (nouvelles citations,
nouveau financement…), elle sera automatiquement rafraîchie au prochain
lancement du script.


A savoir qu'au 24/03/2026, les statuts d'openALEX sont ( https://help.openalex.org/hc/en-us/articles/24347035046295-Open-Access-OA)
•	diamond: Published in a fully OA journal—one that is indexed by the DOAJ or that we have determined to be OA—with no article processing charges (i.e., free for both readers and authors).
•	gold: Published in a fully OA journal.
•	green: Toll-access on the publisher landing page, but there is a free copy in an OA repository.
•	hybrid: Free under an open license in a toll-access journal.
•	bronze: Free to read on the publisher landing page, but without any identifiable license.
•	closed: All other articles.

--------------------------------------------------------------------------------
FORMAT DU CHAMP EXTRA
--------------------------------------------------------------------------------

Le champ extra regroupe sur une seule ligne toutes les métadonnées sans champ
natif dédié dans Zotero. Les entrées sont séparées par " ; " pour permettre
un export Excel avec colonnage automatique (Données → Convertir → Délimité
→ point-virgule).

Exemple :

  Citations: 42 ; Publisher: Elsevier ; Funding: H2020 Euratom (Grant: 633053) ; Corresponding Author: Dupont, Marie (https://orcid.org/0000-0001-xxxx) ; HAL URL: https://hal.science/hal-00123456 ; OpenAlex URL: https://openalex.org/W2345678

Ordre des entrées :
  1. Citations          Nombre de citations (source : OpenAlex)
  2. Publisher          Nom de l'éditeur (source : OpenAlex)
  3. Funding            Financement (source : OpenAlex ou Crossref)
  4. Corresponding Author  Nom et ORCID de l'auteur correspondant (OpenAlex)
  5. HAL URL            URL de la notice HAL, ou "absent de HAL" si introuvable
  6. OpenAlex URL       URL de la fiche OpenAlex

Si une information est introuvable dans toutes les sources interrogées,
une mention explicite est inscrite :

  Funding: non disponible
  Corresponding Author: non disponible
  HAL URL: absent de HAL

Les champs archive et archiveLocation reçoivent également "absent de HAL"
si la notice n'est pas trouvée dans HAL.

--------------------------------------------------------------------------------
STRUCTURE DU SCRIPT
--------------------------------------------------------------------------------

Le script est organisé en 7 blocs numérotés, lisibles dans l'ordre de haut
en bas :

  1. IMPORTS & CONFIGURATION
     Bibliothèques requises et quatre constantes à renseigner avant exécution.

  2. UTILITAIRES ZOTERO
     add_to_extra      : ajoute une entrée dans le champ libre "extra"
                         en évitant les doublons.
     update_with_retry : envoie la mise à jour à Zotero avec backoff
                         exponentiel en cas de rate limit (erreur 429).

  3. HAL
     search_hal_by_doi   : recherche par DOI (prioritaire).
     search_hal_by_title : recherche par titre (fallback si pas de DOI).
     Les deux retournent (hal_id, hal_url) ou (None, None).

  4. OPENALEX
     extract_openalex_taxonomy    : hiérarchie disciplinaire (Domain → Topic).
     extract_openalex_tags        : taxonomy + concepts libres sans doublon.
     extract_funding_openalex     : financements déclarés dans OpenAlex.
     extract_corresponding_author : auteur correspondant avec ORCID si dispo.
     get_openalex_data            : point d'entrée, appelle les quatre
                                    fonctions ci-dessus et retourne un tuple
                                    de 8 valeurs.

  5. CROSSREF  (fallback funding uniquement)
     extract_funding_crossref : interrogé seulement si OpenAlex ne retourne
                                aucun financement. Produit le même format de
                                sortie qu'extract_funding_openalex.

  6. TRAITEMENT D'UNE NOTICE
     _apply_hal, _apply_tags, _apply_funding, _apply_corresponding :
                         sous-fonctions qui écrivent chaque groupe de champs
                         dans la notice Zotero.
     _build_oa_data    : assemble le dict intermédiaire depuis le tuple
                         OpenAlex brut.
     _build_extra      : construit le champ "extra" dans l'ordre défini.
     process_item      : orchestre l'ensemble pour une notice donnée.

  7. POINT D'ENTRÉE
     main() : récupère toutes les notices de la collection et appelle
              process_item sur chacune avec une pause d'1 seconde.

--------------------------------------------------------------------------------
CONTENU DU PACKAGE
--------------------------------------------------------------------------------

  script_zoterobis.py   Script principal d'enrichissement
  check_quality.bat     Script de contrôle qualité du code (pylint)
  README.txt            Ce fichier

--------------------------------------------------------------------------------
PRÉREQUIS
--------------------------------------------------------------------------------

Python 3.10 ou supérieur

Bibliothèques requises :
  pip install requests pyzotero

  requests   2.32.3    
  pyzotero   1.6.11

Connexion internet requise pour accéder aux API HAL, OpenAlex, Crossref
et Zotero.

Un compte Zotero avec :
  - un identifiant de bibliothèque (ZOTERO_LIBRARY_ID)
  - une clé API personnelle avec droits de lecture et écriture (ZOTERO_API_KEY)
  - la clé de la collection cible (COLLECTION_KEY) si applicable

  Ces informations sont disponibles sur : https://www.zotero.org/settings/keys

--------------------------------------------------------------------------------
UTILISATION
--------------------------------------------------------------------------------

1. Renseigner les quatre constantes de configuration en haut du script :

     ZOTERO_LIBRARY_ID    Identifiant numérique de la bibliothèque
     ZOTERO_LIBRARY_TYPE  'group' (bibliothèque partagée) ou 'user'
     ZOTERO_API_KEY       Clé API personnelle Zotero
     COLLECTION_KEY       Clé de la collection à enrichir.
                          Visible dans l'URL de la collection sur zotero.org :
                          https://www.zotero.org/groups/XXXXX/collections/YYYYYY
                          Par défaut, le script traite uniquement cette collection.
                          Pour traiter toute la bibliothèque, voir le point 2 de la                           section UTILISATION.

2. Choisir le mode de récupération des notices dans la fonction main() :

     Par défaut, le script traite uniquement la collection définie par
     COLLECTION_KEY. Pour changer ce comportement, ouvrir script_zoterobis.py,
     descendre jusqu'à la fonction main() (ligne 439) et modifier la ligne all_items :

     Mode collection (défaut, actif) :
       all_items = zot_client.everything(zot_client.collection_items(COLLECTION_KEY))

     Mode bibliothèque complète (traite toutes les notices sans filtre) :
       all_items = zot_client.everything(zot_client.items())

     Pour basculer d'un mode à l'autre, commenter la ligne active avec #
     et décommenter l'autre. COLLECTION_KEY n'est pas utilisée en mode
     bibliothèque complète.

3. Ouvrir un terminal dans le dossier du projet.

4. Lancer le script :

     python script_zoterobis.py

5. Le script récupère d'abord toutes les notices (pagination automatique) :

     📥 Récupération de toutes les notices...
     📚 N notices chargées.

6. Il traite ensuite chaque notice et affiche la progression :

     [1/N] Titre de l'article — notice présente dans HAL
       📎 HAL → archive: HAL | ID: hal-00123456
       🔓 Statut OA : gold
       💰 APC : 2500$
       🏷️  Tags : Physics, Optics, Laser Physics
       📊 Citations : 42
       🏢 Éditeur : Elsevier
       💶 Funding : H2020 Euratom (Grant: 633053)
       ✍️  Corresponding Author: Dupont, Marie (https://orcid.org/0000-0001-xxxx)
       🔗 URL HAL : https://hal.science/hal-00123456
       🔗 URL OpenAlex : https://openalex.org/W2345678
       ✅ Mis à jour dans Zotero

     [2/N] Titre de l'article — notice absente de HAL
       📎 HAL → absent de HAL
       🔓 Statut OA : closed
       💰 APC : APC non disponible
       🏷️  Tags : Physics
       📊 Citations : 5
       🏢 Éditeur : Springer
       💶 Funding : non disponible
       ✍️  Corresponding Author : non disponible
       🔗 URL HAL : absent de HAL
       🔗 URL OpenAlex : https://openalex.org/W9999999
       ✅ Mis à jour dans Zotero

7. Un bilan final est affiché à la fin de l'exécution :

     ✅ Terminé — X notices enrichies sur N traitées.

--------------------------------------------------------------------------------
GESTION DES LIMITES D'API
--------------------------------------------------------------------------------

Le script intègre plusieurs mécanismes de robustesse face aux limites des API :

  Pagination Zotero
    La fonction zot.everything() gère automatiquement la pagination.
    Toutes les notices sont récupérées quel que soit le volume, sans être
    limitées au plafond de 100 résultats par appel de l'API Zotero.

  Rate limit Zotero (erreur 429)
    Chaque mise à jour Zotero est envoyée via update_with_retry(), qui
    détecte les erreurs 429 et attend avant de réessayer, avec un délai
    qui double à chaque tentative :

      Tentative 1 — attente 1s
      Tentative 2 — attente 2s
      Tentative 3 — attente 4s
      Tentative 4 — attente 8s
      Tentative 5 — attente 16s

  Pause entre notices
    Une pause d'1 seconde est appliquée entre chaque notice pour limiter
    la pression sur les API Zotero, HAL, OpenAlex et Crossref.

  Fallback Crossref pour le funding
    Si OpenAlex ne retourne aucune information de financement, le script
    interroge automatiquement Crossref via le DOI avant de conclure
    à l'absence de données.

  Réécriture complète à chaque exécution
    Le champ extra est entièrement recalculé à chaque passage. Aucune
    donnée obsolète ne peut persister d'une exécution à l'autre.

  Éléments ignorés
    Les pièces jointes (type attachment) et les notes (type note) sont
    détectées et ignorées automatiquement, sans provoquer d'erreur.

--------------------------------------------------------------------------------
CONFIGURATION
--------------------------------------------------------------------------------

Avant d'exécuter le script, vérifier et adapter les paramètres suivants
dans le fichier script_zoterobis.py :

  ZOTERO_LIBRARY_ID    Identifiant de la bibliothèque Zotero cible.
                       Visible dans l'URL de la bibliothèque sur zotero.org,
                       ou sur https://www.zotero.org/settings/keys sous la
                       mention "Your userID for use in API calls is XXXXXX".

  ZOTERO_LIBRARY_TYPE  'group' pour une bibliothèque partagée,
                       'user' pour une bibliothèque personnelle.

  ZOTERO_API_KEY       Clé API avec droits lecture + écriture.
                       À générer sur : https://www.zotero.org/settings/keys
                       ⚠️  Ne jamais partager cette clé ni la déposer
                       sur une plateforme publique (GitHub, ChatGPT, etc.).

  COLLECTION_KEY       Clé de la collection à enrichir.
                       Visible dans l'URL de la collection sur zotero.org :
                       https://www.zotero.org/groups/XXXXX/collections/YYYYYY
                       Non utilisée si le script est configuré en mode
                       bibliothèque complète.

--------------------------------------------------------------------------------
REMARQUES
--------------------------------------------------------------------------------

- La recherche par titre (fallback) peut occasionnellement retourner une notice
  incorrecte si le titre est générique ou incomplet. La recherche par DOI
  est toujours préférée et plus fiable.

- Le champ "Corresponding Author" dans OpenAlex est une donnée récente dont
  la couverture est encore incomplète pour les publications anciennes.

- Les données de financement proviennent de Crossref et dépendent de ce que
  les éditeurs ont déclaré à la publication. Elles peuvent être absentes
  pour les articles plus anciens.

- L'API OpenAlex est gratuite et ne nécessite pas de clé d'authentification.
  Documentation officielle : https://docs.openalex.org

- L'API HAL est publique et gratuite.
  Documentation officielle : https://api.archives-ouvertes.fr

- L'API Crossref est publique et gratuite.
  Documentation officielle : https://www.crossref.org/documentation/retrieve-metadata/rest-api/

- En cas d'erreur persistante sur une notice, le script continue sur les
  suivantes sans s'interrompre.

- Le nombre affiché dans "N notices chargées" peut sembler supérieur au
  nombre d'articles visibles dans Zotero. C'est normal : l'API Zotero
  retourne aussi les pièces jointes (PDFs, snapshots) et les notes attachées
  à chaque notice. Ces éléments sont ignorés automatiquement — seules les
  notices articles sont enrichies, d'où l'écart possible entre le total
  affiché et le nombre de notices effectivement traitées.

--------------------------------------------------------------------------------
LICENCE
--------------------------------------------------------------------------------

MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

================================================================================
