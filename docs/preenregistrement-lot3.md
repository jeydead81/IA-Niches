# Pré-enregistrement du lot 3 — low-content

**Figé le 2026-09-30, AVANT toute dépense**, sur le commit qui porte ce fichier.
Jeu : `99-logs/validation-lc-lot3.xlsx`, 40 requêtes de **profondeur 1** (traîne), tirées au
hasard dans l'autocomplete, étiquetées à l'aveugle par Baptiste avant toute analyse.

Pourquoi ce document existe : sur 82 signaux criblés aux lots 1 et 2, les 5 meilleurs du lot 1
donnaient 0,48 à 0,62 en validation — exactement ce que produit le hasard. Avec assez d'essais
on trouve toujours quelque chose. **Une hypothèse qui n'est pas écrite ici avant le run ne
comptera pas comme validée**, quel que soit son chiffre.

## Ce qui est gelé

| | valeur au gel |
|---|---|
| `demande_plafond` | 5 |
| `seuil_verdict_vivant` | 5,0 |
| `cibles_max` / `variantes_max` | 1000 / 1000 (neutralisés) |
| Clé du gate | nombre de mots, puis `n_enfants`, puis profondeur, puis `demand_score`, puis empreinte |
| Pastilles | deux : 🟢 rayon vivant / 🔴 signaux de rayon mort |

`tests/test_preenregistrement_lot3.py` vérifie que ces valeurs n'ont pas bougé : les toucher
avant le run invaliderait la validation, et rien ne le dirait autrement.

## Les hypothèses, et ce qui les réfute

Toutes se mesurent sur le **lot 3 seul**. Un intervalle qui contient le hasard vaut
**non concluant**, jamais « tendance encourageante ».

| # | Hypothèse | Confirmée si | Réfutée si |
|---|---|---|---|
| **H1** | Le score détecte un rayon mort | AUC vivante > morte ≥ 0,75, borne basse au-dessus de 0,50 | AUC < 0,70, ou intervalle contenant 0,50 |
| **H2** | Le seuil 5,0 ne laisse pas passer de morte | aucune « morte » au-dessus de 5,0 | au moins une |
| **H3** | Le nouveau gate paie de meilleures niches | bonnes dans le top 6 simulé > tirage au sort, écart apparié positif | écart ≤ 0 |
| **H4** | Le nombre de mots sépare bonne de mauvaise | AUC ≥ 0,65, borne basse au-dessus de 0,50 | intervalle contenant 0,50 |
| **H5** | Le filtre papetiers écarte des mauvaises sans coût | ≥ 1 mauvaise écartée **et** 0 bonne perdue | une seule bonne perdue suffit à le rejeter |
| **H6** | `part_bsr_50k` sépare bonne de mauvaise | AUC ≥ 0,65, borne basse au-dessus de 0,50 | intervalle contenant 0,50 |
| **H7** | La traîne vaut mieux que la tête de rayon | part de « bonne » du lot 3 > 29,5 % (28 bonnes sur 95 aux lots 1 et 2) | part ≤ 29,5 % |

**H4 porte une réserve à dire maintenant** : le lot 3 est entièrement de la traîne, donc ses
requêtes sont plus longues et moins dispersées en longueur que celles des lots précédents. Si
l'AUC tombe, ce sera peut-être faute de variance, pas faute de signal — et ce sera dit comme ça.

**H7 n'est pas une comparaison propre** : les trois lots ont été étiquetés à des dates
différentes, et l'étiquette de Baptiste peut avoir dérivé. C'est la seule mesure disponible de
la thèse fondatrice du moteur, elle vaut mieux que rien, elle ne vaut pas une expérience
contrôlée.

## Ce que ce run ne pourra pas dire

- **Rien sur la profondeur À L'INTÉRIEUR du lot** : la CLI de calibration injecte les requêtes
  du classeur telles quelles et pose `profondeur = 0`. La comparaison tête/traîne est donc
  ENTRE lots (H7), jamais dans celui-ci.
- **Rien sur le nombre de résultats Amazon** (« moins de 10 000 ») : la donnée n'est pas
  collectée et aucune source achetée ne la fournit.
- **Rien de nouveau sur bonne/mauvaise au-delà de H4, H5 et H6.** Tout autre signal qui
  ressortirait sera déclaré **post-hoc** et ira au pré-enregistrement du lot suivant, comme
  `part_bsr_50k` y est arrivé.

## Protocole

1. Baptiste étiquette les 40 requêtes. Une case vide bloque le lancement.
2. Run unique, `--plafond 1.30`, `--out 99-logs/rapport-calibration-lc-lot3.json`.
   Devis : **0,84 $ DataForSEO** + ~0,16 $ Anthropic (calculé, cache vide).
3. Le rapport et le classeur sont versionnés AVANT toute retouche des critères.
4. Les hypothèses sont évaluées dans l'ordre ci-dessus, chacune avec son intervalle et son `n`.
