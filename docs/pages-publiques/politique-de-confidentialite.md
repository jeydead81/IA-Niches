# Politique de confidentialité

**Dernière mise à jour : [[A COMPLETER : date d'entrée en vigueur, format JJ/MM/AAAA]]**

Ce document décrit exactement ce que le logiciel **IA-Niches** enregistre, pourquoi, où,
pendant combien de temps, et à qui ces informations sont transmises. Chaque affirmation
factuelle qu'il contient a été vérifiée dans le code source ; la liste des fichiers lus
figure en fin de document.

Quand une information ne peut pas être établie depuis le code — identité légale de
l'éditeur, hébergeur, adresse de contact —, elle apparaît en clair comme un élément à
compléter, jamais comme une valeur plausible inventée.

---

## 1. Qui est responsable du traitement

- **Responsable de traitement :** [[A COMPLETER : nom et prénom ou dénomination sociale de l'éditeur]]
- **Statut juridique et immatriculation :** [[A COMPLETER : forme juridique, SIRET / SIREN, ou mention « personne physique non immatriculée »]]
- **Adresse :** [[A COMPLETER : adresse postale du responsable de traitement]]
- **Contact pour toute question relative aux données personnelles :** [[A COMPLETER : adresse e-mail de contact dédiée]]
- **Délégué à la protection des données (DPO) :** [[A COMPLETER : « aucun DPO désigné, la désignation n'étant pas obligatoire au titre de l'article 37 du RGPD » — ou coordonnées du DPO si un est désigné]]

**Hébergement de l'application et des données :**
[[A COMPLETER : nom, raison sociale, adresse et pays d'implantation des serveurs de l'hébergeur — ou mention « l'application est installée et exécutée par l'utilisateur sur son propre matériel », si c'est le mode de distribution retenu]]

Cette précision n'est pas cosmétique. Aujourd'hui, le code ne prévoit aucun serveur
distant : les cinq bases de données sont des fichiers locaux placés dans le dossier
`99-logs/` de l'installation. Selon que l'application tourne sur le poste de l'utilisateur
ou sur un serveur exploité par l'éditeur, l'identité du responsable de traitement et la
localisation des données changent complètement.

---

## 2. Périmètre : ce que fait l'application

IA-Niches analyse des niches de livres sur Amazon.fr pour des auteurs auto-édités. Trois
moteurs d'analyse coexistent : non-fiction, fiction et low-content. Chacun combine :

- l'autocomplétion publique d'Amazon.fr (gratuite),
- l'API **DataForSEO**, qui restitue des pages de résultats Amazon et des fiches produit,
- l'API **Anthropic** (Claude), qui propose des idées de niches et analyse des textes de
  quatrième de couverture.

L'application est **mono-page**, servie par un serveur local, et ne comporte **aucun
traceur, aucun cookie publicitaire, aucune analytique tierce**. Une inspection exhaustive
de l'unique fichier d'interface ne fait apparaître **qu'une seule ressource externe** : un
import de polices Google Fonts (voir § 7.4).

---

## 3. Données traitées, base par base et champ par champ

Toutes les données sont enregistrées dans cinq fichiers SQLite situés dans `99-logs/`.
Aucun autre stockage n'existe : ni fichier de log applicatif sur disque, ni base distante.

### 3.1 `comptes.db` — comptes, sessions, tentatives d'authentification

**Table `comptes`**

| Champ | Contenu réel |
|---|---|
| `user_id` | Identifiant aléatoire (UUID sans tiret). Sans lien avec l'e-mail. |
| `email` | Votre adresse e-mail, ramenée en minuscules et débarrassée des espaces de bord. Aucune autre transformation : ni retrait des points, ni retrait du `+suffixe`. |
| `sel` | 16 octets aléatoires, propres à votre compte. |
| `empreinte` | Empreinte `scrypt` de votre mot de passe (n = 16 384, r = 8, p = 1, 32 octets). |
| `params` | Les paramètres scrypt utilisés, en clair (`scrypt:16384:8:1`), pour pouvoir les durcir plus tard sans invalider les comptes existants. |
| `cree_le` | Horodatage de création du compte. |

**Votre mot de passe n'est jamais enregistré**, ni en clair, ni chiffré de façon
réversible. Seule son empreinte scrypt l'est, et une empreinte ne se retourne pas.

**Table `sessions`**

| Champ | Contenu réel |
|---|---|
| `jeton_empreinte` | **Empreinte SHA-256** du jeton de session — jamais le jeton lui-même. Lire la base ne permet donc pas de voler une session en cours. |
| `user_id` | Le compte auquel la session appartient. |
| `cree_le`, `expire_le` | Ouverture et expiration de la session (30 jours). |

**Table `tentatives`** — c'est la seule table de l'application qui enregistre une **adresse IP**.

| Champ | Contenu réel |
|---|---|
| `email` | Selon le cas : l'adresse e-mail saisie lors d'une tentative de **connexion échouée**, ou la chaîne `ip:<votre adresse IP>` lors d'une **inscription**. |
| `horodatage` | Date et heure de la tentative. |

Ce compteur existe pour une seule raison : sans lui, une liste des mille mots de passe les
plus courants se teste en ligne contre une adresse connue en moins d'une minute.

### 3.2 `usage.db` — consommation et coût technique

**Table `usage`** : `user_id`, `type` d'appel (`scout`, `fiction`, `lowcontent`,
`verdict`, `kdp_keywords`, `dossier`), `cout_usd` (le coût technique réel de l'appel en
dollars, calculé à partir des tarifs des fournisseurs), `n_analyses`, `horodatage`.

Cette table ne contient **ni e-mail, ni adresse IP, ni contenu d'analyse** : uniquement un
identifiant de compte, un type d'opération, un montant et une date.

### 3.3 `history.db` — historique des niches analysées

**Table `passages`** : `user_id`, `type` de moteur, `cle` (le libellé de la niche, ramené
en minuscules et sans accents), `metriques` (un objet JSON ne contenant **que des
nombres** : scores, rangs de vente, nombre de concurrents), `vu_le`.

C'est ce qui permet de dire, au deuxième passage sur la même niche, si le rayon s'est
densifié ou dégagé. Une niche vue une seule fois ne produit aucune comparaison.

À noter : une niche dont la mesure de concurrence a **échoué** n'est volontairement pas
enregistrée — un point que l'on sait faux produirait une évolution mensongère au passage
suivant.

### 3.4 `jobs.db` — travaux d'analyse et leurs résultats

**Table `jobs`** : `id`, `user_id`, `type`, `params`, `statut`, `progression`, `resultat`,
`cout`, `erreur`, `cree_le`, `fini_le`, `maj_le`.

Deux champs méritent d'être explicités, car ce sont les seuls du produit qui conservent du
**texte que vous avez vous-même saisi** :

- **`params`** contient les paramètres de lancement, dont la **graine** — le thème que
  vous avez tapé (« ésotérisme », « sophrologie »…), limité à 80 caractères — ainsi que,
  pour la fiction, les contraintes de trio et le champ de texte libre du compositeur.
- **`resultat`** contient le rapport d'analyse complet au format JSON : niches proposées,
  requêtes Amazon, titres et prix des livres concurrents, scores.

Le champ **`erreur`** ne contient jamais le message brut d'une exception, mais une simple
référence d'incident (par exemple `Erreur interne (ref a1b2c3d4)`). Ce choix est
délibéré : le message d'une erreur réseau porte régulièrement l'URL appelée, et une URL de
fournisseur peut porter des identifiants d'accès.

La liste de progression est bornée aux 200 derniers messages.

### 3.5 `df-cache.db` — cache des réponses Amazon

**Table `kv`** : `key`, `value`, `expires`. Six familles de clés : rangs de vente par
ASIN (`bsr:`), absences de rang constatées (`bsr-absent:`), pages de résultats par mot-clé
(`search:`), fiches livre (`book:`), suggestions d'autocomplétion (`ac:`), classifications
de quatrièmes de couverture (`clf:`).

**Cette base ne contient aucune donnée personnelle** : uniquement des réponses publiques
d'Amazon (titres, prix, notes, classements, textes de présentation de livres) et les
étiquettes qu'un modèle de langage en a tirées. **Aucune clé ne porte de `user_id`** — et
c'est un choix d'architecture assumé, détaillé au § 8.

### 3.6 Ce que l'application ne collecte pas

Pour être complet sur ce qui n'existe pas : aucun nom, aucun prénom, aucune adresse
postale, aucune donnée de paiement, aucun numéro de téléphone, aucune donnée de
navigation, aucune donnée de géolocalisation, aucune donnée sensible au sens de
l'article 9 du RGPD. **Aucun moyen de paiement n'est intégré au produit.**

---

## 4. Finalités et bases légales

| Donnée | Finalité | Base légale (art. 6 RGPD) |
|---|---|---|
| E-mail, empreinte du mot de passe, `user_id` | Créer votre compte et vous authentifier | Exécution du contrat, art. 6.1.b |
| Jeton de session (empreinte) | Vous maintenir connecté sans redemander votre mot de passe à chaque page | Exécution du contrat, art. 6.1.b |
| E-mail et adresse IP dans `tentatives` | Empêcher les attaques par dictionnaire sur les mots de passe et la création automatisée de comptes | Intérêt légitime, art. 6.1.f — sécurité du service et des comptes de nos utilisateurs (également requis par l'art. 32 RGPD) |
| `usage.db` (nombre d'analyses, coût) | Appliquer un plafond d'usage par compte et maîtriser le coût technique réel, qui est facturé à l'éditeur par ses fournisseurs | Exécution du contrat, art. 6.1.b, et intérêt légitime, art. 6.1.f — prévention de l'abus |
| `history.db` (niches et métriques) | Vous permettre de voir l'évolution d'une niche entre deux analyses — c'est une fonctionnalité du produit, pas un profilage | Exécution du contrat, art. 6.1.b |
| `jobs.db` (graine, paramètres, résultats) | Exécuter votre analyse, la reprendre après une déconnexion, et vous en restituer le résultat | Exécution du contrat, art. 6.1.b |
| `df-cache.db` | Éviter de re-payer deux fois la même donnée auprès des fournisseurs | Intérêt légitime, art. 6.1.f — mais sans donnée personnelle, ce traitement ne relève pas du RGPD |

Aucun traitement ne repose sur le consentement, parce qu'aucun traitement n'est
facultatif : tous sont nécessaires au fonctionnement du service ou à sa sécurité. Il n'y a
donc pas de consentement à recueillir, ni à retirer.

**Aucune décision automatisée produisant des effets juridiques à votre égard** au sens de
l'article 22 du RGPD n'est prise. Les scores produits par l'application portent sur des
rayons de livres, pas sur des personnes.

---

## 5. Durées de conservation — et une limite qu'il faut dire clairement

Le code applique deux mécanismes très différents, qu'il serait malhonnête de confondre.

### 5.1 Les durées réellement appliquées

| Donnée | Durée inscrite dans le code | Effet |
|---|---|---|
| Session (cookie et ligne en base) | **30 jours** | Au-delà, la session n'est plus acceptée : il faut se reconnecter. |
| Tentatives de connexion / d'inscription | **15 minutes** de fenêtre glissante | Au-delà, les tentatives ne comptent plus dans le quota, et les lignes périmées sont supprimées à l'occasion de la tentative suivante. |
| Cache des résultats de recherche, des fiches livre et des rangs de vente | **15 jours** | Au-delà, la valeur n'est plus servie et l'information est redemandée à Amazon. |
| Cache des absences de classement | **3 jours** | Volontairement plus court : un livre peut entrer au classement à tout moment. |
| Cache des suggestions d'autocomplétion | **15 jours** | |
| Cache des classifications de quatrièmes de couverture | **30 jours** | |
| Fenêtre de consommation (`usage.db`) | **30 jours glissants** | C'est une fenêtre de **lecture** pour le calcul du plafond. |

### 5.2 Ce qui n'est jamais supprimé automatiquement

Il faut le dire sans détour, parce que c'est une limite réelle du produit et non une
omission de rédaction :

- **`history.db` et `usage.db` ne comportent aucune suppression automatique.** La fenêtre
  de 30 jours glissants de la consommation est une fenêtre de calcul : les lignes plus
  anciennes cessent d'être comptées, mais **restent enregistrées**.
- **`jobs.db` ne comporte aucune suppression automatique.** Vos analyses passées, y
  compris les thèmes que vous avez saisis, restent en base indéfiniment.
- **Les lignes de session expirées restent en base.** Le code contient bien une fonction
  de purge des sessions expirées, mais **aucune partie de l'application ne l'appelle**.
  Ces lignes ne permettent plus de se connecter, mais elles subsistent.
- **Le cache n'efface pas les valeurs périmées.** Un TTL est une date de péremption
  vérifiée à la lecture : passée l'échéance la valeur n'est plus servie, mais la ligne
  demeure jusqu'à ce qu'une nouvelle valeur l'écrase.
- **La purge des tentatives est opportuniste.** Elle n'a lieu qu'au moment où une nouvelle
  tentative est enregistrée. Si plus aucune tentative n'a lieu, une ligne — donc
  éventuellement une adresse IP — peut subsister au-delà des 15 minutes.

**Durée de conservation retenue après la clôture d'un compte :**
[[A COMPLETER : durée que vous vous engagez à respecter, par exemple « suppression sous 30 jours après demande de clôture » — et, tant que la suppression n'est pas automatisée, la procédure manuelle réellement appliquée]]

[[A COMPLETER : décider si une routine de purge sera ajoutée au produit, et sous quel délai. Tant qu'elle n'existe pas, cette section doit rester rédigée telle quelle : annoncer une purge qui n'a pas lieu serait une déclaration fausse.]]

---

## 6. Cookies et stockage local

### 6.1 Le seul cookie

| Nom | `ia_niches_session` |
|---|---|
| Finalité | Vous maintenir authentifié |
| Contenu | Un jeton aléatoire de 32 octets. Le serveur n'en conserve que l'empreinte SHA-256. |
| Durée | 30 jours |
| `HttpOnly` | Oui — le cookie est hors de portée de tout JavaScript, donc involable par injection de script |
| `SameSite` | `Lax` — le cookie ne part pas sur une requête déclenchée depuis un autre site |
| `Secure` | **Déduit du protocole** à chaque requête (en-tête `X-Forwarded-Proto`, à défaut le schéma de l'URL). Une variable d'environnement peut forcer le drapeau ; **rien ne peut le désactiver.** |

Ce cookie est **strictement nécessaire** au service. À ce titre, il ne requiert pas de
consentement préalable au sens de l'article 82 de la loi Informatique et Libertés.
**Aucune bannière cookies n'est donc affichée, et c'est légitime : il n'y a rien d'autre à
consentir.**

### 6.2 Stockage local du navigateur

Quatre clés sont écrites dans le `localStorage` de votre navigateur. Elles ne sont jamais
transmises au serveur et ne contiennent aucune donnée personnelle :

- `ia-niches-job-scout`, `ia-niches-job-fiction`, `ia-niches-job-lowcontent` : l'identifiant
  de l'analyse en cours dans chaque onglet, pour la reprendre après un rechargement de page ;
- `ia-niches-aide-repliee` : `0` ou `1`, selon que vous avez replié le panneau d'aide.

Vous pouvez les effacer à tout moment par les réglages de votre navigateur, sans autre
conséquence que la perte du suivi de l'analyse en cours.

---

## 7. Destinataires et sous-traitants

### 7.1 Qui a accès aux données en interne

[[A COMPLETER : préciser qui, concrètement, a accès aux cinq bases — par exemple « l'éditeur seul », ou la liste des personnes autorisées si l'application est hébergée pour des clients]]

Les fichiers de base de données ne sont pas chiffrés au repos par l'application
elle-même : toute personne disposant d'un accès au système de fichiers du serveur peut les
lire. C'est précisément pourquoi ni le mot de passe ni le jeton de session ne s'y trouvent
sous une forme exploitable.

### 7.2 Anthropic (API Claude) — analyse par modèle de langage

**Ce qui lui est transmis, vérifié dans le code :**

- la **graine** que vous avez saisie (par exemple « ésotérisme »), insérée dans le message
  envoyé au modèle ;
- pour la fiction : le sous-genre choisi, les contraintes de trio, et le contenu du champ
  de texte libre du compositeur ;
- les **titres et quatrièmes de couverture de livres publiés sur Amazon**, envoyés par
  lots pour être classés ;
- les niches et leurs métriques chiffrées, lorsque vous demandez un verdict éditorial, des
  mots-clés KDP ou un dossier de niche.

**Ce qui ne lui est jamais transmis : votre adresse e-mail, votre identifiant de compte,
votre adresse IP, ni aucune donnée de votre compte.** Les appels partent du serveur, pas
de votre navigateur : Anthropic ne voit donc pas non plus votre adresse IP à ce titre.

- Fournisseur : Anthropic PBC — [[A COMPLETER : entité contractante retenue (Anthropic PBC, États-Unis, ou Anthropic Ireland Limited pour l'UE) et référence de l'accord de sous-traitance signé]]
- [[A COMPLETER : confirmer, dans les conditions commerciales applicables à l'API, la durée de rétention des requêtes chez le fournisseur et l'absence d'utilisation à des fins d'entraînement — et citer ici la clause en question]]

### 7.3 DataForSEO — données de marché Amazon

**Ce qui lui est transmis :** des **requêtes de recherche** (mots-clés courts de type
« tarot de marseille », produits par le modèle à partir de votre graine) et des **codes
ASIN** de livres. Rien d'autre.

**Ce qui ne lui est jamais transmis : votre adresse e-mail, votre identifiant de compte ou
votre adresse IP.** Là encore, les appels partent du serveur.

- Fournisseur : DataForSEO — [[A COMPLETER : entité contractante, adresse, et référence de l'accord de sous-traitance signé]]

### 7.4 Google Fonts — polices de caractères

L'unique page de l'application importe deux familles de polices depuis
`fonts.googleapis.com`. **C'est votre navigateur qui effectue cet appel, pas le serveur :
votre adresse IP est donc transmise à Google**, ainsi que les informations habituellement
véhiculées par une requête HTTP (agent utilisateur, en-tête `Referer`).

C'est la seule requête que la page adresse à un tiers, et la seule circonstance où une
donnée vous concernant quitte l'installation sans transiter par le serveur.

- [[A COMPLETER : décider de la suite. Deux options : (a) héberger les fichiers de police localement, ce qui supprime purement et simplement cet appel et le problème juridique associé — la jurisprudence allemande (LG München I, 20/01/2022) a condamné l'appel dynamique à Google Fonts ; (b) le conserver et le mentionner ici. La rédaction ci-dessus est celle de l'option (b). Si l'option (a) est retenue, cette section doit être supprimée.]]

### 7.5 Amazon

L'application interroge l'autocomplétion publique d'Amazon.fr et, selon la configuration,
consulte directement des fiches produit. Ces appels partent du serveur et **ne
transportent aucune donnée vous concernant** : ni identifiant, ni cookie Amazon, ni votre
adresse IP. Ils ne transportent que le mot-clé recherché.

### 7.6 Aucun autre destinataire

Aucune donnée n'est vendue, louée, échangée ou transmise à des fins publicitaires ou
commerciales. Aucun prestataire d'analytique, de mesure d'audience ou de publicité n'est
intégré.

---

## 8. Le cache Amazon est mutualisé entre tous les comptes

C'est un choix d'architecture délibéré, et il mérite d'être dit plutôt que découvert.

`df-cache.db` est **commun à tous les comptes d'une même installation**. Si deux
utilisateurs analysent le même rayon Amazon, la donnée n'est demandée — et payée — qu'une
seule fois. C'est l'économie principale du produit à l'échelle.

Concrètement, cela signifie que la réponse d'Amazon obtenue à l'occasion de l'analyse d'un
utilisateur pourra servir à un autre. **Ce cache ne contient aucune donnée personnelle** :
uniquement des informations publiques publiées par Amazon (titres, prix, notes,
classements, textes de présentation), et les étiquettes qu'un modèle en a tirées.
**Aucune clé du cache ne porte d'identifiant de compte** : il est structurellement
impossible d'y retrouver qui a demandé quoi.

En revanche, la **graine** que vous avez saisie et le **résultat** de votre analyse
restent, eux, strictement rattachés à votre compte dans `jobs.db` et `history.db`, et ne
sont accessibles à aucun autre compte.

---

## 9. Sécurité

Les mesures suivantes sont implémentées et vérifiables dans le code :

- **Mots de passe** : dérivation `scrypt` (16 Mo de mémoire et environ 45 ms par
  vérification), sel aléatoire distinct par compte, comparaison à temps constant. Longueur
  minimale de 12 caractères, maximale de 128 — ce plafond est vérifié en premier, pour
  éviter qu'un mot de passe de plusieurs mégaoctets ne fasse tourner scrypt indéfiniment.
  Une liste de mots de passe notoirement faibles est refusée.
- **Aucune énumération des comptes possible** : une adresse inconnue et un mot de passe
  faux produisent le même message, et le même **temps de réponse** — une adresse inconnue
  déclenche quand même un calcul sur un leurre, sans quoi la rapidité de la réponse
  trahirait l'absence de compte.
- **Limitation des tentatives** : 8 échecs de connexion par adresse e-mail sur 15 minutes ;
  10 inscriptions par adresse IP sur la même fenêtre.
- **Sessions** : jeton aléatoire de 32 octets, dont seule l'empreinte SHA-256 est
  enregistrée. La déconnexion ferme la session **côté serveur** et retire le cookie —
  effacer le seul cookie laisserait le jeton valable pour quiconque en aurait gardé copie.
  Se déconnecter d'un appareil ne déconnecte pas les autres.
- **Cloisonnement des comptes** : l'identifiant de compte provient **exclusivement du
  cookie de session** ; aucun point d'entrée de l'application n'accepte un identifiant
  fourni par le client. Le travail d'analyse d'un autre compte est traité comme
  inexistant — et non comme refusé —, pour ne pas confirmer qu'un identifiant est valide.
- **Protection contre la falsification de requête (CSRF)** : les points d'entrée sensibles
  vérifient l'origine de la requête.
- **Messages d'erreur assainis** : aucune trace technique n'est renvoyée au navigateur,
  uniquement une référence d'incident.
- **Inscriptions fermées par défaut** : sur une installation neuve, seul le premier compte
  peut être créé sans réglage explicite.

**Limites à connaître :** les bases SQLite ne sont pas chiffrées au repos par
l'application. Aucune sauvegarde n'est prévue par le code lui-même.

[[A COMPLETER : décrire la politique de sauvegarde effectivement appliquée, sa fréquence, sa durée de rétention et le lieu de stockage des sauvegardes — une sauvegarde est un traitement à part entière, et sa durée de conservation doit être cohérente avec le § 5]]

[[A COMPLETER : décrire la procédure suivie en cas de violation de données, et le délai de notification à la CNIL — 72 heures au titre de l'article 33 du RGPD]]

---

## 10. Transferts hors de l'Union européenne

Deux sous-traitants au moins impliquent un transfert hors UE, et un troisième une
transmission depuis votre navigateur :

| Destinataire | Ce qui part | Nature du transfert |
|---|---|---|
| Anthropic | Graine saisie, textes de livres Amazon, métriques | [[A COMPLETER : préciser l'entité contractante et le pays de traitement, et le mécanisme de transfert invoqué — clauses contractuelles types de la Commission, ou Data Privacy Framework si l'entité y est certifiée]] |
| DataForSEO | Mots-clés et codes ASIN | [[A COMPLETER : idem — pays de traitement et mécanisme de transfert]] |
| Google (Fonts) | Votre adresse IP, depuis votre navigateur | [[A COMPLETER : idem, ou suppression de ce transfert par l'hébergement local des polices, cf. § 7.4]] |

Il faut souligner un point favorable : **aucune donnée d'identification vous concernant
(e-mail, identifiant de compte) ne part vers Anthropic ni vers DataForSEO.** Ce qui leur
est transmis, ce sont des mots-clés de recherche de livres et des données publiques
Amazon. Le seul destinataire qui reçoive une donnée personnelle au sens strict est Google,
et uniquement votre adresse IP, du fait de l'import de polices.

---

## 11. Vos droits — et les limites réelles de leur exercice

Vous disposez, au titre des articles 15 à 22 du RGPD, des droits d'accès, de
rectification, d'effacement, de limitation, de portabilité et d'opposition, ainsi que du
droit de définir des directives relatives au sort de vos données après votre décès.

**Il faut être franc sur la manière de les exercer : le produit n'offre aujourd'hui aucune
fonction en libre-service.**

### Message de fin d'analyse

Si l'exploitant a configuré un serveur d'envoi, votre adresse e-mail sert **en outre** à
vous prévenir qu'une analyse que vous avez lancée est terminée ou s'est interrompue. Ce
message est **transactionnel** : il fait suite à une action que vous avez déclenchée, et
il n'y a ni newsletter, ni relance commerciale, ni envoi que vous n'ayez pas provoqué.

Ce que ce message contient : le moteur concerné, l'issue (terminée ou interrompue), la
référence de l'analyse, et le cas échéant un lien vers l'application.

**Ce qu'il ne contient jamais** : le contenu de votre analyse. Ni les niches trouvées, ni
les scores, ni les titres relevés, ni le moindre montant. L'e-mail est un canal en clair,
relayé et archivé chez votre fournisseur de messagerie : les résultats de vos analyses ne
transitent pas par là. Le message d'erreur technique d'une analyse interrompue n'y est pas
davantage recopié.

**Cette fonction est éteinte par défaut.** Elle exige deux réglages simultanés du côté de
l'exploitant ; à défaut, aucun message n'est envoyé et votre adresse ne sert qu'à vous
identifier à la connexion.

[[A COMPLETER : indiquer si cette fonction est activée sur cette instance, et si oui, le
prestataire d'envoi utilisé (hébergeur du serveur SMTP) — il devient sous-traitant au sens
du RGPD et doit figurer au tableau des sous-traitants ci-dessus]]

---

Ce qui **n'existe pas** dans le code, et qu'il serait mensonger d'annoncer :

- **aucune suppression de compte en libre-service** — il n'existe aucun bouton, aucun
  écran et aucun point d'entrée permettant de supprimer un compte ;
- **aucune réinitialisation de mot de passe** — il n'existe ni envoi d'e-mail de
  récupération, ni question de sécurité. **Un mot de passe perdu est un compte perdu**,
  sauf intervention manuelle de l'éditeur sur la base ;
- **aucune vérification d'adresse e-mail** — l'adresse saisie n'est jamais confirmée ;
- **aucun changement d'adresse e-mail** depuis l'application ;
- **aucun export automatisé** de vos données — aucune fonction de téléchargement de
  l'historique, de la consommation ou des analyses passées n'est prévue ;
- **aucune interface d'administration** et aucun système de rôles.

**En pratique, tout exercice de droit passe donc par un message écrit à l'éditeur, qui y
répond par une intervention manuelle sur les bases de données.** C'est une limite réelle
du produit à son stade actuel, et non une clause de style.

**Pour exercer vos droits, écrivez à :**
[[A COMPLETER : adresse e-mail de contact — la même qu'au § 1]]

[[A COMPLETER : indiquer le justificatif d'identité demandé, le cas échéant, et le délai de réponse retenu — un mois au titre de l'article 12.3 du RGPD, prorogeable de deux mois pour les demandes complexes]]

[[A COMPLETER : décider si des fonctions de suppression de compte, de réinitialisation de mot de passe et d'export seront ajoutées, et sous quel délai. Tant qu'elles n'existent pas, cette section doit rester rédigée telle quelle.]]

**Réclamation.** Si vous estimez que vos droits ne sont pas respectés, vous pouvez saisir
la Commission nationale de l'informatique et des libertés (CNIL), 3 place de Fontenoy,
TSA 80715, 75334 Paris Cedex 07 — [www.cnil.fr](https://www.cnil.fr).

---

## 12. Mineurs

Le service s'adresse à des auteurs auto-édités et n'est pas destiné aux mineurs de moins
de 15 ans. Aucune vérification d'âge n'est effectuée par le code.

[[A COMPLETER : décider si une mention d'âge minimum doit figurer dans les conditions générales d'utilisation, et laquelle]]

---

## 13. Modifications de cette politique

Toute évolution du traitement des données — nouveau sous-traitant, nouvelle donnée
collectée, nouvelle durée de conservation, mise en place d'un paiement — donnera lieu à
une mise à jour de ce document et à une modification de la date figurant en tête.

[[A COMPLETER : préciser comment les utilisateurs seront informés d'une modification substantielle — bandeau dans l'application, e-mail, ou aucune notification]]

---

<!--
SOURCES VÉRIFIÉES — lecture du code effectuée avant rédaction.
Racine : C:/Users/pharma01/Desktop/O.S.C.A.R/OSCAR - Edition KDP - OBL/IA Niches

1. 01-scripts/auth.py
   - l.43-47   : longueur mot de passe 12 min / 128 max
   - l.48      : SESSION_TTL_S = 30 jours
   - l.53-59   : MAX_TENTATIVES=8, FENETRE_TENTATIVES_S=15 min, MAX_INSCRIPTIONS_PAR_CLIENT=10
   - l.66-72   : liste MOTS_DE_PASSE_INTERDITS
   - l.79      : SCRYPT_N, R, P, DKLEN = 2**14, 8, 1, 32
   - l.132-139 : normalisation e-mail (casse + espaces uniquement)
   - l.149-175 : schémas des tables comptes / sessions / tentatives, champ par champ
   - l.201-212 : sel aléatoire 16 octets par compte, colonne `params`
   - l.231-242 : purge OPPORTUNISTE des tentatives (uniquement lors d'une nouvelle tentative)
   - l.265-271 : dérivation sur un leurre pour un e-mail inconnu (temps de réponse constant)
   - l.278     : hmac.compare_digest
   - l.296-305 : creer_session — jeton token_urlsafe(32), seule l'empreinte est stockée
   - l.318-323 : fermer_session ne ferme que la session courante
   - l.325-328 : purger_sessions_expirees existe...
   - ...et grep exhaustif sur 01-scripts/ + web/ : AUCUN appelant. Les lignes de session
     expirées ne sont donc jamais supprimées.
   - l.331-335 : _empreinte_jeton = SHA-256 nu

2. 01-scripts/usage.py
   - l.17      : FENETRE_GLISSANTE_S = 30 jours — fenêtre de LECTURE (clause WHERE
                 horodatage>=cutoff dans resume/compter/reserver_analyse), aucun DELETE
   - l.36-44   : schéma table `usage` (user_id, type, cout_usd, n_analyses, horodatage)
   - grep "DELETE FROM" sur usage.py : aucune occurrence -> pas de purge

3. 01-scripts/history.py
   - l.60-67   : schéma table `passages` (user_id, type, cle, metriques, vu_le)
   - l.24-26   : METRIQUES_INVERSEES
   - l.75-84   : enregistrer() ne conserve QUE des valeurs numériques (filtre isinstance)
   - l.30      : SEUIL_SIGNIFICATIF
   - grep "DELETE FROM" sur history.py : aucune occurrence -> pas de purge

4. 01-scripts/cache.py
   - l.1       : cache "partagé (cross-user)"
   - l.13      : BOOK_TTL_S = 15 jours
   - l.18      : AUTOCOMPLETE_TTL_S = 15 jours
   - l.22      : CLASSIFICATION_TTL_S = 30 jours
   - l.107-112 : get() renvoie None si expires < now — la ligne N'EST PAS supprimée
   - l.120-186 : familles de clés bsr: / bsr-absent: / search: / book: / ac: / clf:
                 AUCUNE ne contient de user_id
   - schéma table kv : (key, value, expires)

5. 01-scripts/bsr_source.py
   - l.9       : BSR_TTL_S = 15 jours
   - l.14      : ECHEC_BSR_TTL_S = 3 jours

6. 01-scripts/scout_master.py l.27 et 01-scripts/lowcontent_master.py l.40
   - _SEARCH_TTL_S = 15 jours
   01-scripts/autocomplete_expand.py l.30 : AUTOCOMPLETE_TTL_S = 15 jours

7. 01-scripts/jobs.py
   - l.46-70   : schéma table `jobs` (id, user_id, type, params, statut, progression,
                 resultat, cout, erreur, cree_le, fini_le, maj_le)
   - l.19      : DEFAULT_MAX_PROGRESS = 200
   - l.97-108  : progression bornée aux 200 derniers messages
   - liste des méthodes (grep "def ") : create/start/append_progress/finish/fail/
     claim_next/derniere_activite/orphelins/get/list_jobs — AUCUNE méthode de suppression

8. web/server.py
   - l.63-68   : les cinq bases sont des fichiers locaux sous 99-logs/
   - l.147-148 : MAX_LONGUEUR_GRAINE = 80 (la graine part dans un prompt LLM)
   - l.163-199 : limiteur de débit ; TYPES_A_LA_PIECE = verdict / kdp / kdp_keywords / dossier
   - l.214-231 : _cookie_securise — Secure DÉDUIT de X-Forwarded-Proto puis du schéma,
                 forçable mais jamais désactivable
   - l.233-239 : _poser_session — cookie "ia_niches_session", httponly, samesite=lax,
                 max_age = SESSION_TTL_S, path=/
   - l.75      : COOKIE_SESSION = "ia_niches_session"
   - l.251-276 : origine_sure (anti-CSRF)
   - l.330-346 : _erreur_publique — le champ `erreur` ne porte qu'une référence d'incident,
                 motif explicite : l'URL DataForSEO porte les identifiants HTTP Basic
   - l.406-419 : utilisateur_courant — user_id EXCLUSIVEMENT issu du cookie
   - l.443-482 : inscription ; l.470-476 : la clé de limitation est f"ip:{_client_distant}"
                 -> c'est bien une ADRESSE IP écrite dans comptes.db/tentatives
   - l.390-391 : _client_distant = request.client.host
   - l.484-502 : connexion — message unique, 429 sur quota
   - l.504-512 : déconnexion — ferme la session côté serveur ET retire le cookie
   - l.531-547 : _consigner_scout — une niche non mesurée n'est PAS consignée
   - l.549-571 : _consigner_lowcontent, _consigner_fiction
   - l.733-734 : _JOB_RUNNERS = scout / fiction / lowcontent
   - l.757     : params = tout le body sauf "type" et "user_id" -> la graine y figure
   - l.788     : store.create(type_, params, user_id=user_id) -> params persistés en base
   - l.835-843 : job d'un autre compte -> 404, jamais 403
   - l.858-895 : flux SSE, job d'un autre compte traité comme inexistant
   - l.907-937 : /api/verdict ; l.953-970 : /api/kdp-keywords ; l.972-1027 : /api/dossier
                 (les trois envoient des données de niche au LLM, jamais l'e-mail)
   - l.1030-1046 : /api/pdf — stateless, aucune persistance
   - grep "basicConfig|FileHandler" sur 01-scripts/ + web/ : AUCUNE occurrence
     -> aucun fichier de log applicatif n'est écrit sur disque par le code

9. web/index.html
   - l.8       : @import url('https://fonts.googleapis.com/css2?family=Fira+Code...
                 &family=Fira+Sans...') — SEUL appel externe
   - grep -o "https\?://..." sur tout le fichier : une seule URL distincte, celle ci-dessus
   - grep "script src|<img|<iframe|gtag|analytics|googletagmanager" : AUCUNE occurrence
     -> aucun traceur, aucune analytique tierce, aucune image distante
   - l.1393, 1699, 1722 : clés localStorage 'ia-niches-job-lowcontent',
                 'ia-niches-job-scout', 'ia-niches-job-fiction'
   - l.1803    : clé localStorage 'ia-niches-aide-repliee'
   - l.1463, 1489 : écriture / lecture de l'identifiant de job en localStorage

10. 01-scripts/niche_ideator.py
   - l.95-113  : build_user_prompt — la graine saisie part textuellement dans le prompt
   - l.23-60   : SYSTEM_PROMPT — aucune donnée de compte

11. 01-scripts/fiction_classifier.py
   - l.112-124 : build_user_prompt — envoi de lots de blurbs Amazon indexés par ASIN
   - l.196-210 : appel client.messages.create

12. 01-scripts/search_providers.py
   - l.19-24   : endpoints DataForSEO /merchant/amazon/products et /merchant/amazon/asin
   - ce qui part : mot-clé et codes ASIN uniquement

13. 01-scripts/amazon_autocomplete.py
   - l.9-15    : completion.amazon.fr/api/2017/suggestions, marketplace A13V1IB3VIYZZH
   - ce qui part : le préfixe recherché uniquement

14. 01-scripts/util.py
   - l.6-31    : http_get — en-têtes navigateur, aucun identifiant utilisateur

15. Contenu réel de 99-logs/ (ls) : comptes.db, df-cache.db, history.db, jobs.db,
    usage.db (+ fichiers WAL/SHM SQLite). Aucun fichier de log texte.

NON VÉRIFIABLE DANS LE CODE, donc laissé en placeholder :
identité légale et coordonnées de l'éditeur, SIRET, hébergeur et localisation des serveurs,
entités contractantes et accords de sous-traitance Anthropic / DataForSEO, mécanismes de
transfert hors UE, politique de sauvegarde, procédure de violation de données, délai de
réponse aux demandes d'exercice de droits, durée de conservation après clôture de compte.
-->
