# ROADMAP — IA-Niches

Mise à jour : **2026-08-22** · branche `main` · dernier commit lu : `cb6d8b8`.

**La source de vérité de ce fichier est le code** (`01-scripts/` et `web/`), pas la
documentation. `README.md` et `CLAUDE.md` sont tenus à la main : en cas de divergence avec le
code, c'est la doc qu'on corrige. Rien de ce qui suit n'est écrit d'après ces fichiers.

Objectif produit : application vendue en abonnement, pas seulement un outil personnel. Le prix
de **~19 EUR/mois pour ~30 analyses** est une **estimation de cadrage établie en session de
travail** : il n'est écrit dans aucun fichier du dépôt. Le seul chiffre sourçable est
« à 30 analyses/mois la marge est de 88 % » (`01-scripts/usage.py:5`), et c'est lui-même une
projection de plan, pas une mesure. Tout ce document est classé par rapport à cet objectif.

---

## 1. État actuel

### 1.1 Ce qui est livré

Une application web locale mono-page : FastAPI (`web/server.py`, **1 086 lignes, 18 endpoints**
`@app.` comptés dans le fichier) plus un unique `web/index.html` de **118 946 octets** (CSS et JS
inline, zéro build), servi par `GET /`. **48 fichiers `.py`** dans `01-scripts/`. L'hôte et le
port se règlent par `HOST` / `PORT` (défauts inchangés : `127.0.0.1:8000`), lus uniquement sous
`if __name__ == "__main__"`.

**Une seule dépendance réseau tierce, toujours à corriger avant vente** : `index.html:8` importe
deux polices depuis Google Fonts
(`@import url('https://fonts.googleapis.com/css2?family=Fira+Code…')`). Hors ligne, derrière un
pare-feu ou sur un serveur sans sortie Internet, `--mono` / `--sans` retombent sur les fallbacks
système ; et chaque visite déclenche une requête vers un tiers. Vérifié le 2026-08-03 : le fichier
ne contient que **deux** `https://`, celui-ci et le lien `amazon.fr/dp/` des ASIN. Embarquer les
polices en base64, ou assumer les polices système, est un correctif de quelques minutes.

**Trois** moteurs indépendants :

| Moteur | Entrée | Sortie | Coût |
|---|---|---|---|
| Scout **non-fiction** (`scout_master.run_scout`) | une graine libre, ou rien | niches classées, 3 axes pondérés 0,4 / 0,4 / 0,2 | **0,030 $** en local, `BSR_SOURCE=scrape` (**mesuré**) |
| Scout **fiction** (`fiction_master.run_fiction_scout`) | un sous-genre de la taxonomie, contraintes de trio optionnelles | trios sous-genre × tropes × décor, avec saturation | **0,153 $** pour 3 trios (**mesuré**) |
| Scout **low-content** (`lowcontent_master.run_lowcontent_scout`) | une graine, ou un format de la taxonomie | requêtes réelles classées, **4 axes** 0,35 / 0,35 / 0,20 / 0,10 | ~0,05 $ pour 6 niches (**estimé**, aucune mesure datée) |

**Le low-content inverse l'ordre des deux autres, et c'est tout son intérêt.** Ailleurs le LLM
propose et l'autocomplete valide ; ici **l'autocomplete est la source** et le LLM ne fait que
classer des requêtes réelles. La raison est mesurable : en low-content la tête de requête est morte
ou tenue par des éditeurs, l'argent est trois crans plus bas dans la traîne, et un LLM à qui on
demande du long-tail invente aussi la demande qui va avec. Deux axes de plus (rentabilité,
faisabilité) parce que deux questions n'existent pas ailleurs : sous 9,99 € KDP verse 50 % au lieu
de 60 % et le coût d'impression se déduit ensuite ; et un carnet quadrillé ne se produit pas comme
un cahier d'activités illustré.

Sources réelles, et elles seules : API Anthropic (`claude-sonnet-5` par défaut partout, en
tool-use forcé, jamais de parsing de texte libre), DataForSEO (Amazon Products SERP + Amazon
ASIN), l'autocomplete public `completion.amazon.fr` (gratuit) et le scraping direct de
`amazon.fr/dp/{asin}` (gratuit, IP résidentielle uniquement).

Le cœur économique est un **cache SQLite mutualisé entre tous les utilisateurs**
(`99-logs/df-cache.db`), dont les clés portent une empreinte SHA1 automatique du schéma pydantic
— ajouter un champ invalide le cache tout seul. Les **quatre** familles de clés que construit
`cache.py` sont couvertes : `book:`, `bsr:`, `search:`, et `clf:` (qui porte en plus un SHA1 du
prompt système du classifieur — durcir ce prompt n'avait aucun effet sur les livres déjà vus).
Limite assumée : l'empreinte suit les **noms** de champs, pas les types ni la sémantique ; changer
le sens d'un champ sans le renommer exige de vider le cache à la main. **Quatre autres** bases
SQLite locales : `jobs.db`, `usage.db`, `history.db`, et désormais `comptes.db`.

**967 tests collectés, verts** (`python -m pytest`, code de sortie 0, relancé le 2026-08-22), sur
**83 fichiers** `tests/test_*.py`, aucune erreur de collecte. **Tous hors-ligne** : chaque
dépendance lourde (client Anthropic, provider DataForSEO, fetch HTTP, sonde autocomplete) est
injectable par paramètre. Il n'existe **aucun test d'intégration réseau**.

`tests/conftest.py` coupe en plus le SDK et le HTTP sortant avant **chaque** test — écrit après
qu'un test a déclenché un **vrai appel Anthropic facturé** : un test ne doit pas dépendre de la
propreté du code qu'il teste pour rester inoffensif. Il réinitialise aussi les états globaux de
module : le sémaphore `server._CRENEAUX` survivait d'un test à l'autre et produisait des échecs
**intermittents** — six sur une exécution, zéro sur la suivante, sur des sujets sans rapport.

**Un module livré sans aucun chemin d'accès** : `01-scripts/tutoriel_pdf.py` (566 lignes) n'est
importé par aucun module de `01-scripts/` ni de `web/` — `server.py` n'importe que
`positioning_pdf`. C'est un script autonome (`python 01-scripts/tutoriel_pdf.py` régénère les deux
PDF à la racine). Deux tests de `tests/test_tutoriel_pdf.py` lisent `web/server.py` comme source de
vérité : sa constante `ENDPOINTS` porte les routes actuelles, `ENV_VARS` ne cite que des variables
encore lues — mais l'inverse n'est pas vrai : `HOST`, `PORT`, `LOWCONTENT_IDEATOR_MODEL` et
`LOWCONTENT_VERDICT_MODEL` y manquent, et le test ne vérifie que le sens « documenté ⇒ lu ». Ce
n'est pas pour autant « la doc la plus à jour du projet » : ses `PIEGES`, son `GLOSSAIRE` et son
`DEPLOIEMENT` ne sont vérifiés par personne, et `DEPLOIEMENT` dit encore « Utiliser les travaux
asynchrones, pas les endpoints SSE » alors que les endpoints SSE n'existent plus — la consigne
reste juste, sa justification est morte.

### 1.2 Comptes, sécurité, chemin de lancement, et la série d'août — LIVRÉ

Trois chantiers longtemps listés comme bloquants sont **faits**. Ils changent la nature du
produit : il n'est plus mono-utilisateur, et il n'a plus de chemin de dépense hors contrôle
*à l'intérieur de l'application web*.

**Authentification (commit `7ccb4f8`).** `01-scripts/auth.py` (347 lignes) : comptes e-mail +
mot de passe, `hashlib.scrypt` de la bibliothèque standard (**aucune dépendance ajoutée**),
n=2^14 / r=8 / p=1, paramètres écrits dans la base avec chaque empreinte pour pouvoir les durcir
plus tard sans invalider les comptes. Sel par compte. Le jeton de session n'est stocké qu'en
SHA-256, jamais en clair. `verifier()` ne révèle jamais si l'adresse existe — ni par le message,
ni par le **temps de réponse** (dérivation sur un leurre quand le compte est inconnu). Session de
30 jours (`SESSION_TTL_S`), cookie `httponly` + `samesite=lax`.

**Le point structurel : le `user_id` ne vient plus jamais du client.** `utilisateur_courant`
(`web/server.py`) le lit **exclusivement** dans le cookie de session. Quatre endpoints
l'acceptaient auparavant dans le corps ou en paramètre de requête, et le plafond mensuel était
vérifié dessus : il suffisait d'en envoyer un neuf à chaque appel pour dépenser sans limite, et
d'en deviner un autre pour lire l'historique d'autrui. **Aucun endpoint n'expose plus de paramètre
`user_id`.** Sur les 16 endpoints, **12 exigent une session valide** ; les quatre autres sont `GET /`
et les trois portes d'authentification (`inscription`, `connexion`, `deconnexion`).

Le premier compte créé peut reprendre les données accumulées sous `user_id="local"`
(`_adopter_donnees_locales` : `history.db`, `usage.db`, `jobs.db` — **jamais** `df-cache.db`),
mais **seulement s'il le demande** par une case à cocher (`reprendre_donnees_locales`). C'était
automatique : sur une instance exposée, le premier visiteur venu héritait de l'historique de
Baptiste.

**Revue de sécurité adversariale (commits `d443ba8`, `8d37ab8`).** 51 failles confirmées,
7 écartées après réfutation — **chiffres tirés du message de commit `d443ba8`, pas d'un fichier du
dépôt**. Corrigé et vérifiable en code :

- **Toute dépense passe par un contrôle de plafond.** `_verifier_plafond` garde `/api/verdict` et
  `/api/kdp-keywords` ; `POST /api/jobs` fait sa propre vérification avant de créer le job. Les
  trois chemins payants sont couverts (`POST /api/pdf` ne coûte rien : fpdf2 en local).
- **Bornes de volume** : `MAX_IDEES=30`, `MAX_RECHERCHES=20`, `MAX_NICHES_FICTION=20`. Le plafond
  compte des *analyses*, pas des appels payants : sans bornes, une seule « analyse » avec
  `search=9999` déclenchait des milliers de requêtes DataForSEO en ne consommant qu'une unité.
  `_borner` **refuse** (400) au lieu de rogner en silence.
- **Anti-CSRF** : `origine_sure` refuse les requêtes venues d'un autre site, sur `Sec-Fetch-Site`
  (en-tête interdit au script, donc non falsifiable) et sur `Origin`.
- **Cloisonnement des jobs** : `GET /api/jobs/{id}` et `/stream` rendent **404** — et non 403 —
  quand le job appartient à quelqu'un d'autre. Connaître un identifiant suffisait à lire le run
  d'autrui.
- **Limitation des tentatives de connexion** : `MAX_TENTATIVES=8` sur une fenêtre glissante de
  15 minutes, verrou par e-mail, remis à zéro par une connexion réussie ; état distinct traduit en
  429 et non en 401.
- **Politique de mot de passe** : 12 caractères minimum, **128 maximum** (sans ce plafond, un mot
  de passe de plusieurs mégaoctets fait tourner scrypt jusqu'à figer le serveur), liste de mots
  courants refusés. La revue a mesuré que c'est cette liste, et non le réglage de scrypt, qui
  décide si un dictionnaire casse les comptes.
- **Corps malformé → 400, jamais 500** (`_corps_json`, `_identifiants`).
- **`INSCRIPTIONS_OUVERTES` fermé par défaut** : le plafond étant par utilisateur, un compte de
  plus est un plafond neuf. Le **premier** compte passe toujours (amorçage), les suivants exigent
  `INSCRIPTIONS_OUVERTES=1` et sont limités à `MAX_INSCRIPTIONS_PAR_CLIENT=10` par poste et par
  fenêtre.
- **Cookie `Secure` déduit du protocole** (`X-Forwarded-Proto` puis le schéma) au lieu d'un réglage
  qu'on oublie de passer au déploiement. `COOKIE_SECURE=1` peut encore le **forcer**, plus le
  désactiver.

**Un seul chemin de lancement (commits `a30baea` puis `5257323`).** L'interface passe par
`POST /api/jobs` puis se raccroche à `/api/jobs/{id}/stream` (`web/index.html`, `lancerTravail` /
`suivreTravail` / `reprendreTravail`). Le run **survit à la fermeture de l'onglet**, et un
rechargement reprend le travail en cours. Les endpoints de flux direct `GET /api/scout` et
`GET /api/fiction` ont été **supprimés** : deux chemins pour le même travail, dont un seul exercé,
divergent — c'est arrivé aux contraintes de composition fiction, présentes sur le flux direct et
absentes du chemin asynchrone pendant tout un commit. Le sous-genre et les contraintes sont
désormais validés **avant** la création du job (`_valider_volumes`) : 400 immédiate, pas un 202
suivi d'un job en échec.

**Conséquences directes, qui périment trois affirmations de l'ancienne feuille de route :**

1. Le compteur d'usage **est alimenté par le chemin que l'UI emprunte**. Le bandeau « Ce mois-ci :
   N analyse(s) » (`chargerUsage`, `web/index.html`) reflète la consommation réelle. L'ancienne
   mention « reste à 0 quoi que fasse l'utilisateur » est fausse depuis `a30baea`.
2. Le plafond mensuel **est réellement exercé**, puisque `POST /api/jobs` est le seul chemin de
   lancement.
3. **Facturer à l'analyse n'exige plus de travaux préalables côté chemin d'exécution** : le
   backend impute `n_analyses=1` par run, et l'impute **même en cas d'échec** (l'argent est parti,
   le compteur doit le dire). Il reste à décider quoi facturer, pas à instrumenter.

**Plus aucun coût affiché à l'utilisateur (commit `4165efb`).** Tous les montants en dollars ont
disparu de l'interface : barre « Coût de ce run », montant du bandeau mensuel, infobulles, taux de
change, `fmtUsd`, `formatCost` — vérifié le 2026-08-03, zéro occurrence dans `web/index.html`. Le
montant a aussi été retiré des messages de progression de `scout_master` et `fiction_master`, par
où il revenait. **Le backend continue de tout mesurer et de tout imputer** (`CostTracker`,
`jobs.cout`, `usage.db`) : c'est le plafond qui en dépend, et ce sera la base d'une facturation en
jetons ou par abonnement. La **fourchette de prix des livres**, elle, reste affichée : c'est une
donnée de marché, pas un coût. Ajout au même commit d'une pastille « ? » ouvrant un mini-tutoriel
**par onglet**, chacun avec une section « Pièges de lecture ».

**Trois apports métier livrés dans la même série de commits :**

- **Fourchette de prix du rayon** (`6d1f134`) : `scoring.prix_stats` rend min / médiane / max sur
  les seuls organiques ; **un prix absent est exclu, jamais compté zéro** ; `n_prix_connus` dit sur
  combien de livres elle porte. **N'entre dans aucun score** — l'affichage le dit, et une
  fourchette inconnue se dit au lieu d'être remplacée par un zéro.
- **Lecture du contenu des suggestions** (`000947a`) : `niche_validator.lire_suggestions` ne compte
  plus seulement les suggestions, il les lit. `terme_dominant` (un mot hors requête présent dans au
  moins la moitié des suggestions — souvent l'auteur ou le titre qui tient le rayon) et
  `intention_informationnelle` (avis, résumés, citations). Ce sont des **drapeaux affichés, pas des
  termes de score** : les ajouter silencieusement à une note serait un jugement déguisé en mesure.
  « occasion » et « pdf gratuit » ont été volontairement **écartés** des marqueurs, sur décision de
  Baptiste : un acheteur d'occasion reste un acheteur.
- **Compositeur de trio fiction** (`fba99d5`) : `ContraintesTrio` (tropes, décor, texte libre)
  permet à l'auteur de composer son trio ; sans contrainte, le comportement d'origine est inchangé.
  Les contraintes sont **vérifiées côté code après la réponse du modèle**, et une clé hors taxonomie
  **lève** (400) plutôt que d'être ignorée — l'ignorer ferait croire à l'auteur que sa contrainte
  est appliquée. `GET /api/fiction/taxonomie/{sous_genre}` alimente les menus depuis la taxonomie,
  jamais depuis une liste dupliquée en dur côté JS. `contraintes_impossibles` distingue « vos
  contraintes ne se combinent pas » d'un verdict de marché.

**La série du 2026-08-18 au 2026-08-22 — sept chantiers livrés.**

- **Troisième moteur, low-content** (§1.1). Modules : `autocomplete_expand.py`,
  `lowcontent_taxonomy.py` (36 formats, 8 familles), `ip_filter.py`, `lowcontent_ideator.py`,
  `lowcontent_scoring.py`, `lowcontent_master.py`, `lowcontent_verdict.py`, plus quatre fichiers de
  `data/`. `norme: true` (registres, carnets professionnels) déclenche une règle **codée** :
  `lowcontent_verdict` **dégrade un « Go »** si aucune source réglementaire n'est citée — un
  registre incomplet expose l'acheteur, qui est un employeur.
- **Le filtre IP est le seul garde-fou JURIDIQUE du dépôt, et il ne marchait pas.** Mesuré : sur
  198 requêtes portant une marque sous forme mutée, **198 échappaient** au matcher exact. Il tolère
  désormais l'apostrophe typographique (la forme OFFICIELLE de Pat'Patrouille, T'choupi,
  McDonald's), le séparateur libre, le pluriel dans les deux sens et les mots de liaison internes ;
  les bornes de mot restent intactes, c'est elles qui empêchent « om » de sortir de « bonhomme ».
  La même mesure a révélé **cinq faux positifs préexistants** — « cahier de révision BTS MCO » était
  rejeté **en silence**, et un rejet muet ne se remarque pas.
- **Chaîne complète de garde-fous de dépense.** Cinq gardes distincts qui ne protègent PAS de la
  même chose, et les confondre est la source de la moitié des trous trouvés en audit : bornes de
  volume (le VOLUME demandé) · `devis.cout_max_estime` (le pire cas AVANT de lancer, refus en 400) ·
  `CostTracker.verifier` (les dollars PENDANT le run, prédictivement) · `UsageMeter.reserver_analyse`
  (les ANALYSES par utilisateur, sur 30 j glissants, **atomiquement**) · `DEBIT_APPELS_MAX` (les
  appels à la pièce, qui imputent `n_analyses=0` et échappent donc au plafond mensuel).
- **`MAX_NICHES_FICTION` passe de 20 à 11, et c'est DÉRIVÉ, pas choisi** : c'est le plus grand
  nombre de trios dont le devis tient sous `PLAFOND_USD_PAR_RUN`. Au-delà, le run atteignait le
  plafond en route et rendait un rapport **partiel** à quelqu'un qui a payé son plafond entier — ce
  qui se lit comme une arnaque, pas comme une protection. Décision de Baptiste : **réduire le
  maximum offert plutôt qu'afficher un refus après coup.** Le formulaire suit (15 → 11), et des
  tests tiennent ensemble le plafond, les `max` HTML et les presets.
- **Worker séparé** (`worker.py`). Le job survivait à la fermeture de l'onglet, pas au redémarrage
  du serveur : le thread mourait et le job restait `en_cours` pour toujours, l'unité de plafond
  consommée, sans que rien ne le dise. `JobStore.claim_next` est **atomique** (`BEGIN IMMEDIATE`,
  verrou pris AVANT le SELECT) — deux workers sur le même job le paieraient DEUX fois. La file est
  **équitable** : `claim_next` sert celui qui occupe le MOINS de créneaux, l'ancienneté ne départage
  qu'à égalité ; sans ça, un utilisateur qui lance cinq analyses fait attendre les neuf autres, et
  le plafond mensuel ne protège pas de ça (il compte des analyses sur 30 jours, pas des créneaux à
  l'instant t). Les orphelins se trient sur l'**absence de progression**, jamais sur l'âge : un run
  fiction dure 10 à 15 minutes, l'ancienneté tuerait des runs vivants.
- **`marketplace.py`** : source unique de la place de marché, là où la réponse était écrite à
  **neuf endroits**. `MARKETPLACE=com` **LÈVE au démarrage** — six choses du dépôt sont
  irréductiblement françaises et rendraient des **chiffres faux et silencieux** sur une SERP
  américaine, pas une erreur.
- **`notification.py`** : message de fin d'analyse, éteint par défaut, qui ne contient **jamais** le
  résultat, ni un montant, ni l'erreur interne. Branché sur les **deux** exécuteurs — n'en câbler
  qu'un rendrait la notification dépendante de `JOBS_MODE`, et ce serait invisible.
- **Outillage de calibration low-content** (`lowcontent_validation.py`,
  `build_lowcontent_validation_set.py`) — l'outillage seulement, **pas la mesure** (§2.2).
- **Quatre pages publiques en brouillon** (`docs/pages-publiques/`), ancrées sur le code, non
  servies, verrouillées par un test.

**Trois défauts trouvés dans cette série et qui n'auraient pas planté** :

1. **Double facturation ASIN en low-content** : `enrich_asins` puis `resolve_bsrs` sur les mêmes
   ASIN. À la borne serveur, 240 appels pour 120 ASIN, **0,78 $ contre un plafond de 0,60 $, franchi
   en silence**. Le BSR est DÉJÀ dans l'enrichissement.
2. **Un TTL de cache jamais appliqué** : `BOOK_TTL_S` valait 15 j dans `cache.py` (documenté, testé)
   et 7 j dans `fiction_serp_provider.py` (appliqué). Le test surveillait la constante **morte** et
   passait au vert en garantissant le contraire de ce qu'il annonçait.
3. **Un audit qui ignore une décision documentée ne la périme pas.** Signalé : une SERP qui répond
   sans aucun organique déclenche le bonus « moins de 10 concurrents ». C'est exact, la correction a
   été écrite — puis **retirée**, parce qu'un test existant disait déjà : « une SERP qui répond EST
   une mesure ; il ne faut pas punir la mesure sous prétexte de corriger l'absence de mesure ». Le
   risque reste connu et ÉCRIT : une anomalie de parsing produirait le même signal qu'un rayon vide,
   et ce signal est le plus flatteur possible.

### 1.3 Validé EN LIVE (argent réel, réseau réel)

Ces points ne reposent pas sur des mocks. Plusieurs ont été découverts précisément parce qu'un run
réel contredisait les tests.

- Coût d'un scout non-fiction : **0,030 $** en local. Coût d'un scout fiction : **0,153 $** pour
  3 trios.
- Coût d'un verdict éditorial à la pièce : **0,0283 $**. C'est cette mesure qui a fait passer
  `n_verdict` à 0 par défaut — 3 verdicts pesaient 78 % du coût d'un run, pour des analyses non
  lues.
- Coût des 7 mots-clés KDP : **~0,006 $**, mais c'est une **estimation**, sans run daté à l'appui.
  Ce que couvre le chiffre est en revanche exact : le LLM seul, la confirmation par autocomplete
  étant gratuite.
- **Le vivier d'idées a été mesuré, et la mesure infirme l'intuition** (`6d1f134`) : 30 niches sur
  « bien-être », vivier 10 / 20 / 30 → top-4 `demand_score` `[19,12,11,11]` / `[19,15,12,12]` /
  `[19,15,13,12]`. Dans les **trois** cas les 4 niches retenues sont déjà au-dessus du plafond
  `min(demand_score, 10)` du scoring : élargir le vivier change *quelles* niches sont testées,
  jamais leur note sur l'axe demande. Gain mesuré : **nul**. Coût mesuré : **0,0459 $ pour
  30 niches**, soit ~0,0015 $ par niche. Le nombre d'idées a donc cessé d'être un réglage offert à
  l'utilisateur ; seul « Niches à analyser » (`n_search`) reste réglable, défaut 4 dans l'UI.
- Statut des dix lignes de `tutoriel_pdf.COUTS` : chacune porte sa mention, et **trois seulement**
  disent `mesuré` — scout non-fiction local, scout fiction 3 trios, analyse éditoriale. Les sept
  autres disent `calculé`, `extrapolé`, `estime`, `gratuit`, `local`, `lecture`, `one-shot`. Ne
  jamais promouvoir l'une de ces mentions en « mesuré ».
- Le code langue DataForSEO est `fr_FR` et non `fr` ; `location_code = 2250`.
- Parsing BSR : sans le lookahead `(?!\s+\w)`, « n°478 des titres gratuits … 5 en Livres » était
  lu **5** au lieu de **478**. Faux de deux ordres de grandeur, et silencieux.
- L'autocomplete est **préfixe-based** : sonder une expression de longue traîne donnait 0
  confirmation sur 7. D'où la sonde sur les 3 premiers mots (`kdp_keywords.amorce`).
- Budget de poll DataForSEO : à 16 polls (128 s), un ralentissement de la file a effacé un run
  entier — **3 SERP sur 3 expirées**. Porté à 40 polls (~320 s).
- Classifieur de quatrièmes de couverture : Haiku 4.5 mesuré à **42 % d'accord** humain/IA contre
  **80 % requis**. Ne pas rétrograder `FICTION_CLASSIFIER_MODEL`.
- Cas `non_mesurable` observé en réel sur « romance captif huis clos ». Balise « Livre 1 sur 1 »
  qui n'est pas une série, observée sur l'ASIN B0GN4G414V.
- Politique de mot de passe : le même dictionnaire de 10 000 entrées tombe dans les **trois**
  paramétrages de scrypt testés (6,9 / 34 / 60 min). Durcir scrypt sans la liste de mots interdits
  n'aurait sauvé aucun compte. Mesure de la revue de sécurité, portée par `auth.py:61-65`.

### 1.4 Validé en test unitaire SEULEMENT

À traiter comme non éprouvé tant qu'un run réel n'est pas passé dessus.

| Élément | État réel |
|---|---|
| **Toute la couche comptes** (`auth.py`, les 4 endpoints d'authentification, le cloisonnement des jobs) | couverte par `tests/test_auth.py` et les tests serveur, **jamais exposée à un utilisateur autre que Baptiste**, jamais éprouvée contre un attaquant réel ni sur une instance publique. Une revue adversariale n'est pas une mise en production. |
| `POST /api/jobs` et `/api/jobs/{id}/stream` | c'est désormais **le seul chemin de lancement**, et l'UI l'emprunte (vérifié : `web/index.html` appelle `/api/jobs` et `/api/jobs/{id}/stream`). Mais le comportement de reprise après fermeture d'onglet n'a pas de test d'intégration navigateur — il est couvert côté serveur seulement. |
| Plafond `PLAFOND_ANALYSES_MENSUEL` | vérifié sur les trois chemins payants, **jamais déclenché en conditions réelles** (aucun plafond n'est configuré par défaut : non défini = illimité, mais journalisé). |
| `BSR_SOURCE=dataforseo` en conditions serveur | le chiffre de **0,084 $** par scout non-fiction est **calculé, jamais mesuré en production**. |
| Scout fiction à 8 trios (0,409 $) | **extrapolé** depuis les 3 trios réellement mesurés. |
| `ScoredNiche.concurrence_mesuree` | couvert par `tests/test_scoring.py` et `tests/test_history.py`, **jamais éprouvé sur un vrai solde épuisé**. Il coupe tout bonus et tout malus de concurrence quand la SERP n'a pas répondu, écrit « Concurrence non mesurée — à relancer » au lieu d'un verdict, affiche « — / Non mesurée » dans l'UI et exclut la niche de l'historique. Le bonus « place à prendre » (+1,5) reste appliqué : il repose sur le BSR, pas sur la SERP. |
| Delta d'historique | l'écriture est automatique depuis les runners de job, et la **lecture** existe désormais sur les trois onglets. Un delta suppose deux passages espacés sur la même niche : **non observé en conditions réelles à ce jour**. |
| Contraintes de composition fiction | la vérification côté code est testée ; aucun run payant n'a encore été lancé avec des contraintes réelles. |
| **Tout le moteur low-content** | scoring, filtres, arbre d'autocomplete et verdict sont couverts hors ligne. **Aucun run payant complet n'a été lancé**, et surtout **aucun seuil n'est calibré** (§2.2). |
| **`worker.py` et `JOBS_MODE=worker`** | `claim_next`, l'équité de file et la reprise des orphelins sont testés, y compris en concurrence réelle de threads. Jamais exercé avec un second processus sur une vraie charge. |
| **Notification de fin d'analyse** | les deux issues sont testées sur les deux exécuteurs, avec un faux SMTP. **Aucun e-mail réel n'a jamais été envoyé** : aucun serveur SMTP n'est configuré. |
| **`marketplace.py`** | la levée sur `com` est testée. Aucun run n'a jamais tourné sur une autre place de marché — c'est le but. |

Deux fichiers de tests lisent encore `web/index.html` comme du texte (`test_ux_glossaire.py`,
`test_ux_kdp_historique.py`) : ils vérifient la **présence** des chaînes, pas leur
**atteignabilité**. C'est exactement ce qui a laissé passer les boutons morts pendant des semaines.
`tests/js_harness.py` corrige le tir là où ça compte : il extrait les fonctions de rendu **pures**
et les **exécute** avec node.

---

## 2. Ce qui reste avant commercialisation

Classé par ordre de blocage. **Par quoi commencer, en une phrase : §2.2, la calibration du scoring
low-content — c'est le seul chantier qui n'attend que Baptiste, et il tient en une demi-heure de
saisie plus dix minutes de run.**

### 2.1 Ce qui manque encore à la couche comptes

L'authentification est livrée (1.2). Ce qui suit n'est pas du polish : ce sont des trous
d'exploitation qui produiront des demandes de support dès le premier client.

1. **Aucune réinitialisation de mot de passe.** Recherche le 2026-08-03 sur `auth.py`,
   `web/server.py` et `web/index.html` : zéro occurrence de réinitialisation, de jeton de
   récupération ou de « mot de passe oublié ». **Un mot de passe perdu est définitivement perdu** —
   il n'existe aucun chemin, ni pour l'utilisateur, ni pour l'administrateur, pour reprendre la
   main sur un compte. Sur un produit vendu, c'est le premier ticket de support qui arrive, et il
   est aujourd'hui insoluble sans intervention SQL manuelle.
2. **Aucune vérification d'adresse e-mail.** `creer_compte` n'exige qu'une adresse syntaxiquement
   plausible (`_EMAIL`, volontairement permissif : « le seul juge de la validité d'une adresse est
   le serveur de messagerie »). Rien ne prouve que l'adresse appartient à l'inscrit. Conséquences
   à assumer ou à corriger : un compte peut être créé sur l'adresse d'un tiers, et **aucune
   réinitialisation par e-mail ne pourra jamais être branchée sur une adresse non vérifiée** — les
   deux points se traitent ensemble ou pas du tout.
3. **Un envoi d'e-mail existe désormais, mais il ne débloque pas les deux points ci-dessus.**
   `notification.py` sait parler à un serveur SMTP (bibliothèque standard, aucune dépendance
   ajoutée) et envoie un message de fin d'analyse — **éteint par défaut**, il faut
   `NOTIFICATIONS_EMAIL` **et** `SMTP_HOST`. Ce que ça change : la brique technique d'envoi n'est
   plus à écrire. Ce que ça ne change **pas** : aucun serveur SMTP n'est configuré, aucun
   prestataire n'est choisi, **aucun e-mail réel n'a jamais été envoyé**, et le seul envoi codé est
   transactionnel et ne porte **aucun lien d'action**. Brancher une réinitialisation de mot de passe
   dessus supposerait en plus une adresse vérifiée (point 2), donc les deux se traitent ensemble ou
   pas du tout.
4. **Aucune administration des comptes.** Rien ne permet de lister, suspendre ou supprimer un
   compte : `UserStore` n'expose ni listing ni suppression, et aucun endpoint n'irait les chercher.
   Ouvrir les inscriptions se fait par variable d'environnement (`INSCRIPTIONS_OUVERTES`), donc par
   redémarrage du serveur.
5. **`purger_sessions_expirees()` n'a aucun appelant** — vérifié le 2026-08-03 sur `01-scripts/`,
   `web/` **et `tests/`, y compris aucun test**. La table `sessions` ne se purge donc jamais en
   exploitation. Sans conséquence de sécurité (une session expirée est refusée par
   `session_valide`), mais la table croît indéfiniment et la méthode n'est éprouvée nulle part.

### 2.2 Calibrer le scoring low-content — LE chantier suivant

**C'est le seul poste bloquant qui n'attend ni décision produit, ni prestataire, ni argent :
uniquement une demi-heure de saisie de Baptiste et dix minutes de run.**

Les seuils de `data/lowcontent_criteres.json` — `variantes_max=6`, `part_indie_bonne=0.5`,
`redevance_min_bonne=2.0`, et les trois bornes BSR reprises telles quelles du non-fiction — n'ont
été confrontés à **aucun rayon réel**. Le moteur rend des chiffres cohérents entre eux ; rien ne dit
qu'ils correspondent au terrain. Le fichier le dit lui-même dans son en-tête. **Tant que la mesure
n'est pas faite, ne jamais citer ces seuils comme des critères établis.**

**Le protocole inverse celui du classifieur fiction, et c'est le point.** En fiction, Baptiste
CORRIGE des étiquettes que l'IA a produites. Ici il étiquette des requêtes **avant** toute analyse
(`bonne` / `mauvaise` / `morte`) : son jugement est la référence. Si l'IA choisissait les requêtes à
juger, on calibrerait le scoring sur lui-même et la corrélation serait garantie sans rien prouver.
Le CLI applique ça côté code : la liste envoyée au moteur est construite **depuis le classeur**, et
la sonde autocomplete n'y apporte que la mesure `n_enfants` — la faire dépendre du succès d'un appel
réseau ferait basculer le moteur en mode idéation, où le LLM choisirait lui-même les requêtes.

```bash
# Le gabarit est DANS le dépôt : 99-logs/validation-lc.xlsx (8 familles x 4 lignes,
# liste déroulante sur « etiquette »). Il REFUSE d'écraser un classeur déjà étiqueté.
python 01-scripts/build_lowcontent_validation_set.py --gabarit 99-logs/validation-lc.xlsx

# Après remplissage : sonde gratuite -> run payant sur CES requêtes -> rapport JSON
python 01-scripts/build_lowcontent_validation_set.py --xlsx 99-logs/validation-lc.xlsx
```

**Consignes de saisie**, sans lesquelles la mesure ne mesure rien :

- 25-30 requêtes, **minimum 3 par famille** — en deçà, cette famille n'est pas calibrée, elle est
  frôlée, et le rapport le dit. Les seuils sont **globaux**, pas par famille : un jeu à 80 % de
  carnets règle la règle graduée sur ce qui fait un bon rayon de carnets, puis l'applique aux
  coloriages. C'est le vrai risque de sur-ajustement, et il porte sur la règle, pas sur les sujets.
- **environ un tiers de chaque étiquette.** Tout étiqueter « bonne » rend la corrélation
  mathématiquement **indéfinie** (série constante → `spearman` renvoie `None`, pas 0.0) : on aurait
  dépensé 0,20 $ pour ne rien mesurer. Les « morte » sont les plus utiles — elles seules testent le
  second critère de la porte.
- **des cas limites**, où Baptiste hésite entre deux étiquettes : c'est là qu'un scoring se casse.
  Un jeu ne contenant que des évidences ne prouve pas grand-chose.

**Porte, conjointe : Spearman ≥ 0,5 ET aucune requête « morte » en 🟢.** Les deux, pas l'un ou
l'autre : une corrélation honnête qui recommande quand même un rayon mort ferait publier dans le
vide, et ça ne se compense pas par une bonne moyenne d'ensemble.

Quatre décisions de mesure, toutes dans l'esprit de l'invariant 6 : **Spearman et non Pearson** (les
étiquettes sont ordinales, l'écart `morte → mauvaise` n'a aucune raison de valoir l'écart
`mauvaise → bonne`) · **rangs moyens sur les ex aequo** (avec trois étiquettes il y en a partout, un
départage arbitraire mesurerait l'ordre de saisie du fichier) · **les niches à
`concurrence_mesuree=False` sortent du calcul** (leur score a été produit sans bonus ni malus de
SERP, les corréler mesurerait du bruit ; elles sont comptées et annoncées, jamais jetées en silence)
· **les `None` sont exclus des distributions** (moyenner une part indie non mesurée à zéro fausserait
exactement le seuil qu'on cherche à régler).

Le rapport (`99-logs/rapport-calibration-lc.json`) donne en plus **les distributions de signaux par
étiquette** — c'est ce qui permet de régler un seuil au lieu de le déplacer au hasard — et **les
requêtes perdues avant toute dépense**, séparées en deux et jamais additionnées : une « morte »
écartée par le gate gratuit est une bonne nouvelle (le produit l'a rejetée pour zéro centime) ; une
« bonne » écartée là est un **faux négatif que l'utilisateur ne peut PAS voir**, la niche
n'apparaissant nulle part à l'écran. Ce second chiffre est annoncé fort mais **ne ferme pas la
porte** : ajouter un troisième critère de son propre chef ferait passer une intention pour une
règle.

**En cas d'échec, on corrige `data/lowcontent_criteres.json` — jamais le code.** Un seuil qui migre
dans `lowcontent_scoring.py` redevient invisible et non discutable.

> **Ce que la calibration ne fait PAS.** Les 30 requêtes n'entrent jamais dans le produit : elles
> servent une fois, hors ligne, à comparer deux classements. Rien n'est stocké, aucun modèle n'est
> entraîné, la liste n'est conservée nulle part dans le moteur. Ce qui peut changer ensuite, c'est
> au maximum six **nombres** — des seuils sur des signaux mesurés d'un rayon, pas des sujets ni des
> mots-clés. D'où viennent les niches, elles, est complètement séparé : l'arbre d'autocomplete, qui
> ne voit jamais le classeur. On règle la règle graduée, pas la carte du territoire.

**L'ancien contenu de cette section — « l'interface n'expose pas ce que le backend sait faire » —
est FAIT** (2026-08-18), et sa leçon vaut plus que le correctif. Les boutons « Télécharger le PDF »
et « Mots-clés KDP » naissaient dans `verdictBlock(r)`, qui sort par `if(!v) return ''` ; or
`n_verdict=0` partout, donc `verdict` valait **toujours** `None`. Trois endpoints développés,
testés, payés, sans aucun chemin d'accès. `verdictSlot(r)` rend désormais l'un ou l'autre état,
**jamais le vide**, `brancherActions()` est le SEUL site de branchement, et l'historique fiction est
lu. Ce qui l'avait caché : `test_ux_kdp_historique` vérifiait que les chaînes étaient **présentes**
dans le HTML et passait au vert pendant que les boutons étaient morts. **Une chaîne présente dans un
fichier ne prouve rien sur ce qui est cliquable.**

### 2.3 Paiement (Stripe) — non commencé

Aucune ligne de facturation, d'abonnement ou de webhook dans le dépôt : recherche insensible à la
casse de `stripe|webhook|billing|subscription` sur `01-scripts/` et `web/` — **zéro occurrence de
code**, seulement deux commentaires qui mentionnent une facturation « à venir ».

Ce qui a changé : **l'obstacle technique côté exécution est levé**. Le chemin unique
`POST /api/jobs` impute `n_analyses=1` par run, sous un `user_id` issu d'une vraie session, et
l'impute même en cas d'échec. Il reste : choisir le modèle (abonnement ou jetons), brancher un
prestataire, gérer les webhooks d'état d'abonnement, et **ouvrir `INSCRIPTIONS_OUVERTES`** — qui
est fermé précisément parce que rien ne fait payer un nouveau compte aujourd'hui.

**Statut des chiffres de cette section : ESTIMATIONS DE CADRAGE, pas des mesures.** Aucune
transaction n'a jamais eu lieu, donc rien ici n'est mesurable par construction. Les valeurs
~0,50 EUR de frais d'encaissement par abonnement mensuel, marge 88-94 % et seuil de rentabilité à
1-2 clients viennent d'une analyse de session ; **elles ne sont écrites dans aucun fichier du
dépôt**, et le chiffre de frais dépend d'un prestataire qui n'est pas choisi. Le seul chiffre
sourçable dans le code est « à 30 analyses/mois la marge est de 88 % » (`01-scripts/usage.py:5`),
lui-même une projection de plan.

**Correction d'une affirmation fausse qui a circulé ici : « les frais de transaction coûtent plus
cher que DataForSEO + Claude réunis » ne tient pas.** L'arithmétique, au coût de production
(`BSR_SOURCE=dataforseo`, 0,084 $ le scout non-fiction) : 30 analyses = 2,52 $, soit ~2,32 EUR —
**plus de quatre fois** les ~0,50 EUR de frais. Même en local (0,030 $), 30 analyses font 0,90 $ ≈
0,83 EUR, déjà au-dessus. En fiction (0,409 $ pour 8 trios, extrapolé), 30 analyses feraient
12,27 $. L'ancienne formulation ne tenait qu'à très faible usage, et elle s'appuyait sur le chiffre
local — celui-là même que le piège de coût ci-dessous interdit d'employer comme coût de production.
Cohérence de contrôle : 88 % de marge à 30 analyses sur 19 EUR implique ~2,28 EUR de coût
technique, ce qui recoupe le calcul de production. Tous ces montants sont **calculés**, aucun ne
sort d'une facture.

Formulation juste : **le coût technique domine les frais de transaction dès 7 analyses par mois au
coût de production** (0,50 / 0,077 ≈ 6,5 ; le seuil serait de ~19 analyses au coût local, mais
c'est justement le chiffre qu'on s'interdit d'employer pour la production). Les frais de
transaction ne sont déterminants qu'à très faible usage. `CLAUDE.md` §1 porte le même seuil : s'ils
divergent, c'est qu'un des deux n'a pas été recalculé. Le levier de marge reste double et doit être
hiérarchisé par palier d'usage — conversion et réduction du nombre de transactions (annuel plutôt
que mensuel) d'un côté, coût technique par analyse de l'autre. Ce dernier n'est pas « déjà réglé » :
le cache mutualisé et les gates de coût le contiennent, ils ne le suppriment pas.

**Piège de coût à ne jamais oublier en communication commerciale** : les 0,030 $ par scout
non-fiction supposent `BSR_SOURCE=scrape`, qui ne fonctionne que depuis une **IP résidentielle**
(le PC de Baptiste). En production sur serveur, Amazon bloque : il faut `BSR_SOURCE=dataforseo`,
soit **0,084 $ — chiffre CALCULÉ, jamais mesuré en production**. Ne jamais citer le chiffre local
comme coût de production, ni le chiffre serveur comme une mesure.

### 2.4 Incohérences relevées dans le code, à trancher

Petites, mais chacune ment sur quelque chose.

1. **`IDEES_PAR_RUN = 10` est mort.** La constante est définie et longuement justifiée par la
   mesure du vivier (`web/server.py:82`), mais **elle n'est lue nulle part** — grep sur tout le
   dépôt : une seule occurrence, sa définition. Le nombre d'idées réellement utilisé est le
   **défaut de `_run_scout_job` et `_valider_volumes`, soit 12**, l'UI n'envoyant jamais
   `n_ideas`. Le commentaire dit 10, le produit fait 12. Soit brancher la constante, soit corriger
   le commentaire — mais pas laisser les deux.
2. **`.env.example` documente 13 variables, le code en lit 15.** Manquent `HOST` et `PORT`
   (ajoutées par `60e405a`). Le test de `tutoriel_pdf` ne vérifie que le sens « documenté ⇒ lu »,
   pas l'inverse : l'écart est donc indétectable automatiquement.
3. **Les bornes de l'UI et celles du serveur divergent sur la fiction.** Le champ `#fic-n` de
   `web/index.html` a `max="15"`, `MAX_NICHES_FICTION` vaut 20. Sans conséquence de sécurité (le
   serveur est plus permissif que le client), mais l'utilisateur ne peut pas atteindre la borne
   réelle.
4. **`README.md` et `CLAUDE.md` ont été remis à niveau dans le même passage que ce fichier**
   (2026-08-03) : les trois décrivent le même état du code. Ce point listait auparavant un
   README périmé — il ne l'était déjà plus au moment où la phrase a été écrite. En cas de
   divergence future entre les trois, c'est le code qui tranche, jamais le plus récent des
   documents.
5. **Un piège de `tutoriel_pdf.PIEGES` cite encore les « endpoints SSE »** comme alternative à
   éviter. La consigne reste bonne, sa justification n'existe plus.

### 2.5 Actions hors code, en attente

Aucun développement, mais elles bloquent tout run réel.

1. **Régénérer la clé API Anthropic** (`ANTHROPIC_API_KEY`) — exposée en clair dans un chat.
2. **Régénérer les identifiants DataForSEO** (`DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD`) —
   exposés de la même façon. Rappel : `DATAFORSEO_PASSWORD` est le **mot de passe d'API**
   (app.dataforseo.com/api-access), pas celui du compte.
3. **Supprimer et révoquer `SCRAPINGDOG_API_KEY`.** Vérifié le 2026-08-03 : le `.env` de la racine
   porte encore cette entrée, alors que le provider est abandonné depuis la v2 (section 5). C'est
   la seule des quatre clés du fichier qui ne sert plus à rien : elle se retire sans rien casser.
   `.env.example` ne la mentionne déjà plus.
4. **Recharger le solde DataForSEO.** Sans solde : aucune SERP, aucun BSR serveur. Attention à ne
   pas en déduire que les scouts s'arrêtent — c'est faux pour le non-fiction, et l'invariant 6 dit
   pourquoi. Chaque `provider.search()` lève, l'exception est **attrapée** dans
   `scout_master.run_scout`, la niche reste dans la liste avec `search=None`, la phase BSR devient
   un no-op faute d'ASIN, et `score_niche` tourne quand même sur toute la shortlist : le run rend
   une liste complète. Ces niches sortent avec `concurrence_mesuree=False`, sans bonus ni malus de
   concurrence, verdict « Concurrence non mesurée — à relancer », et ne sont pas consignées dans
   l'historique. Seul le scout fiction s'arrête réellement (`return []` quand aucune niche ne
   survit).

Note : `DATAFORSEO_LOGIN` et `DATAFORSEO_PASSWORD` ont pour défaut la chaîne vide
(`DataForSEOProvider.__init__`, `search_providers.py`). La construction du provider **ne casse
pas** ; l'échec ne survient qu'à l'appel HTTP. Un oubli de configuration ne se voit donc pas au
démarrage.

Piège écrit noir sur blanc dans `.env.example` et qu'il faut répéter ici : les identifiants de
modèle valides portent le préfixe `claude-` (`claude-sonnet-5`, `claude-opus-4-8`,
`claude-fable-5`, `claude-haiku-4-5`), et **un identifiant absent de la grille de
`cost_tracker.py` est facturé 0,00 $** — le coût disparaît des rapports sans qu'aucune erreur ne
soit levée. Un coût invisible, pas un coût nul. Ce piège devient plus dangereux depuis `4165efb` :
**l'interface n'affiche plus aucun coût**, donc plus rien à l'écran ne peut alerter sur une
dépense qui a cessé d'être comptée. Le seul témoin est `usage.db`.

---

## 3. Pistes ensuite — NON DÉCIDÉES

Aucune de ces pistes n'est arbitrée. Elles sont listées pour qu'un repreneur ne les redécouvre
pas, pas pour qu'il les implémente.

- **Déploiement.** Aucun Docker, aucun serveur, aucune base partagée : les cinq SQLite sont des
  fichiers locaux dans `99-logs/`. Héberger impose au minimum `BSR_SOURCE=dataforseo` et une
  décision sur le stockage. Deux briques nécessaires existent déjà : `HOST`/`PORT` par variable
  d'environnement, et le drapeau `Secure` du cookie déduit de `X-Forwarded-Proto`.
- **Marketplace anglophone.** `search_providers.py` porte déjà `DEFAULT_LOCATION = 2250` et
  `DEFAULT_LANGUAGE = "fr_FR"` en constantes, et `location_code` / `language_code` sont des
  paramètres du provider. Les exposer ouvrirait `amazon.com` / `.co.uk` / `.de` sans réécrire le
  provider — mais la taxonomie fiction, les prompts et le glossaire sont en français.
- **Le paramètre `signals`** de `run_scout` et de `generate_niches` traverse les signatures jusqu'au
  prompt, mais **aucun appelant ne le remplit** : il vaut toujours `None`. Le mode « à partir de
  rien » se réduit donc à « graine vide ». Le brancher rouvrirait le sujet abandonné en 5.
- **Le champ `NicheCandidate.risques`** est rempli par le LLM (`required` dans le schéma d'outil)
  et propagé nulle part : ni dans `NicheValidation`, ni dans `ScoredNiche`, ni dans le scoring, ni
  dans l'affichage. Champ mort : soit on l'affiche, soit on le retire.
- **L'axe 3 « compatibilité livre »** est figé à la constante `8.0` pour toute niche
  (`compatibilite = 8.0` dans `score_niche`, `scoring.py`). Il ne discrimine rien : le score global
  vaut toujours `demande*0,4 + penetration*0,4 + 1,6`, mécaniquement borné entre 2,4 et 9,6. Soit
  on l'implémente, soit on assume publiquement un score sur 2 axes.
- **Le critère « nombre de résultats Amazon ≤ 10 000 »** n'est pas seulement non codé, il est **non
  mesurable en l'état** : `SearchResult.total_items` vaut `len(items)` de la page de SERP, pas le
  total annoncé par Amazon.
- **Les exclusions métier** (saisonnier, religions à expertise pointue, politique contemporaine,
  borderline TOS, niches d'experts ultra-techniques) n'existent **que comme texte dans le prompt
  système** de l'ideator. Contrairement aux règles KDP, à la taxonomie fiction et désormais aux
  contraintes de composition, elles ne sont **pas doublées côté code** : si le modèle désobéit,
  rien ne le rattrape.
- **Élargir la taxonomie fiction** au-delà des 6 sous-genres de
  `data/fiction_taxonomy_fr_v1.json`. Règle de gouvernance : sous la porte des 80 % d'accord, c'est
  la **taxonomie** qu'on corrige, pas le classifieur.
- **Nettoyage du dépôt — FAIT** (commit `eaa20b2`), plus une piste. Supprimés : `00-config/`,
  `02-veille-hebdo/` (10 fichiers suivis par git), `05-prompts/prompt-directeur-editorial.md` et
  `prompt-critique-strategique.md`, `99-logs/credits-log.csv`, `01-scripts/trends_fr.py`,
  `reddit_fr.py`, `news_fr.py`, et six paquets de `01-scripts/requirements.txt`.
  `03-niches-validees/` et `04-archives/` ont disparu aussi, mais ils étaient **vides et non suivis
  par git** : il n'y avait rien à nettoyer côté dépôt.
  **Nuance sur les six paquets, à ne pas retourner en consigne fausse** : `pytrends`, `praw` et
  `feedparser` étaient bel et bien importés — par `trends_fr.py`, `reddit_fr.py` et `news_fr.py`.
  Ils étaient morts **en cascade**, parce que ces trois modules étaient orphelins, pas parce que
  personne ne les importait. Seuls `pandas`, `beautifulsoup4` et `lxml` avaient réellement zéro
  occurrence. `openpyxl` est **conservé** : `fiction_validation.py` l'importe, et trois fichiers de
  tests aussi (voir section 5).
  Conservés volontairement, à ne pas confondre avec des oublis :
  `99-logs/validation-fiction-2026-07-21.xlsx` et `rapport-validation-classifieur-2026-07-21.json`
  (étalon-or du classifieur, **0,32 $ d'API** — seul chiffre sourçable, `tutoriel_pdf.COUTS`, marqué
  « one-shot » — plus une relecture humaine dont la **durée n'est pas mesurée** : l'« environ une
  heure » ne vient que d'un message de commit, jamais du rapport, qui ne porte que
  `lignes_relues_declarees: 35` sur `livres_du_set: 50`),
  `05-prompts/prompt-onebooklab-template.md` (workflow manuscrit de Baptiste, hors de cet outil),
  `assets/hedgehog.ico`, et `launcher.py` + `IA-Niches.bat` (voir section 4).

---

## 4. En sursis — décision non prise

`01-scripts/launcher.py` et `IA-Niches.bat`. Le `.bat` lance bien `python 01-scripts\launcher.py`,
donc **ce n'est pas du code mort** au sens strict. Son contenu est périmé : son docstring parle
encore d'un « orchestrateur complet (Plan 2) » à venir, et son menu à 3 entrées est antérieur à
l'UI web — il n'expose **ni le scout non-fiction complet, ni la fiction**.

**Le vrai risque n'est pas cosmétique, il est financier — et il est le dernier de son espèce.**
L'entrée 3 du menu s'annonce « Idées de niches par l'IA (clé Anthropic, ~0,02€) » et `_do_niches()`
appelle `generate_niches(seed=seed, n=10)` puis `validate_niches(...)` (vérifié le 2026-08-03 ;
les deux fonctions existent toujours, l'appel n'est donc pas mort à l'import). C'est la première
moitié du scout non-fiction : **un chemin de dépense Anthropic actif, atteignable par un
double-clic sur le raccourci bureau**, sans compte, sans session, sans plafond, sans imputation
d'usage, sans trace dans `usage.db`. Les entrées 1 et 2 (autocomplete, BSR) sont bien gratuites.

Ce point est passé de « une porte parmi d'autres » à **la seule porte restante** : depuis la revue
de sécurité, tous les chemins de dépense de l'application web sont derrière une session et un
contrôle de plafond. Celui-ci ne l'est pas, par construction — c'est un script local qui n'a jamais
vu `web/server.py`.

Trois options, aucune retenue : le mettre à jour, le supprimer avec son `.bat`, ou faire pointer
`IA-Niches.bat` sur `IA-Niches-Web.bat`. **À trancher par Baptiste.**

`assets/hedgehog.ico` : **aucun code ni aucun script du dépôt ne le charge.** Ni `IA-Niches.bat` ni
`IA-Niches-Web.bat` ne mentionnent d'icône, et il n'existe aucun `.lnk` versionné. Les seules
mentions sont documentaires. Le raccourci Windows, s'il existe, vit sur le bureau de Baptiste, hors
dépôt et hors vérification. Ne pas le supprimer sans lui demander.

---

## 5. Abandonné explicitement — ce sont des choix, pas des oublis

Un repreneur qui lit les plans et specs historiques de `docs/superpowers/` croira que ces briques
existent ou restent à faire : ces fichiers datent de la conception et n'ont jamais été révisés.
Toutes ont été **retirées volontairement**.

| Abandonné | Pourquoi |
|---|---|
| **Scrapingdog** (provider Amazon tiers) et tout son appareil : `credits_tracker.py`, `MAX_CREDITS_PER_RUN`, plafond de crédits par run, mode dry-run au premier lancement, retry gaté à 1 tentative / 5 s, compteur « crédits restants sur 1000 » | BSR non fiable et données de concurrence incomplètes. Remplacé par DataForSEO. **Aucun appel** : hors du docstring de `cost_tracker.py`, le mot n'apparaît nulle part dans `01-scripts/` ni `web/`. **Mais la clé n'est pas partie** : `SCRAPINGDOG_API_KEY` figure encore dans le `.env` de la racine — à supprimer et révoquer (§2.5, point 3). Le nom survit aussi dans `docs/superpowers/`, à lire comme des archives de décision, jamais comme l'état du produit. |
| **Rapports Excel `.xlsx`** du scout (onglets Synthèse / Métadonnées / Sponsorisés, mise en forme conditionnelle openpyxl) | Le livrable est une interface web, pas un fichier à ouvrir. Les résultats sortent en JSON (job) et en PDF one-pager. **`openpyxl` reste une dépendance obligatoire** : `fiction_validation.py` l'importe (outil de développement, pas livrable) **et trois fichiers de tests aussi** — `test_fiction_validation.py`, `test_validate_classifier.py`, `test_build_validation_set.py`. Le retirer de `requirements.txt` casserait la collecte de 3 des 46 fichiers de tests. |
| **Google Trends** (`pytrends`), **Reddit** (`praw`), **Google News** (`feedparser`) | Signaux bruyants et mal corrélés à la demande sur Amazon, pour un coût de maintenance élevé. Remplacés par l'ideator LLM + la validation autocomplete gratuite. `trends_fr.py`, `reddit_fr.py` et `news_fr.py` ont été **supprimés** au commit `eaa20b2`, avec les trois paquets qu'ils étaient seuls à importer. Aucun `os.getenv("REDDIT_*")` ne subsiste. Ne pas les recréer : le mode « à partir de rien » se traite par `signals` (section 3), pas par ces trois sources. |
| **Les endpoints de flux direct `GET /api/scout` et `GET /api/fiction`** | **Supprimés au commit `5257323`**, et à ne pas réintroduire. Deux chemins pour le même travail, dont un seul exercé, divergent en silence — c'est arrivé aux contraintes de composition fiction. Par ailleurs leur file de progression mourait avec la requête HTTP : fermer l'onglet perdait un run de 15 minutes, et le fait qu'ils soient des **GET** en faisait une cible de CSRF financière. `queue` n'est plus importé par `web/server.py`. |
| **L'affichage des coûts en dollars dans l'interface** | Retiré au commit `4165efb`. Un montant en dollars par run n'est pas ce qu'achète un auteur, et il se périme à chaque changement de grille. Le backend **mesure et impute toujours tout** : c'est le plafond qui en dépend et ce sera la base de la facturation. Seule la fourchette de prix des **livres** reste affichée : c'est une donnée de marché. |
| **TikTok**, sous toute forme — automatisé comme en saisie manuelle | Creative Center n'est pas scrapable de façon fiable, et une saisie manuelle avant chaque run contredit la promesse du produit : un bouton, un résultat. |
| **Le workflow humain en 5 phases** (validation humaine sur screenshots, analyse éditoriale, pré-production, post-production) | Remplacé par deux scouts automatiques et un verdict à la demande. Le prompt de `niche_verdict.py` interdit explicitement au modèle de réclamer des screenshots : il raisonne sur les métriques du scout. Rien de la phase 4 (sommaire, prompts OneBookLab, briefs de couverture) ni de la phase 5 (quatrième de couverture, fiche AIDA, 15 mots-clés à vérifier) n'existe en code. |
| **Le bonus « +1 zone d'expertise pharmacien »** | Non seulement non codé, mais **délibérément contredit** : le bloc « IMPARTIALITÉ » du prompt système de `niche_ideator.py` impose au modèle de ne privilégier aucun domaine et de ne rien supposer de l'expertise de l'auteur. Cohérent avec un produit vendu à d'autres auteurs qu'un pharmacien. |
| **Le malus « -2 risque KDP TOS »** | Non codé. Le champ `risques` existe mais n'est lu nulle part (voir section 3). |
| **Le réglage du nombre d'idées par l'utilisateur** | Retiré au commit `6d1f134`, **sur mesure et non sur intuition** (§1.3) : élargir le vivier ne change aucune note, seulement quelles niches sont testées, et coûte ~0,0015 $ par niche. À rouvrir uniquement si le plafond `min(demand_score, 10)` du scoring est relevé — c'est lui qui rend le classement aveugle au-delà de 10 suggestions, pas la taille du vivier. |

---

## 6. Invariants à ne pas casser

Rappels courts : le détail vit dans les docstrings du code, qui sont la vraie documentation du
projet.

1. **La saturation est le seul score inversé** (haut = mauvais). Une jauge colorée uniformément
   ferait recommander exactement les pires niches.
2. **`non_mesurable` n'est pas `mort`.** Les deux affichent des zéros et disent le contraire à
   l'utilisateur : l'un invite à re-mesurer, l'autre à écarter la niche.
3. **Un rayon amputé n'est pas un rayon désert** : `FictionShelf.n_echecs > 0` doit rester visible,
   sinon une donnée manquante se lit « place à prendre ».
4. **Une sonde en panne n'est pas un signal absent** : les défauts sont pessimistes
   (`mesure=False`, `autocomplete_score=None`, `concurrence_mesuree=False`), jamais 0. Corollaire :
   **un compteur à zéro faute de mesure ne doit jamais nourrir un bonus.** Même règle pour les
   contraintes de composition : `contraintes_impossibles` dit « vos contraintes ne se combinent
   pas », ce qui n'est pas un verdict de marché. Et un prix absent est **exclu** de la fourchette,
   jamais compté zéro.
5. **Ne jamais passer `niche.rayon` à `est_payant_dans()`** : passer par
   `fiction_taxonomy.label_rayon()`. Le bug a déjà été commis, et il déclare une niche morte sans
   la moindre erreur.
6. **Un échec n'interrompt jamais un run, mais il est toujours compté.** Y compris un job en
   échec : le coût déjà engagé reste imputé.
7. **Instance par appel, jamais à l'import**, pour Cache / JobStore / UsageMeter / NicheHistory /
   UserStore.
8. **`load_dotenv()` avant les imports moteur** dans `web/server.py` : les défauts de modèle sont
   lus à l'import. Cet ordre a l'air d'un détail de style, il est load-bearing.
9. **Pas de `temperature` / `top_p` / `top_k`** sur `claude-sonnet-5` : toute valeur non-défaut
   renvoie une 400.
10. **Le `user_id` vient du cookie de session, jamais du client.** Ne jamais réintroduire un
    paramètre `user_id` sur un endpoint : le plafond mensuel est vérifié dessus, donc un `user_id`
    pilotable par le client est une dépense illimitée.
11. **`user_id` cloisonne `history.py`, `usage.py`, `jobs.py` et `auth.py` — JAMAIS `cache.py`.**
    Le cache de scraping reste mutualisé entre tous les comptes : c'est l'économie principale à
    l'échelle. Y introduire un `user_id` « par cohérence » serait une régression économique
    silencieuse.
12. **Un seul chemin de lancement.** Tout run passe par `POST /api/jobs`. Rouvrir un second chemin,
    c'est rouvrir la divergence qui a déjà rendu les contraintes de composition décoratives sur
    l'un des deux.
