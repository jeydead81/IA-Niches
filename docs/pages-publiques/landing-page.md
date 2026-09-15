# IA-Niches

## Accroche

**Savoir si un rayon Amazon est pénétrable avant d'écrire le livre.**

IA-Niches confronte une idée de niche à ce qui se vend réellement sur amazon.fr : ce que les gens tapent, qui occupe le top, à quel rang de vente, à quel prix. Et quand une mesure n'a pas pu être faite, il l'écrit — au lieu d'afficher un zéro.

Une analyse prend de 2 à 12 minutes selon le moteur et le volume demandé.

---

## Le problème

Chercher une niche à la main, c'est ouvrir trente onglets Amazon, noter des BSR dans un tableur, deviner qui est éditeur et qui est auto-édité, et finir sans savoir si le rayon est tenu ou s'il reste de la place.

Les outils qui automatisent ça ont trois défauts récurrents :

- **Ils affichent un zéro quand ils n'ont rien mesuré.** Une requête Amazon qui échoue, un prix qu'Amazon ne renvoie pas, un éditeur illisible : le tableau montre `0` et vous lisez « rayon vide, place à prendre ». C'est l'erreur qui coûte le plus cher, parce qu'elle fait publier dans le désert.
- **Ils comptent les livres sponsorisés comme des concurrents.** Un livre qui a payé sa place au-dessus des résultats ne dit rien de ce qu'il faut battre organiquement.
- **Ils font inventer les niches par un modèle de langage.** Un LLM à qui on demande des requêtes de longue traîne invente aussi la demande qui va avec.

---

## Ce que fait l'outil

Trois moteurs, trois onglets, trois façons de poser la même question : *ce rayon est-il attaquable ?*

### 1. Non-fiction

Vous donnez une graine (un domaine, un thème). L'IA propose une douzaine de niches. **Chacune est d'abord confrontée gratuitement à l'autocomplete d'Amazon** : celles qui ne déclenchent aucune complétion ne coûtent jamais un appel payant. Les niches retenues passent à la mesure réelle — résultats de recherche avec séparation organique / sponsorisé, rang de vente (BSR) du top, fourchette de prix du rayon, nombre de concurrents qui ciblent vraiment la requête.

Sortie : un score sur trois axes (demande, pénétration, compatibilité), les trois critères BSR (au moins un livre sous 10 000, moyenne du top sous 50 000, au moins un au-delà de 50 000 = de la place), et la liste des livres à battre.

Durées mesurées en live : ~2 min (3 niches), ~4 min (6 niches), ~7 min (10 niches).

### 2. Fiction

La fiction ne s'achète pas sur un sujet mais sur une **promesse d'histoire**. Le moteur part donc d'un *trio* : sous-genre × tropes × décor. Six sous-genres sont couverts, avec leur taxonomie de tropes et de décors.

Vous laissez l'IA proposer des trios, ou vous composez le vôtre en imposant des tropes et un décor. Un trio proposé qui ne respecte pas vos contraintes est **rejeté côté code**, pas seulement déconseillé au modèle.

Le moteur lit ensuite les **quatrièmes de couverture** des livres du rayon et les classe par trope. C'est ce qui permet de calculer la *saturation du trio* : combien de livres déjà en place racontent exactement votre promesse. Aucun comptage de résultats ne donne cette information.

Durées : ~5 min (3 trios), ~8 min (5 trios), ~12 min (8 trios).

### 3. Low-content

Carnets, registres, grilles de jeux, cahiers de coloriage, planners : le livre dont la valeur est dans la structure des pages. 36 formats sont décrits dans la taxonomie de l'outil.

Ici le mécanisme est **inversé** : l'outil descend l'arbre des complétions d'amazon.fr, requête par requête, et remonte ce que les gens tapent réellement. Le modèle de langage n'intervient qu'ensuite, pour **classer** ces requêtes réelles (quel format, quel thème, quel public). Il ne peut pas inventer une demande qui n'existe pas.

S'ajoutent deux mesures qui n'existent nulle part ailleurs dans l'outil :

- **la part indie** — combien de livres du top sont publiés en « Independently published » plutôt que par un papetier installé. Un rayon très demandé mais tenu par des éditeurs n'est pas attaquable par un auteur seul ;
- **la redevance KDP réelle**, calculée sur les barèmes relevés chez Amazon.

Durées : ~3 min (3 niches), ~5 min (6 niches), ~9 min (10 niches).

---

## Ce qui le distingue

### Il dit quand il n'a pas mesuré

C'est le parti pris central, et il traverse tout le code.

- Une recherche Amazon qui échoue produit **« Concurrence non mesurée — à relancer »**, pas un score. Aucun bonus de pénétration n'est appliqué, parce que les compteurs à zéro le sont faute de mesure, pas parce que le rayon est vide.
- Un prix absent affiche **« Prix du rayon : inconnu — c'est une donnée absente »**, jamais 0 €.
- Un BSR non résolu affiche **« non mesuré »**, jamais 0 — zéro est le *meilleur* classement possible, l'afficher pour une donnée absente inverserait complètement la lecture.
- Une part indie non calculable vaut **« non mesuré »**, jamais 0 % — 0 % se lirait « rayon tenu par des éditeurs ».
- En fiction, un rayon dont aucun livre n'est exploitable sort en **« Non mesuré »**, distinct de « rayon mort ».
- Une requête jamais sondée dans l'arbre low-content est marquée comme telle, distincte d'une requête sondée qui n'a rien donné.

Corollaire assumé : l'outil vous rendra parfois « je ne sais pas ». C'est le seul cas où la bonne réponse est celle-là.

### Les sponsorisés sont écartés des calculs de qualité

Titres, notes, avis, prix, comptage des concurrents ciblés, choix des livres dont on va chercher le BSR : tout se calcule sur les résultats **organiques** uniquement. La séparation se fait dès la lecture de la réponse Amazon, pas après coup.

Nuance, parce qu'il n'y a pas de raison de la cacher : leur **nombre** est lu, une fois. Beaucoup de sponsorisés signale une concurrence organique plus faible, et vaut un léger bonus de pénétration. Aucun sponsorisé n'entre jamais dans une mesure de qualité du rayon.

### En low-content, les niches ne sont pas inventées

L'arbre d'autocomplete est la **source** des niches, pas leur validation. Le LLM reçoit des requêtes qu'Amazon complète déjà et les étiquette. Un mode « à partir de rien » existe pour démarrer sans graine — dans ce cas la demande est une hypothèse, et le rapport le dit explicitement au lieu de mélanger les deux.

Ce même arbre apporte un signal qu'aucun comptage ne donne : **une requête que les acheteurs affinent encore** porte une intention plus forte qu'une requête terminale.

### La redevance KDP est calculée, pas supposée

Sous 9,99 € de prix catalogue hors TVA — le prix que vous saisissez dans KDP —, KDP verse 50 % au lieu de 60 %. Les prix du rayon, eux, sont affichés TVA comprise : pour un carnet ou un coloriage, le seuil tombe vers 11,99 € affichés. Le coût d'impression se déduit ensuite, et il dépend de la pagination et du format de coupe. **Un rayon très demandé à 6,99 € peut ne rien rapporter** — voire coûter de l'argent sur une forte pagination.

L'outil applique les barèmes relevés sur les pages d'aide KDP (coût d'impression et taux de redevance, marketplace amazon.fr, format standard et grand format lu sur les dimensions des livres du top), vérifiés au centime sur deux livres réels dans un tableau de bord KDP. Une redevance négative est affichée **telle quelle** : c'est le seul cas où la réponse est « ne publie pas ça ». Et si le prix ou la pagination manque, la redevance est « inconnue », jamais zéro.

### Un devis est fait avant chaque analyse

Avant qu'un seul appel payant ne parte, l'outil estime le coût **maximal** du run — cache supposé vide, configuration de production. Si ce plafond est dépassé, il refuse tout de suite, en vous disant **quel volume tiendrait** : « vous avez demandé 12 ; le maximum qui tient est 7. Rien n'a été lancé, et rien n'a été dépensé. »

C'est ce qui garantit qu'on ne vous rendra jamais un rapport tronqué à mi-parcours. Le plafond en cours de run existe toujours, mais comme filet de dernier recours, plus comme mode de fonctionnement normal.

### Un filtre marques, côté code

En low-content, l'autocomplete est plein de requêtes sous marque déposée — ce sont exactement celles que les gens tapent, donc celles qui ressortent en tête avec tous les signes d'une excellente niche. Un cahier sous marque n'est pas une niche médiocre : c'est un retrait de publication, et répété, une fermeture de compte.

L'outil les écarte avant même l'appel au modèle, **et donne le motif du rejet** — « écartée (marque « pokemon ») » — parce qu'un rejet muet ferait passer un rayon filtré pour un rayon vide.

### Le run survit à la fermeture de l'onglet

L'analyse tourne côté serveur. Vous pouvez fermer la page : en revenant, vous retrouvez la progression depuis le début, ou le résultat s'il est terminé.

---

## Comment ça marche, en 3 étapes

**1. Vous choisissez un moteur et une graine.**
Non-fiction : un thème. Fiction : un sous-genre, et si vous voulez vos tropes et votre décor. Low-content : une graine ou un format. Puis un volume : Rapide, Standard ou Approfondi — la durée annoncée à côté de chaque bouton.

**2. L'outil mesure.**
D'abord ce qui est gratuit (l'autocomplete Amazon), qui sert de filtre : ce qui ne passe pas ne coûte rien. Ensuite ce qui est payant, uniquement sur ce qui a passé le filtre. La progression s'affiche étape par étape, échecs compris.

**3. Vous lisez le rapport, et vous creusez si vous voulez.**
Chaque niche est notée, avec le détail des mesures et la liste des livres du top. À la demande — et seulement à la demande — vous pouvez générer une analyse éditoriale de la niche, les 7 mots-clés backend KDP, ou un dossier de niche en PDF (les concurrents, l'angle, les catégories où ranger le livre).

---

## Ce que ça ne fait PAS

Autant le dire ici plutôt que de vous le laisser découvrir.

- **Ça ne promet aucune vente.** L'outil mesure une demande et une concurrence à un instant donné. Il ne sait pas si votre livre sera bon, ni si votre couverture donnera envie.
- **Ça n'écrit pas le livre.** Ni sommaire, ni chapitres, ni quatrième de couverture, ni brief de couverture.
- **Ça ne couvre qu'amazon.fr.** Pas les autres marketplaces, pas les autres plateformes.
- **Ça ne mesure pas le nombre total de résultats d'une recherche Amazon.** La donnée n'est pas collectée, donc aucun critère du type « moins de 10 000 résultats » n'est appliqué.
- **La redevance suppose l'encre noire et une TVA de 20 %** : aucune fiche Amazon ne dit l'encre ni le taux de TVA appliqué. Le format de coupe (standard ou grand format) est lu sur les dimensions des livres du top ; s'il ne peut pas être déterminé, le barème standard est appliqué et l'écran le dit — la redevance d'un rayon en réalité en grand format est alors surestimée. La couleur premium et le papier avec bois ne sont pas relevés.
- **Il n'y a ni réinitialisation de mot de passe, ni vérification d'adresse e-mail, ni suppression de compte.** Ces chemins n'existent pas dans le produit à ce jour. Un mot de passe perdu est un compte perdu.
- **Aucun paiement n'est intégré.** Voir la section tarif.
- **Ce n'est pas un service hébergé clé en main aujourd'hui.** [[A COMPLETER : mode de distribution retenu — installation locale par le client, hébergement fourni, ou les deux]]

---

## Tarif

[[A COMPLETER : montant TTC affiché au visiteur, en euros — non décidé à ce jour ; les chiffres de cadrage évoqués en session de travail ne sont PAS des décisions]] — [[A COMPLETER : unité (par mois, par an, à vie) et ce qu'elle inclut, par exemple un nombre d'analyses]]

Ce qu'il faut savoir avant que ce chiffre soit fixé :

- **Aucun système de paiement n'est intégré au produit à ce jour.** Pas de prestataire d'encaissement, pas d'abonnement, pas de facturation. La consommation est mesurée et stockée par utilisateur, ce qui donnera la base d'une facturation, mais rien n'est branché.
- Chaque analyse consomme des appels payants chez deux fournisseurs (l'API Anthropic pour l'analyse, DataForSEO pour les données Amazon). C'est ce coût que le devis avant lancement borne.
- Un plafond d'analyses par utilisateur, sur 30 jours glissants, peut être configuré par l'exploitant. Il n'est pas activé par défaut.

[[A COMPLETER : essai gratuit ou démonstration — existe-t-il, et sous quelle forme]]
[[A COMPLETER : délai de rétractation retenu, et mention de la renonciation éventuelle pour un service numérique fourni immédiatement]]
[[A COMPLETER : modalités de résiliation]]

---

## FAQ

**Est-ce que l'outil me garantit que la niche va marcher ?**
Non, et il est construit pour ne pas le laisser croire. Il mesure une demande (ce que les gens tapent), une concurrence (qui est en place et à quel rang de vente), et pour le low-content une rentabilité (la redevance KDP réelle). Le reste — la qualité du livre, la couverture, le moment — ne se mesure pas depuis Amazon. Une niche bien notée est une niche où il reste de la place, pas un livre qui se vendra.

**Combien de temps prend une analyse ?**
De 2 à 12 minutes selon le moteur et le volume : ~2 à ~7 min en non-fiction, ~5 à ~12 min en fiction, ~3 à ~9 min en low-content. Ce sont des ordres de grandeur mesurés en conditions réelles, dominés par la file d'attente du fournisseur de données. Vous pouvez fermer la page pendant ce temps : le travail continue et vous le retrouvez en revenant.

**D'où viennent les données ?**
De trois sources. L'autocomplete public d'amazon.fr, gratuit, qui sert à mesurer la demande et à filtrer avant toute dépense. L'API DataForSEO, payante, pour les pages de résultats Amazon et les fiches produit (rang de vente, éditeur, prix, pagination, quatrième de couverture). L'API Anthropic, payante, pour l'idéation, le classement et les analyses éditoriales. Rien n'est acheté à un revendeur de données tierces.

**Pourquoi le rapport dit parfois « non mesuré » au lieu de me donner un chiffre ?**
Parce que la donnée n'a pas pu être obtenue, et qu'afficher zéro à sa place serait un mensonge dans le sens le plus dangereux. Un zéro de concurrence se lit « place à prendre » ; un zéro de prix se lit « rayon bradé » ; un BSR à zéro se lit « meilleure vente d'Amazon ». Quand la mesure manque, l'outil le dit et vous invite à relancer.

**Pourquoi les livres sponsorisés sont-ils écartés ?**
Parce qu'un livre sponsorisé occupe sa place parce qu'il l'a payée, pas parce qu'il se vend. Le juger comme un concurrent organique fausserait la mesure de ce qu'il faut réellement battre. Leur nombre reste lu, une fois, comme indice : beaucoup de publicité dans un rayon signale souvent une concurrence organique plus faible.

**En quoi le moteur low-content est-il différent des deux autres ?**
Par l'ordre des opérations. En non-fiction, l'IA propose et Amazon valide. En low-content, Amazon fournit d'abord les requêtes réelles — l'outil descend l'arbre des complétions — et l'IA se contente ensuite de les classer. La demande est acquise avant que le modèle ne parle. S'ajoutent deux mesures propres à ce rayon : la part de livres auto-édités dans le top, et la redevance KDP réelle compte tenu du prix et de la pagination.

**Pourquoi calculer la redevance ? Je connais mes prix.**
Parce que le seuil des 9,99 € est brutal : en dessous, KDP verse 50 % au lieu de 60 %, et le coût d'impression se déduit ensuite. Et ce seuil porte sur le prix catalogue hors TVA que vous saisissez dans KDP, pas sur le prix affiché au client, qui inclut la TVA. Un carnet très demandé à 6,99 € avec une forte pagination peut rapporter quelques centimes, ou rien. L'outil applique les barèmes relevés chez Amazon et affiche le résultat même quand il est négatif. Ces barèmes changent sans préavis : ils portent leur date de relevé, et un relevé ancien doit être revérifié.

**Est-ce que je risque de dépenser sans le vouloir ?**
Non. Avant chaque analyse, un devis estime le coût maximal du run en supposant le cache vide. S'il dépasse le plafond configuré, l'analyse est refusée immédiatement, en vous indiquant quel volume tiendrait — rien n'est lancé, rien n'est dépensé. Les analyses complémentaires (analyse éditoriale, mots-clés, dossier PDF) ne partent que si vous cliquez.

**Mes données sont-elles partagées ?**
Vos comptes, votre historique de niches, vos travaux et votre consommation sont cloisonnés par utilisateur. Le cache des réponses Amazon, lui, est volontairement mutualisé : si un autre utilisateur a analysé le même rayon récemment, la donnée n'est pas rachetée. Ce cache ne contient que des données publiques Amazon (résultats de recherche, fiches produit), jamais rien qui vous concerne. [[A COMPLETER : renvoi vers la politique de confidentialité]]

**Qui est derrière l'outil ?**
[[A COMPLETER : présentation de l'éditeur, identité légale et statut]]

---

[[A COMPLETER : appel à l'action final — formulaire d'inscription, liste d'attente, ou prise de contact, selon le mode de distribution retenu]]

<!--
SOURCES VERIFIEES (lecture du code le 2026-08-22, branche a11y-live-et-cibles, commit 8c5f209)

TROIS MOTEURS
- 01-scripts/scout_master.py:26-45  run_scout(), non-fiction : ideator -> validation autocomplete -> search -> BSR -> scoring
- 01-scripts/fiction_master.py      run_fiction_scout(), fiction
- 01-scripts/lowcontent_master.py:1-21  docstring des 6 phases low-content, ordre inverse
- web/index.html:522-524            les trois onglets Non-fiction / Fiction / Low-content

DUREES ANNONCEES
- web/index.html:1186-1202  PRESETS. scout 3/6/10 niches = ~2/~4/~7 min ; fiction 3/5/8 trios = ~5/~8/~12 min ;
                            lowcontent 3/6/10 = ~3/~5/~9 min. Commentaire : "ordres de grandeur mesures en live
                            (latence DataForSEO 85-251 s par SERP en non-fiction ; file ASIN ~250 s payee UNE fois par run)"
- web/index.html:542-546, 614-618, 697-701  memes durees dans les boutons du formulaire

GATE GRATUIT AVANT DEPENSE
- 01-scripts/scout_master.py:14 (import niche_validator) ; CLAUDE.md/§2.2 : shortlist = validated[:n_search]
- 01-scripts/niche_validator.py  validate_niches, autocomplete gratuit
- 01-scripts/lowcontent_master.py:96-113  phase 0 arbre gratuit, filtres appliques AVANT tout appel payant

"IL DIT QUAND IL N'A PAS MESURE"
- 01-scripts/scoring.py:113-125  mesuree = search is not None ; aucun bonus/malus si faux
- 01-scripts/scoring.py:134-137  verdict "Concurrence non mesuree -- a relancer"
- web/index.html:1128, 1138-1140  affichage "Non mesuree" + encadre explicatif
- web/index.html:1111-1113  "Prix du rayon : inconnu -- ... c'est une donnee absente"
- web/index.html:870-871, 884  BSR : "non mesure" et JAMAIS 0 (commentaire : zero est le MEILLEUR classement)
- web/index.html:1270-1276  part indie "non mesuree" et jamais 0 %
- 01-scripts/lowcontent_scoring.py:83-101  _part() exclut les inconnus du denominateur, rend None
- 01-scripts/fiction_scoring.py:160-164 (via CLAUDE.md) + web/index.html:1581  verdict non_mesurable distinct
- 01-scripts/autocomplete_expand.py:44-49  n_enfants=None = JAMAIS sondee, distinct de 0 = sondee et sterile
- web/index.html:1974-1975, 2031  "pieges de lecture" affiches a l'utilisateur

SPONSORISES
- 01-scripts/scoring.py:...  titres/prix/notes/count_targeted calcules sur `organic` uniquement
- 01-scripts/scoring.py:121-122  SEUL usage du nombre de sponsorises : +0.5 penetration si >= 3
- 01-scripts/lowcontent_scoring.py:355-356  "les SPONSORISES sont ecartes de tout calcul de qualite"
- web/index.html:794  glossaire "Sponso ecartes"

LOW-CONTENT : NICHES LUES, PAS INVENTEES
- 01-scripts/autocomplete_expand.py:1-18  docstring : l'arbre est la SOURCE, le LLM classe ensuite
- 01-scripts/lowcontent_ideator.py:1-13   "le LLM CLASSE des requetes reelles, il n'en invente pas" ;
                                          mode ideation subsiste pour graine vide, source="ideation"
- 01-scripts/lowcontent_ideator.py:56-58  "REQUETE_AMAZON : recopie la requete EXACTEMENT"
- 01-scripts/autocomplete_expand.py:34-42  n_enfants = signal d'affinage
- data/lowcontent_taxonomy_fr_v1.json     36 formats (cle "formats")

REDEVANCE KDP
- data/kdp_print_costs.json  _source : RELEVE, pages d'aide KDP G201834340 (couts), G201834330 (redevance),
                             GPQL5W3J6WNRCZTV (TVA) et G201834180 (tailles de coupe) ; date_releve 2026-09-15,
                             marketplace fr ; seuil_taux_haut 9.99, taux_bas 0.5, taux_haut 0.6 ; DEUX bandes par
                             encre ; grand_format (regle OU, 15,55 / 22,86 cm) ; tva.taux_lowcontent 0.2 (SUPPOSE)
- data/kdp_print_costs.json  redevance._note : seuil et taux sur le prix HORS TVA, verifie dans un tableau de bord KDP
                             le 2026-09-15 sur deux livres reels
- data/kdp_print_costs.json  _avertissement : couleur premium et papier avec bois non releves ; baremes Amazon,
                             a reverifier apres un an
- 01-scripts/lowcontent_scoring.py:212       prix_catalogue_ht() : prix affiche TTC -> prix catalogue HORS TVA
- 01-scripts/lowcontent_scoring.py:233, 256  format_coupe_livre() / format_coupe_dominant() : format lu sur les
                                             dimensions ; non determine -> bareme standard, dit a l'ecran
- 01-scripts/lowcontent_scoring.py:275-331  redevance_estimee() : None si prix ou pages manquent ;
                                            redevance NEGATIVE rendue telle quelle
- 01-scripts/lowcontent_scoring.py:3-9      docstring : "un rayon tres demande a 6,99 EUR peut ne rien rapporter"

PART INDIE
- 01-scripts/lowcontent_scoring.py:11-14, 103-113  part_indie / part_editeurs_traditionnels
- web/index.html:778  glossaire "Part indie"

DEVIS AVANT DEPENSE
- 01-scripts/devis.py:1-30  docstring : estimation du PIRE cas en amont, refus immediat, cache suppose VIDE
- 01-scripts/devis.py:118-129  message de refus : "Vous avez demande N ; le maximum qui tient est M.
                               Rien n'a ete lance, et rien n'a ete depense."
- web/server.py:762-768  verifier_devis() appele dans POST /api/jobs AVANT creation du job (400)

FILTRE MARQUES / IP
- 01-scripts/ip_filter.py:1-18  docstring : enjeu JURIDIQUE, cote code et AVANT l'appel LLM, chaque rejet avec son MOTIF
- 01-scripts/lowcontent_master.py:104-106  progress "ecartee (marque ...)"
- data/exclusions_ip.md  liste versionnee (392 lignes, commentaires inclus)

RUN QUI SURVIT A LA FERMETURE DE L'ONGLET
- web/server.py:737-742  docstring POST /api/jobs : thread detache, progression persistee
- web/server.py:858+     GET /api/jobs/{id}/stream, SSE reconnectable
- web/index.html:1435-1436, 1491  reprise du travail au rechargement

ANALYSES COMPLEMENTAIRES A LA DEMANDE
- web/server.py:907-936   POST /api/verdict (0,0283 $ piece, n_analyses=0)
- web/server.py:953-970   POST /api/kdp-keywords (7 mots-cles backend, ~0,006 $)
- web/server.py:972-1028  POST /api/dossier (3 pages ; mots-cles generes SEULEMENT si demandes)
- web/index.html:926, 973, 1069, 1372  ces trois appels sont bien cables dans l'UI

FICTION
- 01-scripts/fiction_scoring.py:4, 117  saturation_trio, "seule metrique qui repond..." (lecture des blurbs)
- 01-scripts/fiction_ideator.py:181-184 (via CLAUDE.md) contraintes verifiees COTE CODE apres le modele
- data/fiction_taxonomy_fr_v1.json  6 sous-genres
- 01-scripts/fiction_serp_provider.py:22-29  n_top = 12 ASIN par niche

CRITERES BSR NON-FICTION
- 01-scripts/scoring.py:12-31  crit1 best < 10 000 ; crit2 top5_avg < 50 000 ; crit3 worst > 50 000

COMPTES ET DONNEES
- 01-scripts/auth.py:1-31  scrypt, mot de passe jamais stocke, jeton de session jamais en clair
- 01-scripts/auth.py:43-59  12 caracteres min, session 30 jours, limitation des tentatives
- 01-scripts/auth.py:26-30  cache MUTUALISE entre comptes, user_id jamais dans cache.py
- 01-scripts/usage.py:1-9   plafond PAR utilisateur, mensuel GLISSANT (30 j), non active par defaut
- web/server.py:387  INSCRIPTIONS_OUVERTES : ferme par defaut
- 01-scripts/cache.py  cache SQLite local, 99-logs/df-cache.db

CE QUI N'EXISTE PAS
- grep stripe|paddle|paypal|checkout sur 01-scripts/ et web/ : aucun prestataire de paiement
- web/index.html:1922-1923  "la facturation se fera en jetons ou par abonnement" (donc pas encore)
- CLAUDE.md §7 + absence dans auth.py : pas de reinitialisation de mot de passe, pas de verification
  d'e-mail, pas de suppression de compte
- 01-scripts/search_providers.py:86 (via CLAUDE.md §4.2) : total_items = len(items) de la page,
  PAS le total annonce par Amazon -> aucun critere "< 10 000 resultats"

NON VERIFIABLE, LAISSE EN PLACEHOLDER
- prix, unite, essai gratuit, delai de retractation, resiliation, identite legale de l'editeur,
  mode de distribution (local vs heberge), politique de confidentialite, appel a l'action final
-->
