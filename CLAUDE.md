# CLAUDE.md — IA-Niches (v2, branche `main`)

> Fichier de contexte permanent, lu en priorité à chaque ouverture du dépôt.
> Il s'adresse à l'agent et au développeur, pas à l'utilisateur final.
>
> **La source de vérité est LE CODE** (`01-scripts/` et `web/`), jamais la documentation.
> Quand ce fichier et le code divergent, le code a raison et ce fichier doit être corrigé.
> Les docstrings du dépôt portent les pièges métier mesurés en live : ce sont elles la vraie doc.
>
> Comptages revérifiés le **2026-10-03** (1 643 tests sur 121 fichiers, 52 modules, 34
> variables d'env, 22 endpoints, `server.py` 1 380 lignes). Références de ligne revérifiées le **2026-08-22**
> (audit adversarial doc/code), après les commits
> `7ccb4f8` → `5257323` (authentification, revue de sécurité, fourchette de prix, compositeur
> de trio, lecture des suggestions, retrait de tout affichage de coût, chemin de lancement
> unique).

---

## 1. CONTEXTE PROJET

**Baptiste** : pharmacien français, auteur sur Amazon KDP fr. Il rédige des livres (pas du
low-content), teste vite plusieurs niches, cible exclusivement Amazon.fr.

**Ce que le produit résout** : trouver des niches de livres réellement demandées et réellement
pénétrables sur Amazon.fr, en remplaçant une recherche manuelle de plusieurs heures par un run
automatisé de quelques minutes.

**Le produit est destiné à être VENDU**, pas seulement à l'usage personnel de Baptiste. Dépôt
GitHub privé. Modèle visé : abonnement unique autour de **19 EUR/mois** pour ~30 analyses en
usage loyal, marge **88-94 %**, seuil de rentabilité **1-2 clients**. **Ces trois chiffres sont
des ESTIMATIONS de cadrage établies en session de travail, pas des mesures du dépôt.** Le seul
chiffre sourçable dans le code est « à 30 analyses/mois la marge est de 88 % »
(`usage.py:4-6`) ; ni « 19 EUR », ni « 94 % », ni le seuil de rentabilité n'apparaissent dans
`01-scripts/` ou `web/`. Ordre de grandeur CALCULÉ (pas mesuré) qui rend ces 88 % cohérents :
30 scouts non-fiction au coût de PRODUCTION (0,084 $, §3) = 2,52 $, soit ~2,3 EUR au taux de
change du moment — environ 12 % de 19 EUR. **Le taux de change n'est plus une constante du
dépôt** : `TAUX_USD_EUR` a disparu avec l'affichage des coûts (commit `4165efb`, §5.27) ; toute
conversion en euros est désormais un calcul de tête, à requalifier comme tel.

Corollaire à ne pas inverser : dès **~7 analyses par mois au coût de production**, le coût
technique dépasse les frais d'encaissement d'un abonnement (0,084 $ ≈ 0,077 EUR par analyse ;
les frais d'un encaissement à 19 EUR tournent autour de 0,50 EUR selon le prestataire —
**chiffre hors dépôt, aucun prestataire n'est intégré**, à revérifier au moment de brancher le
paiement). Le seuil serait de ~19 analyses au coût LOCAL, mais §3 interdit de citer ce coût-là
comme coût de production. Une formule antérieure de ce fichier annonçait l'inverse — que les
frais de transaction dominaient — sur la foi du chiffre local : elle est fausse et ne doit pas
revenir.

Conséquence directe sur les décisions techniques, et **asymétrie structurante du produit** :

| Magasin | Cloisonnement | Pourquoi |
|---|---|---|
| `cache.py` (`df-cache.db`) | **MUTUALISÉ entre tous les comptes** | Deux clients qui analysent le même rayon ne le paient qu'une fois. C'est l'économie principale à l'échelle. Y introduire `user_id` « par cohérence » serait une régression économique silencieuse (`cache.py:1`, rappelé dans `auth.py:26-30`) |
| `history.py`, `usage.py`, `jobs.py` | **PAR utilisateur** | Historique, consommation et travaux sont des données personnelles ; le plafond se compte par compte |
| `auth.py` (`comptes.db`) | par nature | Comptes, sessions, tentatives |

**Posture attendue** : factuelle et tranchée. Aucun compliment gratuit. Chiffrer ce qui peut
l'être. Signaler explicitement les zones d'incertitude et les mesures manquantes.

---

## 2. ARCHITECTURE RÉELLE

Application web mono-page, **jusqu'ici purement locale et désormais déployable** (§2.17,
mais rien n'est déployé) : FastAPI (`web/server.py`, **1 171 lignes,
22 endpoints** — `wc -l` + décorateurs `@app`, vérifié le 2026-10-03) + un unique
`web/index.html` de **125 534 octets** (CSS et JS inline, zéro build). **Une dépendance externe subsiste dans la
page** : un `@import` Google Fonts (`web/index.html:8`, Fira Code + Fira Sans) — hors ligne la
page fonctionne mais retombe sur les polices système ; ne plus écrire « zéro dépendance
externe ».

**Cinq** bases SQLite : `df-cache.db`, `jobs.db`, `usage.db`, `history.db`, **`comptes.db`**.
Elles vivent dans `99-logs/` par défaut, et dans **`DATA_DIR`** dès qu'elle est définie —
`storage.py` en est la source unique (§2.17). **52 fichiers `.py`** dans `01-scripts/`.

**TROIS** moteurs indépendants coexistent désormais : le **scout non-fiction**, le **scout
fiction** et le **scout low-content** (§2.11, livré les 2026-08-18/19). Les trois ne se
lancent QUE par `POST /api/jobs` (§2.6).

### 2.1 Authentification et sessions — `01-scripts/auth.py` (347 lignes)

Livrée par le commit `7ccb4f8`. C'est le seul module dont un défaut ne produit pas un mauvais
chiffre mais une **compromission** (`auth.py:1-5`).

- **Aucune dépendance ajoutée** : `hashlib.scrypt` de la bibliothèque standard,
  `SCRYPT_N, R, P, DKLEN = 2**14, 8, 1, 32` (`auth.py:79`), soit ~16 Mo et ~45 ms par
  vérification. Les paramètres sont **écrits dans la base** avec chaque empreinte (colonne
  `params`) pour pouvoir être durcis plus tard sans invalider les comptes existants
  (`_lire_params`, `auth.py:338-347`).
- **Ce qui n'est jamais stocké** : le mot de passe (sel par compte, `secrets.token_bytes(16)`) et
  le jeton de session en clair (seulement son SHA-256, `_empreinte_jeton`, `auth.py:331-335`).
  Lire la base ne permet donc pas de voler une session.
- **Pas d'énumération des comptes**, ni par le message (`verifier()` rend `None` dans les deux
  cas), ni par le **temps de réponse** : un e-mail inconnu déclenche quand même une dérivation
  sur un leurre (`auth.py:265-271`). `hmac.compare_digest` et non `==`.
- **Politique de mot de passe** (`valider_mot_de_passe`, `auth.py:112-129`) : **12 caractères
  minimum**, **128 maximum** — le plafond est contrôlé AVANT tout le reste, son rôle étant
  d'éviter de lancer scrypt sur une entrée démesurée (déni de service non authentifié) — et une
  liste `MOTS_DE_PASSE_INTERDITS` de 26 entrées. Mesure de la revue : le même dictionnaire de
  10 000 entrées tombe dans les **trois** paramétrages de scrypt testés (6,9 / 34 / 60 min) —
  c'est la politique, pas le réglage de scrypt, qui décide si un dictionnaire casse les comptes.
- **Limitation des tentatives** : `MAX_TENTATIVES=8` sur `FENETRE_TENTATIVES_S=15 min`, verrou
  **par e-mail** pour la connexion ; `MAX_INSCRIPTIONS_PAR_CLIENT=10` **par IP** pour
  l'inscription (sonder mille adresses ne déclencherait aucun compteur par adresse). Une
  connexion réussie remet le compteur à zéro. Dépassement en connexion → `TropDeTentatives`,
  traduit en **429** et non 401 : l'utilisateur légitime doit comprendre que c'est le rythme qui
  bloque, pas son mot de passe.
- **Sessions** : `SESSION_TTL_S = 30 jours`. `fermer_session` ne ferme QUE la session courante
  (se déconnecter du téléphone ne déconnecte pas l'ordinateur).
- **Normalisation d'e-mail** : casse et espaces seulement — pas de retrait des points ni du
  `+suffixe`, qui serait un choix de fournisseur et non une règle générale (`auth.py:132-139`).

**LE point de sécurité, à ne jamais défaire** : le `user_id` vient **exclusivement du cookie de
session** (`utilisateur_courant`, `web/server.py:425-438`). Avant `7ccb4f8`, quatre endpoints
l'acceptaient du client (corps de `POST /api/jobs`, paramètre de `/api/usage`, `/api/jobs`,
`/api/history`) — et comme le plafond mensuel se vérifie dessus, **il suffisait d'envoyer un
`user_id` neuf à chaque appel pour dépenser sans limite**, et d'en deviner un pour lire
l'historique d'autrui. **Ne jamais réintroduire un paramètre `user_id` sur un endpoint.**

**Reprise des données `"local"`** (`_adopter_donnees_locales`, `web/server.py:440-459`) : le
PREMIER compte créé peut réattribuer les lignes `user_id='local'` de `history.db`, `usage.db` et
`jobs.db`, **mais seulement s'il le demande** (`reprendre_donnees_locales` dans le corps, case à
cocher côté UI). C'était automatique : sur une instance exposée, le premier visiteur venu
devenait propriétaire de l'historique et de la consommation de Baptiste. Une base absente ou
d'un autre schéma ne fait pas échouer l'inscription (la reprise est un confort, la création de
compte est le service).

### 2.2 Scout NON-FICTION — `run_scout()` (`01-scripts/scout_master.py`, 167 lignes)

Coût : **0,030 $ en local (MESURÉ**, run réel du 2026-07-21, `tutoriel_pdf.py:60`) ;
**0,084 $ avec BSR serveur (CALCULÉ**, jamais mesuré, `tutoriel_pdf.py:61`). La distinction est
portée par la source elle-même : présenter le second comme mesuré fausserait la tarification
construite dessus. Voir §3.

| Phase | Ce qui se passe | Coût |
|---|---|---|
| 0 | `load_dotenv()` puis ouverture du cache SQLite `99-logs/df-cache.db` (si `use_cache=True`, défaut) | 0 |
| 1 — Ideator | `ideate(seed, signals, n=n_ideas)` → **un seul** appel Anthropic en tool-use **forcé** (`tool_choice` figé sur `proposer_niches`, aucun parsing de texte libre). Sortie : `NicheCandidate[]` avec `niche`, `requete_amazon` COURTE (2-4 mots), `satellite_keywords`, `rationale`, `categorie`, `risques` | LLM |
| 2 — Validation demande | `validate(candidates, pause=0.4, max_queries=3)` — par défaut `niche_validator.validate_niches` — interroge `completion.amazon.fr` sur la requête courte puis les satellites. `demand_score` = nb de suggestions distinctes ; `validated` = au moins une requête auto-complétée. Tri par `(validated, demand_score)` décroissant (`niche_validator.py:153`). **Lit aussi le CONTENU des suggestions** (§2.3) | **gratuit** |
| — **Gate de coût** | `shortlist = validated[:n_search]` (défaut 6 côté `run_scout`, 4 côté formulaire). **Une niche non validée ne coûte jamais un appel payant.** Shortlist vide → retour `[]` immédiat | — |
| A — Concurrence | Par niche : cache `search` (clé keyword+location+language, **TTL 15 j**, `scout_master.py:28`), sinon `provider.search()` sur `merchant/amazon/products` en task_post + poll (8 s d'intervalle, 40 polls max, ~320 s), `search_param=i=stripbooks` si `books_only`. **Un échec est attrapé** (`scout_master.py:89-91`) : avertissement en progress, `sr = None`, le run continue — et la niche ressort marquée `concurrence_mesuree=False` (§4.1). On retient les 3 premiers ASIN **organiques** (`n_bsr_per_niche=3`) | DataForSEO |
| B — BSR batché | `resolve_bsrs()` sur l'**union** des ASIN de toutes les niches : dédup, cache par ASIN — **TTL 15 j pour un RANG** (`BSR_TTL_S`, `bsr_source.py:10`) et **3 j seulement pour une ABSENCE de classement** (`ECHEC_BSR_TTL_S`, `:15`) : un livre peut entrer au classement, figer 15 j une non-mesure nous rendrait aveugles à son arrivée ; une fiche NON LUE (panne, tâche jamais prête) n'est, elle, jamais mémorisée, cf. §5.10 —, puis selon `BSR_SOURCE` (§3) | gratuit ou payant |
| C — Scoring | `scoring.py`, fonctions pures : `bsr_stats`, `count_targeted`, **`prix_stats`**, `score_niche` (3 axes pondérés 0,4 / 0,4 / 0,2). Tri par `global_score` décroissant. Si `search is None`, aucun bonus ni malus de concurrence n'est appliqué et le verdict devient « Concurrence non mesurée — à relancer » | 0 |
| D — Verdict IA | `n_verdict=0` **par défaut**, et **aucun appelant ne le remplit** : ni la CLI, ni `_run_scout_job`. Gate de coût assumé (3 verdicts pesaient 78 % du coût d'un run). Le verdict se demande à la pièce via `POST /api/verdict` — mais l'UI ne l'appelle pas, cf. §5.26 | — |

Le paramètre `signals` (mode « à partir de rien » alimenté par des tendances) traverse `run_scout`
et `niche_ideator` jusqu'au prompt, mais **aucun appelant ne le remplit** : il vaut toujours `None`.

**Le nombre d'IDÉES n'est plus un réglage de l'interface** (commit `6d1f134`) : `web/index.html`
n'a plus de champ correspondant ; seul `#search` (« Niches à analyser », **valeur 6**, max 20) reste
réglable. **Attention à un décalage réel dans le code** : `web/server.py:134` définit
`IDEES_PAR_RUN = 10` avec un long commentaire de mesure, **mais cette constante n'est référencée
nulle part** (`grep` exhaustif sur `01-scripts/`, `web/`, `tests/` : une seule occurrence, sa
définition). Le défaut effectivement appliqué est **12**, en dur dans `_run_scout_job`
(`web/server.py:638`) et `_valider_volumes` (`:706`), et `run_scout` a lui aussi `n_ideas=12`
(`scout_master.py:32`). **Le vivier réel d'un run lancé depuis l'UI est donc de 12 idées, pas
10.** Ne pas citer « 10 » comme le comportement du produit tant que la constante n'est pas
branchée.

La mesure qui justifie de ne plus offrir ce réglage tient, elle (30 niches sur « bien-être »,
2026-08-03, `web/server.py:122-133`) : viviers 10 / 20 / 30 → les 4 niches retenues sont dans les
**trois** cas déjà au-dessus du plafond `min(demand_score, 10)` du scoring (`scoring.py:91`).
Élargir le vivier change QUELLES niches sont testées, jamais leur note sur l'axe demande. Gain
mesuré : nul. Coût mesuré : 0,0459 $ pour 30 niches, soit ~0,0015 $ par niche. **À revoir si le
plafond `min(demand_score, 10)` est relevé** — c'est lui qui rend le classement aveugle au-delà
de 10 suggestions, pas la taille du vivier.

### 2.3 Lecture du CONTENU des suggestions — `niche_validator.lire_suggestions` (commit `000947a`)

`demand_score` (le simple compte) sature vite : mesuré sur 30 niches, 16 dépassaient le plafond
du scoring. Il dit « il y a de la demande », jamais « quelle demande ». Les suggestions étant
déjà collectées et gratuites, `lire_suggestions` (`niche_validator.py:55-96`) en tire deux
lectures, rendues comme des **DRAPEAUX et jamais comme des points de score** :

- **`terme_dominant`** : un mot ABSENT de la requête présent dans au moins la moitié
  (`SEUIL_DOMINANCE=0.5`) des suggestions, avec un minimum de `MIN_SUGGESTIONS_DOMINANCE=4`
  suggestions pour que « la moitié » veuille dire quelque chose. Typiquement un auteur ou un
  titre qui tient le rayon. Un mot compte **une fois par suggestion** (répété dans la même
  complétion, il ne prouve pas que plusieurs personnes le cherchent). On le NOMME sans prétendre
  savoir ce que c'est : décider qu'un mot est un nom propre demanderait un dictionnaire, la
  répétition se mesure. Exposé avec `part_dominante`.
- **`intention_informationnelle`** + `marqueurs_informationnels` : la traîne parle d'avis,
  résumés, citations, biographie, analyse… (`MARQUEURS_INFORMATIONNELS`, 16 entrées,
  `niche_validator.py:31-35`). Ces gens veulent l'information, pas le livre.
- **« occasion » et « pdf gratuit » ont été volontairement ÉCARTÉS** de la liste des marqueurs
  (décision de Baptiste, argumentée dans `niche_validator.py:27-30`) : un acheteur d'occasion
  reste un acheteur, simplement sensible au prix. **Ne pas les réintroduire.**
- Comparaison **accents dépouillés** (`_plat`) : Amazon rend « résumé » et « resume ».
- **Zéro suggestion ne conclut RIEN** : ce n'est pas un rayon sain, c'est une absence de mesure.

Les quatre champs remontent tels quels de `NicheValidation` (`models.py:135-141`) à
`ScoredNiche` (`models.py:116-120`) sans passer par aucun axe (`scoring.py:145-149`), et sont
affichés par `blocSuggestions` (`web/index.html:804`).

### 2.4 Scout FICTION — `run_fiction_scout()` (`01-scripts/fiction_master.py`, 206 lignes)

Coût : **0,153 $ pour 3 trios (MESURÉ)**, **0,409 $ pour 8 trios (EXTRAPOLÉ)** —
`tutoriel_pdf.py:62-63`. Six phases (`fiction_master.py:1-8`).

- **A — Ideator** (payant, **un seul** appel LLM pour TOUS les trios du sous-genre) :
  `generate_trios` injecte dans le prompt la liste exacte des tropes et décors autorisés, puis
  **vérifie côté code** — tout trio hors taxonomie est écarté (`fiction_ideator.py:177-180`).
  `n` est un plafond réel (`out[:n]`, `:188`), pas une suggestion. **Compositeur de trio** : §2.5.
- **B — N × SERP**, une par niche (payant, rapide, pas de file d'attente) : `fetch_shelf_asins`
  contraint la SERP au browse node du sous-genre (`rh=n:...`) quand il existe, sinon au filtre de
  rayon lu dans la taxonomie (`i=digital-text` kindle, `i=stripbooks` papier). On garde les
  `n_top=12` premiers ASIN organiques dédupliqués par `dict.fromkeys` (préserve l'ordre : une SERP
  qui répète un ASIN ne doit ni le facturer deux fois ni écraser sa position). 12 et non 20 :
  -40 % de coût ASIN. Le docstring (`fiction_serp_provider.py:25-27`) chiffre les positions
  13-20 à « 0,024 $ chacun » — **lire 0,024 $ pour le bloc de 8, pas par position** :
  `COST_PER_CALL_USD[2] = 0,003 $` par ASIN (`search_providers.py:24`), soit 8 × 0,003 = 0,024 $
  par niche. Formulation encore à corriger dans le docstring.
  **Chaque niche est isolée par try/except** (`fiction_master.py:96-100`) : une niche qui lève est
  écartée et comptée, les rayons déjà payés sont conservés. Aucune survivante → retour `[]`.
- **C — UN SEUL batch ASIN global.** C'est le point du module : union dédupliquée de tous les
  ASIN (`fiction_master.py:109`), passée en un appel `product_raw_batch` (jusqu'à 100 ASIN par
  task_post). La file DataForSEO met ~250 s **quel que soit** le nombre d'ASIN : la payer une fois
  par run au lieu d'une fois par niche fait passer 10 niches de 42 min à 5 min. Bonus : la dédup
  devient inter-niches, et le nombre d'ASIN économisés est annoncé. Cache livre par ASIN, **TTL 15 j** (`BOOK_TTL_S`, `cache.py:13`, **importé** par `fiction_serp_provider.py:8` — jamais redéfini, cf. §5.32).
  Un payload inexploitable est **absent** du dict rendu, jamais une entrée factice.
- **D — Classification des quatrièmes de couverture** (payant, poste LLM dominant). Seuls les
  livres AVEC blurb. Cache de classification (TTL **30 jours**, `CLASSIFICATION_TTL_S`,
  `cache.py:17`) dont la clé porte les cinq choses qui changent le résultat : ASIN + version de
  taxonomie + modèle + SHA1 du prompt système + empreinte des champs de `TropeClassification`
  (`cache.py:144`). Lots de `LOT_MAX=20` livres (20 blurbs ~ 9k tokens ; 100 blurbs pour
  `max_tokens=4000` rendrait la troncature nominale). Le module lit `stop_reason=="max_tokens"`
  et signale la troncature, compare ASIN rendus / ASIN envoyés, ignore tout ASIN halluciné hors
  lot. Les classifications déjà en cache sont annoncées comme « non repayées ».
- **E — Sonde autocomplete** par niche (gratuit) : `probe_niche` sonde la requête du trio ; si
  elle ne rend rien, elle sonde **seulement alors** la requête canonique du sous-genre, pour
  distinguer « trio trop précis » de « sous-genre fantôme ». Barème 0 / 0,5 / 1. Une query vide
  rend immédiatement `mesure=False`.
- **F — Reconstruction + scoring** : le rayon de chaque niche est reconstruit depuis la table
  globale enrichie et `serp_position` est **ré-affectée selon la position dans CETTE niche**
  (`fiction_master.py:157`), pas celle du batch global, pas celle du cache. Les ASIN non enrichis
  sont comptés dans `FictionShelf.n_echecs` et annoncés. `build_report` applique
  `livres_scorables` (3 exclusions : titre gratuit, non-roman, mauvais rayon) **avant** tout
  calcul, puis `depth_score`, `openness_score`, `saturation_trio`, `demand_matrix` et un verdict
  textuel qui porte explicitement ses réserves.
- **Tri final** : profondeur décroissante, saturation croissante à profondeur égale
  (`fiction_master.py:173`).

### 2.5 Compositeur de trio fiction — `ContraintesTrio` (commit `fba99d5`)

Deux modes coexistent volontairement (`fiction_ideator.py:14-32`) : « propose-moi des trios »
(aucune contrainte, **comportement d'origine strictement inchangé**) et « je compose le mien ».
Le second ne remplace pas le premier : des menus SEULS produiraient des trios morts, rien ne
garantissant qu'un décor donné se combine avec un trope donné dans un marché réel. L'IA garde son
rôle — trouver des combinaisons plausibles À L'INTÉRIEUR des contraintes.

- Trois champs : `tropes` (clés imposées), `decor` (clé imposée), `libre` (texte de l'auteur,
  **hors taxonomie par nature** : signalé au modèle comme une piste pour orienter la requête et
  la rationale, jamais imposé comme clé — le classifieur range déjà les clés inconnues dans
  `other`, et c'est ce signal-là qui fait évoluer la taxonomie).
- **Vérification CÔTÉ CODE après la réponse du modèle** (`fiction_ideator.py:181-184`) : un trio
  qui ne porte pas le trope imposé, ou pas le décor imposé, est écarté. On demande au LLM, puis
  on contrôle — un modèle oublie une consigne sous pression, et rendre un trio hors contrainte
  c'est répondre à côté de la question de l'auteur.
- Une clé hors taxonomie **LÈVE** (`build_user_prompt`, `:103-107` ; `_contraintes_fiction`,
  `web/server.py:279-303`, rend une **400**). Les menus étant peuplés depuis la taxonomie, une
  clé inconnue ne peut venir que d'une requête forgée : l'ignorer ferait croire à l'auteur que sa
  contrainte est appliquée.
- **`contraintes_impossibles`** (`fiction_ideator.py:131-137`) : aucun trio rendu **ALORS QUE**
  des contraintes sont posées = impossibilité de **COMPOSITION**, pas verdict de marché. Rien n'a
  été mesuré à ce stade, aucune requête Amazon n'est partie. `fiction_master.py:81-85` le dit en
  toutes lettres à l'utilisateur et rend `[]`. Ne jamais laisser cette liste vide se lire « ce
  marché est mort ».
- `_contraintes_fiction` est **partagée par tous les chemins de lancement** : c'est exactement la
  divergence qu'on vient de payer (le compositeur n'était branché que sur l'ancien flux direct,
  cf. §2.6).

### 2.11 Scout LOW-CONTENT — `run_lowcontent_scout()` (`01-scripts/lowcontent_master.py`)

Troisième moteur, livré les 2026-08-18/19. **Son ordre est INVERSÉ par rapport aux deux
autres, et c'est tout le sujet.** Ailleurs, le LLM propose et l'autocomplete valide. Ici,
l'autocomplete est la SOURCE.

La raison est mesurable : en low-content, la tête de requête (« livre coloriage »,
« registre ») est morte ou tenue par des éditeurs, et l'argent est trois crans plus bas
dans la traîne (« coloriage licorne 3 ans fille », « registre du personnel obligatoire »).
Un LLM à qui on demande des requêtes long-tail invente aussi la demande qui va avec.
Amazon, lui, ne complète que ce que des gens tapent réellement, et il le donne pour rien.

| Phase | Ce qui se passe | Coût |
|---|---|---|
| 0 — Arbre | `autocomplete_expand.expand()` descend les complétions. `alphabet=True` sonde aussi « seed a »…« seed z » : Amazon ne rend qu'une dizaine de complétions par préfixe, la fin de l'alphabet ne sort jamais du préfixe seul. Filtres IP et saisonnalité appliqués ICI, avant tout appel payant | **gratuit** |
| 1 — Classement | `lowcontent_ideator` : le LLM **CLASSE** les requêtes réelles (format × thème × public), il n'en propose pas. Sans graine il bascule en idéation, et chaque proposition repasse par l'arbre — `source="ideation"` dit alors que la demande est une HYPOTHÈSE. En mode classement seulement, la réponse BRUTE de l'outil est mise en cache PARTAGÉ 15 j (`llmlc:`, §2.14) | LLM |
| 2 — Validation | En mode classement elle est DÉJÀ acquise : ces requêtes viennent de l'autocomplete. Les re-sonder confirmerait une tautologie. **Conséquence à connaître : un `validate` injecté est IGNORÉ dans ce mode** | gratuit |
| 3 — SERP | Une par niche, plafond vérifié entre deux. Shortlist triée par `n_enfants` puis profondeur — une requête que les acheteurs affinent ENCORE porte une intention plus forte | DataForSEO |
| 4 — UN batch ASIN | Union dédupliquée. **Le BSR est LU DANS L'ENRICHISSEMENT** : `parse_enriched_book` le parse déjà, et un second `resolve_bsrs` sur les mêmes ASIN les facturait DEUX fois (§5.31) | DataForSEO |
| 5 — Scoring | `lowcontent_scoring`, pur, **QUATRE axes** : demande 0,35 · pénétration 0,35 · rentabilité 0,20 · faisabilité 0,10 | 0 |

**Deux axes qui n'existent pas ailleurs, et ce n'est pas un raffinement.** RENTABILITÉ :
sous 9,99 € de prix catalogue **HORS TVA**, KDP verse 50 % au lieu de 60 %, et le coût
d'impression se déduit ENSUITE — un rayon très demandé à 6,99 € peut ne rien rapporter. Le
prix lu sur amazon.fr est TTC : seuil et redevance se calculent sur `prix_catalogue_ht`
(TVA de 20 % SUPPOSÉE), au format de coupe DOMINANT du top, lu sur les dimensions (grand
format AU-DELÀ de 15,55 cm de large OU de 22,86 cm de haut — bornes strictes, un 6 x 9 po
exact reste standard). §5.39. FAISABILITÉ : un carnet quadrillé
et un cahier d'activités illustré ne se produisent pas dans le même monde.

**Deux signaux de pénétration propres au rayon.** `part_indie` : douze références peuvent
toutes venir de papetiers (Exacompta, Quo Vadis) — invisible dans un comptage de résultats,
décisif pour savoir si un auteur seul peut attaquer. `n_variantes_quasi_identiques` :
**échelle INVERSÉE**, élevé = mauvais (§5.30).

**`norme: true`** (registres, carnets professionnels) : le contenu est fixé par un texte
externe. Piège de lecture à ne jamais inverser — « normé » ne veut pas dire « difficile » :
le contenu étant imposé, la production est SIMPLE (effort 1). C'est la CONFORMITÉ qui est
exigeante, et `lowcontent_verdict` **dégrade un « Go » côté CODE** si aucune
`source_reglementaire` n'est citée. Un registre incomplet expose l'acheteur, qui est un
employeur.

**Modules** : `autocomplete_expand.py` · `lowcontent_taxonomy.py` (36 formats, 8 familles) ·
`ip_filter.py` · `lowcontent_ideator.py` · `lowcontent_scoring.py` · `lowcontent_master.py` ·
`lowcontent_verdict.py` · `data/lowcontent_taxonomy_fr_v1.json`, `data/exclusions_ip.md`,
`data/kdp_print_costs.json`, `data/lowcontent_criteres.json`.

**Les seuils de `lowcontent_criteres.json` sont des HYPOTHÈSES DOCUMENTÉES, pas des
mesures.** Le fichier le dit en en-tête. Le chunk G (jeu de validation, Spearman ≥ 0,5)
n'est pas fait : jusque-là, ne pas les citer comme des critères établis.

### 2.12 Worker séparé — `01-scripts/worker.py`

Le job survivait déjà à la fermeture de l'onglet (il vit dans `jobs.db`). Il ne survivait
PAS au redémarrage du serveur : le thread mourait et le job restait `en_cours` pour
toujours, l'unité de plafond consommée, sans que rien ne le dise.

- **`JobStore.claim_next` est ATOMIQUE** (`BEGIN IMMEDIATE`, verrou d'écriture pris AVANT
  le SELECT). Deux workers sur le même job le paieraient DEUX fois — c'est l'un des deux
  seuls endroits du dépôt où une course coûte de l'argent réel (l'autre est le plafond
  mensuel, §2.13).
- **`orphelins` trie sur l'ABSENCE DE PROGRESSION, jamais sur l'âge** : un run fiction dure
  10 à 15 minutes, l'ancienneté tuerait des runs vivants. Colonne `maj_le`, posée dès la
  réservation, avec migration `ALTER TABLE` de la base existante.
- **`JOBS_MODE=worker`** : le serveur EMPILE seulement. Le défaut reste `thread` — il n'y a
  pas de second processus sur le poste de Baptiste.
- **Pool de `WORKER_CONCURRENCE` fils (5)** et **équité dans la file** : `claim_next` sert
  celui qui occupe le MOINS de créneaux, l'ancienneté ne départage qu'à égalité. Sans ça, un
  utilisateur qui lance cinq analyses fait attendre les neuf autres — le plafond mensuel ne
  protège pas de ça, il compte des analyses sur 30 jours, pas des créneaux à l'instant t.
- **`RUNS_SIMULTANES_MAX` (5)** borne le mode thread, qui lançait un fil par job SANS AUCUNE
  LIMITE. Le créneau est pris AVANT de marquer le job démarré : un job qui attend reste
  « en attente », ce qui est exactement ce qui se passe.

**`recuperer_orphelins` a QUITTÉ ce module** (2026-09-07) : elle vit dans `jobs.py`, et le
serveur l'appelle lui aussi au démarrage (§2.17). Elle n'avait qu'un appelant — la boucle du
worker — alors que le mode par défaut est `thread` : sans worker, un run coupé par un
redémarrage restait `en_cours` POUR TOUJOURS. Anecdotique en local, **nominal en hébergement**,
où chaque mise en ligne redémarre le service. `worker` importe `server`, donc `server` ne peut
pas importer `worker` : la recopier des deux côtés était la seule autre issue, et celle qui
aurait divergé serait justement celle qui ne tourne pas sur le poste où l'on teste (§5.32).
`ORPHELIN_APRES_S` a suivi, pour la même raison.

**Écart assumé avec le plan** : les runners n'ont PAS été extraits vers un `job_runners.py`.
Ils lisent les chemins de bases que les tests isolent en monkeypatchant `server` ; les
déplacer créerait une SECONDE source de vérité pour ces chemins, et un helper d'isolation
qui en oublierait une ferait écrire les tests dans les vraies bases — c'est déjà arrivé
(45 lignes fabriquées dans `history.db`). Le worker importe donc `server`, et hérite au
passage de son garde `_verifier_config_prod()`.

### 2.13 Garde-fous de dépense — la chaîne complète

Cinq garde-fous distincts, qui ne protègent PAS de la même chose. Les confondre est la
source de la moitié des trous trouvés en audit.

| Garde | Ce qu'il compte | Ce qu'il ne protège PAS |
|---|---|---|
| `_borner` / `_borner_texte` | le VOLUME demandé (`MAX_RECHERCHES` 20, `MAX_NICHES_FICTION` **11**, `MAX_RECHERCHES_LC` 20, textes libres 80 car.) | ce qui est dépensé à l'intérieur d'un run |
| `devis.cout_max_estime` | le pire cas AVANT de lancer ; `POST /api/jobs` refuse en 400 | rien après le lancement |
| `CostTracker.verifier(cout_prevu)` | les dollars PENDANT le run, prédictivement | le volume, et les postes non gardés |
| `UsageMeter.reserver_analyse` | les ANALYSES par utilisateur, sur 30 j glissants, **atomiquement** | les appels « à la pièce » |
| `_reserver_appel` (`DEBIT_APPELS_MAX` 40/h) | les analyses À LA PIÈCE, qui imputent `n_analyses=0` | les runs |

**`MAX_NICHES_FICTION` vaut 11 et non 20, et c'est DÉRIVÉ, pas choisi** : c'est le plus
grand nombre de trios dont le devis tient sous `PLAFOND_USD_PAR_RUN`. Au-delà, le run
atteindrait le plafond en route et rendrait un rapport PARTIEL à quelqu'un qui a payé son
plafond entier — ce qui se lit comme une arnaque, pas comme une protection. **Ne pas la
relever sans relever le plafond** : `tests/test_devis.py` tient les deux ensemble, ainsi
que les `max` des champs HTML et les presets.

### 2.6 Endpoints (`web/server.py`) — **22**

**`GET /api/scout` et `GET /api/fiction` N'EXISTENT PLUS** (commit `5257323`). Deux chemins pour
le même travail, dont un seul exercé, divergent — c'est arrivé aux contraintes de composition,
présentes sur le flux direct et absentes du chemin asynchrone pendant tout un commit. De plus la
file de progression du flux direct mourait avec la requête HTTP : fermer l'onglet perdait un run
de 15 minutes. **Ne pas les réintroduire.** `queue` n'est plus importé par `server.py`.

Sauf mention contraire, **tout endpoint exige une session** (`Depends(utilisateur_courant)`,
**14 occurrences** — 14 des 18 routes ; `POST /api/auth/deconnexion` lit le cookie sans
l'exiger).

| Méthode | Chemin | Session | Rôle |
|---|---|---|---|
| GET | `/` | **non** | Sert `web/index.html` tel quel (lecture disque à chaque appel). SEUL endpoint sans session — sinon l'écran de connexion serait inatteignable |
| POST | `/api/auth/inscription` | non | 201 + session. `INSCRIPTIONS_OUVERTES` fermé par défaut ; **le premier compte passe toujours** (amorçage). Inscriptions fermées → **403 avec un message identique quelle que soit l'adresse** (un 409 « déjà pris » sur une adresse connue aurait fait de l'inscription un oracle d'énumération). Inscriptions ouvertes → limitation **par IP**. `reprendre_donnees_locales` (booléen, facultatif) déclenche §2.1. `origine_sure` |
| POST | `/api/auth/connexion` | non | 200 + session. **Un seul message** pour e-mail inconnu et mot de passe faux (401) ; quota épuisé → 429. `origine_sure` |
| POST | `/api/auth/deconnexion` | cookie | 204. Ferme la session **côté serveur** ET retire le cookie : effacer le seul cookie laisserait le jeton valide pour quiconque en a copie |
| GET | `/api/auth/moi` | oui | `{user_id, email}` de la session en cours |
| GET | `/api/lowcontent/formats` | oui | `[{cle, label, famille, norme, effort}]` triés, lus depuis `data/lowcontent_taxonomy_fr_v1.json`. Source de vérité unique du sélecteur de format ; `norme` est exposé pour que l'UI pose son badge sans re-déduire la taxonomie |
| POST | `/api/dossier` | oui | **Dossier de niche en 3 pages** (marché + concurrents, angle et spec, mots-clés et catégories). Accepte `ScoredNiche` ou `LowContentScored` via `type`. Les CATÉGORIES sont incluses par défaut (0 $, déduites des BSR déjà payés) ; les MOTS-CLÉS non (0,006 $) — le défaut ne dépense pas à l'insu de l'utilisateur. **Quand `inclure_mots_cles` est demandé, c'est un QUATRIÈME chemin payant** : gardé par `_verifier_plafond` **et** `_reserver_appel` (`web/server.py:1076-1077`), il impute `n_analyses=0` — il exige une marge sous le plafond sans la consommer. En low-content c'est `scored.niche` (`LowContentNiche`, qui porte requête, catégorie et satellites) qui part au générateur : le `LowContentScored` entier levait AVANT l'appel, l'exception était avalée, et le dossier sortait sans mots-clés, créneau consommé (corrigé le 2026-09-14). Un dossier sans mots-clés ne dépense rien et n'est pas gardé. `/api/pdf` est conservé comme ALIAS et sert le même document |
| GET | `/api/fiction/sous-genres` | oui | `[{cle, label}]` triés, lus depuis `data/fiction_taxonomy_fr_v1.json`. Source de vérité unique du sélecteur : jamais de liste dupliquée en dur côté JS |
| GET | `/api/fiction/taxonomie/{sous_genre}` | oui | `{sous_genre, tropes, decors}` — alimente les menus du compositeur. Sous-genre inconnu → 400 |
| POST | `/api/jobs` | oui | **SEUL chemin de lancement des TROIS scouts.** 202 + `{id}` immédiat. Body `{type: "scout"\|"fiction"\|"lowcontent", + params}` (`_JOB_RUNNERS`, `web/server.py:752`) ; type inconnu → 400. **Devis préalable** (`verifier_devis`, `:783`, 400 si le pire cas dépasse `PLAFOND_USD_PAR_RUN`). Vérifie le plafond (`usage.autorise`, 429) **avant** de dépenser ; **valide sous-genre, contraintes et bornes de volume AVANT de créer le job** (400 immédiate, jamais un 202 suivi d'un job en échec) ; impute `n_analyses=1` ; consigne dans `history.db`. Thread détaché : fermer l'onglet ne tue pas le run. En cas d'exception, le coût déjà engagé est quand même imputé. `origine_sure` |
| GET | `/api/jobs/{id}` | oui | État complet : statut, progression, résultat, coût, erreur, dates. **404 — et non 403 — quand le job appartient à quelqu'un d'autre** : distinguer les deux confirmerait que l'identifiant existe |
| GET | `/api/jobs` | oui | Liste de l'utilisateur de la session, plus récents d'abord. `limit` (20). **Aucun paramètre `user_id`** |
| POST | `/api/jobs/{id}/annuler` | oui | **Arrête UNE analyse** de la session (2026-10-03 : elle bug ou tourne dans le vide). IMMÉDIAT côté données (statut `annule`), COOPÉRATIF côté thread : on ne tue pas un thread, `annulation.verifier()` lève `Annulation` — une **`BaseException`**, jamais une `Exception` (les `except Exception` « un échec ne coule jamais le run » l'avaleraient ; les moteurs relèvent déjà les `BaseException` en imputant le pire cas) — à chaque message de progression, avant une phase payante (`CostTracker.verifier`) et à chaque cycle d'attente du fournisseur (`search_providers`). Contrôle propre à chaque FIL (`threading.local`), lu en base au plus une fois par demi-seconde. **L'argent déjà engagé reste imputé et l'unité de plafond reste PRISE** : arrêter ne rembourse rien, sinon « lancer puis arrêter » serait gratuit (même règle qu'un échec). Aucune notification. `finish`/`fail`/`start` ne font JAMAIS revenir un travail `annule` à un autre état (le thread peut finir après). 404 — jamais 403 — pour le travail d'un autre compte ; 409 si déjà finie ; `origine_sure`. Marche aussi en `JOBS_MODE=worker` |
| DELETE | `/api/jobs/{id}` | oui | **Supprime UNE analyse** de la session (« Mes analyses », 2026-10-03). **404** — jamais 403 — pour le travail d'un autre compte ; **409** pour une analyse pas finie (son thread écrirait dans le vide) ; 204 sinon ; `origine_sure`. Supprime le travail (étapes, résultat, verdicts et mots-clés rangés dedans) et **RIEN d'autre** : ni `usage.db` (supprimer de l'écran ne rembourse rien et ne libère aucune unité de plafond, sinon « supprimer puis relancer » contournerait le plafond mensuel), ni l'historique d'évolution des niches (`history.db`, série partagée par toutes les analyses d'une même niche) |
| GET | `/api/jobs/{id}/stream` | oui | SSE **reconnectable** branché sur `jobs.db` (poll 0,3 s). Rejoue la progression depuis le début à chaque reconnexion, puis `result` + `cost` + `done`. Le job d'un autre compte est traité comme **inexistant**, pas comme refusé |
| GET | `/api/usage` | oui | Consommation du mois **glissant** (fenêtre 30 j, ni calendaire ni cumulative à vie) : `{n_analyses, cout_usd}`. Le backend rend toujours le coût ; **l'UI n'affiche que le nombre d'analyses** (§5.27) |
| POST | `/api/verdict` | oui | Analyse éditoriale d'UNE niche, **sans état** par défaut (la `ScoredNiche` entière dans le body ; body invalide → 400). **`type` : `scout` (défaut), `lowcontent` ou `fiction`** (§2.18) — UN endpoint pour les trois, jamais un second qui ferait diverger les gardes. Mesuré à **0,0283 $** pièce. **Exige une marge sous le plafond** (`_verifier_plafond`) mais impute `n_analyses=0` : il complète une analyse déjà payée. Une réponse du modèle illisible APRÈS l'appel → **502**, et le coût est soldé dans un `finally` : la réservation restait à 0 $ alors que les jetons étaient facturés (§5.29, `tests/test_solde_apres_exception.py`) **Conservation (2026-10-03)** : avec `?job=<id>&cle=<niche>` le SERVEUR range ce qu'il vient de produire sous `verdict` dans la niche du résultat de ce travail (`JobStore.annoter_resultat`, liste fermée de champs, travail de la session seulement — `user_id` du cookie, règle 4). La réponse porte `_conserve` (true/false) ; un échec d'écriture ne fait JAMAIS échouer la réponse, déjà payée. Sans `job`, strictement sans état. Avant ce correctif, rouvrir une analyse ou recharger faisait disparaître un appel payant et proposait de le repayer. **En fiction le champ est `analyse`, jamais `verdict`** : un résultat fiction porte déjà un `verdict`, le TEXTE du moteur et ses réserves. |
| GET | `/api/history` | oui | `{niche, passages[], delta}`. Une niche vue une seule fois rend `delta: null` avec un **200** : « pas encore de recul » est une réponse, pas un échec |
| POST | `/api/kdp-keywords` | oui | Les 7 mots-clés backend KDP, sans état, **~0,006 $ (ESTIMÉ** — docstring `web/server.py:666` et ligne « estime » de `tutoriel_pdf.COUTS` ; aucune mesure datée). Le LLM propose ~22 candidats, le code applique les règles KDP, l'autocomplete confirme **gratuitement**. Même garde de plafond, `n_analyses=0`, même 502 soldé dans un `finally` **Conservation (2026-10-03)** : avec `?job=<id>&cle=<niche>` le SERVEUR range ce qu'il vient de produire sous `mots_cles` dans la niche du résultat de ce travail (`JobStore.annoter_resultat`, liste fermée de champs, travail de la session seulement — `user_id` du cookie, règle 4). La réponse porte `_conserve` (true/false) ; un échec d'écriture ne fait JAMAIS échouer la réponse, déjà payée. Sans `job`, strictement sans état. Avant ce correctif, rouvrir une analyse ou recharger faisait disparaître un appel payant et proposait de le repayer. |
| POST | `/api/pdf` | oui | **ALIAS historique de `/api/dossier`** : sert le MÊME dossier en 3 pages (`build_dossier_pdf`, `web/server.py:1112`), **pas** le one-pager de `positioning_pdf.py` — deux générateurs divergeraient, et ce dépôt sait ce que ça coûte. Sans état, gratuit, aucune persistance serveur, **pas de vérification de plafond** (rien n'est dépensé) |

### 2.7 Gardes de sécurité (revue adversariale, commits `d443ba8` + `8d37ab8`)

51 failles confirmées, 7 écartées. Ce qui est **codé et vérifiable** :

| Garde | Où | Ce qu'il ferme |
|---|---|---|
| `user_id` exclusivement issu du cookie | `web/server.py:246-258` | Plafond contournable à volonté ; lecture de l'historique d'autrui |
| `_verifier_plafond` | défini `web/server.py:394`, appelé en **trois** endroits : `:984` (`/api/verdict`), `:1024` (`/api/kdp-keywords`) et `:1076` (`/api/dossier`, **uniquement** dans la branche `inclure_mots_cles` — un dossier sans mots-clés ne dépense rien). `POST /api/jobs` ne l'appelle pas : il **réserve atomiquement** (`UsageMeter.reserver_analyse`, `:797-801`), après le devis et les bornes | `UsageMeter.autorise` n'avait **qu'un** site d'appel, `POST /api/jobs`, que l'interface n'empruntait pas : le plafond ne protégeait que le chemin inutilisé. **Les trois endpoints qui dépensent vérifient désormais.** `POST /api/pdf` n'a pas de garde parce qu'il ne dépense rien |
| Bornes de volume `_borner` | `_borner` défini `web/server.py:242` ; `MAX_IDEES=30` (`:135`), `MAX_RECHERCHES=20` (`:136`), **`MAX_NICHES_FICTION=11`** (`:144`, **DÉRIVÉ** du plafond de coût, cf. §2.13), `MAX_RECHERCHES_LC=20` (`:147`) | Le plafond compte des ANALYSES, pas des appels payants : une seule « analyse » avec `search=9999` déclenchait des milliers de requêtes DataForSEO pour une unité de plafond. **Borner le volume est la seule protection réelle du MONTANT.** `_borner` **refuse (400) plutôt que de rogner en silence** — un utilisateur qui demande 9999 doit savoir qu'il ne l'aura pas |
| `origine_sure` (anti-CSRF) | `web/server.py:252-277`, appelé sur `/api/auth/inscription` (`:464`), `/api/auth/connexion` (`:505`), `POST /api/jobs` (`:762`) — **3 sites** | Lancer un run dépense de l'argent réel ; `SameSite=Lax` laisse partir le cookie sur une navigation de premier niveau. S'appuie sur `Sec-Fetch-Site` (en-tête interdit au script, non falsifiable) puis sur `Origin` vs `Host`. **Absent = client hors navigateur** (curl, tests) : laissé passer, un tel client n'a pas de cookie ambiant à voler |
| Cloisonnement des jobs | `web/server.py:563` et `:596-597` | Connaître un identifiant suffisait à lire le run, le résultat et le coût d'autrui |
| Limitation des tentatives | `auth.py:53-59`, `:216-242` | Un top-1000 de mots de passe se teste en ligne en moins d'une minute contre une adresse connue |
| Politique de mot de passe | `auth.py:43-47`, `:66-72`, `:112-129` | Dictionnaire ; et déni de service par mot de passe de plusieurs mégaoctets |
| `_corps_json` / `_identifiants` | `web/server.py:385-396`, `:413-423` | Un corps non-JSON ou un champ mal typé remontait en **500** : trace exposée, et signal donné à l'attaquant qu'il a trouvé un chemin non prévu. Désormais **400** |
| `INSCRIPTIONS_OUVERTES` fermé par défaut | `web/server.py:398-411` | Le plafond étant PAR utilisateur, **un compte de plus est un plafond neuf** : l'inscription libre offrait une dépense illimitée à un anonyme |
| Cookie `Secure` **déduit** du protocole | `web/server.py:215-232` | C'était une variable à 0 par défaut « à passer à 1 au déploiement » : un jeton de 30 jours diffusé en clair le jour où quelqu'un oublie de la lire. Lit `X-Forwarded-Proto` puis le schéma. `COOKIE_SECURE=1` peut **forcer** le drapeau, plus jamais le désactiver |
| `httponly` + `samesite=lax` | `web/server.py:120-125` | Vol du jeton par injection de script ; CSRF sur POST cross-site |

### 2.8 Modules

**Orchestration** — `scout_master.py` (non-fiction) · `fiction_master.py` (fiction, batch ASIN
unique par run).

**Comptes** — `auth.py` (§2.1).

**Modèles et scoring** — `models.py` (326 lignes, tous les types pydantic partagés ; porte aussi
de la logique métier subtile : `est_serie`, `est_payant_dans`, extras/echo avec dépouillement des
diacritiques) · `scoring.py` (non-fiction, 151 lignes, 100 % pur) · `fiction_scoring.py`
(`depth_score` BSR-first 0,4 meilleur + 0,6 médiane, `openness_score`, `saturation_trio` — le
différenciateur, impossible sans avoir lu les quatrièmes de couverture —, matrice de demande à
6 issues ; tous les seuils dans un unique dict `SEUILS`, `fiction_scoring.py:18`, calé sur des
rayons mesurés en live).

**Accès données** — `search_providers.py` (seam de l'étape payante : `search`,
`product_raw_batch` jusqu'à 100 ASIN, `product_info_batch`, mapping pur et testé, parseurs de BSR)
· `bsr_source.py` · `niche_validator.py` (**phase 2 entière du scout non-fiction** : le gate
gratuit de §2.2, `validate_niches` triant par `(validated, demand_score)`, **et
`lire_suggestions`**, §2.3) · `amazon_autocomplete.py` (deux variantes volontairement distinctes :
`fetch_json_strict` qui lève, `_default_fetch_json` qui avale) · `amazon_product.py` (BSR gratuit
par scraping direct ; même partage : `fetch_bsr_strict` lève sur une fiche non lue et n'est le
défaut que de `resolve_bsrs`, `fetch_bsr` garde son `None` pour `launcher` et `demo_free`) · `util.py` (`http_get` : headers navigateur + retry, `getter` injectable ;
il **re-lève après ses retries** — c'est ce qui permet à §5.10 de distinguer une panne d'un
signal absent) · `fiction_serp_provider.py` (scindé en `fetch_shelf_asins` rapide appelable
N fois et `enrich_asins`, la file lente appelée une fois) · `fiction_books.py` (mappe un payload
ASIN réel vers `EnrichedBook`, gère les formes atypiques observées sans jamais lever ; lit la
pagination sous « Nombre de pages de l'édition imprimée », §5.37) ·
`fiction_autocomplete.py` (sonde à deux barreaux).

**LLM** — `niche_ideator.py` · `niche_verdict.py` · `kdp_keywords.py` · `fiction_ideator.py` ·
`fiction_classifier.py` · `lowcontent_ideator.py` · `lowcontent_verdict.py` · `fiction_verdict.py` (§2.18). Tous en **tool-use
forcé**, jamais de parsing de texte libre. **Cinq sont en mode STRICT** (`strict: true` et
`additionalProperties: false` sur CHAQUE objet) : `lowcontent_ideator` depuis le 2026-09-13
(§2.14), puis `lowcontent_verdict`, `fiction_ideator`, `kdp_keywords` et `fiction_classifier`
depuis le 2026-09-14 (`tests/test_strict_lecture_defensive.py`, qui lit l'outil ENVOYÉ, §5.32).
Le strict ne protège pas d'une troncature : ces quatre-là lisent aussi `block.input`
DÉFENSIVEMENT (`_json_si_texte` décode une chaîne JSON valide ; le reste est écarté et compté,
jamais deviné). Trois formes de ce « deviné » existaient : `kdp_keywords` faisait `extend` d'une
CHAÎNE (le rejeu a rendu sept emplacements d'une lettre, qu'une sonde confirmait) ; une
`confiance` illisible valait `0/10` dans `lowcontent_verdict` (elle LÈVE désormais, un zéro se
lirait comme un jugement) ; un seul champ mal typé emportait les 19 autres classifications
payées d'un lot du classifieur. **Acceptation du strict par l'API avec les propriétés
facultatives de ces quatre schémas : non vérifiée** (seul `lowcontent_ideator` l'est, par le run
réel). `niche_ideator` et `niche_verdict` restent hors strict : ils passent par pydantic et
lèvent une `ValidationError` typée.

**Place de marché** — `marketplace.py` (§2.15) : source unique de `location_code`,
`language_code`, identifiant d'autocomplete et domaine des fiches. `MARKETPLACE=fr` par
défaut ; toute autre valeur **lève**.

**Notification** — `notification.py` (§2.16) : message de fin d'analyse, éteint par défaut,
qui ne contient jamais le résultat.

**Infrastructure** — `cache.py` (clé/valeur SQLite **partagé cross-user**, TTL, connexion par
appel + WAL) · `cost_tracker.py` (coût réel : appels DataForSEO + tokens LLM, grille par modèle)
· `jobs.py` (magasin des travaux, **et `recuperer_orphelins` depuis §2.12**) · `usage.py` ·
`history.py` (la seule fonction qui répond à « est-ce que ça bouge ? ») ·
**`storage.py` (§2.17, source unique du répertoire des cinq bases)** ·
`fiction_taxonomy.py` (chargement/validation de la taxonomie, source de vérité
unique des filtres de rayon et des libellés Amazon, rend des copies profondes).

**Sorties** — `positioning_pdf.py` (one-pager, Helvetica core, assainisseur latin-1, dégrade
proprement sans verdict) · `tutoriel_pdf.py` (script autonome, exposé par aucun endpoint ;
`python 01-scripts/tutoriel_pdf.py` régénère les deux PDF à la racine ; constantes
`COUTS` / `ENV_VARS` / `ENDPOINTS` / `GLOSSAIRE` / `VERDICTS` / `PIEGES` / `DEPLOIEMENT`).
**`COUTS` est la seule source du dépôt qui étiquette chaque chiffre mesuré / calculé /
extrapolé / estimé.** `ENDPOINTS` couvre bien les **18** routes actuelles et `ENV_VARS` est à jour
sur `INSCRIPTIONS_OUVERTES` et `COOKIE_SECURE` ; deux tests le tiennent
(`tests/test_tutoriel_pdf.py:100,118`) en lisant `web/server.py` et les `os.getenv` du code comme
source de vérité plutôt qu'en figeant une liste. **Trous connus, non couverts par ces
tests** : (a) `ENV_VARS` ne couvre que **27 des 34** variables lues — il ignore `DEBIT_APPELS_MAX`, `LOWCONTENT_IDEATOR_MODEL`, `LOWCONTENT_VERDICT_MODEL`, `PLAFOND_USD_PAR_RUN`, `RUNS_SIMULTANES_MAX`, `WORKER_CONCURRENCE` et `WORKER_REPOS_S`, parce que le test ne vérifie que le sens « documenté ⇒ lu » et jamais
l'inverse ; (b) `DEPLOIEMENT` contenait une entrée « Utiliser les travaux asynchrones, pas les
endpoints SSE » qui référençait des endpoints **supprimés** — corrigée le 2026-08-22. Les `PIEGES`, le `GLOSSAIRE` et
`DEPLOIEMENT` ne sont vérifiés par personne.

**Outillage dev** — `fiction_validation.py` + `build_validation_set.py` + `validate_classifier.py`
(set de ~50 livres, export xlsx pour correction humaine, mesure de l'accord IA/humain contre la
porte des 80 %) · **`lowcontent_validation.py` + `build_lowcontent_validation_set.py`**
(calibration du scoring low-content, §2.14) · `demo_free.py` (smoke test CLI des deux canaux gratuits : autocomplete et BSR
scrapé ; couvert par `tests/test_demo_free.py`).

**Entrée CLI, GRATUITE et seulement gratuite** — `launcher.py`, lancé par `IA-Niches.bat`.
Deux sondes : autocomplete et BSR scrapé. **Son option 3 (« idées de niches par l'IA ») a été
RETIRÉE le 2026-08-18, sur décision de Baptiste.** Elle appelait `generate_niches` sans compte,
sans `_verifier_plafond`, sans `UsageMeter` et sans même un `CostTracker`. Le montant n'était pas
le sujet (~0,02 € annoncés) : c'était le SEUL chemin du dépôt à dépenser sans laisser de trace
dans `usage.db`, or c'est `usage.db` qui porte tout le raisonnement de marge — ce qu'il ne voit
pas, personne ne le voit.
**Ce module ne doit jamais rappeler un chemin payant** : `tests/test_launcher.py` est le cliquet,
et il échoue si `niche_ideator`, `run_scout`, `search_providers` ou `dataforseo` réapparaissent
dans le fichier. Sa fixture coupe en outre le SDK et le HTTP sortant avant chaque test — écrite
après qu'un test a déclenché un vrai appel Anthropic (§6.1).
`IA-Niches-Web.bat` lance `python web\server.py` : c'est le point d'entrée réel du produit.

### 2.9 Interface (`web/index.html`)

- **Écran de connexion occultant** (`initAuth`, `:1276-1365`) : tous les endpoints sauf `/`
  exigent une session ; sans cet écran l'utilisateur ne verrait que des 401. Au chargement,
  `GET /api/auth/moi` décide d'entrer ou de sortir. Bascule connexion / inscription, case
  « reprendre mes données locales » visible en inscription seulement, et **message explicite
  quand la reprise a eu lieu** (silencieuse côté serveur : ne pas la dire laisserait croire que
  l'historique antérieur est perdu).
- **Un seul chemin de lancement** (`lancerTravail`, `:911-934`) : `POST /api/jobs` puis
  `EventSource` sur `/api/jobs/{id}/stream`. L'id est mémorisé en `localStorage` par onglet —
  **trois clés** : `ia-niches-job-scout`, `ia-niches-job-fiction`, `ia-niches-job-lowcontent` — et
  `reprendreTravail` s'y raccroche au chargement — **un rechargement reprend le run en cours**, et
  un run terminé pendant l'absence est retrouvé et affiché — **et `vue.jobId` est posé dans les DEUX cas** (travail en cours repris, travail terminé retrouvé) : c'est là que se range l'analyse payée à la pièce, et le chemin « terminé » l'oubliait (rechargement après la fin d'un run = analyse suivante non conservée ; corrigé le 2026-10-03, `tests/test_conservation_analyses.py`).
  **Les trois appels doivent vivre dans `entrer()`, jamais au niveau module** : celui du
  low-content y était, donc il partait AVANT que la session soit confirmée, se prenait un 401 et
  ne reprenait rien — un run de neuf minutes perdu à chaque rechargement, en silence, l'onglet
  réaffichant un formulaire vide comme si rien n'avait tourné. Corrigé le 2026-08-22. Le flux rejouant TOUTE la progression, la liste
  d'étapes est vidée à chaque raccrochage pour ne pas empiler deux fois les mêmes lignes.
  Une **429** est traduite en « limite atteinte, rien n'a été lancé », jamais en « erreur ».
- **Aide contextuelle** : une pastille « ? » fixe ouvre un mini-tutoriel **par onglet**
  (`AIDE`), chacun avec sa section « Pièges de lecture » — **trois entrées, `nf` / `fic` / `lc`**.
  `ongletActif()` est une **table explicite** et non une cascade booléenne : la version
  `? 'fic' : 'nf'` a survécu à l'ajout du troisième onglet et rendait `'nf'` sur `#tab-lc`,
  l'auteur lisant donc les pièges de la NON-FICTION en regardant un rayon low-content, sans que
  rien ne le signale. Une vue ajoutée sans sa ligne se voit désormais (`AIDE[undefined]`).
  Plus un glossaire en bulle unique partagée, survol **et** clic/tap (une tablette ne survole
  rien), épinglé jusqu'à Échap.
- **Aucun montant nulle part** : ni `TAUX_USD_EUR`, ni `fmtUsd`/`formatCost`, et `grep` rend
  zéro occurrence de `usd` (§5.27). Attention en vérifiant : le caractère `$` est omniprésent
  dans `index.html` — c'est l'alias de `document.querySelector` et le marqueur d'interpolation
  des gabarits, pas un symbole monétaire. `fmtEur` (`:1048`) sert **uniquement** au prix des
  LIVRES, donnée de marché.
- **Refonte « Vif » (2026-10-03)** : moins de texte, un emoji porte le sens, un chiffre porte la
  preuve, la phrase se déplie. Les trois moteurs restent trois ENTRÉES nommées par ce qu'on
  écrit (📘 / 📖 / 📓) : un auto-routage depuis un champ libre serait refusé, un mauvais
  aiguillage consomme une unité de plafond et rend des chiffres plausibles hors sujet. **Règle
  qui tient la simplification** (`tests/test_ux_v3.py`) : on replie une EXPLICATION, jamais une
  MISE EN GARDE — « l'ordre n'est pas un classement », « pas un rejet », « non mesuré », les
  éditeurs illisibles à côté de la part indie, le seuil 9,99 € HT restent visibles. Les
  alertes visibles distinguent un FAIT (barème KDP, redevance négative : ⚠️) d'un seuil
  d'HYPOTHÈSE non calibré (redevance sous 2 €, éditeurs > 50 % : ℹ️, fond neutre). Les
  VARIANTES n'alertent pas sur la carte (le score les ignore depuis le 2026-09-30,
  `variantes_max=1000`) : le chiffre reste dans « Toutes les mesures », élevé = mauvais.
  Une couleur seule ne porte jamais un jugement : drapeau texte ou `aria-label`. Le CSS de la refonte est une surcouche en FIN de feuille (« Surcouche v3 »), les
  couches v2 et « Foyer » en dessous ne sont pas purgées.
- **Compositeur de trio** : `#fic-tropes` (multi-sélection), `#fic-decor`, `#fic-libre`, peuplés
  par `/api/fiction/taxonomie/{sous_genre}` et **rechargés à chaque changement de sous-genre**
  (garder les anciens ferait composer un trio impossible, refusé ensuite par le serveur sans que
  l'auteur comprenne). Champs vides = mode « propose-moi des trios ».

### 2.10 Tests

**1643 tests** sur **121 fichiers** `tests/test_*.py`, **1643 passés, 0 ignoré, 0 échec,
0 erreur**, code de sortie 0 (`python -m pytest -p no:warnings`, relancé le 2026-10-03,
compteurs lus dans le rapport `--junit-xml` et non dans la sortie console ; la suite avait
connu des échecs INTERMITTENTS, cf. §5.33).

**Données RÉELLES d'abord, et tout écart DÉCLARÉ dans le docstring** — règle née du run 4
(§5.37). Fixtures réelles versionnées : `fixtures/fiction/v2_asin_payloads.json` (8 captures
amazon.fr du 2026-07-20), `fixtures/cache_calibration_run4_reel.json` (état du cache après le
run 4 pour les 31 requêtes du classeur : 31 SERP, 185 fiches, 84 classifications, extrait en
`?mode=ro` ; seule altération, les organiques tronqués aux 12 premiers), et
`fixtures/bsr_scrape_fr_reel.json` (29 extraits `BsrInfo.raw` réels, déjà débalisés et tronqués
à 300 caractères — pas le HTML complet). Versionner l'état du cache n'est pas un luxe : les
tests qui COPIAIENT `99-logs/df-cache.db` (ignoré par git) sortaient IGNORÉS sur tout clone
neuf. Pour la même raison, `fixtures/asin_fr_raw.json` (ignoré par git) ne sert à aucun test
versionné. `tests/outils_calibration.py` porte ce chargement ; `conftest` redirige sous
`tmp_path` les captures de la CLI de calibration et fait LEVER toute purge dont le cache résolu
est le vrai `99-logs/df-cache.db` — garde de TEST : dans le code de production il interdirait à
Baptiste la purge qu'il a décidée.

**« 0 ignoré » est la moitié importante de cette ligne, et elle a coûté cher à établir.**
`httpx` et `pypdf` ne sont importés par aucun module de production — ils ne figuraient donc
pas dans `requirements.txt`. Sur un poste où ils manquent, les tests concernés sortent en
`pytest.importorskip` : la suite affiche un vert complet **en ayant ignoré 136 tests, dont
TOUTE la couche serveur** (`test_server_*`, `test_securite_*`, `test_history`) — donc
l'authentification et les gardes de dépense. Mesuré le 2026-09-06 : 818 passés / 156 ignorés
sans les deux paquets, 954 / 20 avec, 974 / 0 une fois `node` disponible. **Toujours lire le
nombre d'IGNORÉS avant d'annoncer une suite verte** : c'est la même famille que §5.26, un
vert qui ne prouve pas ce qu'on croit qu'il prouve.

Deux fichiers exercent l'interface pour de vrai plutôt que d'y chercher des chaînes :
`tests/js_harness.py` extrait les fonctions de rendu PURES de `web/index.html` et les
APPELLE avec node (skip explicite si node est absent). C'est ce qui distingue un test de
présence d'un test de comportement — cf. §5.26, où la présence passait au vert sur des
boutons morts.
`python -m pytest` depuis la racine (`pytest.ini` fixe `pythonpath=01-scripts`, `testpaths=tests`).
**Tous hors-ligne** : chaque dépendance lourde (client Anthropic, provider DataForSEO, fetch HTTP,
sonde autocomplete) est injectable par paramètre. Aucun test d'intégration réseau.
Fichiers ajoutés par les derniers commits : `test_auth.py`, `test_server_auth.py`,
`test_securite_depense.py`, `test_securite_inscription.py`, `test_isolation_bases.py`.
Deux fichiers testent l'interface en lisant `web/index.html` comme du texte
(`test_ux_glossaire.py`, `test_ux_kdp_historique.py`) — mais ils vérifient la **présence** des
chaînes, pas leur **atteignabilité** (§5.26).

### 2.14 Calibration du scoring low-content — `lowcontent_validation.py` (G1)

Les seuils de `data/lowcontent_criteres.json` sont des **HYPOTHÈSES** : `variantes_max=6`,
`part_indie_bonne=0.5`, `redevance_min_bonne=2.0` n'ont été confrontés à aucun rayon réel.
Le moteur rend des chiffres cohérents entre eux ; rien ne dit qu'ils correspondent au
terrain. Ce module produit la mesure qui manque.

**Le protocole INVERSE celui du classifieur fiction, et c'est le point.** En fiction,
Baptiste CORRIGE des étiquettes que l'IA a produites. Ici il étiquette des requêtes AVANT
toute analyse (`bonne` / `mauvaise` / `morte`) : son jugement est la référence. Si l'IA
choisissait les requêtes à juger, on calibrerait le scoring sur lui-même.

Modes du CLI : `--gabarit` écrit un classeur pré-découpé par famille (8 familles
× 4 lignes, liste déroulante sur la colonne d'étiquette) ; `--xlsx` sonde gratuitement
chaque requête puis lance le run payant **sur ces requêtes-là** et écrit le rapport JSON ;
`--rejouer` et `--purger-fiches-sans-pages` ne dépensent rien (voir « quatrième run » plus bas).
Plafond de dépense explicite (`--plafond`, 2 $ par défaut). Coût d'un jeu de 30 requêtes :
au pire **~0,80 $ pour 31 requêtes sur un poste résidentiel, ~1,35 $ avec `BSR_SOURCE=dataforseo`** (`devis.cout_max_estime`, cache vide : une SERP et
six fiches ASIN par requête, plus un appel LLM) — **calculé, pas mesuré**. L'estimation de
« 0,15-0,25 $ » écrite ici au départ ne sortait d'aucun calcul et était fausse d'un facteur 3.
**Durée : les SERP partent UNE PAR UNE** (`lowcontent_master`, phase 3) — 40 à 250 s chacune,
donc 20 min à 2 h pour 30 requêtes selon la file DataForSEO. `--inclure-saisonnier` fait scorer
les requêtes saisonnières au lieu de les écarter : le filtre saisonnier est un réglage du
PRODUIT, pas un seuil qu'on calibre.

**Relu avant le premier run réel, le jeu de 31 requêtes de Baptiste a fait apparaître cinq
défauts silencieux, tous invisibles à 12 requêtes** (`tests/test_calibration_31_requetes.py`) :
(1) l'ideator ne FORÇAIT pas la requête verbatim — le prompt le demandait, le code gardait le
texte réécrit par le modèle (« tresor » accentué), qui sortait ensuite de l'appariement et
remontait comme un faux négatif attribué au gate gratuit ; (2) une requête inventée en mode
classement était gardée avec `source="autocomplete"`, soit une demande inventée présentée comme
observée ; (3) `max_tokens=4000` fixe et `stop_reason` jamais lu — 31 niches tronquaient en
silence ; (4) `n_ideas` (12) plafonnait la shortlist sans message, ce qui touchait AUSSI le
produit — un client demandant 20 recherches en obtenait 12 ; (5) la CLI plantait APRÈS la
dépense et AVANT d'écrire le rapport (`total_usd` formaté comme un attribut alors que c'est une
méthode, et « 🟢 » / « ⚠ » imprimés sur une sortie cp1252). Le JSON s'écrit désormais avant
toute ligne d'affichage.

**Puis un pré-mortem adversarial (4 angles, chaque constat soumis à un réfutateur) en a trouvé
cinq autres, que la répétition à blanc ne pouvait pas voir — son faux modèle rendait TOUT ce
qu'on lui donnait** (`tests/test_calibration_premortem.py`) :

1. **La RÈGLE DE SÉLECTION du prompt** (« ne retiens que les requêtes à DEUX spécificateurs…
   écarte le reste sans le signaler ») faisait trier au modèle le jeu qu'on veut mesurer : une
   quinzaine des 31 requêtes, surtout les « morte ». Elle est voulue dans le PRODUIT (l'arbre
   rend 80 requêtes) et fausse pour une MESURE. `classer_toutes=True` — imposé par la CLI,
   jamais optionnel — REMPLACE ce paragraphe (deux consignes opposées dans un même prompt,
   c'est laisser le modèle choisir) ; toute requête fournie et non rendue est nommée, et en
   produit le tri est au moins compté. Le rapport sépare `ecartees_*` (filtre IP ou
   saisonnier, recalculés avec les MÊMES fonctions que le moteur) de `non_rendues` (omises,
   tronquées, plafond) : aucun gate ne joue en mode classement, les verser dans `ecartees_*`
   les faisait passer pour des rejets « pour zéro centime » alors qu'elles étaient dans un
   prompt payé. **Une « morte » non scorée ferme la porte** : « aucune morte en vert » est
   INDÉCIDABLE pour elle, pas satisfait (règle 3).
2. **Plus de 100 ASIN en un seul task_post** : la limite DataForSEO tronquait la fin du lot en
   silence — et la FICTION du produit y était exposée (11 trios × 12 = 132).
   `product_raw_batch` poste par lots de `LOT_ASIN_MAX=100`, **tous AVANT la première
   lecture** : la file est par tâche, poster puis poller lot par lot la ferait payer une fois
   par lot.
3. **Un rang « Fournitures de bureau » lu comme un rang « Livres »** : `parse_bsr_rank` rend le
   rang quel que soit le rayon, et un carnet est souvent classé hors Livres. +0,70 mesuré sur
   un score global, assez pour faire passer une morte en vert (§5.5). Seul le rang du rayon
   Livres hors gratuits entre dans les seuils — même règle que `est_payant_dans` en fiction.
   **Un rang au rayon illisible non plus** : l'écarter ne coûte qu'une absence de mesure, le
   garder pouvait valoir +2 en demande.
4. **Une sonde autocomplete en panne lue comme « zéro complétion »** : `expand` prenait la
   version laxiste par défaut, qui avale un 503 et rend `[]` — écrit ensuite dans le cache
   MUTUALISÉ pour 15 jours, donc « Amazon ne complète rien » pour tous les comptes. La sonde
   STRICTE est désormais le défaut (`_sonder` laissait déjà remonter les exceptions ; encore
   fallait-il que la panne en soit une). Côté calibration, une niche à demande non mesurée
   sort du Spearman (`n_demande_non_mesuree`) : son axe demande reposait sur un minimum
   inventé (`demand_score=1`).
5. **Les sous-catégories lues — et facturées — dans le batch ASIN, puis jetées** : le dossier
   low-content annonçait « donnée non mesurée ». Elles sont reprises, converties au schéma
   `{category, rank}` que lit `categories.py` (le parseur des fiches écrit `{rang, categorie}`,
   et une recopie brute se ferait écarter en silence). Rayon Livres seulement.

**Enfin, une revue adversariale du CORRECTIF lui-même (4 angles, 16 agents) a trouvé ce qu'il
cassait ou corrigeait à moitié** (`tests/test_calibration_revue.py`) :

1. **La sonde stricte tuait le job du produit** — le défaut le plus grave, confirmé par les
   quatre angles. Passer l'autocomplete en strict pour ne plus écrire une panne dans le cache
   mutualisé faisait remonter UN seul 503 parmi 80 sondes jusqu'au job : échec, unité de
   plafond consommée, rien à l'écran — là où le run continuait avant. §5.29 inversé par un
   correctif de §5.10. **La sonde reste stricte ; c'est `expand` qui absorbe une panne PAR
   SONDE** (rien en cache, parent à `n_enfants=None`, pannes annoncées) et ne lève que si
   AUCUNE n'aboutit. Le master s'arrête alors AVANT toute dépense et le dit — continuer
   basculerait en idéation sur la graine, c'est-à-dire sur une demande inventée. En
   idéation, la re-sonde de chaque proposition (APRÈS l'appel LLM payé) pose `None` au lieu
   de tuer le run. Les tests tournent sur le MASTER avec la sonde par défaut : ceux d'avant
   appelaient `expand` isolé, la régression leur était invisible.
2. **Un lot ASIN qui échoue abandonnait le lot déjà facturé.** Le découpage par 100 posait un
   nouveau cas : 2e envoi qui lève → sortie avant tout poll → les 100 tâches du 1er lot, créées
   donc facturées, ni relues ni imputées, puis repayées par le canal BSR. Un lot en échec est
   désormais sauté et annoncé, les autres sont relus, et `enrich_asins` impute
   `taches_creees` (le seul endroit qui sait ce que DataForSEO a réellement créé) — le pire
   cas si la relecture elle-même lève.
3. **La porte ne se fermait que pour une voie sur trois.** Une « morte » à SERP tombée
   (« ⚪ », jamais verte, mais son score n'a jamais vu le rayon) ou à demande non mesurée est
   aussi indécidable qu'une morte omise. `mortes_indecidables` réunit les trois voies.
4. **Un rejet du filtre IP APRÈS le modèle** (marque glissée dans le libellé ou les
   satellites d'une requête propre) finissait en « non rendue ». Il ne se devine pas en
   rejouant le filtre sur la requête : l'ideator le remonte par `journal_rejets`.
5. **Le devis ignorait que la réponse du modèle grandit avec n** (poste lu dans l'ideator et
   la grille de `cost_tracker`, jamais recopié), et l'enrichissement — le poste le plus lourd
   — était vérifié à 0 : il ne refusait qu'APRÈS avoir dépassé. Il est désormais prédictif.

**Porte du plan, conjointe : Spearman ≥ 0,5 ET aucune requête « morte » en 🟢.** Une
corrélation honnête qui recommande quand même un rayon mort ferait publier dans le vide.

**Deux conditions de MESURE COMPLÈTE s'y ajoutent depuis le 2026-09-29** (décision de
Baptiste, pré-mortem du run 6) : **toutes** les requêtes analysables doivent être calibrées
(`n_calibrees == n_requetes - écartées`) et **au moins une « morte » doit avoir été SCORÉE**
(`n_mortes_scorees`, exposé au rapport et à l'écran). Les deux ferment en INDÉCIDABLE, jamais
en échec, et le conseil suit la cause. Mesure qui les a fait ajouter, sur les entrées réelles
du run 5 rescorées : un jeu amputé à 10 niches sur 46 sortait la porte **FRANCHIE** avec un
Spearman de **+0,522**, contre **+0,462** pour le run complet — ce sont les « mortes » qui
portent le signal (+0,219 sans elles), donc **l'échec partiel est le scénario qui FABRIQUE un
faux vert**, pas celui qui le dégrade. Et « aucune morte en vert » se vérifiait sur l'ensemble
vide dès que les neuf mortes étaient toutes écartées ou non rendues. **Les écartées par les
filtres gratuits (IP, saisonnier) restent hors décompte** : ce sont des gates du PRODUIT, et
la décision antérieure qui refusait de leur faire fermer la porte tient toujours. Assertion
retournée au passage : une « bonne » NON RENDUE ferme désormais la porte
(`tests/test_porte_mesure_complete.py`, `test_calibration_premortem.py`).

**Et une condition de DÉCIDABILITÉ, qui n'est pas un troisième critère** (2026-09-13, avant
le premier run payant) : `n_part_indie_mesuree` et `n_redevance_mesuree` doivent être non
nuls. Le trou trouvé : un run dont le batch ASIN tombe garde des scores parfaitement
calculables — la SERP fournit encore titres, prix, concurrents et variantes, et le BSR est
rattrapé gratuitement par le canal scrape —, donc un **Spearman calculable et une porte qui
s'ouvre**, alors que `part_indie` et `redevance_estimee` valent `None` partout
(`redevance_estimee(12.99, None) is None`, vérifié). La calibration aurait affiché « ✅ PORTE
FRANCHIE » et serait sortie en code 0 sans avoir pu confronter `part_indie_bonne` ni
`redevance_min_bonne` — deux des trois seuils qu'elle existe POUR régler. Même logique que
`mortes_indecidables` : indécidable n'est pas satisfait (règle 3). **Le seuil est « au moins
une »**, jamais une proportion : exiger « la moitié des niches » inventerait un seuil de son
propre chef (§4.2) ; les deux compteurs sont dans le rapport, c'est Baptiste qui juge si la
mesure suffit. **Un correctif proposé par l'audit — `n_calibrees == n_requetes` — a été
ÉCARTÉ après vérification : dans le scénario même qu'il visait, SERP et sonde ayant réussi,
les 31 niches restent calibrables et la condition ne se déclenche jamais.** Trois fixtures
existantes ont dû être rendues réalistes (elles décrivaient sans le dire un enrichissement
tombé) ; **aucune de leurs assertions n'a été touchée**.

**Premier run RÉEL, le 2026-09-13 : refusé en bloc — et c'est ce refus qui a fait apparaître
deux défauts** (`tests/test_calibration_run_refuse.py`). Compte DataForSEO neuf, non VÉRIFIÉ :
toute requête réelle répond `40104` (« Please verify your account »), posé à la RACINE du
JSON, sans aucune tâche. Coût : 0 $ chez DataForSEO, **0,0905 $ chez Anthropic** — le
classement part avant la première SERP, et `lowcontent_ideator` n'avait alors aucun cache,
donc une relance le repayait (cache du classement depuis le 2026-09-14, plus bas). **`appendix/user_data` répond `20000` sur un compte non vérifié : il prouve
l'authentification, pas le droit d'utiliser l'API.** `appendix/errors`, gratuit lui aussi,
renvoie bien `40104` : c'est lui qui discrimine. Les deux défauts :
(1) **le motif du refus était jeté.** `search` ne lisait que `tasks[0]` et a affiché
« task_post refusé : None None » trente et une fois ; `product_raw_batch` ne levait rien, ne
créait aucune tâche et ne disait pas pourquoi — exactement ce qu'un solde épuisé en cours de
run produirait. `_motif_refus` (`search_providers.py`) lit la tâche, puis la racine ; le batch
verse les refus de compte ET les refus par tâche dans `lots_en_echec`, qu'`enrich_asins`
annonce déjà. Ce motif est le texte de DataForSEO — il ne porte aucun identifiant — mais il
apparaît aussi dans la progression de l'interface web et y nomme le fournisseur.
(2) **La CLI conseillait « corriger data/lowcontent_criteres.json » avec 0 niche calibrée** :
suivi, ce conseil réglait les seuils sur rien. `RapportCalibration.porte_indecidable` (défaut
PESSIMISTE `True`) sépare une porte fermée faute de mesure complète d'une porte fermée PAR la
mesure ; seule la seconde renvoie aux critères. Choix assumé : un Spearman calculé et mauvais
reste indécidable si une « morte » manque. Le code de sortie ne change pas (2 dans les deux
cas). **Écarté par Baptiste** : un contrôle préalable gratuit par `appendix/errors`, avant
l'appel Anthropic, qui aurait économisé les 0,0905 $.

**Deuxième run réel, le même jour : planté APRÈS l'appel payé**
(`tests/test_calibration_run_plantage.py`). Compte vérifié, 31 requêtes sondées, puis
`AttributeError: 'str' object has no attribute 'get'` dans `lowcontent_ideator` : le modèle a
rendu des niches sous forme de TEXTE là où le schéma attend des objets. Les MÊMES 31 requêtes
étaient passées au run précédent — même entrée, autre forme de sortie. Coût : ~0,09 $
d'Anthropic de plus, 0 $ chez DataForSEO, **aucun rapport**. Deux défauts :
(1) **l'outil n'était pas en mode STRICT.** Sans `strict: true`, l'API ne garantit pas que
`tool_use.input` respecte le schéma. Le mode strict — sans beta, pris en charge sur
claude-sonnet-5 — exige `additionalProperties: false` sur CHAQUE objet, et ne protège pas
d'une troncature : d'où `_niches_lisibles`, qui décode une chaîne JSON valide (le contenu du
modèle, seulement sérialisé) et ignore en les COMPTANT chaîne illisible, type inattendu et
éléments qui ne sont pas des objets — jamais une exception. Les requêtes concernées restent
nommées « non classées ». (2) **La CLI ne laissait aucune trace d'un run qui lève** : le
rapport s'écrivait avant l'affichage, mais après `construire_rapport`. Une exception — ou un
Ctrl-C, qui pendant le batch ASIN brûle 0,558 $ sans rien mettre en cache — produit désormais
un rapport INDÉCIDABLE portant la cause et le coût déjà engagé, code de sortie **4**
(exception) ou **130** (Ctrl-C). Le même défaut latent, dans `fiction_classifier`,
`fiction_ideator`, `kdp_keywords` et `lowcontent_verdict`, est corrigé depuis le 2026-09-14
(§2.8).

**Quatrième run réel (0,7208 $) : complet, et porte INDÉCIDABLE — puis un rejeu à blanc hors
ligne a trouvé ce qui aurait brûlé le cinquième.** Éditeur lu sur 31 niches, redevance sur 0 :
la pagination n'était jamais lue (§5.37), et le cache mutualisé ressert ces 185 fiches telles
quelles pendant 15 jours (§5.38). Relancé tel quel, le run aurait rendu le même rapport en
repayant le classement. Le brut de ces fiches est perdu. Ce qui est désormais codé :

| Correctif | Ce qu'il ferme |
|---|---|
| **Codes de sortie** : 0 porte franchie · 2 non franchie OU indécidable (inchangé) · 4 exception après le début · 130 Ctrl-C · **5 refus AVANT toute dépense** | « Rien n'a été dépensé » se confondait avec une porte indécidable après dépense |
| **Devis de la CLI** (`devis_calibration`), avant la sonde et avant Anthropic | Lit le cache EN LECTURE SEULE (`?mode=ro`, aucune ligne écrite) : SERP en cache / à payer, fiches utiles / en cache SANS pagination / à payer. N lu dans la signature de `run_lowcontent_scout`, poste LLM lu dans `devis.ventilation_max_estimee` — rien recopié (§5.32). Refuse (code 5) si le total atteint `--plafond` (`>=`, comme `CostTracker.verifier`) ou si AUCUNE fiche utile n'est ni en cache ni à payer — le cas exact du run 4. N'inclut pas la relance BSR payante des fiches non enrichies : le plafond du run reste le filet. `devis.cout_max_estime` (cache vide, pire cas produit) est inchangé |
| **Re-sonde** (`requetes_non_sondees`, `SondeIndisponible`) | UNE re-sonde gratuite des requêtes à `None` ; si toutes restent muettes, ou une « morte », arrêt AVANT le classement (code 5) : « aucune morte en vert » serait indécidable à coup sûr. Une « bonne » ou « mauvaise » muette ne bloque pas, elle se compte (`n_demande_non_mesuree`) |
| **Rapport jamais écrasé** | Un fichier existant fait prendre un nom horodaté à côté : le rapport du run 4, non versionné, s'effaçait au run suivant sans `--out` |
| **Captures brutes** (`JournalCapture`), CLI de calibration seulement | Sous `99-logs/captures/calibration-<horodatage>/` (racine FIXE, ignorée par git — elle suivait `--out` et pouvait tomber dans un dossier versionnable) : `asin.jsonl` (payload écrit au moment où le poll le lit, donc conservé après un Ctrl-C), `serp.jsonl` (réponses de `task_post`, refus compris, et de `task_get`), `classement.jsonl` (entrées de l'outil, `stop_reason`, jetons, écrits AVANT lecture), `progression.log`, `entrees.json`, `cout.json`. **Jamais dans le cache partagé** (décision de Baptiste). Ni identifiants ni corps posté. Une écriture qui échoue est comptée, jamais levée. Les fiches servies par le cache n'y figurent pas : leur brut n'existe plus |
| **`--rejouer ENTREES.json [--criteres JSON]`** (`rejouer_entrees`) | `run_lowcontent_scout(journal_entrees=…)` archive les ENTRÉES exactes de `score_lowcontent` par niche (format, risques, `n_enfants`, validation, SERP, fiches, BSR, sous-catégories), **date du jour comprise, passée explicitement** : `part_recents` lit la date, un rejeu un autre jour rescorait autre chose. Aucun fournisseur, aucun modèle. **Un rejeu ne franchit JAMAIS la porte** (`rejeu=True`, indécidable) : des seuils réglés sur ce jeu ne s'y valident pas ; il dit seulement s'il l'AURAIT franchie. Code de sortie 2 |
| **Purge ciblée** `--purger-fiches-sans-pages` (décision de Baptiste, voie A) | APERÇU par défaut. `--confirmer` exige `--ecrites-avant <date du correctif du parseur>` : `pages=None` ne distingue pas une fiche mal lue d'une VRAIE absence (livre audio B0FS7JQNJ6), qui serait sinon rachetée à chaque purge. Sauvegarde horodatée (base, `-wal`, `-shm`), vérification que la sauvegarde porte les clés, puis suppression en `BEGIN IMMEDIATE` avec revérification de chaque ligne. Visées : EXACTEMENT les clés `book:` valides des N premiers organiques des SERP en cache du classeur. Jamais `search:`, `clf:`, ni une autre fiche. Serveur arrêté, hors run. **Jamais exécutée par un agent sur le vrai cache** |
| **Prolongation du cache** `--prolonger-cache --jusqu-a <date> [--tout] [--confirmer]` (2026-09-29) | Un TTL s'applique à l'**ÉCRITURE** : `Cache.set` stocke `now() + ttl_s` en date ABSOLUE et `get` compare cette colonne, donc **changer une constante ne déplace AUCUNE ligne déjà écrite**. Les 301 fiches du run 5, payées, expiraient le 2026-10-03 quoi qu'on fasse aux constantes. Même protocole que la purge (aperçu, sauvegarde horodatée vérifiée, `BEGIN IMMEDIATE`, revérification) **plus un JOURNAL DE RESTAURATION** (`<cache>.prolongation-<horodatage>.json`, date d'origine clé par clé) : une prolongation d'essai doit se défaire sans restaurer toute la base, ce qui perdrait au passage ce qui a été acheté depuis. Ne RACCOURCIT jamais (une date antérieure lève) et ne RESSUSCITE pas une ligne déjà expirée — `get` la traite comme absente, la relever ferait resservir à tous les comptes une mesure dont le TTL a statué. Portée par défaut : les clés du JEU ; `--tout` vise le fichier entier, et c'est un choix explicite parce que le cache est mutualisé. **Appliqué le 2026-09-30** : 620 lignes vivantes (543 fiches, 64 SERP, 6 BSR, 5 classifications, 2 classements) repoussées au **2030-01-01** sur décision de Baptiste, pour que rien n'expire pendant les tests de calibration. Conséquence à ne pas oublier le jour où un client arrive : **aucun écran ne montre l'âge d'une mesure** |
| **Cache du classement** (`lowcontent_ideator`, mode classement SEULEMENT) | Clé `llmlc:` + SHA1 de modèle, consigne système, prompt utilisateur et outils (`strict` compris) — une empreinte, jamais un compteur. TTL 15 j, **mutualisé** : les requêtes sont des complétions publiques d'Amazon (§1). On garde la réponse BRUTE de l'outil, relue par la logique courante. Écrite seulement si complète : ni `max_tokens`, ni entrée illisible, ni requête hors liste, ni omise en `classer_toutes`. Jamais en idéation, où une relance est voulue. Le premier run paie le classement de toute façon |
| **Garde prédictif du batch ASIN** | Il comptait l'union ENTIÈRE : un plafond calé au plus juste refusait un batch à 0 $, puis le canal BSR repartait scraper chaque ASIN. Seules les fiches absentes du cache sont vérifiées, et le garde est AUSSI dans `enrich_asins`, juste avant l'envoi : les 185 fiches du run 4 expirent dans la même seconde, une phase 4 à cheval sur cet instant achetait 0,555 $ (calculé) sans vérification. Refus → les fiches du cache sont rendues, rien ne lève |
| **Tâches facturées non imputées** | `TaskPostRefuse` est la SEULE panne de SERP non imputée : poll épuisé, relecture illisible et Ctrl-C surviennent APRÈS la création de la tâche (5 SERP créées imputées 0 $ au rejeu), sur les trois moteurs. Une relecture illisible pendant le poll du batch ne jette plus le lot (`lectures_en_echec`, tâche relue au cycle suivant). Un Ctrl-C impute le pire cas (`enrich_asins`, `resolve_bsrs`, phase 3 : 185 tâches créées imputées 0 $ au rejeu) ; la CLI écrit « au moins X $ engagés » et ne prétend plus que les fiches d'un batch interrompu sont en cache. Une écriture de cache refusée ne jette plus un batch payé. **Depuis le 2026-09-29** (pré-mortem du run 6) : un lot ASIN dont le `task_post` LÈVE est imputé au PIRE cas (`taches_incertaines`, `lots_exception`) et annoncé « peut-être facturés », au lieu d'être compté « ni facturé » — un `ReadTimeout` à 30 s veut dire que la requête est partie, pas qu'elle n'a rien créé, et le chemin SERP des trois moteurs codait déjà ce pire cas sur le MÊME `_post`. Seul un refus EXPLICITE (`TaskPostRefuse`, `RefusCompte`) reste non imputé, des deux côtés |
| **Refus de COMPTE** (`RefusCompte`, sous-classe de `TaskPostRefuse`) | Refus posé à la RACINE sans aucune tâche, sans liste de codes. Au premier : plus aucun appel au fournisseur, le cache CONTINUE de servir, les niches restantes sortent ⚪ et comptées (31 `task_post` en rafale au premier run). Même traitement sur les trois moteurs. Côté batch ASIN (`product_raw_batch`), les lots suivants ne partent plus : ils sont comptés, pas envoyés (relevé au rejeu final, 100 + 85) ; une exception à l'envoi, elle, n'arrête rien. **Statut du job produit et remboursement de l'unité de plafond : inchangés** (décision). Non couvert : un refus de solde posé PAR TÂCHE (forme jamais capturée) |
| **Avertissements et conseils** (`_conseil_indecidable`, `n_pages_mesurees`) | « aucune fiche exploitable » quand l'éditeur était lu sur 31 niches, et « le cache ne repaiera que ce qui manque » alors qu'il resservait les fiches mal lues : faux tous deux. Le conseil suit désormais la cause (SERP tombées → compte ; redevance jamais calculée avec éditeur lu → LECTURE, rejeu du brut, purge) |
| **Progression** | « N/M recherche(s) Amazon servie(s) par le cache — non relue(s) » et « N/M fiche(s) servie(s) par le cache » : c'était exactement l'alerte qui manquait. Jamais « à payer » (§5.27) |
| **Diagnostics par étiquette** dans `signaux` | Compteurs `n_bonus_part_indie`, `part_indie_min`/`max`, `n_crit3`, `n_malus_recents` et médianes des QUATRE axes. Sans seuil, sans effet sur la porte : c'est Baptiste qui juge |

**HORS PÉRIMÈTRE, et une porte franchie ne voudra donc PAS dire « seuils calibrés »**. Ces
défauts de DÉFINITION du score demandent une décision de Baptiste, qui contredirait la lettre
de « jamais le code » plus bas. Aucun n'est codé :

- **R17**, `n_concurrents_cibles` : malus sur **28/31** niches. Rejoué sur les 31 SERP réelles
  du cache, la mesure dépend de la longueur de la SERP. `scoring.count_targeted` est partagée
  avec la non-fiction, dont `history.db` stocke la valeur.
- **R18**, `n_variantes_quasi_identiques` grossit avec la profondeur. Sur les 50 SERP du cache,
  une fenêtre de 12 titres ne dépasse jamais 6, et rho vaut **+0,018 / +0,085 / +0,062**
  (fenêtres 12 / 24 / 48) : aucune fenêtre ne le rend discriminant.
- **R19**, crit3 « place à prendre » (+1,5) : il touche **8/9 mortes, 12/15 mauvaises, 6/7
  bonnes**, et toujours 8/9 mortes sur le top 3. Il grandit avec le pire BSR, plus élevé dans
  un rayon mort, et aucune valeur du seuil n'inverse ce sens. **DÉCIDÉ le 2026-09-18** (run 5 :
  14/14 mortes) : **le bonus ne pèse plus sur le score** ; crit3 reste dans `criteres_bsr_ok`.
- **Saturation de `part_indie`** : 1,0 sur **24/31** niches au run 4. Seuls les compteurs de
  diagnostic ci-dessus sont codés.
- **R22**, `redevance_min_bonne=2,0` saturerait sur **21 à 27/31** une fois les pages lues
  (**CALCULÉ**, pages supposées). Le bonus revient à « prix ≥ 8,10 € » sous 110 pages.
  **Chiffres établis AVANT le calcul hors TVA et le grand format (§5.39)**, à refaire au
  rejeu : sous 110 pages, 2,0 € de redevance demandent désormais ~9,72 € affichés en format
  standard et ~10,75 € en grand format (**calculé**, TVA 20 %).
- **R24**, poids des axes et constantes codés en dur. Le prix est le signal le plus corrélé
  (+0,53 ; intervalle de Fisher ~[0,22 ; 0,75] **calculé**) : rien ne se règle sur une porte
  indécidable.
- **R27**, malus pris sur les `risques` rendus par le LLM sans vérification (saisonnier −1,
  TOS −2), appliqués même sous `--inclure-saisonnier`. Une seule des 31 requêtes est
  saisonnière selon `est_saisonnier`, qui ne voit pas « autumn ». **Saisonnier DÉCIDÉ le
  2026-09-18 : drapeau affiché, sans malus** (il frappait 2 bonnes sur 12 au run 5). Le −2 de
  `ip_marque` / `tos` reste.
- **Seuils des pastilles** 🟢 / 🟡 (7,5 / 6,0) : déplacés du code vers `lowcontent_criteres.json`
  (`seuil_verdict_vert`, `seuil_verdict_jaune`) le 2026-09-18 et fixés à **6,0 / 5,0** par
  Baptiste : à 7,5 / 6,0 le run 5 rejoué sortait 50 rouges sur 51. HYPOTHÈSE lue sur le run 5
  (rouge = probablement mort, jaune = vivant, à examiner), à vérifier sur un lot neuf. Deux
  copies du seuil supprimées (§5.32) : `SEUIL_VERT` dans `lowcontent_validation`, et `grade`
  (7,5 / 6,0) qui colorait la pastille de la carte low-content — elle suit désormais le
  verdict du serveur.
- **Demande comptée une fois** (2026-09-18) : en mode classement `demand_score =
  max(1, n_enfants)`, et un bonus « au moins 3 affinages » recomptait le même nombre. Retiré.
- **R30**, la progression cliente recopie encore le motif brut du fournisseur (compromis
  ci-dessus) : à filtrer à la frontière client avant l'ouverture des inscriptions.
- **R31** : seul le relibellé est fait. Page 2 du dossier : « estimation de l'IA, non
  calculée ». Page 1 : « non mesuré » sans unité. Pas de redevance calculée depuis l'angle.

Corriger les pages ne peut pas faire passer une morte en vert : +0,4 point global au plus, score
maximal 6,01 contre un seuil vert à 7,5 (**calculé** sur le rejeu). Hors code, le prochain run
suppose la purge des 185 fiches par Baptiste, avec sauvegarde, et un solde DataForSEO vérifié
dans le tableau de bord.

**Cinquième run réel (2026-09-18, 1,061 $) : COMPLET et DÉCIDABLE, porte NON franchie.** 51
requêtes — les 31 du run 4 et 20 NEUVES tirées au hasard dans l'autocomplete puis étiquetées à
l'aveugle (colonne « lot » du classeur) —, 51/51 calibrées, redevance et pages 51/51.
Spearman **+0,358** (anciennes +0,433, neuves +0,399), 0 morte en vert, mais UNE seule niche
verte sur 51 (une « mauvaise ») et aucune bonne au-dessus de 6,31. Le score sépare une morte
d'une vivante (AUC 0,73), presque pas une bonne d'une mauvaise (0,57) ; le prix médian est le
signal le plus solide. Aucune variante du SEUL fichier de critères n'atteint 0,5 sur les
neuves (0,491 au mieux sur 144 combinaisons, même choisies sur les neuves) : c'est la
DÉFINITION du score qui bloque. Décisions de Baptiste qui en découlent : R19 et R27 ci-dessus,
seuils des pastilles dans le fichier (6,0 / 5,0), demande comptée une fois, et deux compteurs
au rapport, HORS porte (`n_verts`, `meilleur_score_bonne`). Rejoué sur le run 5 : Spearman
**+0,462** (anciennes +0,543, neuves +0,442) ; pastilles : 14 mortes rouges sur 14, bonnes 5
jaunes / 7 rouges, mauvaises 1 verte / 6 jaunes / 18 rouges. À VALIDER sur un lot neuf, un
rejeu ne franchissant jamais la porte. Le score écarte un rayon mort ; il ne départage pas
encore une bonne d'une mauvaise, et le produit ne doit pas se vendre comme un sélecteur.
Les tests qui photographient le run 4 lisent désormais les 31 lignes du lot « run 4 »
(`outils_calibration.etiquetees_run4` / `xlsx_run4`). Captures :
`99-logs/captures/calibration-20260918-155619/` (`entrees.json` pour `--rejouer`).

Quatre décisions de mesure :

| Décision | Pourquoi |
|---|---|
| Spearman et non Pearson | Les étiquettes sont ORDINALES. L'écart `morte → mauvaise` n'a aucune raison de valoir l'écart `mauvaise → bonne` |
| Rangs **moyens** sur les ex aequo | Trois étiquettes = des ex aequo partout ; un départage arbitraire mesurerait l'ordre de saisie du fichier |
| Les niches à `concurrence_mesuree=False` **sortent du calcul** | Leur score a été produit sans bonus ni malus de SERP : les corréler mesurerait du bruit. Comptées et annoncées (`n_non_mesurees`), jamais jetées en silence |
| `None` exclus des distributions | Moyenner une part indie non mesurée à zéro fausserait exactement le seuil qu'on cherche à régler |

**Mesure que le plan ne demandait pas** : les requêtes perdues AVANT toute dépense (filtre
IP, saisonnier, gate gratuit). Une « morte » écartée là est le gate qui travaille pour zéro
centime (`ecartees_correctement`) ; une « bonne » écartée là est un **faux négatif que
l'utilisateur ne peut PAS voir**, la niche n'apparaissant nulle part
(`bonnes_perdues_avant_analyse`). Séparées, jamais additionnées. Annoncées fort, mais elles
**ne ferment pas la porte** — ajouter un critère de son propre chef ferait passer une
intention pour une règle (§4.2).

**En cas d'échec, on corrige `data/lowcontent_criteres.json` — jamais le code.** Un seuil
qui migre dans `lowcontent_scoring.py` redevient invisible et non discutable.

### 2.15 Place de marché — `marketplace.py`

Source unique de « sur quelle place de marché travaille-t-on ». La réponse était écrite à
**neuf endroits** : `location_code=2250` dans les trois orchestrateurs et dans
`bsr_source`, `language_code="fr_FR"` dans deux, l'identifiant de marketplace et l'hôte
d'autocomplete dans `amazon_autocomplete`, le domaine des fiches dans `amazon_product` et
dans les deux constructeurs d'URL de `TopBook`.

**Ce module ne rend PAS le produit multi-marché, et c'est délibéré.** Six choses du dépôt
sont irréductiblement françaises : les browse nodes de la taxonomie fiction, les libellés
de rayon comparés au texte d'Amazon (§5.4), les barèmes d'impression KDP relevés en EUROS,
les mots saisonniers, le corpus du filtre IP et les prompts des cinq modules LLM.

Aucune ne lèverait sur une SERP américaine — elles rendraient des **chiffres** : rayon
filtré sur un browse node inexistant, redevance au barème européen, filtre saisonnier qui
cherche « noel » dans « christmas planner ». Faux, plausibles, silencieux. D'où le choix :
**`MARKETPLACE=com` LÈVE au démarrage**, en listant ce qui manque. `com` est *décrit* (ses
deux codes DataForSEO sont justes) et déclaré non prêt.

**Nuance d'ordre à connaître** (même famille que §5.21) : `ACTIF = marketplace_actif()` est résolu
au chargement du module. `web/server.py` appelle `load_dotenv()` AVANT ses imports moteur, donc le
serveur — le point d'entrée réel du produit — lève bien au démarrage. En CLI, les orchestrateurs
importent `marketplace` avant leur propre `load_dotenv()` : un `MARKETPLACE` défini **uniquement**
dans `.env` y est ignoré et on reste sur `fr`. Sans danger (`fr` est la seule place prête) mais ce
n'est pas une levée : en CLI, passer la variable dans l'environnement du shell.

**Piège que ce module s'est infligé à lui-même** : `ACTIF` valait d'abord `MARKETPLACES[DEFAUT]`,
sans lire l'environnement. `marketplace_actif()` — la fonction qui lève — n'avait alors **aucun
appelant de production**, seulement des tests : `MARKETPLACE=com` se serait lu « bascule
effectuée » pendant que le produit continuait sur `fr` sans rien dire. Exactement le défaut que le
module existe pour empêcher, appliqué à lui-même.

### 2.16 Message de fin d'analyse — `notification.py`

**Éteint par défaut** : il faut `NOTIFICATIONS_EMAIL` **et** `SMTP_HOST`. Une configuration
à moitié faite n'envoie pas « au mieux », elle n'envoie pas. Aucune dépendance ajoutée
(`smtplib` + `email.message`, comme `hashlib.scrypt` pour l'authentification).

| Règle | Pourquoi |
|---|---|
| Un échec d'envoi ne fait **jamais** échouer un run | Le run a coûté de l'argent réel, son résultat est en base, l'unité de plafond est consommée. Le marquer « en échec » effacerait de l'écran un travail payé et réussi (§5.29) |
| **Aucun résultat** dans le corps | L'e-mail est un canal en clair, relayé, archivé, indexé chez le fournisseur du destinataire. Les niches trouvées sont ce que l'auteur a payé pour être seul à savoir. Aucun montant non plus (§5.27). `resultat` et `cout_usd` sont dans la signature de `corps_fin_de_job` et **ignorés** : un paramètre absent invite à « juste ajouter le top 3 » |
| Aucune erreur interne recopiée | Elle peut porter l'URL DataForSEO, donc les identifiants HTTP Basic — même motif que `_erreur_publique` |
| Aucun secret journalisé | Le mot de passe est retiré de toute ligne de log : une exception de bibliothèque porte régulièrement la ligne d'authentification entière (règle 6) |

Branché sur les **deux** exécuteurs (thread du serveur, pool de `worker.py`) : n'en câbler
qu'un rendrait la notification dépendante de `JOBS_MODE`, et ce serait invisible — rien à
l'écran ne distingue « pas de message » de « message pas envoyé ». Deux tests fonctionnels
vérifient les **deux issues** sur les deux exécuteurs.

La notification part **après** la sortie du créneau de concurrence : le pool n'en tient que
`RUNS_SIMULTANES_MAX`, et un dialogue SMTP lent (jusqu'à 20 s de délai) les garderait aux
frais de ceux qui font la queue. L'ordre « compté » / « prévenu » n'a aucune conséquence,
contrairement à l'ordre « imputé avant terminé » qui reste load-bearing.

L'adresse est relue depuis `comptes.db` au moment de l'envoi plutôt que portée par le job :
l'y recopier en ferait une donnée personnelle de plus, dupliquée dans une base qui n'en a
pas besoin.

**Piège payé une fois, et le plus instructif du module** : `_notifier` lisait
`UserStore(_COMPTES_DB)` alors que la constante s'appelle `_USERS_DB`. Le `NameError` était avalé
par le `except Exception` de `_notifier` — qui est là pour une BONNE raison, et qui masquait donc
intégralement la panne : **aucun e-mail ne pouvait partir, et rien nulle part ne le disait**. Les
deux tests fonctionnels ne le voyaient pas parce qu'ils monkeypatchent `server._notifier` : ils
vérifiaient que le serveur APPELLE la notification, jamais qu'elle fonctionne. **Remplacer la
fonction qu'on teste, c'est tester le harnais.** Un test résout désormais une VRAIE adresse depuis
un `comptes.db` isolé.

### 2.17 Hébergement — `storage.py`, `Procfile`, `requirements.txt` racine

Livré le 2026-09-07. **Le dépôt est DÉPLOYABLE ; rien n'est déployé** (§7). Quatre manques,
tous silencieux — c'est ce qui les rendait dangereux.

| Manque | Ce qui se serait passé | Ce qui le ferme |
|---|---|---|
| Rien ne dit comment construire | Un constructeur automatique cherche `requirements.txt` **à la racine** ; le nôtre est dans `01-scripts/` | `requirements.txt` racine qui **inclut** (`-r 01-scripts/requirements.txt`) et ne recopie rien : deux listes divergeraient, et celle installée en PROD cesserait d'être celle qu'on teste |
| Rien ne dit comment démarrer | L'hébergeur devine, et devine mal sur un point d'entrée qui n'est ni `main.py` ni `app.py` | `Procfile` : `web: python web/server.py`. **Pas d'`uvicorn` direct** — ce serait un second chemin de lancement (§2.6), et `HOST`/`PORT`, lus sous `__main__`, cesseraient d'être lus |
| `HOST=127.0.0.1` | Déploiement MUET : construction réussie, journaux propres, rien ne répond | `_hote()` DÉDUIT : `0.0.0.0` dès `APP_ENV=prod`, `127.0.0.1` sinon, un `HOST` explicite primant toujours. Même raisonnement que `_cookie_securise` — ce qui s'oublie doit se déduire |
| Répertoire des bases en dur | Disque de conteneur effacé à chaque mise en ligne → **perte TOTALE et SILENCIEUSE** | `storage.data_dir()` + `DATA_DIR`, **EXIGÉE dès `APP_ENV=prod`** |

**Pourquoi `storage.py` LÈVE au lieu de retomber sur un défaut prudent.** Partout ailleurs,
un réglage oublié dégrade doucement (`_cookie_securise` déduit, `_plafond_analyses_mensuel`
retombe sur illimité-mais-journalisé). Ici c'est impossible : sans volume, `comptes.db`,
`usage.db`, `history.db`, `jobs.db` et `df-cache.db` disparaissent au prochain `git push` —
les clients, la consommation qui porte le plafond ET la future facturation, l'antériorité de
l'historique, et le cache mutualisé qui est l'économie principale du modèle. **Rien ne le
signalerait** : le service repart sur des bases vides, le premier visiteur crée « le premier
compte », l'amorçage joue, tout a l'air normal. C'est la règle 3 appliquée au stockage — un
répertoire vide ne doit jamais pouvoir se lire comme « pas encore de client ».
Le chemin était écrit à quatre endroits (les 4 constantes de `server.py`, plus le
`df-cache.db` construit à l'identique par les trois orchestrateurs) ; un seul resté en dur
suffirait à faire repartir une base sur le disque éphémère pendant que les autres suivent le
volume, et **la plus discrète ferait le plus de dégâts** — un cache perdu ne lève rien, il
fait simplement repayer tout le monde. `tests/test_deploiement.py` porte le cliquet.

**Récupération des travaux interrompus au démarrage** (`_recuperer_travaux_interrompus`,
branchée sur le `lifespan` de l'app — pas `@app.on_event`, déprécié). En `JOBS_MODE=worker`
elle ne fait rien : c'est le worker qui exécute, donc lui qui récupère, et que les deux s'en
chargent ferait passer en échec un travail que l'autre vient de reprendre. Aucune exception
ne remonte : le ménage ne doit jamais empêcher de démarrer. **Un test démarre l'application
POUR DE VRAI** (`with TestClient(...)`) au lieu de vérifier que la fonction existe — une
fonction correcte branchée sur un hook qui ne se déclenche pas est le défaut central de ce
dépôt (§5.26, §2.16).

**Limite connue, et c'est un manque, pas une décision** : un run coupé moins de 30 minutes
avant le redémarrage n'est pas encore un orphelin (c'est l'absence de progression qui le
définit, pas l'âge — un run fiction VIVANT dure 15 minutes) et attendra le redémarrage
suivant. Aucun balayage périodique n'existe.

**Ce qui marche déjà sans rien faire** : le cookie `Secure` se déduit de
`X-Forwarded-Proto` que tout proxy TLS envoie, `origine_sure` fonctionne derrière ce proxy,
et `_verifier_config_prod` refuse de démarrer sans `BSR_SOURCE=dataforseo`.

### 2.18 Verdict FICTION — `fiction_verdict.py` (2026-10-03)

« Analyser cette niche » sur une carte fiction, comme en non-fiction et low-content. Accord de
Baptiste : verdict Go / Go prudent / No-Go, confiance /10, facteur décisif, **UN angle** (titre,
sous-titre, promesse, couverture, prix, requêtes) et **trois livres du rayon à étudier**. **Hors
périmètre v1** : PDF, mots-clés KDP (`/api/kdp-keywords` refuse `type: fiction` en 400),
redevance, spécification d'intérieur — aucun module ne calcule une redevance fiction, en avancer
une serait une devinette (règle 7).

Même sortie que les deux autres (`NicheVerdict`) pour que l'interface rende les trois avec le
même bloc, plus UN champ propre à la fiction : `comparables` (`LivreComparable`). Outil
`rendre_verdict_fiction`, **tool-use forcé, `strict: true`**, lecture défensive (confiance
illisible LÈVE, jamais 0/10 ; angle illisible compté). Modèle : `VERDICT_MODEL` (celui du
verdict non-fiction, importé — pas de variable nouvelle). Les quatrièmes de couverture ne partent
PAS au modèle : texte tiers, long, surface d'injection ; la classification porte déjà tropes et
décor, et le prompt est borné quelle que soit la taille du rayon reçu (`MAX_LIVRES_PROMPT`).
**Coût : non mesuré** (aucun run live) ; ordre de grandeur des autres verdicts, ~0,03 $.

**Trois gardes, côté CODE** (`tests/test_fiction_verdict.py`) :

| Garde | Règle |
|---|---|
| **Rayon non mesuré** (`rayon_non_mesure` : matrice `non_mesurable`, ou aucun livre, ou aucun livre scorable) | `generate_fiction_verdict` LÈVE `RayonNonMesure` AVANT l'appel, et l'endpoint rend **400 AVANT toute réservation** : rien dépensé, rien décompté du débit horaire. Ni « Go » ni **« No-Go »** : non mesuré n'est pas mort (règle 3, §5.2). L'interface n'offre pas le bouton sur une telle carte |
| **Rayon incomplet** (`rayon_incomplet` : `n_echecs > 0`, OU le mot « incomplet » dans le texte du moteur) | « Go » ramené à « Go prudent », raison écrite en tête du facteur décisif. **Ne fait que DÉGRADER** : un « No-Go » ne remonte jamais. Le texte du moteur double le compteur parce qu'un travail enregistré AVANT l'ajout de `FictionNicheReport.n_echecs` vaut `0` — « complet » par défaut, optimiste donc faux |
| **Comparables vérifiés** | Un ASIN que le modèle n'a pas pu lire dans le rayon MESURÉ est écarté et COMPTÉ (écrit dans le facteur) ; le titre affiché est celui du rayon, jamais celui du modèle ; doublons et excédent au-delà de trois passés sans compte |

**Pièges propres à ce verdict.** (1) `verdict` est déjà une chaîne sur un résultat fiction : le
verdict du modèle se range sous **`analyse`** (`JobStore.CHAMPS_ANNOTABLES`), l'écraser aurait
effacé de l'écran les réserves du moteur. (2) `FictionNicheReport` interdit les champs extra et la
page renvoie la carte telle quelle (`autocomplete_score`, `analyse`) : l'endpoint ne garde que les
champs du modèle. (3) La clé de la niche dans le travail est `niche.query` ; **une clé vide ne
désigne aucune niche** (`JobStore._est_la_niche`). (4) Les requêtes proposées sont des PISTES non
vérifiées : l'écran dit « à tester », pas « à viser ».

**Non vérifié** : l'acceptation du mode strict par l'API avec ce schéma (propriétés
facultatives), comme pour les quatre autres outils passés en strict le 2026-09-14 (§2.8) ; la
qualité réelle des angles et des comparables — aucune réponse live capturée, fixtures inventées
et déclarées comme telles.

---

## 3. SOURCES DE DONNÉES ET COÛTS

| Source | Usage | Coût |
|---|---|---|
| **API Anthropic** | Ideator non-fiction, ideator fiction, classifieur de blurbs, verdict éditorial, mots-clés KDP | Payant au token. Grille dans `cost_tracker.py:8-14` — les **quatre clés portent le préfixe `claude-`** : `claude-sonnet-5` (défaut partout) 2 $/10 $ par million in/out en tarif intro **jusqu'au 31/08/2026**, puis 3 $/15 $ ; `claude-opus-4-8` 5 $/25 $ ; `claude-fable-5` 10 $/50 $ ; `claude-haiku-4-5` 1 $/5 $. **Un identifiant absent de la grille est facturé 0,00 $** (`cost_tracker.py:22-24`, `if not p: return 0.0`) : un coût invisible, pas nul. Écrire `opus-4-8` sans le préfixe dans `IDEATOR_MODEL` suffit à faire disparaître la dépense des rapports sans lever la moindre erreur |
| **DataForSEO — Amazon Products** (`/v3/merchant/amazon/products`) | SERP : organiques vs sponsorisés, ASIN, prix, note, avis, badges | 0,003 $/appel en priority 2 (file rapide ~1-4 min, **défaut**), 0,0015 $ en priority 1 (jusqu'à ~45 min). Cache **15 j** |
| **DataForSEO — Amazon ASIN** (`/v3/merchant/amazon/asin`) | BSR, rayon, blurb, série, éditeur, date, langue. Batché jusqu'à 100 ASIN | Même tarif par ASIN. **La file met ~250 s quel que soit le lot** → batch unique par run. Cache livre **15 j**, cache BSR **15 j** (3 j pour une absence de classement) |
| **Classification de blurbs** (dérivée, pas une source réseau) | Étiquettes tropes/décor/`est_roman` produites par le LLM et remises en cache | **TTL 30 j** (`CLASSIFICATION_TTL_S`, `cache.py:17`) — le plus long des quatre, parce que la clé porte déjà tout ce qui peut invalider le résultat (§2.4 D) |
| **Amazon autocomplete** (`completion.amazon.fr/api/2017/suggestions`, marketplace `A13V1IB3VIYZZH`) | Validation de la demande non-fiction **et lecture du contenu des suggestions** (§2.3), sonde fiction, confirmation des mots-clés KDP | **Gratuit.** Endpoint public, aucune clé. Pause 0,4 s entre requêtes |
| **Fiche `amazon.fr/dp/{asin}` scrapée** | BSR, source par défaut en local | **Gratuit — mais IP résidentielle uniquement** (voir piège ci-dessous) |
| `data/fiction_taxonomy_fr_v1.json` | 6 sous-genres, tropes, décors, browse nodes, requêtes canoniques, filtres et libellés de rayon | Gratuit, fichier local versionné |

Codes DataForSEO : `location_code=2250` (France) et `language_code="fr_FR"` — **pas `"fr"`**
(validé en live).

### PIÈGE DE COÛT À TOUJOURS SIGNALER — `BSR_SOURCE`

`BSR_SOURCE=scrape` (défaut) lit les fiches Amazon depuis une **IP résidentielle** : gratuit sur
le PC de Baptiste, **bloqué depuis un datacenter**. En production il faut
`BSR_SOURCE=dataforseo`, ce qui fait passer un scout non-fiction de **0,030 $ (mesuré) à
0,084 $ (calculé, jamais mesuré en conditions serveur)**.
**Ne jamais citer le chiffre local comme coût de production.**

### Variables d'environnement (`.env` uniquement)

**Trente-quatre** variables sont lues par `os.getenv` dans `01-scripts/` et `web/`
(recensement exhaustif sur ces deux dossiers, aucun autre `.py` du dépôt n'en lit, revérifié
le 2026-09-07 — la trente-quatrième est `DATA_DIR`, §2.17). **`.env.example` les documente
désormais TOUTES**, `HOST`, `PORT` et les deux `LOWCONTENT_*_MODEL` compris : le trou de
quatre variables signalé ici jusqu'au 2026-09-06 est fermé, et l'en-tête du fichier porte le
compte juste. Ne pas chercher « ONZE » ni « VINGT » dans le fichier, ces citations ont
longtemps traîné ici et n'y correspondent plus.

Deux tests tiennent une partie de l'invariant (`tests/test_tutoriel_pdf.py`), mais dans un
seul sens : **documenté ⇒ lu**. Rien ne vérifie l'inverse — la couverture complète de
`.env.example` est donc tenue à la main et peut se dégrader au prochain ajout, sans qu'aucun
test ne le dise. `tutoriel_pdf.ENV_VARS` reste, lui, partiel (les postes de déploiement y
sont désormais : `DATA_DIR`, `APP_ENV`, `HOST`/`PORT`, `JOBS_MODE`).

| Variable | Défaut | Obligatoire |
|---|---|---|
| `ANTHROPIC_API_KEY` | aucun (`os.getenv` sans défaut → `None`) | oui |
| `DATAFORSEO_LOGIN` | `""` — un défaut vide ne fait pas échouer la construction du provider, l'échec survient à l'appel HTTP | oui |
| `DATAFORSEO_PASSWORD` | `""` — c'est le **mot de passe d'API** (app.dataforseo.com/api-access), pas celui du compte | oui |
| `BSR_SOURCE` | `"scrape"` (`bsr_source.py:27`). Toute autre valeur que `scrape`/`dataforseo` lève `ValueError`. Ignorée si `fetch_bsr_fn` est injecté | non |
| `DATAFORSEO_PRIORITY` | `2` (`_resolve_priority`, `search_providers.py:27`). Valeur non entière ou hors plage → `warnings.warn` + repli sur 2. Un argument explicite prime sur l'env | non |
| `INSCRIPTIONS_OUVERTES` | **non défini = FERMÉ** (`web/server.py:227`). Accepte `1/true/yes/oui`. **Le premier compte passe toujours** | non |
| `COOKIE_SECURE` | non défini → le drapeau est **déduit** de `X-Forwarded-Proto` puis du schéma (`web/server.py:101-117`). `1/true/yes/oui` **force** le drapeau ; **aucune valeur ne peut le désactiver** | non |
| `HOST` | **DÉDUIT** (`_hote()`) : `0.0.0.0` si `APP_ENV=prod`, `127.0.0.1` sinon ; une valeur explicite prime toujours. Lue **uniquement** sous `if __name__ == "__main__"` : sans effet si le serveur est lancé par `uvicorn server:app` à la main. Le défaut local était injouable en conteneur — écouter la boucle locale y rend le service injoignable **sans la moindre erreur** (§2.17) | non |
| `PORT` | `"8000"`. Même portée que `HOST`. Valeur non entière → repli silencieux sur 8000. Les plateformes imposent le leur | non |
| `DATA_DIR` | non défini = `99-logs/`. **EXIGÉE dès `APP_ENV=prod`** : `storage.data_dir()` LÈVE, donc le serveur refuse de démarrer. Sans volume persistant, les cinq bases disparaissent à chaque mise en ligne, sans aucun signal (§2.17). Le répertoire est créé s'il manque — un volume neuf est vide | non (oui en prod) |
| `PLAFOND_ANALYSES_MENSUEL` | non défini → `None` = illimité, mais l'usage reste journalisé (`web/server.py:88-98`). Valeur non entière → retombe silencieusement sur illimité. **Plafond PAR utilisateur, glissant sur 30 jours** | non |
| `IDEATOR_MODEL` | `claude-sonnet-5` (`niche_ideator.py:20`), choisi après un A/B live du 2026-07-05 : qualité à parité avec `claude-opus-4-8` pour ~2× moins cher | non |
| `VERDICT_MODEL` | `claude-sonnet-5` (`niche_verdict.py:9`) | non |
| `KDP_KEYWORDS_MODEL` | `claude-sonnet-5` (`kdp_keywords.py:19`) | non |
| `FICTION_IDEATOR_MODEL` | `claude-sonnet-5` (`fiction_ideator.py:34`) | non |
| `FICTION_CLASSIFIER_MODEL` | `claude-sonnet-5` (`fiction_classifier.py:15`). **Ne pas rétrograder** : Haiku 4.5 mesuré à 42 % d'accord contre 80 % requis | non |
| `LOWCONTENT_IDEATOR_MODEL` | `claude-sonnet-5` (`lowcontent_ideator.py:30`). | non |
| `LOWCONTENT_VERDICT_MODEL` | `claude-sonnet-5` (`lowcontent_verdict.py:24`). | non |
| `MARKETPLACE` | `"fr"` (`marketplace.py`). Toute autre valeur **LÈVE**, `"com"` compris : il est décrit et déclaré non prêt (§2.15). Valeur vide → retombe sur `fr`, un `MARKETPLACE=` étant un oubli et non une demande de bascule | non |
| `APP_ENV` | non défini. `"prod"` est LA variable d'exposition : elle déclenche `_verifier_config_prod` (qui exige `BSR_SOURCE=dataforseo`), **exige `DATA_DIR`** et fait écouter `0.0.0.0`. Refus de démarrer sur une configuration dangereuse, jamais un défaut silencieux | non |
| `JOBS_MODE` | `"thread"` (`web/server.py:110`). `"worker"` fait que `POST /api/jobs` **empile seulement** : sans ce garde, serveur ET worker exécuteraient le même job — deux fois les SERP, deux fois les tokens | non |
| `RUNS_SIMULTANES_MAX` | `5` (`RUNS_SIMULTANES_DEFAUT`, `web/server.py:76`). Nombre de créneaux d'exécution simultanés. C'est un plafond de CHARGE, pas de dépense | non |
| `PLAFOND_USD_PAR_RUN` | `0.60` (`cost_tracker.py`). Plafond **prédictif** : `verifier(cout_prevu)` refuse AVANT de dépenser, il n'interrompt pas au milieu. Combiné au devis préalable, c'est ce qui empêche un rapport partiel facturé | non |
| `DEBIT_APPELS_MAX` | `2 × MAX_RECHERCHES` = **40 par heure et par utilisateur** (`web/server.py:170`). **Garde-fou, PAS un palier tarifaire** : le modèle économique n'étant pas fixé, la valeur est ancrée sur ce que le produit sait faire, pas sur ce qu'on veut vendre | non |
| `WORKER_CONCURRENCE` | `5` (`CONCURRENCE_DEFAUT`, `worker.py:67`). Taille du pool de `worker.py` | non |
| `WORKER_REPOS_S` | `2.0` (`worker.py:58`). Attente entre deux tentatives de `claim_next` quand la file est vide | non |
| `NOTIFICATIONS_EMAIL` | non défini = **ÉTEINT**. Et il ne suffit pas : sans `SMTP_HOST`, rien ne part (§2.16) | non |
| `SMTP_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_FROM` / `_TLS` | port `587`, TLS actif. `SMTP_FROM` retombe sur `SMTP_USER`. Port non entier → repli sur 587 | non |
| `BASE_URL` | non définie → le message de fin part **sans lien** plutôt qu'avec un lien mort : rien dans le code ne connaît le nom de domaine, il n'y a pas de déploiement | non |

Les `REDDIT_*` **ne sont plus lues nulle part** : les modules qui les lisaient ont été supprimés
(commit `eaa20b2`). Plus aucun résidu côté `.py`.

---

## 4. CRITÈRES DE DÉCISION — CE QUI EST CODÉ vs CE QUI EST UNE INTENTION

**Règle absolue : ne jamais présenter une intention comme une règle appliquée.**

### 4.1 CODÉ et vérifiable

| Critère | Où | Détail |
|---|---|---|
| BSR 1 — au moins 1 livre du top organique avec BSR < 10 000 | `scoring.py:26` | `crit1 = best < 10_000` |
| BSR 2 — moyenne du top < 50 000 | `scoring.py:27` | `crit2 = top5_avg < 50_000`. **Nuance assumée** (`scoring.py:15-17`) : le scout ne récupère que le **top 3** (`n_bsr_per_niche=3`), donc `bsr_top5_avg` est la moyenne d'au plus 3 BSR. **Le nom du champ ment sur son contenu** |
| BSR 3 — présence d'un BSR > 50 000 (« place à prendre ») | `scoring.py:28` | `crit3 = worst10 > 50_000`. Le seuil « idéalement > 100 000 » n'est **pas** codé ; `worst_top10` est le max des 3 BSR disponibles au plus |
| Conjonction des 3 critères | `scoring.py:31` | `"ok": crit1 and crit2 and crit3`, exposé en `ScoredNiche.criteres_bsr_ok`, affiché comme badge dans l'UI et « OUI — place à prendre » dans le PDF |
| **Séparation organic / sponsored à la source** — et exclusion des sponsorisés de tous les calculs de QUALITÉ | `search_providers.py:67,80` + `scoring.py:64,81-88,116-117` + `scout_master.py:92` | Détection `sponsored = it.get("type") == "amazon_paid"`, deux listes distinctes dès `map_dataforseo_result`. Titres, notes, avis, `count_targeted` **et `prix_stats`** ne lisent que les organiques ; les ASIN envoyés au BSR viennent exclusivement de `sr.organic`. **Ne pas lire « exclus de TOUS les calculs »** : `score_niche` lit bien `search.sponsored` et leur NOMBRE entre dans le score — voir la ligne « bonus beaucoup de sponsorisés ». `n_sponsored` est exposé et affiché |
| Comptage des concurrents réellement ciblés | `scoring.py:38-45` | `count_targeted` extrait les mots de 4 lettres et plus de la requête et compte les titres organiques qui en contiennent au moins la moitié. Exposé en `n_concurrents_cibles` |
| **Fourchette de prix du rayon** (commit `6d1f134`) | `scoring.py:48-73` + `models.py:112-115` | `prix_stats` rend `min` / `median` / `max` **sur les seuls organiques**. Un prix ABSENT est **exclu, jamais compté zéro** (Amazon ne rend pas toujours le prix ; zéro tirerait la fourchette vers le bas et ferait croire à un rayon bradé). `n_prix_connus` dit sur combien de livres elle porte — « 9,99-19,99 € » sur deux livres ne se lit pas comme sur vingt. **N'entre dans AUCUN score** : un rayon cher n'est ni meilleur ni pire, l'y ajouter serait un jugement déguisé en mesure |
| **Garde « concurrence non mesurée »** (commit `60e405a`) | `scoring.py:107-119` + `models.py:103-107` | `mesuree = search is not None`. Quand la SERP a échoué, **aucun** bonus ni malus de concurrence n'est appliqué : sans ce garde, `n_cibles == 0` faute de mesure déclenchait le bonus « moins de 10 concurrents » (+2) et une niche dont rien n'avait été mesuré sortait à 6,88 « Intéressant ». Exposé en `ScoredNiche.concurrence_mesuree`, **défaut pessimiste `False`**. L'UI affiche un encadré explicite (`web/index.html:851-854`) |
| Seuils de concurrence 30/50 | `scoring.py:110-115` | **Malus doux, jamais exclusion**, et **seulement si `mesuree`** : plus de 50 → −2 sur la pénétration, plus de 30 → −1, moins de 10 → +2. Une niche à 200 concurrents n'est jamais rejetée : elle perd au maximum 0,8 point de score global |
| Bonus « place à prendre » | `scoring.py:118-119` | `penetration += 1.5` si `crit3`. **Hors du garde `mesuree`** : il repose sur le BSR, pas sur la SERP — une niche non mesurée peut donc encore le toucher |
| Bonus « beaucoup de sponsorisés » | `scoring.py:116-117` | `+= 0.5` si au moins 3 sponsorisés (beaucoup de sponso = concurrence organique plus faible). **Seul** usage de `search.sponsored` dans un calcul de score : +0,5 en pénétration, soit +0,2 sur le score global |
| Pondération 0,4 / 0,4 / 0,2 | `scoring.py:125` | |
| Seuils de verdict 7,5 et 6,0 | `scoring.py:128-130` | **Quatre** libellés, pas trois : « Concurrence non mesurée — à relancer » court-circuite les seuils quand `mesuree` est faux, puis à analyser en priorité / intéressant / faible |
| **Drapeaux de lecture des suggestions** | `niche_validator.py:55-96` + `scoring.py:145-149` | `terme_dominant`, `part_dominante`, `intention_informationnelle`, `marqueurs_informationnels` sont **recopiés tels quels** dans `ScoredNiche` et **n'entrent dans aucun axe** |
| Règles KDP des 7 mots-clés | `kdp_keywords.py` | **Vérifiées côté code**, pas seulement demandées au prompt : limite dure de 50 caractères, 7 emplacements, `TERMES_INTERDITS` (livre/ebook/kindle/gratuit/meilleur/nouveau/années/amazon/bestseller…), dédup normalisée, chevauchement total avec le titre. **Chaque rejet sort avec son motif** |
| Taxonomie fiction contraignante | `fiction_ideator.py:177-180` / `fiction_classifier.py:148-164` | L'ideator **écarte** tout trio hors taxonomie ; le classifieur range les clés inconnues dans `other` au lieu de les jeter. Asymétrie assumée : l'ideator invente, le classifieur observe |
| **Contraintes de composition vérifiées après le modèle** | `fiction_ideator.py:181-184` | Trope imposé absent, ou décor imposé non respecté → trio écarté. Le prompt les demande, le code les impose |

### 4.2 NON CODÉ — intentions, prompts ou impossibilités

| Sujet | Statut réel |
|---|---|
| Exclusions « saisonnier / religions à expertise pointue / politique contemporaine / borderline TOS / niches d'experts ultra-techniques » | **Non codées.** Elles n'existent que comme texte dans le prompt système de l'ideator (`niche_ideator.py:38-45`). Aucun filtre, aucune liste de mots interdits, aucune vérification a posteriori. **Si le modèle désobéit, rien ne le rattrape** — contrairement aux règles KDP, à la taxonomie fiction et aux contraintes de composition, explicitement doublées en code |
| Axe 3 « compatibilité livre » | **Non implémenté.** `scoring.py:123` le fige à la constante `8.0` pour toute niche. L'axe ne discrimine rien : le score global vaut toujours `demande×0,4 + penetration×0,4 + 1,6`, mécaniquement borné entre 2,4 et 9,6 |
| Bonus « expertise pharmacien » (santé/nutrition/bien-être) | **Non codé et délibérément contredit** : `niche_ideator.py:47-50` impose au contraire au modèle de ne privilégier aucun domaine et de ne rien supposer de l'expertise de l'auteur |
| Malus pour risque KDP TOS | **Non codé.** `NicheCandidate.risques` (`models.py:24`) est rempli par le LLM (champ `required` dans le schéma d'outil) mais n'est propagé nulle part : ni `NicheValidation`, ni `ScoredNiche`, ni le scoring, ni l'affichage. **Champ mort** |
| « Nombre de résultats de recherche Amazon inférieur à 10 000 » | **Non codé et non mesurable en l'état** : la donnée n'est pas collectée. `SearchResult.total_items` vaut `len(items)` de la page de SERP (`search_providers.py:86`), pas le total annoncé par Amazon, et n'entre dans aucun calcul |
| `IDEES_PAR_RUN = 10` | **Constante morte** (`web/server.py:134`, zéro référence ailleurs). Le vivier réellement appliqué est de **12**. Ne pas documenter 10 comme le comportement du produit — cf. §2.2 |

---

## 5. PIÈGES ÉTABLIS EN LIVE

Section critique. Chacun a coûté un bug réel.

**Scoring et lecture des résultats**

1. **La saturation est le seul score inversé.** Sur `depth_score` et `openness_score`, élevé = bon ;
   sur `saturation_trio`, élevé = **mauvais**. Une jauge colorée uniformément fera recommander
   exactement les pires niches. Encodé dans `history.py:25-26` (`METRIQUES_INVERSEES`) et dans le
   tri de `fiction_master.py:173`.
2. **`non_mesurable` n'est pas « mort ».** Les deux affichent des zéros partout mais disent le
   contraire à l'utilisateur : l'un l'invite à re-mesurer, l'autre à écarter la niche.
   `fiction_scoring.py:160-164` rend explicitement `non_mesurable` quand aucun livre n'est
   scorable, et `_verdict` l'écrit en toutes lettres. Vu en live sur « romance captif huis clos ».
3. **Un rayon amputé n'est pas un rayon désert.** `FictionShelf.n_echecs > 0` signifie que des
   ASIN n'ont pas pu être enrichis (`fiction_master.py:159-162`, `fiction_scoring.py:206-208`).
   Masquer cette mention transforme une donnée manquante en « place à prendre ».
4. **Le piège `label_rayon`.** `FictionNiche.rayon` vaut `"kindle"`/`"papier"` (paramètre interne)
   alors que `EnrichedBook.bsr_rayon` porte le libellé Amazon `"Boutique Kindle"`/`"Livres"`.
   Passer `niche.rayon` tel quel à `est_payant_dans()` rend `False` pour **tous** les livres et
   déclare la niche morte **sans la moindre erreur**. Passer par `fiction_taxonomy.label_rayon()`.
   Documenté trois fois (docstrings de `EnrichedBook.est_payant_dans` `models.py:251-259`, de
   `fiction_taxonomy.label_rayon`, de `fiction_scoring.livres_scorables`) parce que le bug a déjà
   été commis une fois.
5. **Les BSR Kindle et papier ne se comparent pas** : deux classements distincts, c'est la raison
   d'être du champ `bsr_rayon` (`models.py:222-233`).
6. **Les titres gratuits ont leur propre classement** — ~25 % du top Kindle mesuré
   (`SEUILS["part_gratuits_mesuree"]`). Exclus via `bsr_gratuit`, à ne jamais réintroduire dans
   un calcul maison.
7. **Le lookahead sur « en Livres ».** Un ebook affiche « n°478 des titres gratuits dans la
   Boutique Kindle … 5 en Livres électroniques de fiction criminelle ». Sans le `(?!\s+\w)`, le
   parseur renvoyait 5 au lieu de 478 — faux de deux ordres de grandeur, et silencieux.
   `search_providers.py:199-203`, `amazon_product.py:13`.
8. **« Livre 1 sur 1 » n'est pas une série** : Amazon balise un tome unique comme une collection
   d'un seul titre. `EnrichedBook.est_serie` (`models.py:245-249`) exige `serie_total > 1`
   (constaté sur B0GN4G414V).

**Mesure de la demande**

9. **L'autocomplete est préfixe-based.** Sonder une expression longue de longue traîne rend
   systématiquement 0 (« cosy mystery boulangerie bretagne » → rien), ce qui garantissait 0
   confirmation sur 7 en live. `kdp_keywords.py` sonde donc les **3 premiers mots** (amorce) :
   on vérifie que l'amorce est cherchée, **pas** que la phrase exacte l'est — ce qu'aucun outil
   ne peut établir depuis l'autocomplete.
10. **Une mesure en panne n'est pas un signal absent.** Invariant le plus répété du dépôt, et
    présent dans les deux moteurs : `AutocompleteSignal.mesure` a un défaut **pessimiste**
    `False` (`models.py:204-213`), `FictionNicheReport.autocomplete_score` rend `None` et non
    `0.0` (`models.py:320-326`), `MotsClesKDP.sonde_indisponible` existe pour la même raison
    (`models.py:152-155`), `ScoredNiche.concurrence_mesuree` fait de même pour la SERP
    non-fiction (`models.py:103-107`), `lire_suggestions` ne conclut rien sur zéro suggestion, et
    `amazon_autocomplete.py` maintient deux fonctions (`fetch_json_strict` qui lève,
    `_default_fetch_json` qui avale) précisément pour ne jamais confondre une panne réseau avec
    « personne ne cherche ça ». **Même partage côté BSR depuis le 2026-09-14** : `resolve_bsrs`
    écrivait une fiche NON LUE (503, tâche jamais prête) 3 jours dans le cache MUTUALISÉ comme
    « absence de classement », pour tous les comptes. Seul un `None` RENDU par une fiche lue
    (`fetch_bsr_strict`, `_Payloads.lus`) se mémorise désormais ; les pannes sont annoncées.
    **Trou connu** : un captcha servi en 200 se lit encore comme une absence (aucune capture HTML
    réelle d'un blocage, donc aucun discriminant codé).
11. **L'autocomplete ne gate jamais seul.** Le spike M0 §V3 est formel et le code le respecte :
    `_matrix_mesuree` (`fiction_scoring.py:168-183`) n'utilise nulle part l'autocomplete pour
    arbitrer `demand_matrix`.
12. **Un point unique n'est pas une tendance.** `history.py` rend `None` quand il n'y a qu'un
    passage. `SEUIL_SIGNIFICATIF=0.10` (`history.py:30`) filtre le bruit de mesure : en deçà, on
    n'annonce rien plutôt que de faire réagir un auteur sur du vent.
13. **Un vivier plus large ne change pas la note de demande.** Le scoring plafonne à
    `min(demand_score, 10)` (`scoring.py:91`) : trois viviers (10/20/30) mesurés sur
    « bien-être » sortent tous leurs 4 finalistes au-dessus du plafond. Élargir change QUELLES
    niches sont testées, jamais leur note. Ne pas « améliorer » le produit en augmentant le
    vivier sans relever d'abord ce plafond.

**Coût, cache, infrastructure**

14. **L'empreinte de schéma dans la clé de cache** (`cache.py:20-81`) : les **quatre** clés
    portent un SHA1 des **noms** de champs de leur modèle pydantic — `book:` (`EnrichedBook`,
    `cache.py:121`), `bsr:` (`BsrInfo`, `:113`), `search:` (`SearchResult`, `:117`) et `clf:`
    (`TropeClassification`, `:144`). `clf:` porte **en plus** la version de taxonomie, le modèle
    et un SHA1 du prompt système (`_prompt_tag()`) : ce qui change le raisonnement, là où
    l'empreinte de champs couvre ce qui change la forme du résultat. Sans elles, ajouter un champ
    (le blurb l'a été en M4) sert des objets amputés en silence — 15 jours pour `book:`,
    **30 jours pour `clf:`** — et durcir le prompt n'a aucun effet sur les livres déjà vus.
    **Limite assumée** : l'empreinte suit les noms, pas les types ni la sémantique — changer le
    sens d'un champ sans le renommer exige de vider le cache à la main. Ni la logique du PARSEUR :
    le run 4 l'a payé (§5.38).
    **Corollaire des derniers commits** : `ScoredNiche` a gagné quatre champs de prix et quatre
    drapeaux de suggestions, mais **il n'est pas mis en cache** — aucune purge n'était nécessaire.
15. **Le cache est mutualisé entre tous les utilisateurs, par conception** (`cache.py:1`, rappelé
    dans `auth.py:26-30`). Ce n'est pas un oubli de cloisonnement : deux clients qui analysent le
    même rayon ne le paient qu'une fois. **Maintenant que l'authentification existe**, la règle
    est active et non plus théorique : `user_id` vit dans `history.py` / `usage.py` / `jobs.py` /
    `auth.py`, **jamais** dans `cache.py`.
16. **La file ASIN se paie une fois par run, pas par niche** (`fiction_master.py:10-13`) : ~250 s
    quel que soit le lot. Revenir à un batch par niche ferait passer 10 niches de 5 à 42 minutes.
17. **Le budget de poll a été doublé après un incident** (`search_providers.py:145-150`) : à
    16 polls (128 s), un simple ralentissement de la file DataForSEO effaçait un run entier —
    3 SERP sur 3 expirées, mesuré en live. C'est désormais 40 polls (~320 s), aligné sur le
    chemin ASIN, et le message d'erreur dit le budget écoulé pour distinguer « file lente » d'une
    vraie erreur de requête.
18. **Pas de `temperature` / `top_p` / `top_k` sur `claude-sonnet-5`** : ces paramètres sont
    supprimés et toute valeur non-défaut renvoie une **400** (`fiction_classifier.py:182-184`).
    La stabilité des étiquettes se joue dans le prompt.
19. **Ne pas rétrograder le classifieur.** Haiku 4.5 mesuré à 42 % d'accord humain/IA contre 80 %
    requis. « Accord » est défini explicitement (`fiction_validation.py:1-8`) :
    Jaccard(tropes) ≥ 0,5 **ET** décor identique **ET** `est_roman` identique. Sous la porte des
    80 %, c'est la **taxonomie** qu'on corrige, pas le classifieur.
20. **Instance par appel, jamais à l'import.** `Cache`, `JobStore`, `UsageMeter`, `NicheHistory`
    **et `UserStore`** ouvrent une connexion SQLite par appel avec WAL ; `web/server.py:56-59` ne
    garde que des constantes `Path`. Construire un magasin à l'import écrirait de vrais fichiers
    dans le dépôt dès qu'un test importe `server.py`, et casserait la sûreté en concurrence (le
    serveur lance un thread par run).
21. **Les défauts de modèle sont lus à l'import, AVANT `load_dotenv()` en CLI.**
    `DEFAULT_MODEL = os.getenv(...)` s'exécute au chargement du module alors que `scout_master.py`
    n'appelle `load_dotenv()` qu'à l'intérieur de `run_scout` (ligne 48), après avoir importé
    `niche_ideator` (ligne 16). Un `IDEATOR_MODEL` défini uniquement dans `.env` est donc
    **ignoré en ligne de commande**. `web/server.py` y échappe parce qu'il appelle `load_dotenv`
    (ligne 32) **avant** ses imports moteur (ligne 33 et suivantes) : un ordre qui a l'air d'un
    détail de style et qui est en fait load-bearing.
22. **`POST /api/jobs` accepte deux jeux de noms de paramètres** (`_run_scout_job`,
    `web/server.py:638-639`) : `n_ideas`/`n_search` **et** les noms historiques `ideas`/`search`,
    parce qu'une divergence a été constatée en live — un client reprenant les noms de l'ancien
    flux direct voyait son plafond silencieusement ignoré et payait les défauts. À conserver tant
    qu'un client tiers peut exister, même si l'UI n'envoie plus que `n_search`.
23. **Le plafond couvre désormais TOUT chemin payant — l'ancienne rédaction de ce piège était
    périmée deux fois.** (a) `GET /api/scout` et `GET /api/fiction` **n'existent plus** ;
    (b) `_verifier_plafond` garde `/api/verdict` et `/api/kdp-keywords`, et `POST /api/jobs` fait
    sa propre vérification. **Et l'interface passe désormais exclusivement par `/api/jobs`** — le
    bandeau « Ce mois-ci : N analyse(s) » se remplit donc réellement. Nuance à conserver :
    `/api/verdict` et `/api/kdp-keywords` imputent avec `n_analyses=0` (ils complètent une analyse
    déjà comptée) — **ils exigent une marge sous le plafond sans la consommer**, tandis que leur
    coût en dollars, lui, est bien enregistré.
24. **`FictionNicheReport` interdit les champs extra** (`model_config extra="forbid"`,
    `models.py:302`) : un champ mal nommé lève à la construction plutôt que d'être avalé en
    silence. C'est ce qui a permis d'attraper l'ancien `autocomplete_score` mal placé. Corollaire
    à ne pas oublier : `autocomplete_score` étant une `@property`, elle n'est pas sérialisée par
    `model_dump` — `_run_fiction_job` la ré-injecte à la main (`web/server.py:456`).
25. **L'en-tête `Content-Disposition` doit rester encodable en latin-1** (exigence Starlette) :
    `_content_disposition` (`web/server.py:620-627`) émet un nom ASCII de repli et un
    `filename*` RFC 5987 UTF-8, sinon un nom de niche accentué fait planter la réponse. Même
    famille de contrainte pour les PDF : fpdf2 en police core Helvetica exige l'assainisseur
    latin-1 de `positioning_pdf.py`.

**Interface**

26. **~~Les boutons « Télécharger le PDF » et « Mots-clés KDP » sont inatteignables~~ —
    CORRIGÉ le 2026-08-18, dans les deux moitiés.** Ils naissaient dans `verdictBlock(r)`,
    qui sort par `if(!v) return ''` ; or `_run_scout_job` appelle `run_scout` sans
    `n_verdict`, donc `verdict` valait TOUJOURS `None`. Trois endpoints — `/api/verdict`,
    `/api/pdf`, `/api/kdp-keywords` — étaient développés, testés, payés, et sans aucun
    chemin d'accès.
    `verdictSlot(r)` rend désormais l'un ou l'autre état, JAMAIS le vide : un bouton
    « Analyser cette niche (~10 s) » tant qu'il n'y a pas de verdict, le bloc complet
    ensuite. `brancherActions()` est le SEUL site de branchement — les boutons naissent
    deux fois (au rendu, puis après injection), et deux sites divergeraient.
    **L'historique fiction, écrit et jamais lu, est corrigé aussi** : `renderFic` porte
    maintenant son `histslot`, chargé à l'ouverture de la carte.
    **La leçon, elle, est intacte et vaut plus que le correctif** : `test_ux_kdp_historique`
    vérifiait que les chaînes étaient PRÉSENTES dans le HTML et passait au vert pendant que
    les boutons étaient morts. Une chaîne présente dans un fichier ne prouve rien sur ce qui
    est cliquable. Les nouveaux tests EXÉCUTENT les fonctions de rendu (§2.10).

27. **Plus aucun coût affiché, nulle part** (commit `4165efb`). Ont disparu de `web/index.html` :
    la barre « Coût de ce run », le montant du bandeau mensuel, les infobulles de coût,
    `TAUX_USD_EUR`, `fmtUsd`, `formatCost` — `grep` rend zéro occurrence de `usd` ou de `$`
    monétaire. Le montant a **aussi** été retiré des messages de `progress` de
    `scout_master.py:125-130` et `fiction_master.py:179-180`, parce qu'il revenait à l'écran par
    ce canal ; les CLI, elles, l'impriment toujours (`scout_master.py:155`,
    `fiction_master.py:201`) — c'est l'outil de contrôle du développeur, pas l'écran du client.
    **Le backend continue de TOUT mesurer et imputer** : le plafond en dépend, et ce sera la base
    d'une facturation en jetons ou par abonnement. **Ne pas confondre « ne plus afficher » et
    « ne plus compter ».** Seule exception, volontaire : la **fourchette de prix des LIVRES**
    (`fmtEur`, `web/index.html:1048`) reste — c'est une donnée de marché, pas une facture.
28. **Les bornes serveur et formulaire coïncident désormais — les vérifier ENSEMBLE.**
    `#search` va jusqu'à 20 (`web/index.html:555`) comme `MAX_RECHERCHES` (`web/server.py:136`) ;
    `#fic-n` jusqu'à **11** (`:625`) comme `MAX_NICHES_FICTION` (`:144`) ; `#lc-search` jusqu'à 20
    comme `MAX_RECHERCHES_LC` (`:147`). La règle à tenir n'est plus « le serveur est plus
    permissif » mais **« le serveur ne doit jamais être PLUS STRICT que le formulaire »** : sinon
    une saisie valide à l'écran ressort en 400, et c'est l'utilisateur qui paie l'incohérence.
    `tests/test_devis.py` et `tests/test_ux_presets.py` lisent la constante au lieu de figer un
    littéral, pour que relever le plafond ne laisse pas le formulaire en arrière.


30. **En low-content, `n_variantes_quasi_identiques` se lit à l'ENVERS.** Élevé = mauvais :
    dix couvertures pour un seul intérieur, c'est une ferme de variantes, et publier la
    onzième n'y gagne rien. C'est le piège n°1 (saturation fiction) transposé, et la carte
    l'écrit à l'écran. Une jauge colorée uniformément ferait recommander exactement les
    pires rayons.

31. **Le BSR est DÉJÀ dans l'enrichissement ASIN.** `parse_enriched_book` le parse ;
    appeler `resolve_bsrs` derrière sur les MÊMES ASIN les facture une seconde fois. À la
    borne serveur : 240 appels pour 120 ASIN, 0,78 $ contre un plafond de 0,60 $, franchi
    **en silence**. Seuls les ASIN ABSENTS du dict d'enrichissement valent un second
    passage — `a not in enrichis`, jamais `a not in rangs` : un livre rendu SANS BSR
    lisible (un carnet classé « en Fournitures de bureau ») ne rendra rien de plus au
    second appel, `parse_asin_bsr` étant plus stricte que `parse_bsr_rank`.

32. **Une constante dupliquée dans deux modules est un défaut invisible par construction.**
    `BOOK_TTL_S` valait 15 j dans `cache.py` (documenté, testé) et 7 j dans
    `fiction_serp_provider.py` (appliqué). Le test d'harmonisation surveillait la constante
    MORTE et passait au vert en garantissant le contraire de ce qu'il annonçait. Règle qui
    en découle : **tester la valeur réellement PASSÉE**, jamais la présence d'une constante.

33. **Un état global de module se propage entre tests exactement comme un chemin de base.**
    Le sémaphore de créneaux (`server._CRENEAUX`) survivait d'un test à l'autre : un test
    terminé pendant qu'un fil détenait encore un créneau laissait la place prise pour les
    suivants, qui échouaient **par intermittence**, sur des sujets sans rapport. Six échecs
    sur une exécution, zéro sur la suivante. `conftest.isoler_bases` le réinitialise.

34. **`n_enfants=0` ne veut pas dire « feuille stérile ».** Une requête au fond de l'arbre
    n'est JAMAIS sondée, tout comme celles que le budget de sondes a coupées : leur
    compteur vaut `None`, pas zéro. Ce n'est pas cosmétique — ce compteur est le premier
    critère de tri de la shortlist, donc il DÉCIDE DE CE QU'ON PAIE.

35. **Le filtre IP ne matchait que la forme EXACTE, et personne ne pouvait le savoir.**
    Mesuré sur 198 requêtes portant une marque sous une forme mutée : **198 échappaient**.
    Le matcher tolère désormais apostrophe typographique (la forme OFFICIELLE de
    Pat'Patrouille, T'choupi, McDonald's), séparateur libre entre mots, pluriel dans les
    DEUX sens, déterminant et mots de liaison internes optionnels. Les bornes de mot
    restent intactes : c'est elles qui empêchent « om » de sortir de « bonhomme ».
    **Et la mesure a révélé cinq faux positifs qui existaient déjà** — « cahier de révision
    BTS MCO » était rejeté en silence. Un rejet muet ne se remarque pas. Règle appliquée :
    on RETIRE un terme dont l'usage légitime est une catégorie COURANTE du low-content, on
    le GARDE quand cet usage est incident. Deux arbitrages restent, nommés dans le test.

36. **Un audit qui ignore une décision documentée ne la périme pas.** Signalé : une SERP
    qui répond sans aucun organique déclenche le bonus « moins de 10 concurrents ». C'est
    exact, et la correction a été écrite — puis retirée, parce que
    `test_un_rayon_mesure_et_reellement_vide_reste_une_bonne_nouvelle` disait déjà : « une
    SERP qui répond EST une mesure ; il ne faut pas punir la mesure sous prétexte de
    corriger l'absence de mesure ». Le risque reste connu et ÉCRIT : une anomalie de
    parsing produirait le même signal qu'un rayon vide, et ce signal est le plus flatteur
    possible. Si elle est observée en live, c'est ce test-là qu'il faudra retourner.

37. **Une fixture INVENTÉE a fait payer 185 fiches pour rien.** `asin_fr_lowcontent.json`
    (ASIN `B0LOWCONT1`, commit `feacd71`) écrivait la pagination sous une clé de FORMAT :
    `{"Broché": "120 pages"}`. Le parseur de `fiction_books.py` a été écrit pour elle, et ses
    tests passaient au vert. Or amazon.fr écrit « Nombre de pages de l'édition imprimée » : 8
    captures réelles sur 8, ebook Kindle compris. Aucune n'a jamais porté la forme inventée.
    Au run 4, `pages=None` sur les 185 fiches payées : redevance jamais calculée, porte
    indécidable, 0,7208 $. La fixture est supprimée, le parseur lit la vraie clé (la clé de
    format reste un simple repli), et `format_papier`, jamais observé, reste `None`.
    **Le cliquet est `tests/test_fixtures_pagination_reelles.py`** : seule une capture réelle
    DÉCLARÉE peut fonder une assertion `.pages` sur une sortie de `parse_enriched_book`.
    **Même famille, même jour** : l'expression `_SUB` du scraping BSR avait été réglée sur une
    fixture HTML inventée. Sur 29 extraits réels, elle perdait 11 sous-catégories sur 75 et en
    polluait 7. **Règle** : un test qui valide un parseur contre une forme que personne n'a
    observée ne prouve que l'accord de son auteur avec lui-même. Toute forme d'une source
    externe vient d'une capture ; une fixture inventée le DIT dans son docstring (§2.10).

38. **Le cache garde des objets ANALYSÉS : corriger un parseur ne rattrape rien.** `book:` et
    `search:` stockent l'`EnrichedBook` et le `SearchResult` déjà parsés. Leur empreinte suit
    les NOMS des champs (§5.14), pas la logique du parseur. Le parseur corrigé laisse donc le
    cache MUTUALISÉ resservir, 15 jours et à tous les comptes, les fiches qu'il avait mal lues.
    Le rapport conseillait pourtant de « relancer ». **Voie retenue par Baptiste : la purge
    ciblée à la main** (§2.14), avec sauvegarde et date butoir. Une empreinte du source du
    parseur dans la clé aurait invalidé aussi le cache FICTION à chaque retouche de
    `fiction_books.py`. Le brut, lui, ne va jamais dans le cache partagé : seule la CLI de
    calibration l'écrit dans des fichiers de run, et le produit ne capture rien. **Choix
    inverse, et délibéré, pour le classement low-content** : on y garde la réponse BRUTE de
    l'outil, justement pour qu'un correctif de lecture s'applique sans rien repayer.
    **Corollaire de lecture** : après un correctif de parseur, la ligne « N/M fiche(s)
    servie(s) par le cache » est l'alerte, pas une bonne nouvelle.
    **Depuis le 2026-10-03 cette ligne n'atteint plus l'utilisateur** (décision de Baptiste : il n'a pas à savoir
    qu'un cache existe) : `progression_publique.py` la retire à la LECTURE d'un travail et du flux SSE, le brut
    reste dans `jobs.db` et dans la CLI. **Pour ce diagnostic, lire `jobs.db` ou lancer la CLI, pas l'écran.**

39. **Le prix d'Amazon est TTC, le prix catalogue KDP est HORS TVA — et le grand format a sa
    propre grille.** La formule comparait le prix affiché au seuil de 9,99 € et calculait la
    redevance dessus : un carnet à 10,49 € affichés (8,74 € HT à 20 %) passait pour « 60 % »
    et prenait +2 en rentabilité. **Ampleur au run 4 NON MESURÉE** : 5 niches sur 31 (toutes
    « mauvaise ») basculent quand on RECONSTRUIT les médianes sur la fixture, tronquée à 12
    organiques, et 2 autres (disjointes) sur 6 organiques ; le produit prend la médiane sur
    toute la SERP (`depth=100`), non versionnée, et trois des cinq basculent au centime.
    **Vérifié dans le tableau de bord KDP de Baptiste le 2026-09-15** : le prix saisi est HT,
    9,47 € HT (9,99 € TTC) donnent 50 %, et le barème retrouve au centime les redevances de
    deux livres réels (5 x 8 po et A4, encre noire). Le grand format coûte 2,48 € sous 110
    pages contre 2,05 € : 120 fiches sur 184 lisibles au run 4. **La page fr_FR du barème
    (G201834340) écrit « largeur ET hauteur »** ; les trois autres pages et le tableau
    officiel des tailles disent « OU » — c'est « OU » qui est codé (`kdp_print_costs.json`).
    Hypothèses dites à l'écran, jamais tues : TVA de 20 % supposée (non observable par ASIN),
    encre noire supposée, format « non déterminé » → barème standard. Le prix médian affiché
    reste TTC : c'est la donnée de marché. Tests : `test_redevance_hors_tva_grand_format.py`.
    **Deux corollaires, relevés par la revue du correctif.** (1) Un résultat ANTÉRIEUR (sans
    `prix_catalogue_ht`, relu depuis `jobs.db` ou renvoyé à `/api/verdict` et `/api/dossier`)
    garde un drapeau et une redevance calculés sur le prix affiché : la carte, le brief du
    verdict et le dossier n'en montrent plus la redevance (« à recalculer »), et seul un ancien
    « sous 9,99 € » reste signalé, le prix hors TVA étant toujours plus bas. (2) `history.db`
    stocke `rentabilite` et `global_score` sans version de formule : un passage d'avant et un
    passage d'après feraient lire un faux « recul » (−2 en rentabilité sans aucun mouvement du
    marché). Aucun écran ne montre l'historique low-content aujourd'hui ; **à traiter AVANT d'y
    brancher un `histslot`**. Même famille que §5.38 : un correctif de calcul change ce que
    mesure un chiffre déjà stocké.


**Invariant transversal**

29. **Un échec n'interrompt jamais un run, mais il est toujours compté — et il ne doit jamais se
    lire comme une mesure.** Search en échec → niche scorée sans concurrence
    (`scout_master.py:89-91`) **et marquée `concurrence_mesuree=False`**, ce qui la prive de tout
    bonus de pénétration, lui donne un verdict explicite et l'exclut de l'historique
    (`_consigner_scout`, `web/server.py:381-382` : un point qu'on sait faux produirait au passage
    suivant un delta spectaculaire et mensonger) ; SERP créée puis non lue (poll épuisé,
    relecture illisible, Ctrl-C) → **imputée**, seul un `TaskPostRefuse` explicite ne l'est pas ;
    lot ASIN dont l'ENVOI lève → **imputé au pire cas** (`taches_incertaines`) et annoncé
    « peut-être facturé », parce que le code ne peut pas savoir ce que le fournisseur a créé ;
    refus de COMPTE (`RefusCompte`) → plus aucun appel au fournisseur, le cache continue de
    servir, niches restantes non mesurées et comptées ; scrape BSR en échec sur un ASIN → `None`
    pour cet ASIN, jamais mémorisé comme absence ; lecture illisible après un appel LLM payé sur
    `/api/verdict` ou `/api/kdp-keywords` → 502, coût soldé dans un `finally` ; niche fiction en échec → écartée et comptée, rayons déjà payés conservés
    (`fiction_master.py:96-100`) ; livre au payload atypique → `None` au lieu d'une
    `ValidationError` qui tuerait le run ; job en échec → **le coût déjà engagé reste imputé**
    (`web/server.py:549-552`) ; base absente à la reprise des données locales → l'inscription
    aboutit quand même (`:277-280`).

---

## 6. RÈGLES DE FONCTIONNEMENT PERMANENTES

1. **TDD non négociable.** Les tests d'abord, **en rouge**, avant toute ligne d'implémentation.
   On vérifie que le test échoue pour la bonne raison, puis on écrit le minimum qui le fait
   passer. Aucune fonctionnalité ne rentre sans test hors-ligne, dépendance lourde injectée par
   paramètre — c'est ce qui tient les 1643 tests sans réseau. Données réelles d'abord ; une
   fixture inventée est déclarée comme telle (§5.37).
2. **Transparence sur les échecs et les coûts.** Toujours dire quelle source a échoué, combien
   d'ASIN n'ont pas pu être enrichis, combien de sponsorisés ont été écartés. Ne jamais masquer
   un échec partiel ni arrondir un coût vers le bas. Distinguer toujours un chiffre mesuré d'un
   chiffre extrapolé. **Nuance depuis `4165efb`** : le coût n'est plus montré à l'utilisateur
   final, il reste intégralement mesuré et disponible côté serveur — la transparence porte
   désormais sur les échecs à l'écran, et sur le coût dans la CLI, les logs et `usage.db`.
3. **Ne jamais présenter une absence de mesure comme un verdict de marché.** `non_mesurable` n'est
   pas « niche morte ». Sonde autocomplete en panne n'est pas « personne ne cherche ça ». Rayon
   amputé n'est pas « place à prendre ». `delta: null` n'est pas une erreur. Zéro trio sous
   contraintes n'est pas « ce marché est mort ». C'est la faute la plus grave que ce produit
   puisse commettre : elle fait publier un livre sur une niche vide, ou renoncer à une bonne.
4. **Sécurité : ne jamais rouvrir ce qui a été fermé.** Pas de `user_id` en paramètre ou en corps
   de requête. Pas de nouveau chemin de dépense qui contourne le plafond. Pas de paramètre de
   volume non borné. Pas de secret en clair en base. Toute nouvelle route qui dépense passe par
   `_verifier_plafond` **et** `origine_sure`.
5. **Ne jamais toucher aux dossiers hors du projet.** Le périmètre est la racine du dépôt
   `IA Niches` et rien d'autre. En particulier, ne jamais approcher les dossiers personnels ou
   comptables de Baptiste.
6. **Secrets dans `.env` uniquement.** Jamais de clé dans un fichier versionné, jamais dans un
   message, jamais dans un log. `.env.example` documente les noms, pas les valeurs.
7. **Pas de devinettes.** Si une donnée manque, le dire ou la demander. Ne jamais écrire un nom de
   fichier, de fonction, d'endpoint ou un chiffre qui n'a pas été vu dans le code.
8. **Le code est la doc.** Avant de modifier un module, lire son docstring : il porte les
   contraintes mesurées en live. Toute décision non évidente se documente **dans le code**, pas
   dans un .md à part. Quand un piège de §5 est corrigé ou aggravé, mettre ce fichier à jour.
9. **Économie de coût.** Le gate de validation autocomplete (gratuit) avant tout appel payant est
   structurel : ne jamais lancer un appel DataForSEO ou LLM « au cas où ». Vérifier le cache
   avant. Grouper les appels ASIN. Un nouvel appel payant se justifie par écrit.
10. **Confirmation avant action lourde** : avant d'écraser un fichier existant, de vider le cache,
    de lancer un run réel qui dépense, ou de modifier une valeur par défaut de modèle.
11. **Sortie utile en cas d'échec** : rapport partiel avec mention explicite des sources tombées,
    jamais un plantage muet. C'est déjà l'invariant du code (§5.29), c'est aussi la règle de
    conduite de l'agent.

---

## 7. CE QUI N'EXISTE PAS

À ne jamais présenter comme disponible, à ne jamais réintroduire par inadvertance.

- **`GET /api/scout` et `GET /api/fiction`** : **supprimés** (commit `5257323`). Il n'existe plus
  qu'un seul chemin de lancement, `POST /api/jobs` + `/api/jobs/{id}/stream`. Ne pas les
  recréer « pour le debug » : c'est précisément le chemin non exercé qui dérive.
- **Paiement, abonnement, facturation, jetons, prestataire d'encaissement** : **rien n'est
  intégré.** L'usage et le coût sont mesurés et stockés (`usage.db`), ce qui donne la base d'une
  facturation future, mais aucun montant n'est présenté à l'utilisateur et aucun encaissement
  n'existe. **En revanche l'authentification, les comptes et le multi-utilisateur EXISTENT
  désormais** (§2.1) — ne plus les lister ici.
- **Réinitialisation de mot de passe (par e-mail), vérification d'adresse, changement
  d'e-mail, rôles ou administration** : aucun de ces chemins n'est codé. `INSCRIPTIONS_OUVERTES`
  se règle par `.env`, pas par une interface. **Nuance depuis le 2026-10-02** : le CHANGEMENT
  de mot de passe par un utilisateur connecté (`POST /api/auth/mot-de-passe`, exige l'ancien,
  referme les autres sessions) et la CLÔTURE de compte (`POST /api/auth/compte/suppression`,
  exige le mot de passe, efface travaux, consommation et historique — jamais le cache
  mutualisé) existent, avec leur menu dans l'interface. Un mot de passe OUBLIÉ reste un compte
  perdu : il n'y a ni envoi de lien, ni question secrète, et c'est délibéré — ce serait une
  surface d'attaque sur un service sans adresse vérifiée. **Nuance depuis `notification.py`** : un e-mail SORTANT existe désormais (message
  de fin d'analyse, §2.16), éteint par défaut. Ça ne rend ni l'adresse vérifiée, ni le mot de
  passe récupérable — le seul envoi codé est transactionnel et ne porte aucun lien d'action.
- **Support d'une autre place de marché qu'`amazon.fr`** : `marketplace.py` rassemble les
  neuf codages en dur, et `MARKETPLACE=com` **lève** au démarrage. Six choses du dépôt sont
  irréductiblement françaises (§2.15). Ne pas lire ce module comme un support multi-marché :
  il rend le manque explicite, il ne le comble pas.
- **Mentions légales, politique de confidentialité et CGV SERVIES** : les quatre documents
  existent en **brouillon** dans `docs/pages-publiques/`, ancrés sur le code, mais aucun
  endpoint ne les sert et chacun porte des `[[A COMPLETER : … ]]` (identité légale,
  hébergeur, prix, délai de rétractation). `tests/test_pages_publiques.py` verrouille le
  lien : dès qu'une route sert un de ces fichiers, il ne doit plus rester un marqueur.
- **Calibration du scoring low-content** : l'outillage existe (§2.14), et une mesure décidable
  aussi (run 5, 2026-09-18) — **porte NON franchie** (+0,358).
  Les seuils de `data/lowcontent_criteres.json` restent des hypothèses tant que Baptiste n'a
  pas rempli le gabarit et fait tourner `build_lowcontent_validation_set.py --xlsx`. Ne
  jamais citer ces seuils comme des critères établis.
- **Scrapingdog** : aucun code, aucune clé, aucun appel. Côté `.py`, le mot ne subsiste que
  dans le docstring de `cost_tracker.py:2`. Il subsiste en revanche dans des fichiers non
  exécutables encore versionnés (`README.md`, `ROADMAP.md`, `docs/superpowers/**`) et une
  variable résiduelle peut traîner dans le `.env` local (non versionné) : la nettoyer ne change
  rien au comportement, mais ne pas la lire comme une intégration vivante.
- **`credits_tracker.py`, `MAX_CREDITS_PER_RUN`, plafond de crédits par run, mode dry-run au
  premier lancement, retry gaté à 1 tentative avec 5 s de délai, compteur « crédits restants sur
  1000 »** : rien de tout cela n'existe. Les seuls garde-fous de dépense sont
  `PLAFOND_ANALYSES_MENSUEL` (via `_verifier_plafond` et `POST /api/jobs`) et les bornes de
  volume `MAX_IDEES` / `MAX_RECHERCHES` / `MAX_NICHES_FICTION`.
- **Rapport Excel `.xlsx` du scout** (onglets Synthèse / Métadonnées / Sponsorisés, mise en forme
  conditionnelle) : n'existe pas. `openpyxl` est **conservé** dans `requirements.txt` parce qu'il
  est importé par `fiction_validation.py` **et par trois fichiers de tests**
  (`test_build_validation_set.py`, `test_fiction_validation.py`, `test_validate_classifier.py`) :
  outillage de validation **manuelle** du classifieur, pas un livrable. Les résultats du scout ne
  sortent qu'en JSON (job) et en PDF one-pager.
- **Google Trends (`pytrends`), Reddit (`praw`), Google News (`feedparser`)** : les modules
  `trends_fr.py`, `reddit_fr.py` et `news_fr.py` ont été **supprimés** (commit `eaa20b2`), avec
  eux le dossier `02-veille-hebdo/`. Nuance à respecter : `pytrends`, `praw` et `feedparser`
  n'étaient pas sans import, ils étaient importés par ces trois modules et sont donc morts **en
  cascade** ; seuls `pandas`, `beautifulsoup4` et `lxml` avaient réellement zéro occurrence (le
  parsing des fiches Amazon se fait en expressions régulières pures, cf. `amazon_product.py`).
- **Les dossiers `00-config/`, `02-veille-hebdo/`, `03-niches-validees/` et `04-archives/`** :
  absents du disque, ne pas les recréer, ne pas y renvoyer. Dossiers réellement présents :
  `01-scripts/`, `05-prompts/`, `99-logs/`, `assets/`, `data/`, `docs/`, `tests/`, `web/`.
  **Nuance d'attribution** : `eaa20b2` ne supprime que `00-config/` et `02-veille-hebdo/` ;
  `03-niches-validees/` et `04-archives/` étaient **vides et n'ont jamais été versionnés** — git
  ne suit pas les dossiers vides, chercher leur suppression dans `git show eaa20b2` est une perte
  de temps. De `05-prompts/`, seul `prompt-onebooklab-template.md` subsiste — workflow manuscrit
  personnel de Baptiste, **hors du périmètre de cet outil**. Restent versionnés et à conserver :
  `99-logs/validation-fiction-2026-07-21.xlsx` et
  `99-logs/rapport-validation-classifieur-2026-07-21.json` (étalon-or du classifieur), plus
  `assets/hedgehog.ico`. Coût de reproduction : **0,32 $ d'API**, seul chiffre sourçable
  (`tutoriel_pdf.COUTS`, marqué « one-shot »), plus une relecture humaine dont la **durée n'est
  pas mesurée** — l'« environ une heure » ne vient que du message du commit `eaa20b2` et de
  `ROADMAP.md`, jamais du code ni du rapport, qui ne porte que `lignes_relues_declarees: 35` sur
  `livres_du_set: 50` et la mention `validation tacite declaree par Baptiste`.
- **TikTok**, sous quelque forme que ce soit : ni automatisé, ni en input manuel.
- **Le mode « à partir de rien » nourri par des tendances** : `signals` existe dans les signatures
  et va jusqu'au prompt, mais aucun appelant ne le remplit. Il se réduit à « graine vide ».
- **Le workflow humain en 5 phases** (validation humaine, analyse sur screenshots, pré-production,
  post-production) : aucune trace en code. Le prompt de `niche_verdict.py` dit même explicitement
  au modèle de ne pas réclamer de screenshots et de raisonner sur les chiffres.
- **Sommaire détaillé en chapitres, prompts OneBookLab, briefs de couverture, quatrième de
  couverture, fiche produit AIDA, liste de 15 mots-clés à vérifier** : rien.
  `MotsClesKDP.a_verifier` n'est pas cette liste : c'est le reliquat des candidats au-delà des
  7 emplacements.
- **Aucun endpoint ne sert le dossier de passation ni le guide utilisateur.** `tutoriel_pdf.py`
  est un script autonome.
- **Aucune base partagée, aucun Docker, aucun déploiement EN COURS.** Cinq fichiers SQLite
  (`df-cache.db`, `jobs.db`, `usage.db`, `history.db`, `comptes.db`), désormais dans le
  répertoire que `DATA_DIR` désigne. **Nuance depuis le 2026-09-07** : le dépôt est
  DÉPLOYABLE — `requirements.txt` racine, `Procfile`, `HOST` déduit, `DATA_DIR` exigée en
  prod, récupération des travaux interrompus au démarrage (§2.17). Rien n'est déployé pour
  autant : aucun hébergeur n'est configuré, aucun volume n'existe, aucun HTTPS n'est monté,
  et **`JOBS_MODE=worker` suppose que les deux processus voient le MÊME `DATA_DIR`** — sur
  une plateforme où un volume ne s'attache qu'à un seul service, ce mode est inutilisable en
  l'état, il faut rester en `thread`.
- **Aucun test d'intégration réseau.**
