# Conditions générales de vente et d'utilisation

**Service : IA-Niches**

Version en vigueur au [[A COMPLETER : date d'entrée en vigueur de la présente version]].

---

## 1. Objet et acceptation

Les présentes conditions générales de vente et d'utilisation (ci-après « CGV ») régissent
l'accès au service IA-Niches et son utilisation, ainsi que la vente de l'abonnement qui y
donne accès.

Elles sont conclues entre :

- **L'éditeur** : [[A COMPLETER : dénomination sociale ou nom et prénom de l'entrepreneur individuel]],
  [[A COMPLETER : forme juridique de l'éditeur — entrepreneur individuel, micro-entrepreneur, SASU, SARL, EURL, autre]], [[A COMPLETER : adresse du siège ou du domicile professionnel]],
  immatriculé sous le numéro [[A COMPLETER : numéro SIREN (9 chiffres) ou SIRET (14 chiffres) de l'éditeur, identique à celui des mentions légales]],
  [[A COMPLETER : numéro de TVA intracommunautaire, ou mention « non assujetti à la TVA — article 293 B du CGI » selon le régime retenu]],
  contact : [[A COMPLETER : adresse e-mail de contact du service]] ;
- **L'utilisateur** : toute personne physique ou morale qui crée un compte sur le service.

La création d'un compte vaut acceptation pleine et entière des présentes CGV. L'utilisateur
qui n'accepte pas ces conditions doit renoncer à créer un compte.

Une version des présentes CGV est accessible à l'adresse
[[A COMPLETER : URL de la page CGV, ou mention du mode de mise à disposition si le service reste auto-hébergé]].

---

## 2. Description du service

IA-Niches est un outil d'aide à la décision destiné aux auteurs auto-édités publiant sur
Amazon. Il assiste la recherche de niches éditoriales en croisant des données publiques
d'Amazon.fr et une analyse produite par un modèle de langage.

### 2.1 Fonctionnalités

Le service comporte **trois moteurs d'analyse** distincts :

| Moteur | Objet |
|---|---|
| Non-fiction (`scout`) | Idées de niches non-fiction, validation de la demande, mesure de la concurrence, notation |
| Fiction (`fiction`) | Composition et évaluation de trios (tropes / décor), lecture des quatrièmes de couverture du rayon |
| Low-content (`lowcontent`) | Niches de carnets, cahiers et journaux, avec filtrage des marques et franchises |

Chaque analyse est lancée sous forme de **travail asynchrone** : l'utilisateur reçoit
immédiatement un identifiant, puis suit la progression du traitement. Fermer l'onglet
n'interrompt pas l'analyse en cours.

Le service produit également, à la demande et à partir d'une analyse déjà réalisée : une
analyse éditoriale d'une niche, une proposition de sept mots-clés au format KDP, un dossier
de niche au format PDF, et un suivi de l'évolution d'une niche entre deux passages.

### 2.2 Sources de données

Le service interroge :

- l'**autocomplétion publique d'Amazon.fr**, pour mesurer la demande et confirmer les
  mots-clés ;
- l'**API DataForSEO**, pour les résultats de recherche Amazon, les classements de vente
  (BSR) et les métadonnées des livres ;
- l'**API d'Anthropic**, pour la génération d'idées, la classification des quatrièmes de
  couverture, l'analyse éditoriale et les propositions de mots-clés.

Pour limiter le coût et la charge sur ces fournisseurs, les réponses sont conservées dans
un cache technique pour une durée limitée : quinze jours pour les fiches de livres, les
classements de vente, les résultats de recherche et les suggestions d'autocomplétion ;
trente jours pour les classifications de quatrièmes de couverture ; trois jours pour la
mémorisation d'un classement introuvable. **Ce cache est mutualisé entre tous les comptes**
et ne contient aucune donnée personnelle : uniquement des réponses des fournisseurs
relatives à des produits Amazon publics (voir article 10.4).

### 2.3 Ce que le service n'est pas

Le service ne publie pas de livre, ne rédige pas de manuscrit, ne se connecte à aucun
compte Amazon ou KDP de l'utilisateur, et n'accède à aucune donnée de vente privée de
l'utilisateur.

---

## 3. Compte et accès

### 3.1 Création du compte

L'accès au service suppose la création d'un compte au moyen d'une **adresse e-mail** et
d'un **mot de passe**. Le mot de passe doit comporter **au moins 12 caractères et au plus
128 caractères** ; les mots de passe figurant en tête des dictionnaires d'attaque sont
refusés. Le mot de passe n'est jamais conservé en clair : seule une empreinte dérivée par
la fonction `scrypt`, avec un sel propre à chaque compte, est stockée.

L'ouverture des inscriptions est un **réglage de l'instance**. Sur une instance dont les
inscriptions ne sont pas ouvertes, seule la création du tout premier compte est possible.

### 3.2 Session

L'authentification repose sur un cookie de session d'une durée de **30 jours**, marqué
`HttpOnly` (inaccessible aux scripts) et `SameSite=Lax`, et transmis en `Secure` dès lors
que le service est servi en HTTPS. La déconnexion ferme la session **côté serveur** et
supprime le cookie ; elle ne ferme que la session utilisée, et non les autres appareils
connectés.

Pour prévenir les attaques par essais successifs, le nombre de tentatives de connexion
échouées est limité à **8 par adresse e-mail sur une fenêtre glissante de 15 minutes**. Le
dépassement de ce seuil bloque temporairement les tentatives sur cette adresse ; il ne
signifie pas que le mot de passe est erroné.

### 3.3 Fonctions d'administration de compte absentes

L'utilisateur est informé, **sans réserve ni euphémisme**, que les fonctions suivantes
**n'existent pas** dans le service à la date des présentes :

- réinitialisation d'un mot de passe oublié ;
- vérification de l'adresse e-mail ;
- changement d'adresse e-mail ;
- suppression du compte depuis l'interface ;
- gestion de rôles ou espace d'administration.

**Un mot de passe perdu est un compte perdu.** Toute demande de suppression de compte ou de
données doit être adressée à [[A COMPLETER : adresse e-mail de contact]] et sera traitée
manuellement par l'éditeur (voir article 10.6).

### 3.4 Confidentialité des identifiants

L'utilisateur est seul responsable de la confidentialité de ses identifiants et de toute
activité réalisée depuis son compte. Le compte est **personnel** : sa mise à disposition de
tiers, sa revente ou son partage sont interdits.

---

## 4. Obligations de l'utilisateur

L'utilisateur s'engage à :

1. fournir une adresse e-mail valide et à jour ;
2. utiliser le service conformément aux présentes CGV et à la réglementation applicable ;
3. ne pas tenter de contourner les limites techniques du service, notamment le plafond
   d'analyses, le limiteur de débit, les bornes de volume par analyse et le mécanisme de
   devis préalable ;
4. ne pas automatiser d'appels au service en dehors de l'usage prévu, ni en faire un usage
   de nature à en dégrader la disponibilité pour les autres utilisateurs ;
5. ne pas tenter d'accéder aux données d'un autre compte ;
6. ne pas revendre, redistribuer ni republier en l'état les résultats produits par le
   service sous forme de service concurrent.

L'utilisateur reste **seul responsable des décisions éditoriales et commerciales** qu'il
prend au vu des résultats produits.

### 4.1 Respect des règles Amazon KDP — responsabilité de l'auteur

Le respect des règles de la plateforme Amazon KDP — exactitude des métadonnées, règles
applicables au contenu limité, respect des droits de propriété intellectuelle et des
marques de tiers — **incombe exclusivement à l'auteur**.

Le moteur low-content applique un filtre de marques, franchises et personnages, alimenté
par une liste versionnée dans le service. Ce filtre est explicitement conçu et documenté
comme **une première ligne, jamais une garantie juridique** : la couverture de la liste
n'est pas exhaustive et ne peut pas l'être. Le fait qu'une niche passe ce filtre ne
constitue en aucun cas une validation juridique, ni un avis sur la disponibilité d'un
terme, ni une garantie contre un retrait de publication ou une fermeture de compte KDP.

L'éditeur ne saurait être tenu responsable d'un retrait de publication, d'un blocage ou
d'une fermeture de compte prononcés par Amazon à l'encontre de l'utilisateur.

---

## 5. Tarif, facturation et paiement

### 5.1 État actuel

**Aucun mécanisme de paiement n'est intégré au service à la date des présentes.** Le
service comptabilise l'usage et le coût technique par utilisateur à des fins de contrôle
interne, mais aucun montant n'est présenté à l'utilisateur et aucun encaissement n'est
opéré.

Le présent article n'entrera en application qu'à la mise en service effective de
l'abonnement.

### 5.2 Prix

Le prix de l'abonnement est de [[A COMPLETER : montant TTC du service en euros, et le taux de TVA appliqué ou la mention de franchise en base — non décidé à ce jour]] par mois,
[[A COMPLETER : mention « TVA non applicable, article 293 B du CGI » ou taux de TVA applicable]].

Le prix applicable est celui affiché au jour de la souscription.

### 5.3 Périmètre d'usage inclus

L'abonnement donne droit à [[A COMPLETER : nombre d'analyses incluses par période, et définition retenue d'une « analyse »]].

Le service applique techniquement, lorsqu'il est configuré, un **plafond d'analyses par
utilisateur sur une fenêtre glissante de 30 jours** — et non sur un mois calendaire ni sur
un cumul à vie. Lorsqu'aucun plafond n'est configuré sur l'instance, l'usage n'est pas
bridé mais reste comptabilisé.

Indépendamment de ce plafond, le service applique :

- un **limiteur de débit** sur les analyses complémentaires demandées à la pièce (analyse
  éditoriale d'une niche, mots-clés KDP, dossier de niche), plafonnées par défaut à
  40 appels par heure et par compte. Un refus à ce titre est un refus de **rythme** : rien
  n'est dépensé et il suffit d'attendre ;
- des **bornes de volume** par analyse, refusées explicitement plutôt que rognées en
  silence ;
- un **devis préalable** : le coût maximal d'une analyse est estimé **avant** tout appel
  payant, et l'analyse est refusée en amont si elle dépasse le plafond de coût configuré,
  en indiquant le volume qui tiendrait. Ce mécanisme existe pour ne jamais rendre un
  rapport tronqué à un utilisateur qui a payé son plafond entier.

### 5.4 Modalités de paiement

Le paiement s'effectue par [[A COMPLETER : moyen(s) de paiement acceptés]] via
[[A COMPLETER : prestataire de paiement retenu — aucun n'est intégré à ce jour]].

L'abonnement est prélevé [[A COMPLETER : périodicité et date de prélèvement retenues]].
Une facture est mise à disposition [[A COMPLETER : modalité de mise à disposition des factures]].

### 5.5 Défaut de paiement

En cas d'échec de paiement, l'éditeur pourra suspendre l'accès au service après
[[A COMPLETER : délai et modalités de relance retenus]]. La suspension n'emporte pas
suppression des données de l'utilisateur pendant la durée prévue à l'article 10.5.

### 5.6 Révision des prix

L'éditeur peut modifier ses tarifs. Toute modification est notifiée à l'utilisateur au
moins [[A COMPLETER : délai de préavis retenu, 30 jours minimum recommandé]] avant son
entrée en vigueur, et ne s'applique qu'aux périodes d'abonnement postérieures. L'utilisateur
qui refuse le nouveau tarif peut résilier dans les conditions de l'article 6.

---

## 6. Durée et résiliation

### 6.1 Durée

L'abonnement est conclu pour une durée d'un mois, **renouvelable par tacite reconduction**
par périodes successives d'un mois, jusqu'à résiliation par l'une des parties.

### 6.2 Résiliation par l'utilisateur

L'utilisateur peut résilier à tout moment, sans motif et sans frais, par
[[A COMPLETER : modalité de résiliation retenue — à ce jour aucune fonction de résiliation n'existe dans l'interface]].

La résiliation prend effet **au terme de la période en cours** déjà payée. Aucun
remboursement au prorata n'est dû pour la période entamée, sauf disposition légale
contraire.

### 6.3 Résiliation par l'éditeur

L'éditeur peut résilier ou suspendre l'accès :

- en cas de manquement de l'utilisateur aux présentes CGV, après mise en demeure restée
  sans effet pendant [[A COMPLETER : délai retenu, en jours calendaires, et son point de départ]], sauf manquement grave justifiant une
  suspension immédiate ;
- en cas d'arrêt du service, moyennant un préavis de
  [[A COMPLETER : délai de préavis retenu en cas d'arrêt du service]] et le remboursement
  au prorata des périodes payées non consommées.

### 6.4 Effets de la résiliation

La résiliation met fin à l'accès au service. Les données de l'utilisateur sont conservées
puis effacées dans les conditions de l'article 10.5.

---

## 7. Droit de rétractation

### 7.1 Principe

Conformément aux articles L221-18 et suivants du Code de la consommation, le consommateur
dispose d'un délai de **quatorze jours** à compter de la conclusion du contrat pour exercer
son droit de rétractation, sans avoir à motiver sa décision.

Ce droit ne bénéficie qu'aux consommateurs au sens du Code de la consommation, et le cas
échéant aux professionnels remplissant les conditions de l'article L221-3 du même code. Il
n'est pas ouvert aux autres professionnels.

### 7.2 Renonciation pour un service numérique exécuté immédiatement

Le service est un **contenu numérique fourni sur un support immatériel** et un **service
exécuté immédiatement** dès la souscription.

En application de l'**article L221-28 du Code de la consommation**, l'utilisateur qui
demande l'exécution du service avant la fin du délai de quatorze jours :

1. **demande expressément** l'exécution immédiate du service, et
2. **reconnaît expressément** qu'il perdra son droit de rétractation une fois le contrat
   pleinement exécuté, ou, s'agissant d'un contenu numérique, dès le commencement de
   l'exécution avec son accord préalable exprès et son renoncement exprès à ce droit.

Cette demande et cette renonciation sont recueillies au moment de la souscription par
[[A COMPLETER : modalité de recueil retenue — case à cocher distincte non pré-cochée recommandée ; aucune n'existe à ce jour dans l'interface]].

**En l'absence de cette demande expresse et de cette renonciation expresse, le droit de
rétractation demeure et s'exerce dans les conditions de l'article 7.3.**

### 7.3 Exercice du droit de rétractation

L'utilisateur exerce son droit de rétractation en adressant une déclaration dénuée
d'ambiguïté à [[A COMPLETER : adresse e-mail ou postale de rétractation]]. Il peut utiliser
le formulaire type de rétractation figurant en annexe des présentes.

Le remboursement intervient dans un délai de quatorze jours à compter de la réception de la
demande, par le même moyen de paiement que celui utilisé pour la transaction initiale.

Lorsque l'exécution a commencé à la demande de l'utilisateur avant la fin du délai,
l'éditeur peut retenir un montant proportionné au service déjà fourni, conformément à
l'article L221-25 du Code de la consommation.

### Annexe — Formulaire type de rétractation

> À l'attention de [[A COMPLETER : dénomination, adresse postale, adresse e-mail de l'éditeur]] :
>
> Je vous notifie par la présente ma rétractation du contrat portant sur la prestation de
> services ci-dessous :
>
> - Commandé le / reçu le : ……………
> - Nom du consommateur : ……………
> - Adresse du consommateur : ……………
> - Signature (uniquement en cas de notification sur papier) : ……………
> - Date : ……………

---

## 8. Nature des résultats — estimations, aucune garantie de résultat

**Cet article est central et prime sur toute présentation commerciale du service.**

### 8.1 Le service produit des estimations, pas des certitudes

Les scores, verdicts, classements, fourchettes de prix et recommandations produits par le
service sont des **estimations**, calculées à partir de données publiques d'Amazon.fr
observées **à un instant donné**, et d'analyses produites par un modèle de langage.

Ces estimations reposent sur des échantillons volontairement limités. À titre d'exemple, la
moyenne des classements de vente d'une niche non-fiction porte sur les trois premiers
résultats organiques, et non sur le rayon entier. Un marché Amazon évolue en permanence :
un résultat exact au moment de la mesure peut être obsolète peu après.

### 8.2 Aucune garantie de résultat commercial

**L'éditeur ne garantit aucun résultat commercial.** Le service ne garantit ni ventes, ni
classement, ni visibilité, ni rentabilité, ni acceptation d'un ouvrage par Amazon. Une
niche présentée comme prometteuse peut ne produire aucune vente ; une niche notée
faiblement peut réussir.

Le service est un outil d'aide à la décision. La décision, elle, appartient à l'auteur.

### 8.3 Une absence de mesure n'est pas un verdict de marché

Le service est conçu pour **distinguer explicitement ce qu'il a mesuré de ce qu'il n'a pas
pu mesurer**, et l'utilisateur s'engage à lire les résultats dans ce sens.

Concrètement, et tel qu'implémenté :

- une niche dont la mesure de concurrence a échoué est signalée comme
  **« concurrence non mesurée »** et ne reçoit alors ni bonus ni malus de pénétration ;
- une niche fiction dont aucun livre n'a pu être analysé est déclarée **« non mesurable »**,
  ce qui est différent de « niche morte » ;
- un rayon dont une partie des livres n'a pas pu être enrichie l'indique explicitement : un
  rayon amputé n'est pas un rayon désert ;
- une sonde de demande indisponible est signalée comme telle, et jamais rendue comme un
  « personne ne cherche ça » ;
- une niche vue une seule fois ne produit aucune évolution : un point unique n'est pas une
  tendance ;
- une composition de trio fiction qui ne donne aucun résultat sous contraintes signale une
  **impossibilité de composition**, et non un verdict sur le marché — aucune mesure n'a
  alors été effectuée.

**Interpréter l'une de ces mentions comme un verdict de marché relève de la seule
responsabilité de l'utilisateur.**

### 8.4 Résultats partiels

Une analyse dont une source a échoué n'est pas interrompue : elle est rendue avec la mention
explicite des sources tombées et des éléments manquants. Un tel résultat partiel constitue
une exécution du service.

---

## 9. Disponibilité, dépendance à des fournisseurs tiers et responsabilité

### 9.1 Disponibilité

L'éditeur met en œuvre les moyens raisonnables pour assurer l'accessibilité du service. Il
ne souscrit **aucun engagement de niveau de service** (taux de disponibilité garanti, délai
de rétablissement) sauf stipulation contraire expresse
[[A COMPLETER : engagement de disponibilité éventuellement retenu — aucun n'existe à ce jour]].

L'accès peut être interrompu pour maintenance, mise à jour ou raison de sécurité.

### 9.2 Dépendance à des fournisseurs tiers

**Le service dépend de fournisseurs tiers sur lesquels l'éditeur n'a aucun contrôle** :

- **Amazon**, dont les pages, l'autocomplétion et les conditions d'utilisation peuvent
  changer sans préavis, et dont l'accès peut être restreint selon l'origine des requêtes ;
- **DataForSEO**, fournisseur des données de recherche et de classement, dont
  l'indisponibilité, les délais de file d'attente ou l'évolution tarifaire affectent
  directement les analyses ;
- **Anthropic**, fournisseur des modèles de langage, dont l'indisponibilité, les quotas ou
  l'évolution tarifaire affectent directement les analyses.

L'indisponibilité, la dégradation, la modification technique ou la modification des
conditions commerciales de l'un de ces fournisseurs peut **dégrader, ralentir, restreindre
ou interrompre** tout ou partie du service. L'éditeur ne saurait en être tenu responsable.

Si une telle évolution rendait le service durablement inexploitable, l'éditeur en informera
les utilisateurs et pourra mettre fin au service dans les conditions de l'article 6.3.

### 9.3 Limitation de responsabilité

L'éditeur est tenu d'une **obligation de moyens** au titre de l'exécution du service.

Dans les limites permises par la loi, l'éditeur n'est pas responsable des dommages indirects
ou immatériels, notamment : perte de chiffre d'affaires, perte de bénéfice, perte de chance,
manque à gagner, préjudice commercial ou d'image, coûts de publication engagés à tort,
sanction ou fermeture de compte prononcée par une plateforme tierce.

Sauf faute lourde ou dolosive, et dans les limites permises par la loi, la responsabilité
totale de l'éditeur au titre du contrat est plafonnée au montant effectivement payé par
l'utilisateur au cours des [[A COMPLETER : durée retenue pour le plafond de responsabilité, par exemple les douze mois précédant le fait générateur]].

Aucune stipulation des présentes ne saurait exclure ou limiter la responsabilité de
l'éditeur dans les cas où la loi l'interdit, notamment en cas de dommage corporel, de faute
lourde ou dolosive, ou au titre des garanties légales dues au consommateur (conformité et
vices cachés, articles L217-1 et suivants du Code de la consommation et 1641 et suivants du
Code civil).

---

## 10. Données

### 10.1 Ce que le service stocke

Le service enregistre des données dans **cinq bases de données locales** à l'instance :

| Base | Contenu |
|---|---|
| `comptes.db` | Adresse e-mail, empreinte du mot de passe et sel, paramètres de dérivation, date de création, sessions (empreinte du jeton uniquement), horodatage des tentatives de connexion échouées |
| `history.db` | Niches analysées par l'utilisateur, sous forme normalisée, et leurs métriques numériques, avec la date de passage |
| `usage.db` | Nombre d'analyses et coût technique par utilisateur, par type d'appel, avec horodatage |
| `jobs.db` | Travaux lancés : type, paramètres saisis, progression, résultat, coût, erreur éventuelle, dates |
| `df-cache.db` | Cache des réponses des fournisseurs (données produits Amazon publiques), **mutualisé entre tous les comptes** |

Le service **ne stocke jamais** : le mot de passe en clair, ni le jeton de session en clair
(seule son empreinte SHA-256 est conservée). Lire la base ne permet donc pas de voler une
session.

### 10.2 Cookies et stockage local

Le seul cookie déposé est le **cookie de session** (`ia_niches_session`), strictement
nécessaire au fonctionnement du service, d'une durée de 30 jours.

**Aucun traceur, aucun cookie publicitaire, aucun outil d'analyse d'audience tiers n'est
présent dans le service.**

L'interface utilise en outre le **stockage local du navigateur** (`localStorage`) pour deux
usages purement fonctionnels : mémoriser l'identifiant de l'analyse en cours afin de la
reprendre après un rechargement, et mémoriser l'état ouvert ou fermé d'un panneau d'aide.
Ces données restent dans le navigateur de l'utilisateur.

L'interface charge une **police de caractères depuis Google Fonts**
(`fonts.googleapis.com`). Ce chargement expose l'adresse IP de l'utilisateur à ce
fournisseur. Hors ligne, l'interface fonctionne et retombe sur les polices du système.
[[A COMPLETER : décision retenue — héberger la police localement pour supprimer cette dépendance, ou la documenter dans la politique de confidentialité]]

### 10.3 Ce qui est transmis aux sous-traitants

- **Anthropic** reçoit le texte des requêtes d'analyse, ce qui inclut la **graine saisie par
  l'utilisateur** (thème ou piste de recherche), les contraintes de composition qu'il choisit,
  et des extraits de données produits publiques d'Amazon. Il **ne reçoit ni l'adresse e-mail
  ni l'identifiant de compte** de l'utilisateur.
- **DataForSEO** reçoit les **mots-clés et identifiants de produits (ASIN)** interrogés. Il
  **ne reçoit aucune donnée d'identification** de l'utilisateur.

L'utilisateur est invité à ne saisir aucune donnée personnelle ou confidentielle dans les
champs libres de l'interface : leur contenu est transmis au fournisseur de modèle de langage.

### 10.4 Cache mutualisé

Le cache des réponses des fournisseurs est **partagé entre tous les comptes**, par
conception : deux utilisateurs qui analysent le même rayon ne le font interroger qu'une
fois. Ce cache ne contient **aucun identifiant d'utilisateur** ni aucune donnée personnelle :
il ne porte que des réponses relatives à des produits Amazon publics. Il n'est donc pas
possible, à partir de ce cache, de savoir quel compte a demandé quelle analyse.

### 10.5 Conservation

Les données de compte, d'historique, d'usage et de travaux sont conservées pendant toute la
durée du contrat, puis [[A COMPLETER : durée de conservation après résiliation retenue]].

Les sessions expirent automatiquement après 30 jours. Les horodatages de tentatives de
connexion échouées sont purgés après 15 minutes. Les entrées de cache expirent
automatiquement dans les délais indiqués à l'article 2.2.

**Aucune purge automatique des historiques, usages et travaux n'est implémentée à ce jour :**
leur effacement est une opération manuelle de l'éditeur.

### 10.6 Droits de l'utilisateur

L'utilisateur dispose des droits d'accès, de rectification, d'effacement, de limitation,
d'opposition et de portabilité prévus par le RGPD. Ces droits s'exercent auprès de
[[A COMPLETER : adresse e-mail de contact pour l'exercice des droits]].

Aucune fonction de l'interface ne permettant à ce jour de supprimer un compte ou de modifier
une adresse e-mail, ces demandes sont traitées **manuellement** par l'éditeur dans un délai
de [[A COMPLETER : délai de traitement retenu, un mois maximum au titre du RGPD]].

Le détail des traitements figure dans la politique de confidentialité, accessible à
[[A COMPLETER : URL de la politique de confidentialité]].

### 10.7 Sécurité

L'éditeur met en œuvre les mesures suivantes, implémentées dans le service : dérivation du
mot de passe par `scrypt` avec sel par compte, stockage du seul condensat du jeton de
session, cookie `HttpOnly` et `SameSite=Lax`, transmission en `Secure` sur HTTPS, contrôle
de l'origine des requêtes sensibles, limitation des tentatives de connexion, cloisonnement
strict des données par compte, et refus de tout identifiant d'utilisateur fourni par le
client.

Ces mesures ne constituent pas une garantie d'inviolabilité. L'utilisateur est informé que
le service est conçu pour un fonctionnement **local ou auto-hébergé** ; le niveau de
sécurité effectif dépend également des conditions de déploiement retenues
[[A COMPLETER : préciser le mode d'hébergement retenu et l'hébergeur, s'il devient hébergé par l'éditeur]].

---

## 11. Propriété intellectuelle

### 11.1 Propriété du service

Le service, son code, son interface, sa documentation, ses taxonomies et ses listes
d'exclusion demeurent la propriété exclusive de l'éditeur. Le contrat confère à
l'utilisateur un **droit d'usage personnel, non exclusif et non cessible**, pour la durée de
l'abonnement.

Sont notamment interdits : la copie, la décompilation, la rétro-ingénierie, la
redistribution, la mise à disposition de tiers du service ou de tout ou partie de son code,
sauf autorisation écrite préalable de l'éditeur.
[[A COMPLETER : vérifier la cohérence avec le fichier LICENSE présent dans le dépôt]]

### 11.2 Résultats produits

Les rapports, dossiers PDF, mots-clés et analyses générés à la demande de l'utilisateur lui
sont destinés et peuvent être utilisés librement pour son activité d'édition, y compris à
des fins commerciales.

L'utilisateur ne peut en revanche revendre, redistribuer ou republier ces résultats en tant
que tels sous forme de service concurrent.

### 11.3 Droits des tiers

Les données de produits, titres, classements et métadonnées restituées proviennent de
sources publiques et demeurent la propriété de leurs titulaires respectifs. Le service n'est
affilié à Amazon d'aucune manière, ni approuvé ou sponsorisé par Amazon. Les marques citées
appartiennent à leurs propriétaires.

---

## 12. Modification des CGV

L'éditeur peut modifier les présentes CGV, notamment pour tenir compte d'une évolution
légale, technique ou de l'offre.

Toute modification substantielle est notifiée à l'utilisateur par
[[A COMPLETER : canal de notification retenu]] au moins
[[A COMPLETER : délai de préavis retenu, 30 jours recommandé]] avant son entrée en vigueur.

L'utilisateur qui n'accepte pas les nouvelles conditions peut résilier son abonnement avant
leur entrée en vigueur, dans les conditions de l'article 6.2. La poursuite de l'utilisation
du service après l'entrée en vigueur vaut acceptation.

---

## 13. Litiges et médiation

### 13.1 Réclamation préalable

En cas de difficulté, l'utilisateur est invité à contacter l'éditeur à
[[A COMPLETER : adresse e-mail de réclamation]]. L'éditeur s'engage à répondre dans un délai
de [[A COMPLETER : délai de réponse retenu]].

### 13.2 Médiation de la consommation

Conformément aux articles L612-1 et suivants du Code de la consommation, le consommateur
peut recourir gratuitement à un médiateur de la consommation en vue de la résolution
amiable du litige l'opposant à l'éditeur, après avoir tenté une réclamation écrite directe.

Médiateur désigné : [[A COMPLETER : nom du médiateur de la consommation, adresse postale et site web — l'adhésion à un dispositif de médiation est une OBLIGATION LÉGALE pour tout professionnel vendant à des consommateurs en France]].

Le consommateur peut également recourir à la plateforme européenne de règlement en ligne des
litiges [[A COMPLETER : vérifier la disponibilité de la plateforme RLL de la Commission européenne à la date de publication]].

### 13.3 Droit applicable et juridiction compétente

Les présentes CGV sont soumises au **droit français**.

À défaut de résolution amiable, le litige sera porté devant les juridictions compétentes.
Pour le consommateur, les règles de compétence des articles R631-3 du Code de la
consommation et 46 du Code de procédure civile s'appliquent : il peut saisir, à son choix,
la juridiction du lieu de son domicile ou celle du lieu d'exécution de la prestation.

Pour l'utilisateur professionnel, compétence est attribuée aux tribunaux du ressort de
[[A COMPLETER : ressort retenu pour les litiges avec les professionnels]].

---

## 14. Dispositions diverses

**Nullité partielle.** Si une stipulation des présentes est déclarée nulle ou inapplicable,
les autres stipulations conservent leur plein effet.

**Non-renonciation.** Le fait pour l'éditeur de ne pas se prévaloir d'un manquement ne vaut
pas renonciation à s'en prévaloir ultérieurement.

**Cession.** L'utilisateur ne peut céder le contrat sans accord écrit de l'éditeur.
L'éditeur peut céder le contrat en cas de transmission de son activité, sous réserve
d'information préalable de l'utilisateur.

**Preuve.** Les enregistrements conservés dans les systèmes de l'éditeur constituent une
preuve des opérations réalisées, sauf preuve contraire apportée par l'utilisateur.

**Force majeure.** Aucune des parties n'est responsable d'un manquement dû à un cas de force
majeure au sens de l'article 1218 du Code civil.

<!--
SOURCES VÉRIFIÉES — chaque affirmation factuelle du document a été lue dans le code, à la
racine C:/Users/pharma01/Desktop/O.S.C.A.R/OSCAR - Edition KDP - OBL/IA Niches.

TROIS MOTEURS D'ANALYSE (art. 2.1)
- web/server.py:733-734 — _JOB_RUNNERS = {"scout", "fiction", "lowcontent"}
- web/server.py:35-37 — imports run_scout, run_fiction_scout, run_lowcontent_scout
- web/server.py:737-830 — POST /api/jobs, seul chemin de lancement, 202 + id immédiat,
  thread détaché (« fermer l'onglet ne l'arrête pas »)

FONCTIONS COMPLÉMENTAIRES (art. 2.1)
- web/server.py:907 POST /api/verdict ; :953 POST /api/kdp-keywords ;
  :972 POST /api/dossier ; :1030 POST /api/pdf ; :939 GET /api/history

SOURCES DE DONNÉES ET CACHE (art. 2.2)
- 01-scripts/cache.py:1-3 — cache clé/valeur SQLite « partagé (cross-user) », TTL
- 01-scripts/cache.py:13 BOOK_TTL_S = 15 j ; :18 AUTOCOMPLETE_TTL_S = 15 j ;
  :22 CLASSIFICATION_TTL_S = 30 j
- 01-scripts/bsr_source.py:9 BSR_TTL_S = 15 j ; :14 ECHEC_BSR_TTL_S = 3 j
- 01-scripts/scout_master.py:27 et 01-scripts/lowcontent_master.py:40 — _SEARCH_TTL_S = 15 j
- 01-scripts/devis.py:1-30 — postes DataForSEO (SERP + ASIN) et Anthropic (ideator, classif)

COMPTES ET MOT DE PASSE (art. 3.1)
- 01-scripts/auth.py:43-47 — LONGUEUR_MIN 12 / LONGUEUR_MAX 128
- 01-scripts/auth.py:66-72 — MOTS_DE_PASSE_INTERDITS
- 01-scripts/auth.py:79 — SCRYPT_N/R/P/DKLEN
- 01-scripts/auth.py:186-190 — sel = secrets.token_bytes(16), sel PAR COMPTE
- 01-scripts/auth.py:24-27 (docstring) — « ce qu'on ne stocke JAMAIS »
- web/server.py:379-387 + :443-452 — _inscriptions_ouvertes(), premier compte toujours admis

SESSION ET COOKIE (art. 3.2, 10.2)
- 01-scripts/auth.py:48 — SESSION_TTL_S = 30 jours
- web/server.py:112 — COOKIE_SESSION = "ia_niches_session"
- web/server.py:233-239 — httponly=True, samesite="lax", secure=_cookie_securise
- web/server.py:214-231 — Secure déduit de X-Forwarded-Proto puis du schéma
- 01-scripts/auth.py:300-311 — creer_session rend le jeton en clair, ne stocke que
  _empreinte_jeton ; :331-335 — SHA-256
- web/server.py:504-512 — déconnexion : fermeture serveur ET delete_cookie
- 01-scripts/auth.py:53-56 — MAX_TENTATIVES = 8, FENETRE_TENTATIVES_S = 15 min
- web/server.py:484-502 — 429 sur TropDeTentatives, message unique en 401

FONCTIONS ABSENTES (art. 3.3)
- Recensement exhaustif des décorateurs @app dans web/server.py : aucune route de
  réinitialisation de mot de passe, de vérification d'e-mail, de changement d'adresse,
  de suppression de compte, ni d'administration.

GARDE-FOUS DE DÉPENSE (art. 4.3, 5.3)
- 01-scripts/usage.py:15 — FENETRE_GLISSANTE_S = 30 j (glissante, ni calendaire ni à vie)
- 01-scripts/usage.py:118-158 — reserver_analyse, BEGIN IMMEDIATE, PlafondAtteint
- web/server.py:201-211 — _plafond_analyses_mensuel(), None = illimité mais journalisé
- web/server.py:167-169 — TYPES_A_LA_PIECE, DEBIT_FENETRE_S = 3600,
  DEBIT_APPELS_MAX_DEFAUT = 2 * MAX_RECHERCHES (soit 40)
- web/server.py:181-197 — _reserver_appel, 429 « c'est le rythme », « Rien n'a ete depense »
- web/server.py:241-249 — _borner : refuse (400) plutôt que de rogner en silence
- 01-scripts/devis.py:1-35 + web/server.py:763-768 — devis AVANT dépense, PLAFOND_DEPASSE
  porte le volume qui tiendrait

FILTRE DE MARQUES — PREMIÈRE LIGNE (art. 4.1)
- data/exclusions_ip.md:8-10 — « Ce fichier est le SEUL garde-fou juridique du dépôt […]
  c'est un retrait de publication, et répété, une fermeture de compte »
- data/exclusions_ip.md, section « Ajouts du 2026-08-19 » — « La couverture n'est PAS
  exhaustive et ne peut pas l'être : le filtre est une première ligne, jamais une
  garantie juridique »
- 01-scripts/ip_filter.py:1-19 — docstring, enjeu juridique, rejet avec motif
- Portée du filtre : 01-scripts/lowcontent_ideator.py:25,165,259 et
  01-scripts/lowcontent_master.py:32,105 — appelé UNIQUEMENT par le moteur low-content

NATURE DES RÉSULTATS — ESTIMATIONS (art. 8)
- 01-scripts/scoring.py:15-17 — bsr_top5_avg porte sur AU PLUS 3 BSR (n_bsr_per_niche = 3)
- 01-scripts/scoring.py:107-119 — garde concurrence_mesuree, défaut pessimiste False,
  aucun bonus ni malus si la SERP a échoué ; :128-130 — verdict « Concurrence non mesurée »
- 01-scripts/fiction_scoring.py:160-164 — verdict « non_mesurable » quand aucun livre
  n'est scorable
- 01-scripts/fiction_scoring.py:206-208 + 01-scripts/fiction_master.py:159-162 —
  n_echecs annoncé (rayon amputé ≠ rayon désert)
- 01-scripts/history.py:12-14 (docstring) et :113-118 — delta() rend None sur un seul
  passage : « un point unique n'est JAMAIS une tendance »
- 01-scripts/history.py:30 — SEUIL_SIGNIFICATIF = 0.10
- 01-scripts/fiction_ideator.py:131-137 + fiction_master.py:81-85 —
  contraintes_impossibles = impossibilité de COMPOSITION, pas verdict de marché
- 01-scripts/fiction_master.py:96-100 et 01-scripts/scout_master.py:89-91 — un échec
  n'interrompt pas le run, il est signalé et compté (art. 8.4)

DÉPENDANCE AUX TIERS (art. 9.2)
- 01-scripts/bsr_source.py:27 + CLAUDE.md §3 — BSR_SOURCE=scrape suppose une IP
  résidentielle, bloqué depuis un datacenter
- 01-scripts/search_providers.py:145-150 — budget de poll porté à 40 (~320 s) après un
  incident de lenteur de la file DataForSEO qui avait effacé un run entier
- 01-scripts/fiction_master.py:10-13 — la file ASIN met ~250 s quel que soit le lot

CINQ BASES ET LEUR CONTENU (art. 10.1)
- web/server.py:64-67 — _JOBS_DB, _USAGE_DB, _HISTORY_DB, _USERS_DB (99-logs/)
- 01-scripts/cache.py:88-97 — table kv de df-cache.db
- 01-scripts/auth.py:150-180 — tables comptes / sessions / tentatives
- 01-scripts/history.py:56-62 — table passages (user_id, type, cle, metriques, vu_le)
- 01-scripts/usage.py:38-48 — table usage (user_id, type, cout_usd, n_analyses, horodatage)
- 01-scripts/jobs.py:49-65 — table jobs (params, progression, resultat, cout, erreur, dates)

COOKIES, STOCKAGE LOCAL, RESSOURCE EXTERNE (art. 10.2)
- web/index.html:8 — @import url('https://fonts.googleapis.com/css2?family=Fira+Code…')
  SEULE ressource externe du fichier (grep https?:// , <script src, <link)
- web/index.html:1463,1479,1489,1492,1496 — localStorage : identifiant du job en cours
- web/index.html:1799-1807 — localStorage : état du panneau d'aide
- Aucun traceur : aucune occurrence d'analytics, gtag, matomo, plausible, pixel dans
  web/index.html

TRANSMISSION AUX SOUS-TRAITANTS (art. 10.3)
- 01-scripts/niche_ideator.py:95-99 — build_user_prompt injecte la graine saisie
  (« Graine fournie : « {seed} » ») ; :122-130 — client.messages.create
- 01-scripts/search_providers.py — DataForSEO reçoit mots-clés et ASIN
- Aucun appel ne transmet l'e-mail ni le user_id à un tiers (grep sur email/user_id dans
  niche_ideator.py, fiction_ideator.py, search_providers.py : aucune occurrence)

CACHE MUTUALISÉ SANS DONNÉE PERSONNELLE (art. 10.4)
- 01-scripts/cache.py:110-133 — clés de cache : bsr:, search:, book:, ac:, clf: — aucune
  ne porte de user_id
- 01-scripts/auth.py:26-30 (docstring) — « user_id cloisonne history.py, usage.py et
  jobs.py — JAMAIS cache.py »

CONSERVATION ET PURGES (art. 10.5)
- 01-scripts/auth.py:325-328 — purger_sessions_expirees ; :235-238 — purge opportuniste
  des tentatives au-delà de FENETRE_TENTATIVES_S
- 01-scripts/cache.py:99-104 — expiration par TTL à la lecture
- Aucune purge automatique dans history.py, usage.py, jobs.py (grep DELETE FROM sur ces
  trois fichiers : aucun résultat)

SÉCURITÉ (art. 10.7)
- web/server.py:406-419 — utilisateur_courant : user_id issu EXCLUSIVEMENT du cookie
- web/server.py:751-754 — une clé "user_id" envoyée par le client est ignorée
- web/server.py:251-276 — origine_sure (anti-CSRF, Sec-Fetch-Site puis Origin vs Host)
- web/server.py:835-844 — 404 et non 403 sur le job d'un autre compte
- web/server.py:1052-1058 — HOST/PORT, défaut 127.0.0.1:8000 (fonctionnement local)

PAIEMENT (art. 5.1)
- Aucun prestataire d'encaissement dans le code : grep stripe|paddle|lemonsqueezy|paypal
  |checkout sur 01-scripts/ et web/ — aucun résultat. usage.db mesure le coût technique
  (usage.py:1-9) mais aucun montant n'est présenté à l'utilisateur.
-->
