# IA-Niches

Application web locale qui cherche des niches de livres sur **Amazon.fr** pour les auteurs KDP.
**Trois moteurs indépendants**, et le troisième ne marche pas comme les deux autres :

| Moteur | Comment il trouve les niches |
|---|---|
| **non-fiction** | l'IA propose, l'**autocomplete Amazon** (gratuit) élimine ce que personne ne cherche, **DataForSEO** ne paie la concurrence et les BSR que sur les survivantes. Niche + requête + score sur 3 axes + fourchette de prix du rayon |
| **fiction** | trios sous-genre × tropes × décor, avec **lecture des quatrièmes de couverture** — c'est ce qui permet de mesurer la saturation d'un trope |
| **low-content** | **l'ordre est inversé** : l'autocomplete est la SOURCE, l'IA ne fait que classer des requêtes réelles. En low-content la tête de requête est morte et l'argent est trois crans plus bas dans la traîne ; un LLM à qui on demande du long-tail invente aussi la demande qui va avec (§5) |

Sortie : une liste de niches classées, plus des fonctions à la demande (verdict éditorial, dossier
de niche en 3 pages, PDF, mots-clés KDP, historique).

L'accès se fait par **compte e-mail + mot de passe** (§3). Tout se lance par un **travail
asynchrone** : le run survit à la fermeture de l'onglet.

> **La source de vérité de ce projet est le code** (`01-scripts/`, `web/`). `CLAUDE.md` et
> `ROADMAP.md` décrivent la v2 et sont tenus à la main : en cas de divergence, le code a raison
> et c'est la doc qu'on corrige. **Ne pas supprimer `CLAUDE.md`** : **24 lignes du code vivant**
> le citent comme normatif, réparties sur **19 fichiers**
> (`grep -rn CLAUDE 01-scripts web tests --include=*.py --include=*.html`, comptage refait le
> 2026-08-22).
> Les dossiers v1 ont disparu, mais **pas de la même façon** : `00-config/` et `02-veille-hebdo/`
> ont été supprimés par le commit `eaa20b2` ; `03-niches-validees/` et `04-archives/` étaient
> **vides et n'ont jamais été versionnés** — git ne suit pas les dossiers vides, aucun commit ne
> peut donc les avoir supprimés.

---

## 1. Sécurité — à lire avant tout

- Les clés API (**Anthropic**, **DataForSEO**) vivent **uniquement dans `.env`**, exclu de git
  (`.gitignore` ligne 4 ; la ligne 5 exclut aussi `.env.*`, la ligne 6 ré-inclut `.env.example`).
  Ne jamais coller une clé dans un fichier suivi, ni dans un test.
- Le code lit **15** variables d'environnement (`os.getenv`, seul mécanisme de lecture : aucun
  `os.environ` dans `01-scripts/` ni `web/`). `.env.example` en documente **13** — il lui manque
  `HOST` et `PORT`, et **son propre en-tête annonce encore « ONZE »** : commentaire périmé, à
  corriger.
- Les bases SQLite d'exécution (`99-logs/*.db`) sont ignorées par git (`.gitignore` lignes 47-54,
  motif `99-logs/*.db` qui couvre aussi `comptes.db`) : elles contiennent des données d'usage
  réelles, le cache payant, **et les empreintes de mots de passe**.
- **Ce qui n'est jamais stocké en clair** (`01-scripts/auth.py`) : le mot de passe (seulement
  `hashlib.scrypt` avec un sel par compte, bibliothèque standard, aucune dépendance ajoutée) et le
  jeton de session (seulement son SHA-256 — sans quoi lire la base suffirait à voler une session).
- **Avant toute mise en vente ou passage du dépôt en public** :
  1. **Régénérer la clé Anthropic** (console.anthropic.com) et **le mot de passe d'API DataForSEO**
     (app.dataforseo.com/api-access). Elles ont vécu en local sur un poste de travail.
  2. **Supprimer et révoquer `SCRAPINGDOG_API_KEY`** du `.env` de la racine : le produit
     n'appelle plus ce service depuis la v2. Elle n'a jamais fuité par le dépôt (`.env` n'a jamais
     été versionné), mais une clé tierce qui traîne se révoque.
  3. Envisager une réécriture d'historique (`git filter-repo`) si une clé a transité un jour dans
     un commit. Les fichiers supprimés en `eaa20b2` restent lisibles dans l'historique git.
  4. Détail sans risque : les lignes 32-34 de `.gitignore` commentent encore des chemins qui
     n'existent plus (`99-logs/credits-log.csv`, `02-veille-hebdo/…`).
- **Ce que la revue de sécurité adversariale du 2026-08-03 a fermé** (commits `d443ba8`,
  `8d37ab8`), à ne pas rouvrir par mégarde :
  - le `user_id` **ne vient plus jamais du client**. Quatre endpoints l'acceptaient dans le corps
    ou en paramètre, et le plafond mensuel était vérifié dessus : en envoyer un neuf à chaque appel
    suffisait à dépenser sans limite, et en deviner un autre à lire l'historique d'autrui. Il vient
    désormais exclusivement du cookie de session (`utilisateur_courant`, `web/server.py:246`).
    **Ne jamais réintroduire un paramètre `user_id` sur un endpoint** ;
  - **toute dépense vérifie le plafond avant de dépenser** — `POST /api/jobs` en ligne
    (`web/server.py:516-520`), `POST /api/verdict` et `POST /api/kdp-keywords` via
    `_verifier_plafond` (`:188`). Auparavant `UsageMeter.autorise` n'avait qu'**un seul** site
    d'appel, celui que l'interface n'empruntait pas ;
  - **bornes sur les paramètres de volume** : `MAX_IDEES=30`, `MAX_RECHERCHES=20`,
    `MAX_NICHES_FICTION=20`. Le plafond compte des *analyses*, pas des appels payants : sans
    bornes, une seule « analyse » avec `search=9999` déclenchait des milliers de requêtes
    DataForSEO. `_borner` **refuse en 400** plutôt que de rogner en silence ;
  - **garde anti-CSRF `origine_sure`** (`Sec-Fetch-Site` + `Origin`) sur les trois endpoints qui
    créent quelque chose : inscription, connexion, `POST /api/jobs` ;
  - **cloisonnement des jobs** : connaître un identifiant suffisait à lire le run d'autrui.
    `GET /api/jobs/{id}` et son flux rendent **404** — et non 403 — sur le job d'un autre compte ;
  - **limitation des tentatives de connexion** (`MAX_TENTATIVES=8` sur `FENETRE_TENTATIVES_S`
    = 15 min) et des inscriptions par client (`MAX_INSCRIPTIONS_PAR_CLIENT=10`) ;
  - **politique de mot de passe** : 12 caractères minimum, 128 maximum (au-delà, scrypt devient
    lui-même un déni de service), liste de mots courants refusés ;
  - **corps malformé → 400**, jamais 500 (`_corps_json`, `_identifiants`) ;
  - **`INSCRIPTIONS_OUVERTES` fermé par défaut** (§3) ;
  - **cookie `Secure` déduit du protocole** (`X-Forwarded-Proto` puis le schéma) au lieu d'un
    réglage qu'on oublie de passer au déploiement.
- Le serveur écoute `127.0.0.1:8000` par défaut. Il y a maintenant une authentification, mais
  **aucun HTTPS intégré, aucun déploiement, aucune base partagée** : une exposition publique
  suppose au minimum un proxy TLS devant.

---

## 2. Installation

```bash
pip install -r 01-scripts/requirements.txt
cp .env.example .env       # puis remplir (voir tableau ci-dessous)
```

Python 3.10+ (le code utilise `int | None`). Aucun build front, aucun Docker, aucune base externe :
tout est local — **à une exception près**, l'import de polices Google dans `web/index.html` (§4).

`requirements.txt` ne contient que des paquets **réellement importés** : `requests`,
`python-dotenv`, `pydantic`, `anthropic`, `fastapi`, `uvicorn`, `fpdf2`, `openpyxl`, `pytest`.
**L'authentification n'a ajouté aucune dépendance** : `hashlib.scrypt`, `hmac`, `secrets` et
`sqlite3` sont dans la bibliothèque standard.

Six paquets de la v1 ont été retirés par le commit `eaa20b2`, pour deux raisons distinctes qu'il ne
faut pas confondre : `pytrends`, `praw` et `feedparser` étaient bel et bien importés — par
`trends_fr.py` / `reddit_fr.py` / `news_fr.py`, supprimés dans le même commit, donc morts **en
cascade** ; `pandas`, `beautifulsoup4` et `lxml` n'avaient, eux, **aucune occurrence** (le parsing
des fiches Amazon se fait en expressions régulières pures, cf. `amazon_product.py`). `openpyxl`
est **conservé** : importé par `01-scripts/fiction_validation.py` **et** trois fichiers de tests
(`test_build_validation_set.py`, `test_fiction_validation.py`, `test_validate_classifier.py`).

### Variables d'environnement — les 34 lues par le code

`.env.example` les documente **toutes** depuis le 2026-09-07. Deux tests
(`tests/test_tutoriel_pdf.py`) tiennent l'invariant, mais dans un seul sens —
**documenté ⇒ lu**. Rien ne vérifie l'inverse : la couverture complète est tenue à la
main, et peut se dégrader au prochain ajout sans qu'aucun test ne le dise.

**Obligatoires**

| Variable | Défaut | Rôle |
|---|---|---|
| `ANTHROPIC_API_KEY` | aucun (`None`) | Toute la partie IA : les deux ideators, le classifieur de quatrièmes, le verdict, les mots-clés KDP. |
| `DATAFORSEO_LOGIN` | `""` | Compte DataForSEO (SERP Amazon + fiches ASIN). |
| `DATAFORSEO_PASSWORD` | `""` | **Mot de passe d'API** (app.dataforseo.com/api-access), **pas** celui du compte web. |

Les défauts vides ne font pas échouer le démarrage : l'échec survient au premier appel HTTP.

**Comptes et sécurité**

| Variable | Défaut | Rôle |
|---|---|---|
| `INSCRIPTIONS_OUVERTES` | **non défini = fermé** | Autorise la création de comptes **au-delà du premier**. Le plafond mensuel étant *par utilisateur*, un compte de plus est un plafond neuf : laisser l'inscription libre revient à offrir une dépense illimitée à un anonyme. Valeurs acceptées : `1`, `true`, `yes`, `oui`. **Le premier compte passe toujours**, sinon une installation neuve serait inutilisable. |
| `COOKIE_SECURE` | non défini | **Ne peut plus que FORCER** le drapeau `Secure`, jamais le désactiver. Normalement inutile : le drapeau est **déduit** de `X-Forwarded-Proto` puis du schéma de la requête. À ne renseigner que derrière un proxy TLS qui n'annonce pas le protocole. |
| `PLAFOND_ANALYSES_MENSUEL` | non défini = illimité | Plafond glissant sur 30 jours **par utilisateur**. Vérifié par **tous** les chemins payants depuis `d443ba8`. Valeur non entière → illimité, silencieusement. |

**Coût et infrastructure**

| Variable | Défaut | Rôle |
|---|---|---|
| `BSR_SOURCE` | `scrape` | `scrape` = fiche amazon.fr grattée gratuitement depuis l'IP locale. `dataforseo` = batché, payant, fiable en datacenter. Toute autre valeur lève `ValueError`. |
| `DATAFORSEO_PRIORITY` | `2` | `2` = file rapide (~1-4 min, 0,003 $/appel). `1` = file standard, moitié prix, jusqu'à ~45 min. Valeur invalide → avertissement + repli sur 2. |
| `HOST` | **déduit** : `0.0.0.0` si `APP_ENV=prod`, `127.0.0.1` sinon | Une valeur explicite prime toujours. Lue par le bloc `__main__` de `web/server.py` uniquement. En conteneur, écouter la boucle locale rend le service injoignable **sans la moindre erreur** (CLAUDE.md §2.17). |
| `PORT` | `8000` | Idem. Valeur non entière → repli silencieux sur 8000. Les plateformes imposent le leur. |
| `DATA_DIR` | `99-logs/` | Où vivent les cinq bases. **EXIGÉE dès `APP_ENV=prod`** : sans volume persistant, les bases disparaissent à chaque mise en ligne, sans aucun signal — le serveur refuse donc de démarrer (CLAUDE.md §2.17). |

**Choix des modèles** — toutes valent `claude-sonnet-5` par défaut.

| Variable | Rôle |
|---|---|
| `IDEATOR_MODEL` | Ideator non-fiction. |
| `VERDICT_MODEL` | Verdict éditorial. |
| `KDP_KEYWORDS_MODEL` | Mots-clés backend KDP. |
| `FICTION_IDEATOR_MODEL` | Ideator fiction (trios). |
| `FICTION_CLASSIFIER_MODEL` | Classifieur de quatrièmes. **Ne pas rétrograder** : Haiku 4.5 mesuré à 42 % d'accord contre 80 % requis. |
| `LOWCONTENT_IDEATOR_MODEL` | Classement des requêtes low-content. |
| `LOWCONTENT_VERDICT_MODEL` | Verdict low-content. |

**Charge, dépense et exécution**

| Variable | Défaut | Rôle |
|---|---|---|
| `PLAFOND_USD_PAR_RUN` | `0.60` | Plafond **prédictif** : `verifier(cout_prevu)` refuse AVANT de dépenser, il n'interrompt pas au milieu. Combiné au devis préalable (`devis.py`), c'est ce qui empêche un rapport partiel facturé au plafond entier. |
| `RUNS_SIMULTANES_MAX` | `5` | Créneaux d'exécution simultanés. Plafond de **charge**, pas de dépense. Avant lui, le serveur lançait un fil par job sans aucune limite. |
| `DEBIT_APPELS_MAX` | `40`/h/utilisateur | Limite les appels **à la pièce** (`/api/verdict`, `/api/kdp-keywords`), qui imputent `n_analyses=0` et échappent donc au plafond mensuel. **Garde-fou, pas un palier tarifaire** : le modèle économique n'étant pas fixé, la valeur est ancrée sur ce que le produit sait faire. |
| `JOBS_MODE` | `thread` | `worker` fait que `POST /api/jobs` **empile seulement**. Sans ce garde, serveur ET worker exécuteraient le même job : deux fois les SERP, deux fois les tokens. |
| `WORKER_CONCURRENCE` | `5` | Taille du pool de `worker.py`. |
| `WORKER_REPOS_S` | `2.0` | Attente entre deux `claim_next` quand la file est vide. |
| `APP_ENV` | non défini | `prod` est LA variable d'exposition : `_verifier_config_prod` (exige `BSR_SOURCE=dataforseo`), `DATA_DIR` exigée, écoute sur `0.0.0.0`. **Refus de démarrer** sur une configuration dangereuse, jamais un défaut silencieux. |
| `MARKETPLACE` | `fr` | Toute autre valeur **LÈVE au démarrage**, `com` compris. Voir §10. |

**Message de fin d'analyse** — éteint par défaut, il faut `NOTIFICATIONS_EMAIL` **et** `SMTP_HOST`.

| Variable | Défaut | Rôle |
|---|---|---|
| `NOTIFICATIONS_EMAIL` | non défini = éteint | Prévient l'auteur quand son analyse est finie. Une configuration à moitié faite n'envoie pas « au mieux » : elle n'envoie pas. |
| `SMTP_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_FROM` / `_TLS` | port `587`, TLS actif | `SMTP_FROM` retombe sur `SMTP_USER`. Le message ne contient **jamais** le résultat de l'analyse ni le moindre montant. |
| `BASE_URL` | non définie | Sert **uniquement** au lien du message. Absente, le message part sans lien plutôt qu'avec un lien mort — rien dans le code ne connaît le nom de domaine. |

**Piège de facturation** : un identifiant de modèle absent de la grille de `cost_tracker.py` est
facturé **0,00 $** — un coût invisible, pas un coût nul. Les quatre identifiants tarifés portent
le préfixe `claude-` : `claude-sonnet-5` (2 $/10 $ par million de tokens in/out en tarif intro
**jusqu'au 31/08/2026**, puis 3 $/15 $ — la bascule est automatique, dans `llm_cost_usd`),
`claude-opus-4-8` (5 $/25 $), `claude-fable-5` (10 $/50 $), `claude-haiku-4-5` (1 $/5 $).

**Piège de démarrage** : les défauts de modèle sont lus **à l'import**, donc avant le
`load_dotenv()` que `scout_master.py` appelle à l'intérieur de `run_scout()`. Un `IDEATOR_MODEL`
défini uniquement dans `.env` est **ignoré en ligne de commande**. `web/server.py` y échappe parce
qu'il appelle `load_dotenv` (ligne 32) **avant** ses imports moteur — cet ordre est load-bearing,
ne pas le « ranger ».

---

## 3. Premier démarrage

1. **Lancer le serveur.**

   ```bash
   python web/server.py          # ou double-clic sur IA-Niches-Web.bat
   ```

   Puis ouvrir `http://127.0.0.1:8000`.

2. **Créer le premier compte.** L'interface s'ouvre sur un **écran de connexion** qui occulte
   l'application : hors `GET /` et les trois POST d'authentification (`inscription`, `connexion`, `deconnexion`), tous les endpoints rendent 401 sans session — `GET /api/auth/moi` compris, donc
   afficher les boutons derrière ne montrerait que des erreurs. Cliquer sur « Créer un compte », saisir une
   adresse e-mail et un mot de passe d'**au moins 12 caractères** (les mots de passe les plus
   courants sont refusés, la longueur est plafonnée à 128).

   Le premier compte passe **même avec `INSCRIPTIONS_OUVERTES` non défini** : c'est l'amorçage.

3. **La case « Rattacher à ce compte les analyses effectuées avant la création des comptes ».**
   Elle n'apparaît qu'en mode inscription et n'a d'effet que pour le **tout premier** compte. Cochée,
   elle réattribue à ce compte l'historique, la consommation et les jobs accumulés sous
   `user_id="local"` avant l'authentification (`_adopter_donnees_locales`). Décochée, ces données
   restent sous `"local"` et deviennent inaccessibles depuis l'interface.

   **Elle doit être cochée explicitement.** La reprise était automatique dans la première version
   de l'authentification : sur une instance exposée, le premier visiteur venu devenait alors
   propriétaire de l'historique et de la consommation de Baptiste. C'est pour cela que la reprise
   est devenue une demande, et qu'elle est annoncée en clair une fois faite.

4. **Les inscriptions suivantes sont fermées.** Tant que `INSCRIPTIONS_OUVERTES` n'est pas mis à
   `1` (ou `true`/`yes`/`oui`) dans `.env` **et le serveur relancé**, toute autre création de compte
   rend **403 « les inscriptions sont fermées sur cette instance »** — message identique quelle que
   soit l'adresse, pour ne pas transformer l'inscription en oracle d'énumération des clients.

   Motif : le plafond mensuel est *par utilisateur*. Un compte de plus est un plafond neuf, donc une
   dépense neuve, sur une clé API qui est celle de l'exploitant. À rouvrir le jour où le paiement
   sera branché.

5. **La session dure 30 jours** (`SESSION_TTL_S`), cookie `httponly` + `samesite=lax`. « Se
   déconnecter » ferme la session **côté serveur** et pas seulement le cookie : effacer le cookie
   seul laisserait le jeton valide pour quiconque en aurait gardé copie.

**Rappel économique à ne pas casser** : `user_id` cloisonne `history.py`, `usage.py` et `jobs.py`.
**Jamais `cache.py`** — le cache de scraping reste mutualisé entre tous les comptes, c'est ce qui
évite de repayer deux fois la même donnée DataForSEO. Y introduire un `user_id` « par cohérence »
serait une régression économique silencieuse.

---

## 4. Lancement

### Interface web (usage normal)

Ouvre `http://127.0.0.1:8000` — adresse et port surchargeables par `HOST` / `PORT` (§2). Page
unique (`web/index.html`, 125 534 octets, CSS + JS inline, zéro build, aucun `<script src>` ni
`<link>`) : écran de connexion, **trois onglets** — non-fiction, fiction avec compositeur de trio,
low-content avec sélecteur de format —, progression en direct (SSE reconnectable), tableau de
niches dépliable, glossaire contextuel et **pastille d'aide « ? » fixe** ouvrant un mini-tutoriel
**par onglet**, chacun terminé par une section « Pièges de lecture ».

**Une seule ressource tierce subsiste** : `web/index.html:8` fait un
`@import url('https://fonts.googleapis.com/css2?…')` pour Fira Sans et Fira Code. Chaque ouverture
émet donc une requête vers Google. La page reste fonctionnelle hors ligne (les deux variables CSS
portent un repli : `system-ui,sans-serif` et `ui-monospace,monospace`), mais l'application n'est
pas strictement locale tant que cet import est là.

**Endpoints exposés par `web/server.py` — 18** (décorateurs `@app.`, comptés le 2026-08-22) :

| Groupe | Routes |
|---|---|
| Page | `GET /` — sert `index.html`, seul endpoint **hors `/api/auth/`** à ne pas exiger de session |
| Comptes | `POST /api/auth/inscription` · `POST /api/auth/connexion` · `POST /api/auth/deconnexion` (ces trois-là n'exigent pas de session en cours) · `GET /api/auth/moi` |
| Travaux | `POST /api/jobs` · `GET /api/jobs` · `GET /api/jobs/{id}` · `GET /api/jobs/{id}/stream` |
| Fiction | `GET /api/fiction/sous-genres` · `GET /api/fiction/taxonomie/{sous_genre}` |
| Low-content | `GET /api/lowcontent/formats` — source de vérité unique du sélecteur de format, `norme` exposé pour que l'UI pose son badge sans re-déduire la taxonomie |
| À la demande | `POST /api/dossier` (dossier de niche en 3 pages ; `POST /api/pdf` en est un **alias** et sert le même document) · `POST /api/verdict` · `POST /api/kdp-keywords` · `GET /api/history` |
| Compteur | `GET /api/usage` |

`POST /api/jobs` accepte `type: "scout" | "fiction" | "lowcontent"` ; un type inconnu rend 400.

**Un seul chemin de lancement.** Les endpoints de flux direct `GET /api/scout` et `GET /api/fiction`
ont été **supprimés** (commit `5257323`). L'interface fait `POST /api/jobs`, reçoit un id
immédiatement (202), puis se raccroche à `GET /api/jobs/{id}/stream`.

Ce que ça change concrètement :

- **le run survit à la fermeture de l'onglet** — le thread est détaché et écrit sa progression dans
  `jobs.db`, pas dans une file en mémoire liée à la requête HTTP ;
- **un rechargement reprend le travail en cours** : l'id est gardé en `localStorage`, le flux rejoue
  toute la progression depuis le début à chaque raccrochage, et un run terminé pendant l'absence est
  affiché avec son résultat ;
- **le plafond est vérifié avant de dépenser**, avec une 429 lisible (« Vous avez atteint votre
  limite d'analyses pour ce mois-ci. Rien n'a été lancé. ») ;
- **le sous-genre et les contraintes de composition sont validés AVANT la création du job**
  (`_valider_volumes`) : 400 immédiate, jamais un 202 suivi d'un job en échec.

Motif de la suppression, à retenir : deux chemins pour le même travail dont un seul est exercé
divergent. C'est arrivé au compositeur de trio fiction, présent sur le flux direct et absent du
chemin asynchrone pendant tout un commit.

`POST /api/jobs` accepte deux jeux de noms de paramètres (`n_ideas`/`n_search` **et** les noms
historiques `ideas`/`search`), volontairement, après une divergence constatée en live.

### Ligne de commande

La CLI **ne connaît ni comptes ni plafond** : elle appelle les orchestrateurs directement, sans
passer par le serveur.

```bash
# Scout non-fiction (défauts argparse : --ideas 12, --search 6)
python 01-scripts/scout_master.py --seed "ésotérisme"
python 01-scripts/scout_master.py                              # mode "graine vide"
python 01-scripts/scout_master.py --seed "sommeil" --ideas 15 --search 8

# Scout fiction (défauts : --n-niches 8, --rayon kindle ; pas de contraintes de trio en CLI)
python 01-scripts/fiction_master.py --sous-genre cosy_mystery
python 01-scripts/fiction_master.py --sous-genre dark_romance --n-niches 5 --rayon papier

# Scout low-content
python 01-scripts/lowcontent_master.py --seed "carnet"
python 01-scripts/lowcontent_master.py --format-cle registres_reglementaires

# Canaux gratuits, smoke test (0 $)
python 01-scripts/demo_free.py --suggest "tarot"
python 01-scripts/demo_free.py --bsr 2266283340

# Régénère les deux PDF à la racine (passation + guide utilisateur)
python 01-scripts/tutoriel_pdf.py

# Outillage dev du classifieur fiction (--sous-genre est REQUIS : sans lui, argparse
# sort en SystemExit 2. Défauts : --n-niches 5, sortie validation-fiction-<date>.xlsx)
python 01-scripts/build_validation_set.py --sous-genre cosy_mystery
python 01-scripts/validate_classifier.py <fichier.xlsx>

# Calibration du scoring low-content (§12 — c'est L'ÉTAPE SUIVANTE du projet)
python 01-scripts/build_lowcontent_validation_set.py --gabarit 99-logs/validation-lc.xlsx
python 01-scripts/build_lowcontent_validation_set.py --xlsx  99-logs/validation-lc.xlsx

# Worker séparé : exécute les travaux hors du processus serveur (JOBS_MODE=worker)
python 01-scripts/worker.py
```

**Aucune de ces commandes CLI ne consigne l'historique ni n'impute l'usage** : `_consigner_scout`,
`_consigner_fiction` et `UsageMeter` vivent dans `web/server.py`, pas dans les orchestrateurs. Un
suivi d'évolution n'existe donc que pour les runs lancés depuis l'interface web.

Sous-genres fiction valides (`data/fiction_taxonomy_fr_v1.json`, version `fr_v1`) :
`cosy_mystery`, `thriller_psychologique`, `romantasy`, `romance_contemporaine`, `dark_romance`,
`feel_good`. C'est la source unique : `GET /api/fiction/sous-genres` et
`GET /api/fiction/taxonomie/{sous_genre}` la servent à l'UI, rien n'est dupliqué en dur côté JS.

`01-scripts/launcher.py` (lancé par `IA-Niches.bat`) est un menu CLI **antérieur à l'UI web**,
désormais **gratuit et seulement gratuit** : deux sondes, autocomplete et BSR scrapé.

**Son entrée 3 (« idées de niches par l'IA ») a été RETIRÉE le 2026-08-18**, sur décision de
Baptiste. Elle appelait `generate_niches` sans compte, sans `_verifier_plafond`, sans `UsageMeter`
et sans même un `CostTracker`. Le montant n'était pas le sujet (~0,02 € annoncés) : c'était le
**seul chemin du dépôt à dépenser sans laisser de trace dans `usage.db`**, or c'est `usage.db` qui
porte tout le raisonnement de marge — ce qu'il ne voit pas, personne ne le voit.

`tests/test_launcher.py` est le cliquet : il échoue si `niche_ideator`, `run_scout`,
`search_providers` ou `dataforseo` réapparaissent dans le fichier. Sa fixture coupe en outre le SDK
et le HTTP sortant avant chaque test — écrite après qu'un test a déclenché un **vrai appel
Anthropic facturé**, parce qu'un test ne doit pas dépendre de la propreté du code qu'il teste pour
rester inoffensif.

---

## 5. Les trois moteurs

### Scout non-fiction — `01-scripts/scout_master.py`

**Produit** : des `ScoredNiche` classées — niche, requête Amazon courte, mots-clés satellites,
score global /10, axes *demande* / *pénétration* / *compatibilité*, critères BSR §4.1 de
`CLAUDE.md` (oui/non), BSR du top, nombre de concurrents réellement ciblés, nombre de sponsorisés,
fourchette de prix du rayon, et le drapeau `concurrence_mesuree`.

**Chaîne** : ideator LLM (1 appel, tool-use forcé) → validation autocomplete Amazon (gratuit) →
**gate de coût** : seules les `n_search` premières niches validées passent à l'étape payante →
SERP DataForSEO par niche → BSR des 3 premiers ASIN organiques, résolus en **un seul batch
global** → scoring (fonctions pures).

**Le nombre d'idées n'est plus un réglage de l'interface** (commit `6d1f134`). L'ideator est un
appel LLM unique quel que soit le nombre demandé ; ce qui coûte, c'est le nombre de niches
*analysées*. Mesure à l'appui (30 niches sur « bien-être », 2026-08-03) : sur les viviers 10, 20 et
30, les 4 niches retenues sont déjà **toutes au-dessus du plafond `min(demand_score, 10)`** du
scoring — élargir le vivier change *quelles* niches sont testées, jamais leur note sur l'axe
demande. Gain mesuré : nul. Coût mesuré : 0,0459 $ pour 30 niches, soit ~0,0015 $ par niche.
Seul « Niches à analyser » reste réglable dans l'UI (défaut 4, borné 1-20 côté champ **et** côté
serveur).

> **À corriger dans le code, pas dans ce README** : la constante `IDEES_PAR_RUN = 10`
> (`web/server.py:82`) porte cette décision et son argumentaire, mais **n'est référencée nulle
> part** (`grep -rn IDEES_PAR_RUN 01-scripts web tests` : une seule occurrence, sa définition). Le
> défaut réellement appliqué quand le client omet `n_ideas` — ce que fait l'interface — est **12**
> (`web/server.py:430` et `:473`). Constaté le 2026-08-03.

**Fourchette de prix du rayon** (`scoring.prix_stats`) : min / médiane / max sur les **seuls
organiques**, un prix absent étant **exclu et jamais compté zéro** (le compter à zéro ferait croire
à un rayon bradé). `n_prix_connus` dit sur combien de livres elle porte. Elle **n'entre dans aucun
score** : un rayon cher n'est ni meilleur ni pire, cela dépend de la stratégie de l'auteur.

**Lecture du contenu des suggestions** (`niche_validator.lire_suggestions`, commit `000947a`) :
le simple *compte* de suggestions sature vite (mesuré : 16 niches sur 30 dépassaient le plafond du
scoring). Deux lectures supplémentaires, rendues comme des **drapeaux et non comme des points de
score** — `terme_dominant` (un mot absent de la requête présent dans au moins la moitié des
suggestions : souvent l'auteur ou le titre qui tient le rayon) et `intention_informationnelle`
(résumés, avis, citations : ces gens veulent l'information, pas le livre). « occasion » et
« pdf gratuit » ont été **volontairement écartés** des marqueurs, sur décision de Baptiste : un
acheteur d'occasion reste un acheteur. Zéro suggestion ne conclut rien — c'est une absence de
mesure, pas un rayon sain.

**Ce que « sponsorisés » veut dire exactement** : la séparation organique / `amazon_paid` se fait à
la source (`search_providers.py`), et aucun résultat sponsorisé ne fournit d'ASIN pour les BSR, ni
n'entre dans le comptage des concurrents ciblés, ni dans la fourchette de prix. Leur **nombre**, lui,
est bel et bien compté : `score_niche` ajoute **+0,5** à l'axe pénétration à partir de 3 sponsorisés
(beaucoup de sponso = concurrence organique plus faible), et `n_sponsored` est exposé et affiché.

**Quand la SERP tombe** (solde DataForSEO épuisé, file en panne), le run ne s'arrête pas — mais
depuis `60e405a` il ne ment plus. `ScoredNiche.concurrence_mesuree` (défaut pessimiste `False`)
neutralise **tout** bonus et malus de concurrence, le verdict devient
« Concurrence non mesurée — à relancer », l'UI l'affiche comme non mesurée, et la niche n'est
**pas** consignée dans l'historique (un point qu'on sait faux produirait au passage suivant un delta
spectaculaire et mensonger). Avant ce correctif, `n_concurrents_cibles = 0` déclenchait le bonus
« moins de 10 concurrents » (+2 en pénétration) : une niche dont rien n'avait été mesuré ressortait
à 6,88 « Intéressant ». **Nuance** : le bonus « place à prendre » (+1,5) reste appliqué sans SERP —
il repose sur le BSR, pas sur la SERP.

**Durée** : 2 à 7 minutes selon la charge de DataForSEO.

Le verdict IA n'est **pas** généré pendant le run (`n_verdict=0` par défaut, `scout_master.py:36`,
en CLI comme côté serveur) : 3 verdicts pré-générés pesaient 78 % du coût pour des textes rarement
lus. Il se demande à la pièce par `POST /api/verdict`.

### Scout fiction — `01-scripts/fiction_master.py`

**Produit** : des `FictionNicheReport` — un trio sous-genre x tropes x décor, avec `depth_score`
(profondeur du rayon), `openness_score` (ouverture), `saturation_trio` (couverture du trio par les
concurrents, calculée en **lisant les quatrièmes de couverture**), une matrice de demande à
6 issues et un verdict textuel qui porte ses réserves.

**Chaîne** (6 étapes A-F) : ideator contraint à la taxonomie (tout trio hors taxonomie est écarté
côté code) → une SERP par niche → **un seul batch ASIN pour tout le run** → classification des
blurbs par lots de 20 → sonde autocomplete à deux barreaux → reconstruction des rayons + scoring.

Le batch ASIN unique est la raison d'être du module : la file DataForSEO met ~250 s **quel que
soit** le nombre d'ASIN. La payer une fois par run au lieu d'une fois par niche fait passer
10 niches de 42 min à 5 min.

**Compositeur de trio** (commit `fba99d5`). L'auteur peut imposer ses **tropes**, son **décor** et
une **piste personnelle en texte libre** (`ContraintesTrio`) au lieu de subir la proposition de
l'IA. Les menus sont peuplés par `GET /api/fiction/taxonomie/{sous_genre}` et **rechargés à chaque
changement de sous-genre** — les tropes ne sont pas les mêmes d'un sous-genre à l'autre. Deux
garde-fous :

- les contraintes sont **vérifiées côté code** après la réponse du modèle, pas seulement demandées
  au prompt ; une clé hors taxonomie **lève** (400) plutôt que d'être ignorée, sinon l'auteur
  croirait sa contrainte appliquée ;
- `contraintes_impossibles` distingue « **vos contraintes ne se combinent pas** » d'un verdict de
  marché. Sans contrainte, le comportement d'origine est inchangé.

**Durée** : 10 à 15 minutes (869 s mesurés sur 3 trios).

**Piège de lecture** : `saturation_trio` est un **score inversé** — élevé = mauvais. Une jauge
colorée comme les autres ferait recommander exactement les pires niches. (Le low-content en a un
second, `n_variantes_quasi_identiques`, ci-dessous.)

### Scout low-content — `01-scripts/lowcontent_master.py`

**Son ordre est INVERSÉ par rapport aux deux autres, et c'est tout le sujet.** Ailleurs, le LLM
propose et l'autocomplete valide. Ici, **l'autocomplete est la source**.

La raison est mesurable : en low-content, la tête de requête (« livre coloriage », « registre ») est
morte ou tenue par des éditeurs, et l'argent est trois crans plus bas dans la traîne (« coloriage
licorne 3 ans fille », « registre du personnel obligatoire »). Un LLM à qui on demande des requêtes
long-tail invente aussi la demande qui va avec. Amazon, lui, ne complète que ce que des gens tapent
réellement — et il le donne pour rien.

**Chaîne** : arbre d'autocomplete (`autocomplete_expand`, gratuit ; `alphabet=True` sonde aussi
« graine a »…« graine z », parce qu'Amazon ne rend qu'une dizaine de complétions par préfixe) →
filtres **IP** et **saisonnalité** appliqués ICI, avant tout appel payant → l'IA **classe** les
requêtes réelles (format × thème × public) → SERP par niche → **un seul batch ASIN** → scoring.

**Quatre axes** au lieu de trois : demande 0,35 · pénétration 0,35 · **rentabilité** 0,20 ·
**faisabilité** 0,10. Les deux derniers n'existent pas ailleurs, et ce n'est pas un raffinement :

- **rentabilité** — sous 9,99 € de prix catalogue, KDP verse 50 % au lieu de 60 %, et le coût
  d'impression se déduit ensuite (deux bandes par encre : forfait de 2,05 € jusqu'à 110 pages, puis
  0,75 € + 0,012 €/page). Un rayon très demandé à 6,99 € peut ne rien rapporter ;
- **faisabilité** — un carnet quadrillé et un cahier d'activités illustré ne se produisent pas dans
  le même monde.

**Deux signaux de pénétration propres au rayon** :

- **`part_indie`** — douze références peuvent toutes venir de papetiers (Exacompta, Quo Vadis).
  Invisible dans un comptage de résultats, décisif pour savoir si un auteur seul peut attaquer. Un
  éditeur inconnu rend **`None`**, jamais `False` : `False` voudrait dire « ce n'est pas de
  l'indie », donc une conclusion ;
- **`n_variantes_quasi_identiques`** — **échelle INVERSÉE, élevé = mauvais.** Dix couvertures pour
  un seul intérieur, c'est une ferme de variantes ; publier la onzième n'y gagne rien.

**Le filtre IP est le seul garde-fou JURIDIQUE du dépôt** (`ip_filter.py`, corpus dans
`data/exclusions_ip.md`). Il tolère l'apostrophe typographique (la forme officielle de
Pat'Patrouille, T'choupi, McDonald's), le séparateur libre, le pluriel dans les deux sens et les
mots de liaison internes. Mesuré : sur 198 requêtes portant une marque sous forme mutée, **198
échappaient** à la version exacte. La même mesure a révélé **cinq faux positifs préexistants** —
« cahier de révision BTS MCO » était rejeté en silence.

**`norme: true`** (registres, carnets professionnels) : le contenu est fixé par un texte externe.
**Piège de lecture à ne jamais inverser** — « normé » ne veut pas dire « difficile ». Le contenu
étant imposé, la production est SIMPLE (effort 1) ; c'est la **conformité** qui est exigeante, et
`lowcontent_verdict` **dégrade un « Go » côté code** si aucune source réglementaire n'est citée. Un
registre incomplet expose l'acheteur, qui est un employeur.

> **Les seuils de `data/lowcontent_criteres.json` sont des HYPOTHÈSES, pas des mesures.** Le fichier
> le dit dans son en-tête. Tant que la calibration (§12) n'est pas faite, ne pas les citer comme des
> critères établis.

**Durée** : 3 à 9 minutes.

---

## 6. Fonctions à la demande

| Fonction | Endpoint | Coût interne | État |
|---|---|---|---|
| Verdict éditorial d'une niche (Go / Go prudent / No-Go, confiance /10, facteur décisif, 2-3 angles d'attaque, critique stratégique) | `POST /api/verdict` | 0,028 $ | Sans état : la niche entière est passée dans le body. Vérifie le plafond, impute avec `n_analyses=0`. Bouton « Analyser cette niche (~10 s) » sur chaque ligne. |
| **Dossier de niche en 3 pages** (marché + concurrents, angle et spec, mots-clés et catégories) | `POST /api/dossier` | 0 $ (catégories) · ~0,006 $ si mots-clés | Accepte une `ScoredNiche` **ou** une `LowContentScored` via `type`. Les catégories sont incluses par défaut (déduites des BSR déjà payés) ; les mots-clés **non** — le défaut ne dépense pas à l'insu de l'utilisateur. `POST /api/pdf` est un alias et sert le même document. |
| 7 mots-clés backend KDP | `POST /api/kdp-keywords` | ~0,006 $ (estimé) | ~22 candidats proposés par le LLM, règles KDP vérifiées **côté code** (50 caractères, termes proscrits, chevauchement avec le titre, doublons, motif de rejet lisible), puis confirmation **gratuite** par l'autocomplete Amazon. Vérifie le plafond, impute avec `n_analyses=0`. |
| Historique et évolution d'une niche | `GET /api/history` | 0 $ | Enregistré automatiquement par les runners de `POST /api/jobs` — **jamais par les CLI**, et **jamais pour une niche dont la SERP a échoué** (`concurrence_mesuree=False`). Une seule mesure → `delta: null` avec un **200** : « pas encore de recul » est une réponse, pas une erreur. Seuil de significativité 0,10. Affiché sur les **trois** onglets. |

> **Ces boutons ont été morts pendant des semaines, et c'est la leçon la plus chère du dépôt.**
> Ils naissaient dans `verdictBlock(r)`, qui sort par `if(!v) return ''` — or `n_verdict=0` partout,
> donc `verdict` valait **toujours** `None`. Trois endpoints développés, testés, payés, sans aucun
> chemin d'accès. Corrigé le 2026-08-18 : `verdictSlot(r)` rend désormais l'un ou l'autre état,
> **jamais le vide**, et `brancherActions()` est le SEUL site de branchement.
>
> Ce qui l'avait caché : `test_ux_kdp_historique` vérifiait que les chaînes étaient **présentes**
> dans le HTML, et passait au vert pendant que les boutons étaient morts. **Une chaîne présente dans
> un fichier ne prouve rien sur ce qui est cliquable.** Les tests actuels EXÉCUTENT les fonctions de
> rendu avec node (`tests/js_harness.py`).
| Consommation du mois glissant | `GET /api/usage` | 0 $ | Fenêtre de 30 jours, ni calendaire ni cumulative à vie. Affichée en nombre d'analyses, **sans montant**. |

---

## 7. Coûts

> **Aucun montant n'est montré à l'utilisateur dans l'interface** (commit `4165efb`). Tous les
> dollars ont disparu : barre « Coût de ce run », montant du bandeau mensuel, infobulles, taux de
> change, `fmtUsd`, `formatCost` — et aussi les montants qui revenaient par les **messages de
> progression** de `scout_master` et `fiction_master`. Le bandeau ne dit plus que
> « Ce mois-ci : N analyse(s) ». Le backend, lui, continue de **tout** mesurer et imputer : le
> plafond en dépend, et ce sera la base d'une facturation en jetons ou par abonnement.
> **La fourchette de prix des LIVRES reste affichée** : c'est une donnée de marché, pas un tarif.
>
> Les chiffres ci-dessous sont donc destinés **au développeur et à l'exploitant**, pas à
> l'utilisateur final.

Les lignes marquées **mesuré** viennent de runs réels du 2026-07-21 et sont reprises telles quelles
de la table `COUTS` de `01-scripts/tutoriel_pdf.py`. Les autres sont **calculées**, **extrapolées**
ou **estimées** — la colonne « Origine » est la seule chose qui distingue un chiffre relevé d'un
chiffre déduit. Colonne « standard » = `DATAFORSEO_PRIORITY=1` : moitié prix sur la donnée, mais
jusqu'à ~45 min d'attente.

| Demande | priority (défaut) | standard | Origine |
|---|---|---|---|
| Scout non-fiction, BSR local (`scrape`) | 0,030 $ | 0,021 $ | mesuré |
| Scout non-fiction, BSR serveur (`dataforseo`) | **0,084 $** | 0,048 $ | calculé |
| Scout fiction, 3 trios | 0,153 $ | 0,113 $ | mesuré |
| Scout fiction, 8 trios | 0,409 $ | 0,299 $ | extrapolé |
| Scout low-content, 6 niches | ~0,05 $ | ~0,03 $ | **estimé** — aucune mesure datée |
| Jeu de calibration low-content, 31 requêtes | ~0,80 $ au pire (poste résidentiel) · ~1,35 $ (`BSR_SOURCE=dataforseo`) | — | **calculé**, jamais mesuré — moins si le cache a déjà vu ces rayons |
| Verdict éditorial (1 niche) | 0,028 $ | 0,028 $ | mesuré |
| Mots-clés KDP (1 niche) | ~0,006 $ | ~0,006 $ | **estimé** — aucune mesure datée |
| Ideator seul, vivier de 30 idées | 0,0459 $ | 0,0459 $ | mesuré (2026-08-03) |
| Sonde autocomplete | 0 $ | 0 $ | endpoint public |
| PDF, historique, consultation d'un job | 0 $ | 0 $ | local |
| Set de validation du classifieur (50 livres) | 0,32 $ | — | one-shot |

**PIÈGE `BSR_SOURCE` — ne jamais citer le chiffre local comme coût de production.** Le défaut
`scrape` lit les fiches `amazon.fr/dp/{asin}` depuis une **IP résidentielle**. Depuis un datacenter,
Amazon bloque : il faut `BSR_SOURCE=dataforseo`, et le scout non-fiction passe de 0,030 $ à
**0,084 $**, soit ×2,8.

Le **cache SQLite mutualisé** (`99-logs/df-cache.db`) est l'économie principale à l'échelle : deux
utilisateurs qui analysent le même rayon ne le paient qu'une fois. Ce partage est **délibéré**, pas
un oubli de cloisonnement.

**TTL harmonisés à 15 jours** — BSR, livre, SERP et autocomplete — sauf la **classification de
quatrièmes, à 30 jours**, parce que sa clé porte déjà tout ce qui peut invalider le résultat (ASIN,
version de taxonomie, modèle, empreinte du prompt système, empreinte des champs). Ce qu'on échange
contre 15 jours, c'est de la fraîcheur ; mais le produit compare des **ordres de grandeur** de BSR
(sous 10 000, sous 50 000, au-delà), pas un classement à la journée, et un rayon ne change pas de
tranche en deux semaines. Un BSR **absent** est mémorisé à part et pour 3 jours seulement
(`ECHEC_BSR_TTL_S`) : une absence est une information plus fragile qu'une mesure.

> **Piège structurel, déjà payé une fois** : `BOOK_TTL_S` valait 15 j dans `cache.py` (documenté,
> testé) et 7 j dans `fiction_serp_provider.py` (appliqué). Le test surveillait la constante MORTE
> et passait au vert en garantissant le contraire de ce qu'il annonçait. **Tester la valeur
> réellement PASSÉE, jamais la présence d'une constante.**
Les **quatre** familles de clés portent une empreinte SHA1 du schéma pydantic — `book:`, `bsr:`,
`search:` et `clf:`, qui cumule empreinte de schéma **et** empreinte du prompt système du
classifieur. Ajouter un champ invalide automatiquement les entrées ; sans cela, `clf:` servait
pendant **30 jours** des objets amputés. Limite assumée : l'empreinte suit les **noms** de champs,
pas leur sémantique — changer le sens d'un champ sans le renommer exige de vider le cache à la main.

---

## 8. Structure du dépôt

Les dossiers v1 ont disparu : `00-config/` et `02-veille-hebdo/` **supprimés** par le commit
`eaa20b2`, `03-niches-validees/` et `04-archives/` simplement effacés du disque — ils étaient
vides et n'ont jamais été versionnés. `05-prompts/` subsiste avec **un seul** fichier,
`prompt-onebooklab-template.md` : il sert le workflow manuscrit de Baptiste, hors de cet outil, et
n'est importé par aucun module.

L'arbre ci-dessous liste **les 49 modules `.py` de `01-scripts/`**, groupés par rôle.

```
├── 01-scripts/                # Le moteur
│   ├── scout_master.py            # Orchestrateur non-fiction
│   ├── fiction_master.py          # Orchestrateur fiction (6 étapes, batch ASIN unique)
│   ├── lowcontent_master.py       # Orchestrateur low-content (l'autocomplete est la SOURCE)
│   ├── models.py                  # Tous les types pydantic + la logique métier subtile
│   ├── scoring.py / fiction_scoring.py / lowcontent_scoring.py   # 100 % de fonctions pures
│   ├── niche_ideator.py / fiction_ideator.py / lowcontent_ideator.py   # LLM, tool-use forcé
│   ├── niche_validator.py / amazon_autocomplete.py / fiction_autocomplete.py  # Demande, gratuit
│   ├── autocomplete_expand.py     # Arbre des complétions — la source du low-content
│   ├── ip_filter.py               # SEUL garde-fou juridique : marques et franchises
│   ├── search_providers.py        # DataForSEO (SERP + ASIN batché) + parseurs BSR
│   ├── bsr_source.py / amazon_product.py  # BSR : scrape gratuit ou DataForSEO payant
│   ├── fiction_serp_provider.py / fiction_books.py / fiction_classifier.py / fiction_taxonomy.py
│   ├── lowcontent_taxonomy.py / lowcontent_verdict.py
│   ├── marketplace.py             # Source UNIQUE de la place de marché (§10)
│   ├── niche_verdict.py / kdp_keywords.py / positioning_pdf.py / dossier_pdf.py  # À la demande
│   ├── auth.py                    # Comptes, mots de passe (scrypt), sessions
│   ├── cache.py / cost_tracker.py / jobs.py / usage.py / history.py   # Infrastructure
│   ├── storage.py                 # Source UNIQUE du répertoire des cinq bases (DATA_DIR)
│   ├── devis.py                   # Estimation du PIRE cas avant de lancer (§7)
│   ├── worker.py                  # Exécuteur hors serveur, pool + file équitable
│   ├── notification.py            # Message de fin d'analyse, éteint par défaut
│   ├── util.py                    # HTTP avec en-têtes navigateur
│   ├── tutoriel_pdf.py            # Générateur des 2 PDF racine
│   ├── demo_free.py               # Smoke test des canaux gratuits (0 $)
│   ├── launcher.py                # Menu CLI, GRATUIT et seulement gratuit (§4)
│   ├── requirements.txt
│   ├── fiction_validation.py, build_validation_set.py, validate_classifier.py   # Outillage dev
│   └── lowcontent_validation.py, build_lowcontent_validation_set.py             # Calibration (§12)
├── web/
│   ├── server.py                  # FastAPI, 18 routes @app, 1 157 lignes
│   └── index.html                 # UI complète en un fichier (125 534 octets)
├── data/
│   ├── fiction_taxonomy_fr_v1.json      # 6 sous-genres : source de vérité unique
│   ├── lowcontent_taxonomy_fr_v1.json   # 36 formats, 8 familles
│   ├── lowcontent_criteres.json         # Seuils du scoring LC — HYPOTHÈSES tant que §12 n'est pas fait
│   ├── kdp_print_costs.json             # Barèmes d'impression KDP, en EUROS, avec date de relevé
│   └── exclusions_ip.md                 # Corpus du filtre IP
├── tests/                         # 1038 tests sur 87 fichiers, tous hors-ligne
├── docs/
│   ├── spike_fiction_M0.md            # Spike de conception du moteur fiction
│   ├── pages-publiques/               # Mentions légales, confidentialité, CGV, landing — BROUILLONS
│   └── superpowers/plans/ · specs/    # Plans TDD ; cités depuis le code et les tests
├── 05-prompts/prompt-onebooklab-template.md   # Workflow manuscrit, hors outil
├── 99-logs/                       # 5 bases SQLite locales, git-ignorées (+ .db-wal/.db-shm)
│   ├── df-cache.db · jobs.db · usage.db · history.db · comptes.db
│   ├── validation-fiction-2026-07-21.xlsx           # SUIVI par git : étalon-or du classifieur
│   ├── rapport-validation-classifieur-2026-07-21.json   # SUIVI par git
│   └── validation-lc.xlsx         # SUIVI par git : gabarit de calibration LC, À REMPLIR (§12)
├── assets/hedgehog.ico            # Icône du raccourci Windows
├── .env / .env.example
├── pytest.ini · .gitattributes · .gitignore · LICENSE
├── Procfile · requirements.txt   # Hébergement (le second INCLUT 01-scripts/requirements.txt)
├── CLAUDE.md · ROADMAP.md · README.md
├── IA-Niches-Web.bat              # Lance le serveur + ouvre le navigateur
├── IA-Niches.bat                  # Lance launcher.py (menu CLI antérieur à l'UI web)
├── IA-Niches - Dossier de passation.pdf   # Généré par tutoriel_pdf.py
└── IA-Niches - Guide utilisateur.pdf      # idem
```

Le code est **massivement auto-documenté** : les docstrings contiennent les pièges métier mesurés
en live (BSR Kindle vs papier non comparables, titres gratuits exclus, lookahead « en Livres »,
`label_rayon`, autocomplete préfixé…). C'est la vraie documentation du projet.

`tutoriel_pdf.py` n'en fait pas partie : c'est un **générateur de PDF**, pas une source de vérité.
Deux tests le tiennent — l'un vérifie qu'il couvre **tous** les endpoints réellement exposés (il lit
`web/server.py`), l'autre qu'il ne cite **que** des variables encore lues (il balaie
`01-scripts/*.py` et `web/server.py`). Sa table `ENDPOINTS` couvre les routes actuelles, comptes
compris, et sa table `COUTS` est la seule source du dépôt qui étiquette chaque chiffre
mesuré / calculé / extrapolé / estimé. Le reste (`PIEGES`, `GLOSSAIRE`, `DEPLOIEMENT`) n'est
vérifié par personne — et `DEPLOIEMENT` référence encore des endpoints supprimés.

---

## 9. Tests

```bash
python -m pytest                    # depuis la racine
python -m pytest --collect-only     # 1038 tests collected, 87 fichiers, 0 erreur de collecte
```

`pytest.ini` fixe `pythonpath=01-scripts`, `testpaths=tests`, `python_files=test_*.py`,
`addopts=-q`. **Les 1038 tests sont tous hors-ligne** : chaque dépendance lourde (client Anthropic,
provider DataForSEO, fetch HTTP, sonde autocomplete) est injectable par paramètre. Aucune clé API
n'est nécessaire pour les faire passer. `tests/conftest.py` coupe en plus le SDK et le HTTP sortant
avant **chaque** test, et réinitialise les états globaux de module (`server._CRENEAUX`) — un
sémaphore qui survivait d'un test à l'autre provoquait des échecs **intermittents**, six sur une
exécution et zéro sur la suivante, sur des sujets sans rapport.

`tests/js_harness.py` extrait les fonctions de rendu **pures** de `web/index.html` et les APPELLE
avec node (skip explicite si node est absent). C'est ce qui distingue un test de présence d'un test
de comportement — cf. l'encadré du §6, où la présence passait au vert sur des boutons morts.

**TDD non négociable** : les tests d'abord, **en rouge**, avant toute ligne d'implémentation, et on
vérifie qu'ils échouent pour la BONNE raison. C'est ce qui tient ces 1038 tests sans réseau.

---

## 10. Invariants à ne pas casser

- **Un échec n'interrompt jamais un run, mais il est toujours compté.** SERP en échec → niche
  scorée sans concurrence **et marquée `concurrence_mesuree=False`** (aucun bonus/malus de
  concurrence, verdict « non mesurée », pas de consignation dans l'historique) ; ASIN non enrichi →
  `n_echecs` incrémenté et annoncé ; niche fiction en échec → écartée, rayons déjà payés
  conservés ; job en échec → le coût engagé reste imputé.
- **Une sonde en panne n'est pas un signal absent.** `AutocompleteSignal.mesure` a un défaut
  pessimiste `False`, `autocomplete_score` rend `None` et non `0.0`. Confondre les deux fait
  déclarer morte une niche qu'on n'a simplement pas mesurée.
- **`non_mesurable` n'est pas « mort »**, **un rayon amputé n'est pas un rayon désert**, et
  **`contraintes_impossibles` n'est pas un verdict de marché**.
- **Le `user_id` vient du cookie de session, jamais du client.** Ne jamais réintroduire un
  paramètre ou un champ `user_id` sur un endpoint.
- **`user_id` cloisonne `history.py` / `usage.py` / `jobs.py`, jamais `cache.py`.**
- **Toute nouvelle dépense vérifie le plafond avant de dépenser**, et impute même en cas d'échec.
- **Pas de `temperature` / `top_p` / `top_k`** sur `claude-sonnet-5` : toute valeur non-défaut
  renvoie une 400.
- **Instance par appel, jamais à l'import** pour Cache / JobStore / UsageMeter / NicheHistory /
  UserStore : sinon importer `server.py` en test écrit de vrais fichiers dans le dépôt.
- **Un seul chemin de lancement.** Ne pas réintroduire un second chemin (flux direct) : celui qui
  n'est pas exercé dérive.
- **Deux scores sont INVERSÉS** : `saturation_trio` (fiction) et `n_variantes_quasi_identiques`
  (low-content). Élevé = mauvais. Une jauge colorée uniformément ferait recommander exactement les
  pires niches.
- **Une seule source pour la place de marché** : `marketplace.py`. `location_code=2250`,
  `language_code="fr_FR"` (**pas** `fr`), identifiant d'autocomplete et domaine des fiches y vivent
  ensemble. `MARKETPLACE=com` **LÈVE au démarrage** : six choses du dépôt sont irréductiblement
  françaises (browse nodes, libellés de rayon, barèmes KDP en euros, mots saisonniers, corpus du
  filtre IP, prompts). Un run `.com` ne planterait pas — il rendrait des **chiffres faux et
  plausibles**, ce qui est pire.
- **Le message de fin d'analyse ne contient jamais le résultat**, ni le moindre montant, ni l'erreur
  interne (elle peut porter les identifiants DataForSEO). Un échec d'envoi ne fait **jamais** échouer
  un run : le run a coûté de l'argent réel et son résultat est en base.
- **Le BSR est DÉJÀ dans l'enrichissement ASIN.** Appeler `resolve_bsrs` derrière sur les mêmes
  ASIN les facture une seconde fois — mesuré : 240 appels pour 120 ASIN, 0,78 $ contre un plafond de
  0,60 $, franchi **en silence**. Seuls les ASIN absents de l'enrichissement valent un second
  passage.
- **`MAX_NICHES_FICTION` vaut 11, et c'est DÉRIVÉ, pas choisi** : c'est le plus grand nombre de
  trios dont le devis tient sous `PLAFOND_USD_PAR_RUN`. Ne pas la relever sans relever le plafond —
  au-delà, le run atteindrait le plafond en route et rendrait un rapport **partiel** à quelqu'un qui
  a payé son plafond entier, ce qui se lit comme une arnaque et non comme une protection.
- **Tester la valeur réellement PASSÉE, jamais la présence d'une constante.** `BOOK_TTL_S` valait
  15 j dans `cache.py` (documenté, testé) et 7 j dans `fiction_serp_provider.py` (appliqué) : le
  test surveillait la constante MORTE et garantissait au vert le contraire de ce qu'il annonçait.

---

## 11. Limites connues / ce qui n'existe pas encore

**Bloquants pour une mise en vente**

- **Pas de paiement, pas d'abonnement, pas de facturation.** Les comptes existent, le plafond
  existe, la mesure du coût existe — la monétisation, non. `INSCRIPTIONS_OUVERTES` est fermé par
  défaut précisément parce qu'un compte gratuit de plus est une dépense de plus.
- **Le scoring low-content n'est pas calibré** (§12). Les seuils de `data/lowcontent_criteres.json`
  sont des **hypothèses documentées**, pas des mesures : le moteur rend des chiffres cohérents entre
  eux, rien ne dit qu'ils correspondent au terrain. L'outillage de calibration existe, la mesure non.
- **`IDEES_PAR_RUN` est déclarée et non branchée** (§5) : le défaut appliqué est 12, pas 10.
- **`BSR_SOURCE=scrape` ne survit pas au déploiement** (§7).
- **Aucune autre place de marché qu'`amazon.fr`** : `marketplace.py` rassemble les neuf codages en
  dur et rend le manque **explicite**, il ne le comble pas (§10).
- **Les quatre pages publiques sont des brouillons non servis** (`docs/pages-publiques/`) : mentions
  légales, confidentialité, CGV, landing. Chacune porte des `[[A COMPLETER : … ]]` — identité légale,
  hébergeur, prix, délai de rétractation. `tests/test_pages_publiques.py` verrouille le lien : dès
  qu'une route sert un de ces fichiers, il ne doit plus rester un seul marqueur.
- **Réinitialisation de mot de passe, vérification d'adresse, changement d'e-mail, suppression de
  compte, rôles, administration** : aucun de ces chemins n'est codé. Un mot de passe perdu est un
  compte perdu. Le seul e-mail sortant est le message de fin d'analyse, transactionnel et sans lien
  d'action.
- **Le dépôt est DÉPLOYABLE, rien n'est déployé.** Depuis le 2026-09-07 : `requirements.txt` à la
  racine (il inclut celui de `01-scripts/`, il ne le recopie pas), `Procfile`, `HOST` déduit
  d'`APP_ENV`, `DATA_DIR` **exigée** en production, et les travaux interrompus par un redémarrage
  sont récupérés au démarrage. Ce qui manque encore : un hébergeur configuré, **un volume
  persistant monté sur `DATA_DIR`** — sans lui les cinq bases disparaissent à chaque mise en ligne,
  sans aucun signal —, et le proxy TLS (le cookie obtient son drapeau `Secure` tout seul derrière
  lui, mais le proxy reste à monter). Toujours aucun Docker, aucune base partagée : cinq fichiers
  SQLite. **`JOBS_MODE=worker` suppose que serveur et worker voient le MÊME `DATA_DIR`** — là où un
  volume ne s'attache qu'à un seul service, rester en `thread`.

**Limites de mesure**

- **L'axe 3 « compatibilité livre » n'est pas implémenté** : figé à la constante `8.0` pour toute
  niche. Le score global vaut donc toujours `demande×0,4 + pénétration×0,4 + 1,6`, mécaniquement
  borné entre 2,4 et 9,6.
- **`bsr_top5_avg` ment sur son contenu** : le scout ne récupère que le top 3 (`n_bsr_per_niche=3`).
  Même remarque pour `worst_top10`.
- **Le critère « ≤ 10 000 résultats Amazon » n'est ni codé ni mesurable** : la donnée n'est pas
  collectée (`SearchResult.total_items` = nombre d'items de la page, jamais utilisé dans un calcul).
- **Les exclusions métier (saisonnier, religions à expertise pointue, politique contemporaine,
  risque TOS) n'existent que dans le prompt** de l'ideator. Aucun filtre Python ne rattrape un
  modèle qui désobéit — contrairement aux règles KDP et à la taxonomie fiction, doublées en code.
- **Le champ `NicheCandidate.risques` est mort** : rempli par le LLM, propagé nulle part.
- **Aucun bonus « expertise pharmacien »**, et c'est délibéré : le prompt de l'ideator impose au
  contraire une clause d'impartialité explicite qui interdit de privilégier un domaine.
- **Le paramètre `signals`** (mode « à partir de rien » nourri par des tendances) traverse les
  signatures jusqu'au prompt, mais aucun appelant ne le remplit : il vaut toujours `None`. Le mode
  « à partir de rien » se réduit à « graine vide ».
- **Aucun test d'intégration réseau** : rien ne détecte une rupture de contrat côté DataForSEO ou
  Amazon avant un run réel.

**Corrigé depuis, ne pas le réintroduire dans la doc** : les boutons « Télécharger le PDF »,
« Mots-clés KDP » et l'historique fiction ont été inatteignables pendant des semaines (§6). Les
trois sont branchés depuis le 2026-08-18, et les tests EXÉCUTENT désormais les fonctions de rendu.

**Ce qui n'existe plus du tout** : `GET /api/scout` et `GET /api/fiction` (supprimés, commit
`5257323` — ne pas les réintroduire) ; Scrapingdog (côté `.py`, le mot ne survit que dans le
docstring d'en-tête de `cost_tracker.py` ; il subsiste dans des archives de décision de
`docs/superpowers/` toujours suivies par git, ainsi que dans ce README, `CLAUDE.md` et
`ROADMAP.md`, qui en parlent pour dire qu'il est abandonné) ; le compteur de crédits et ses
garde-fous ; le mode dry-run ; les rapports Excel du scout (`openpyxl` ne sert qu'à la validation
**manuelle** du classifieur) ; Google Trends, Reddit, Google News, TikTok ; le workflow humain en
5 phases ; la pré-production (sommaires, prompts de rédaction, briefs de couverture) et la
post-production (4e de couverture, fiche produit AIDA). Depuis `eaa20b2`, les trois modules de
veille et les dossiers v1 sont supprimés, pas seulement inutilisés.

---

## 12. Reprendre le travail — l'étape suivante

> Cette section est le point d'entrée d'une nouvelle session, sur ce PC ou un autre. Elle dit
> **ce qui est fait**, **ce qui bloque** et **par quoi commencer**. Le détail technique vit dans
> `CLAUDE.md` (lu en priorité par l'agent) ; `ROADMAP.md` porte le classement complet.

### Fait, livré, poussé

Trois moteurs · comptes et sessions · travaux asynchrones avec file équitable · chaîne complète de
garde-fous de dépense (devis avant lancement, plafond prédictif par run, plafond mensuel atomique
par utilisateur, bornes de volume, limiteur de débit) · filtre IP juridique · message de fin
d'analyse · brouillons des pages légales. **1038 tests, tous hors ligne.**

### L'étape suivante, et elle n'attend que Baptiste

**Calibrer le scoring low-content.** Les seuils de `data/lowcontent_criteres.json`
(`variantes_max=6`, `part_indie_bonne=0.5`, `redevance_min_bonne=2.0`) n'ont été confrontés à aucun
rayon réel. Le protocole **inverse** celui du classifieur fiction : là-bas Baptiste CORRIGE des
étiquettes produites par l'IA, ici il étiquette des requêtes **avant** toute analyse — son jugement
est la référence. Si l'IA choisissait les requêtes à juger, on calibrerait le scoring sur lui-même.

```bash
# 1. Le gabarit existe déjà dans le dépôt : 99-logs/validation-lc.xlsx
#    (8 familles x 4 lignes, liste déroulante sur la colonne « etiquette »)
#    Pour le régénérer : --gabarit. Il REFUSE d'écraser un classeur déjà étiqueté.

# 2. Remplir les colonnes « requete » et « etiquette » : bonne | mauvaise | morte
#    Viser 25-30 lignes, MINIMUM 3 par famille, et environ un tiers de chaque étiquette.
#    Tout étiqueter « bonne » rendrait la corrélation INDÉFINIE : il faut des cas dont on
#    connaît la réponse aux deux bouts. Les cas limites sont les plus utiles.

# 3. Lancer la mesure : ~0,80 $ au pire pour 31 requêtes sur ton poste, plafond
#    explicite à 2 $. Compter 20 min à 2 h : les SERP partent une par une.
#    --inclure-saisonnier fait scorer les requêtes saisonnières au lieu de les écarter.
python 01-scripts/build_lowcontent_validation_set.py --xlsx 99-logs/validation-lc.xlsx
```

**Porte, conjointe : Spearman ≥ 0,5 ET aucune requête « morte » en 🟢.** Une corrélation honnête qui
recommande quand même un rayon mort ferait publier dans le vide. En cas d'échec, on corrige
`data/lowcontent_criteres.json` **jamais le code** : un seuil qui migre dans `lowcontent_scoring.py`
redevient invisible et non discutable.

Le rapport (`99-logs/rapport-calibration-lc.json`) donne aussi les **distributions de signaux par
étiquette** — c'est ce qui permet de régler un seuil au lieu de le déplacer au hasard — et les
requêtes perdues **avant** toute dépense, séparées en deux : une « morte » écartée là est le gate
gratuit qui travaille, une « bonne » écartée là est un faux négatif que l'utilisateur ne peut PAS
voir, puisque la niche n'apparaît nulle part.

### Ensuite, par ordre de blocage

1. **Paiement (Stripe)** — rien n'est intégré. `usage.db` mesure et stocke tout, ce qui donne la
   base d'une facturation, mais aucun montant n'est présenté et aucun prestataire n'est branché.
   `INSCRIPTIONS_OUVERTES` reste fermé par défaut jusque-là : un compte gratuit de plus est une
   dépense de plus sur la clé API de l'exploitant.
2. **Pages publiques** — remplir les `[[A COMPLETER]]`, trancher l'hébergement (plusieurs
   paragraphes de la politique de confidentialité en dépendent), faire relire les CGV.
3. **Déploiement** — le dépôt est prêt côté code (`requirements.txt` racine, `Procfile`, `HOST`
   déduit, `DATA_DIR` exigée en prod, récupération des travaux interrompus). Reste à faire, chez
   l'hébergeur et non dans le code : créer le service, **monter un volume et le pointer par
   `DATA_DIR`**, poser les variables (`APP_ENV=prod`, `BSR_SOURCE=dataforseo`, les clés), vérifier
   que le proxy TLS envoie `X-Forwarded-Proto`. Toujours aucun Docker, aucune base partagée.
4. **Hygiène** — `IDEES_PAR_RUN` à brancher ou à supprimer, résidus Scrapingdog dans les archives
   de `docs/superpowers/`.

### Règles de travail à ne pas contourner

**TDD non négociable** — les tests d'abord, **en rouge**, et on vérifie qu'ils échouent pour la
bonne raison. **Le code est la source de vérité** : quand ce README, `CLAUDE.md` ou `ROADMAP.md`
divergent du code, c'est la doc qu'on corrige. **Ne jamais présenter une absence de mesure comme un
verdict de marché** — c'est la faute la plus grave que ce produit puisse commettre, elle fait
publier un livre sur une niche vide ou renoncer à une bonne.

---

## Licence

Projet **propriétaire** — © 2026 Baptiste. Tous droits réservés. Voir [`LICENSE`](LICENSE).
Non destiné à la redistribution ou à l'usage commercial par des tiers sans autorisation.
