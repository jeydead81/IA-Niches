# Pages publiques — BROUILLONS, non servies

Quatre documents rédigés à partir de ce que le code fait **réellement**, pas de ce que le
produit voudrait dire de lui-même :

| Fichier | Rôle | Obligatoire ? |
|---|---|---|
| `mentions-legales.md` | Éditeur, directeur de publication, hébergeur, marques citées | Oui — art. 6-III LCEN, dès la mise en ligne |
| `politique-de-confidentialite.md` | Données traitées, durées, sous-traitants, droits RGPD | Oui — dès qu'un compte existe |
| `cgv.md` | Conditions de vente et d'utilisation, rétractation, résiliation | Oui — dès le premier encaissement |
| `landing-page.md` | Texte commercial, avec l'annexe des sources dans le code | Non |

## Statut

**Aucun endpoint ne les sert.** `web/server.py` ne les référence pas, et
`tests/test_pages_publiques.py` verrouille ce point : dès qu'une route sert un de ces
fichiers, il ne doit plus rester un seul `[[A COMPLETER : … ]]` dedans.

C'est la raison d'être du test. Des mentions légales publiées avec
« [[A COMPLETER : numéro SIREN … ]] » sont pires que pas de mentions légales : elles
affichent au visiteur que l'obligation a été vue et pas honorée, et elles ne remplissent
aucune des conditions de l'article 6-III.

## Ce que le code ne peut pas savoir

Tout ce qui est laissé en marqueur relève d'une décision de Baptiste ou d'un fait
extérieur au dépôt. Les trois plus structurants :

- **Identité légale de l'éditeur** — personne physique ou société. Les deux blocs sont
  rédigés dans `mentions-legales.md`, il faut en supprimer un.
- **Hébergeur** — le code ne contient aucune configuration de déploiement : le serveur
  démarre sur `127.0.0.1:8000`, les cinq bases sont des fichiers SQLite locaux dans
  `99-logs/`. Auto-hébergement et prestataire n'appellent pas la même mention, et le
  choix décide aussi de ce que dit la politique de confidentialité sur la localisation.
- **Prix, unité, essai** — non décidés. Les chiffres de cadrage évoqués en session de
  travail (§1 de `CLAUDE.md`) ne sont **pas** des décisions, et un test interdit qu'un
  montant par mois ou par an apparaisse dans le corps de la landing.

## Ce qui est déjà vrai et vérifié

Les affirmations produit de la landing sont sourcées ligne à ligne dans son annexe
« Sources dans le code ». Trois points s'y trouvent parce qu'ils sont réellement codés et
qu'ils sont ce qui distingue l'outil :

- le **gate gratuit avant toute dépense** (`niche_validator.validate_niches`,
  `lowcontent_master` phase 0) ;
- l'**absence de mesure jamais présentée comme un verdict** — prix inconnu, part indie
  « non mesuré », concurrence non mesurée (§5.10 de `CLAUDE.md`) ;
- **aucun système de paiement intégré**, dit explicitement plutôt que laissé à
  l'interprétation.

## Avant publication

1. Remplir tous les marqueurs — chacun porte sa consigne, un test le vérifie.
2. Trancher l'hébergement, puis relire la politique de confidentialité en entier :
   plusieurs paragraphes en dépendent.
3. Faire relire les CGV par un juriste. Elles sont construites sur le code, pas sur une
   pratique de marché, et ce n'est pas la même compétence.
4. Retirer l'annexe « Sources dans le code » de la landing : c'est un outil de
   vérification interne, pas du texte client.
