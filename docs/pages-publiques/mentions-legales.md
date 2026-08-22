# Mentions légales

**Service concerné : IA-Niches** — outil web d'analyse de niches de livres sur Amazon.fr, destiné aux auteurs auto-édités.

**Dernière mise à jour : [[A COMPLETER : date de mise en ligne de cette version, format JJ/MM/AAAA]]**
**Adresse du service : [[A COMPLETER : URL exacte du site, ex. https://www.exemple.fr — le service tourne aujourd'hui en local sur 127.0.0.1:8000 par défaut, aucun nom de domaine n'existe dans le code]]**

---

## 1. Éditeur du site

Conformément à l'article 6-III de la loi n° 2004-575 du 21 juin 2004 pour la confiance dans l'économie numérique (LCEN).

> **Ne conservez qu'UN des deux blocs ci-dessous**, selon le statut juridique retenu. Supprimez l'autre entièrement.

### Option A — Personne physique / entrepreneur individuel

| | |
|---|---|
| Nom et prénom | [[A COMPLETER : nom et prénom de l'éditeur]] |
| Statut | [[A COMPLETER : entrepreneur individuel, micro-entrepreneur, autre]] |
| Adresse du siège / domiciliation | [[A COMPLETER : adresse postale complète]] |
| Numéro SIREN / SIRET | [[A COMPLETER : numéro SIREN (9 chiffres) ou SIRET (14 chiffres) de l'entrepreneur individuel, tel qu'il figure sur l'avis de situation INSEE]] |
| Numéro RCS ou RM | [[A COMPLETER : ville et numéro d'immatriculation, ou « non applicable »]] |
| Numéro de TVA intracommunautaire | [[A COMPLETER : numéro de TVA, ou mention « non assujetti à la TVA — article 293 B du CGI » si franchise en base]] |
| Téléphone | [[A COMPLETER : numéro de téléphone joignable]] |
| Adresse électronique de contact | [[A COMPLETER : adresse e-mail de contact]] |

### Option B — Société

| | |
|---|---|
| Dénomination sociale | [[A COMPLETER : dénomination sociale exacte de la société, telle qu'inscrite au RCS]] |
| Forme juridique | [[A COMPLETER : SASU, SARL, EURL, autre]] |
| Capital social | [[A COMPLETER : montant du capital social en euros, tel qu'il figure dans les statuts]] |
| Siège social | [[A COMPLETER : adresse postale complète]] |
| Numéro RCS | [[A COMPLETER : ville et numéro d'immatriculation]] |
| Numéro SIRET | [[A COMPLETER : numéro SIRET de la société (14 chiffres, établissement du siège)]] |
| Numéro de TVA intracommunautaire | [[A COMPLETER : numéro de TVA intracommunautaire (FR + 11 caractères), ou mention « non assujetti à la TVA — article 293 B du CGI » en franchise en base]] |
| Représentant légal | [[A COMPLETER : nom et qualité du représentant]] |
| Téléphone | [[A COMPLETER : numéro de téléphone joignable]] |
| Adresse électronique de contact | [[A COMPLETER : adresse e-mail de contact]] |

> **Bloc optionnel — profession réglementée.** À n'inclure que si l'éditeur fait état de son titre de pharmacien dans la communication commerciale du service. IA-Niches n'est ni une activité pharmaceutique, ni un service de santé : le code n'exécute aucun traitement de cette nature. Si le titre n'est pas mis en avant, supprimez ce bloc.
>
> *Titre professionnel : [[A COMPLETER : intitulé exact du titre professionnel revendiqué, tel que délivré]] — [[A COMPLETER : ordre professionnel de rattachement et numéro d'inscription]] — [[A COMPLETER : règles professionnelles applicables et pays d'octroi du titre]]*

---

## 2. Directeur de la publication

Directeur de la publication au sens de l'article 6-III-1-c de la LCEN :

**[[A COMPLETER : nom et prénom du directeur de la publication — en pratique l'éditeur personne physique, ou le représentant légal de la société]]**

Contact : [[A COMPLETER : adresse e-mail du directeur de la publication]]

---

## 3. Hébergement

Article 6-III-2 de la LCEN.

| | |
|---|---|
| Hébergeur | [[A COMPLETER : dénomination sociale de l'hébergeur]] |
| Adresse | [[A COMPLETER : adresse du siège de l'hébergeur]] |
| Téléphone | [[A COMPLETER : numéro de téléphone de l'hébergeur]] |

> **Point à trancher avant publication.** À ce jour, le code ne contient **aucune configuration d'hébergement** : le serveur démarre par défaut sur `127.0.0.1:8000`, il n'existe ni conteneur, ni fichier de déploiement, ni base de données distante. Les cinq bases de données du service (`comptes.db`, `history.db`, `usage.db`, `jobs.db`, `df-cache.db`) sont des fichiers SQLite **locaux**, situés dans le dossier `99-logs/` de la machine qui exécute le service.
>
> - Si le service reste **auto-hébergé** sur une machine contrôlée par l'éditeur, remplacez ce tableau par la mention correspondante : [[A COMPLETER : « Le service est hébergé sur une infrastructure exploitée directement par l'éditeur, à l'adresse indiquée au §1 » ou l'équivalent retenu]].
> - S'il est déployé chez un prestataire, complétez le tableau **et** vérifiez que la localisation des serveurs figure dans la politique de confidentialité.

---

## 4. Nature du service

IA-Niches est un outil d'aide à la décision éditoriale. Il permet à un auteur d'analyser des niches de livres sur Amazon.fr au moyen de trois moteurs d'analyse : **non-fiction**, **fiction** et **low-content**.

Pour produire ces analyses, le service interroge :

- l'**autocomplétion publique d'Amazon.fr** (`completion.amazon.fr`), afin de mesurer la demande sur des requêtes ;
- les **fiches produit publiques d'Amazon.fr** (`www.amazon.fr/dp/...`), pour lire les classements de vente ;
- l'API **DataForSEO**, prestataire technique fournissant des données de résultats de recherche et de fiches produit Amazon ;
- l'API **Anthropic**, prestataire technique fournissant le modèle de langage qui génère les propositions de niches, les classifications et les analyses éditoriales.

Le détail des données traitées, de leur durée de conservation et des sous-traitants figure dans la **politique de confidentialité** : [[A COMPLETER : lien vers la politique de confidentialité]].

---

## 5. Propriété intellectuelle

Le code source d'IA-Niches, son interface, sa structure, ses textes, ses barèmes d'analyse et sa documentation sont la **propriété exclusive de l'éditeur**. Le logiciel est diffusé sous licence propriétaire : *« Tous droits réservés / All rights reserved »*.

Aucune autorisation n'est accordée pour utiliser, copier, modifier, fusionner, publier, distribuer, sous-licencier ou vendre tout ou partie de ce logiciel sans l'accord écrit préalable et explicite de l'éditeur. Toute reproduction, représentation ou extraction, totale ou partielle, non autorisée est constitutive de contrefaçon au sens des articles L. 335-2 et suivants du code de la propriété intellectuelle.

**Contenus affichés par le service.** Les titres d'ouvrages, prix, notes, nombres d'avis, identifiants ASIN et images éventuellement affichés dans les résultats d'analyse proviennent des pages publiques d'Amazon.fr ou des prestataires de données cités au §4. Ils demeurent la propriété de leurs titulaires respectifs et ne sont affichés qu'à titre de mesure et de citation, dans le cadre de l'analyse demandée par l'utilisateur.

**Résultats produits pour l'utilisateur.** [[A COMPLETER : décision à prendre et à formuler ici — qui détient les droits sur les rapports d'analyse, PDF et listes de mots-clés générés pour un utilisateur, et ce que l'utilisateur peut en faire (usage personnel, usage commercial, revente). Rien dans le code ne tranche cette question, elle relève des conditions générales.]]

---

## 6. Marques citées — absence d'affiliation à Amazon

**IA-Niches n'est ni affilié, ni partenaire, ni approuvé, ni sponsorisé, ni certifié par Amazon**, ni par aucune de ses filiales.

« Amazon », « Amazon.fr », « Kindle », « Kindle Direct Publishing » et « KDP » sont des marques déposées d'Amazon.com, Inc. ou de ses sociétés affiliées. Elles ne sont citées ici et dans l'interface qu'à titre de **référence descriptive nécessaire**, pour indiquer la place de marché sur laquelle porte l'analyse.

Le service interroge des pages et des points d'accès **publics** d'Amazon.fr et affiche des liens vers les fiches produit correspondantes. Il ne se substitue à aucun outil officiel d'Amazon, n'accède à aucun compte vendeur ou auteur, et ne modifie aucune donnée sur Amazon.

**Marques de tiers dans les niches analysées.** Le service comporte un filtre qui écarte, avant analyse, les niches portant une marque, une franchise ou un personnage protégé, et indique à l'utilisateur le motif du rejet. Ce filtre est un garde-fou : il ne constitue **ni une garantie de licéité, ni un avis juridique**. Il appartient à l'utilisateur de vérifier, avant toute publication, que son projet ne porte pas atteinte aux droits de tiers ni aux conditions d'utilisation de la plateforme sur laquelle il publie.

---

## 7. Liens et ressources externes

L'interface affiche des **liens sortants vers les fiches produit d'Amazon.fr** (`https://www.amazon.fr/dp/...`), ouverts dans un nouvel onglet. Ces liens pointent vers un site tiers dont l'éditeur ne contrôle ni le contenu, ni la disponibilité, ni les pratiques. L'éditeur ne saurait être tenu responsable du contenu des sites ainsi atteints.

[[A COMPLETER : indiquer si ces liens sont ou seront des liens d'affiliation Amazon. Dans l'état actuel du code, les liens sont construits à partir du seul identifiant ASIN, sans identifiant d'affiliation ; si un tag d'affiliation est ajouté un jour, la mention d'affiliation devient obligatoire ici et dans l'interface.]]

**Ressource externe chargée par la page.** L'interface charge une feuille de style de polices de caractères depuis le service **Google Fonts** (`fonts.googleapis.com`). C'est la seule ressource externe appelée par la page. Ce chargement implique que l'adresse IP du visiteur est transmise à ce service ; les conséquences en matière de données personnelles sont traitées dans la politique de confidentialité. En l'absence d'accès à ce service, l'interface reste fonctionnelle et retombe sur les polices du système.

**Aucun traceur, aucune régie publicitaire, aucune mesure d'audience tierce** n'est présente dans l'interface.

---

## 8. Cookies

Le service dépose **un seul cookie**, nommé `ia_niches_session`. Il est strictement nécessaire au fonctionnement du service : il porte le jeton de session qui maintient l'utilisateur connecté à son compte.

| Caractéristique | Valeur |
|---|---|
| Nom | `ia_niches_session` |
| Finalité | authentification / maintien de la session |
| Durée de vie | 30 jours |
| Accessible au JavaScript de la page | non (`HttpOnly`) |
| Transmission depuis un autre site | non (`SameSite=Lax`) |
| Transmission réservée aux connexions chiffrées | oui dès lors que le service est servi en HTTPS |

S'agissant d'un cookie strictement nécessaire à la fourniture d'un service expressément demandé par l'utilisateur, il est **dispensé de consentement préalable** au sens de l'article 82 de la loi Informatique et Libertés. Aucun cookie publicitaire, aucun cookie de mesure d'audience et aucun traceur tiers n'est déposé.

---

## 9. Limites du service et responsabilité

IA-Niches est un **outil de mesure et d'aide à la décision**. Il ne garantit ni le succès commercial d'un ouvrage, ni l'exactitude ou l'exhaustivité des données publiées par des tiers.

En particulier :

- les données analysées proviennent de sources externes (Amazon.fr et les prestataires cités au §4) qui peuvent être indisponibles, incomplètes ou modifiées sans préavis ;
- le service est conçu pour **distinguer explicitement une absence de mesure d'un résultat négatif** : lorsqu'une source n'a pas répondu, le rapport le signale (mentions du type « concurrence non mesurée » ou « non mesurable ») au lieu de présenter un rayon comme vide. L'utilisateur est invité à lire ces mentions avant toute décision de publication ;
- les analyses éditoriales, propositions de niches et suggestions de mots-clés sont générées par un modèle de langage : elles constituent des hypothèses à vérifier, non des faits établis ;
- le service ne fournit **aucun conseil juridique, fiscal ni financier**. Il n'engage aucune appréciation sur la conformité d'un projet éditorial aux conditions d'utilisation d'une plateforme de publication.

L'éditeur met en œuvre les moyens raisonnables pour assurer la disponibilité et l'exactitude du service, sans obligation de résultat. Sa responsabilité ne saurait être engagée à raison des décisions éditoriales ou commerciales prises par l'utilisateur sur la base des rapports produits.

[[A COMPLETER : si des conditions générales d'utilisation ou de vente existent, renvoyer ici vers leur lien — elles seules peuvent valablement encadrer les limitations de responsabilité vis-à-vis d'un utilisateur professionnel comme consommateur.]]

---

## 10. Données personnelles

Le traitement des données personnelles (compte, historique d'analyses, consommation, journaux techniques), les durées de conservation, les sous-traitants et les modalités d'exercice des droits sont décrits dans la **politique de confidentialité** : [[A COMPLETER : lien vers la politique de confidentialité]].

Contact pour toute question relative aux données personnelles : [[A COMPLETER : adresse e-mail dédiée, ou reprise de l'adresse de contact du §1]].

> **Point à porter à la connaissance des utilisateurs, et vérifié dans le code :** le service ne comporte **ni réinitialisation de mot de passe, ni vérification d'adresse e-mail, ni suppression de compte en autonomie**. Un mot de passe perdu ne peut pas être réinitialisé depuis l'interface. Toute demande de suppression de compte ou de données doit être adressée à l'éditeur, qui la traite manuellement. [[A COMPLETER : préciser le délai de traitement retenu pour ces demandes]].

---

## 11. Médiation et règlement des litiges

[[A COMPLETER : si le service est proposé à des consommateurs à titre onéreux, l'adhésion à un médiateur de la consommation est obligatoire (article L. 616-1 du code de la consommation) — indiquer ici le nom, l'adresse postale et le site du médiateur retenu. Si le service n'est proposé qu'à des professionnels, supprimer cette section et le dire explicitement dans les conditions générales.]]

Plateforme européenne de règlement en ligne des litiges : [[A COMPLETER : conserver ou retirer cette mention selon le public visé et l'état de la plateforme au moment de la publication]].

---

## 12. Droit applicable et juridiction compétente

Les présentes mentions légales sont soumises au **droit français**.

En cas de litige, et à défaut de résolution amiable, [[A COMPLETER : clause de juridiction retenue — attention : une clause attributive de compétence est inopposable à un consommateur, qui conserve le droit de saisir la juridiction de son domicile]].

---

## 13. Signalement de contenu

Conformément à l'article 6-I-5 de la LCEN, tout contenu manifestement illicite peut être signalé à l'éditeur à l'adresse suivante : [[A COMPLETER : adresse e-mail de signalement]].

<!--
SOURCES VERIFIEES — chaque affirmation factuelle ci-dessus a ete lue dans le code, a la date
du 22/08/2026, sur le depot « IA Niches ». Ce qui ne pouvait pas etre verifie est reste en
placeholder [[A COMPLETER : la consigne de ce qui est attendu]].

TROIS MOTEURS D'ANALYSE (non-fiction, fiction, low-content)
  web/server.py:35-37  — imports de run_scout, run_fiction_scout, run_lowcontent_scout
  01-scripts/scout_master.py, 01-scripts/fiction_master.py, 01-scripts/lowcontent_master.py

SOURCES DE DONNEES EXTERNES APPELEES PAR LE CODE (recensement exhaustif des URL de 01-scripts/*.py)
  01-scripts/amazon_autocomplete.py:10   — https://completion.amazon.fr/api/2017/suggestions
  01-scripts/amazon_product.py:59        — https://www.amazon.fr/dp/ (lecture des fiches)
  01-scripts/search_providers.py:20-21   — https://api.dataforseo.com/v3/merchant/amazon/products
                                            et .../merchant/amazon/asin
  API Anthropic via le SDK officiel, sept points d'instanciation :
    01-scripts/niche_ideator.py:118-119, 01-scripts/niche_verdict.py:125-126,
    01-scripts/fiction_ideator.py:127-128, 01-scripts/fiction_classifier.py:131-132,
    01-scripts/lowcontent_ideator.py:105-106, 01-scripts/lowcontent_verdict.py:115-116,
    01-scripts/kdp_keywords.py:159-160

COOKIE UNIQUE, SES ATTRIBUTS ET SA DUREE
  web/server.py:112       — COOKIE_SESSION = "ia_niches_session"
  web/server.py:233-239   — _poser_session : httponly=True, samesite="lax",
                            secure=_cookie_securise(request), max_age=SESSION_TTL_S
  web/server.py:214-231   — _cookie_securise : drapeau Secure DEDUIT du protocole
                            (X-Forwarded-Proto puis schema d'URL)
  01-scripts/auth.py:48   — SESSION_TTL_S = 30 * 24 * 3600, soit 30 jours

ABSENCE DE TRACEUR ET DE MESURE D'AUDIENCE
  web/index.html — recherche insensible a la casse de
    « gtag | analytics | matomo | <script src | googletagmanager | facebook | pixel | plausible »
    : AUCUNE occurrence.

UNIQUE RESSOURCE EXTERNE CHARGEE PAR LA PAGE
  web/index.html:8 — @import url('https://fonts.googleapis.com/css2?family=Fira+Code...
                     &family=Fira+Sans...'). Seule URL externe du fichier.

LIENS SORTANTS VERS AMAZON.FR AFFICHES DANS L'INTERFACE
  web/index.html:879       — <a href="' + esc(b.url) + '" target="_blank" rel="noopener">
  01-scripts/scoring.py:158 — url=f"https://www.amazon.fr/dp/{o.asin}" (TopBook)
  01-scripts/lowcontent_scoring.py:415 — meme construction
  Aucun parametre d'affiliation n'est ajoute a ces URL dans le code.

FILTRE DES MARQUES / FRANCHISES / PERSONNAGES, AVEC MOTIF DE REJET
  01-scripts/ip_filter.py:1-18 — docstring : « ecarte les niches portant une marque, une
    franchise ou un personnage », « chaque rejet sort avec son MOTIF », filtre applique
    COTE CODE et AVANT l'appel LLM
  data/exclusions_ip.md — liste versionnee des termes exclus

DISTINCTION « ABSENCE DE MESURE » / « RESULTAT NEGATIF »
  01-scripts/scoring.py:111 et :148   — concurrence_mesuree
  01-scripts/models.py:178 et :251    — concurrence_mesuree, defaut pessimiste False
  01-scripts/fiction_scoring.py:160-164 — « Aucun livre scorable -> non_mesurable, JAMAIS mort »
  01-scripts/lowcontent_verdict.py:164 — branche « if not s.concurrence_mesuree »

CINQ BASES SQLITE LOCALES
  web/server.py:65-68 — _JOBS_DB, _USAGE_DB, _HISTORY_DB, _USERS_DB sous 99-logs/
  01-scripts/cache.py:1-3 — df-cache.db, cache cle/valeur PARTAGE entre comptes
  01-scripts/auth.py:149-172 — tables comptes / sessions / tentatives de comptes.db

ABSENCE DE REINITIALISATION DE MOT DE PASSE, DE VERIFICATION D'E-MAIL,
DE SUPPRESSION DE COMPTE
  01-scripts/auth.py — l'API publique de UserStore se limite a : creer_compte, verifier,
    compte, n_comptes, tentatives_recentes, noter_tentative, creer_session,
    session_valide, fermer_session, purger_sessions_expirees. Aucune methode de
    reinitialisation, de verification d'adresse ni de suppression de compte.
  Aucun envoi d'e-mail dans le depot : recherche « smtplib | sendmail » sur *.py et
    *.html — AUCUNE occurrence.

ABSENCE D'HEBERGEMENT CONFIGURE / SERVICE LOCAL PAR DEFAUT
  web/server.py:1058 — uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"),
                       port=int(os.getenv("PORT", "8000")))
  Aucun Dockerfile, aucun fichier de deploiement, aucune base distante dans le depot.

PROPRIETE INTELLECTUELLE DU LOGICIEL
  LICENSE (racine du depot) — « Copyright (c) 2026 Baptiste. Tous droits reserves. /
    All rights reserved. », licence proprietaire, aucune autorisation d'usage, de copie,
    de modification ou de distribution sans accord ecrit prealable.

NON VERIFIABLE DANS LE CODE, DONC LAISSE EN PLACEHOLDER : identite legale et statut de
l'editeur, SIRET/RCS/TVA, adresse postale, telephone, adresses e-mail, directeur de la
publication, hebergeur, nom de domaine, existence de liens d'affiliation, titularite des
droits sur les rapports produits, mediateur de la consommation, clause de juridiction,
delai de traitement des demandes de suppression, date de mise en ligne.
-->
