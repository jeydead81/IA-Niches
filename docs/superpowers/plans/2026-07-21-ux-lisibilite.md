# Revue UX — lisibilité pour un utilisateur non technique

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Charge aussi la skill `ui-ux-pro-max` (l'UI existante a été construite avec).

**Goal:** Qu'un auteur de 60 ans, non technique, comprenne ce qu'il voit **sans qu'on lui explique**.

---

## Le diagnostic, chiffré

Relevé sur `web/index.html` : **10 termes techniques** (BSR ×5, ASIN ×10, trio ×13, trope ×4, saturation ×4, rayon ×7, autocomplete ×11…) et **zéro** infobulle, aide ou glossaire.

Les libellés sont déjà en français (« Profondeur », « Ouverture », « Saturation du trio ») — le problème n'est pas la langue, c'est que **rien n'ancre les chiffres**. Face à « Profondeur 0,96 », l'utilisateur ne sait ni sur quelle échelle, ni si c'est bien, ni quoi en faire.

**Principe directeur : ne pas simplifier les données, expliquer les données.** Retirer le BSR appauvrirait l'outil ; il faut dire ce qu'est un BSR. La rigueur reste, la barrière tombe.

**Contrainte : ne rien casser.** Le design existant (bleu/ambre, Fira, dense) est cohérent — on l'étend, on ne le remplace pas. Les 260 tests doivent rester verts.

---

## Task U1 : glossaire au survol sur chaque terme technique

**Files:** Modify `web/index.html` · Test `tests/test_ux_glossaire.py`

Un petit `?` cliquable/survolable à côté de chaque terme, avec une explication en français courant. **Le texte est la partie importante de cette tâche** — le voici, à reprendre mot pour mot :

| Terme | Explication à afficher |
|---|---|
| **BSR** | Classement des ventes Amazon. Plus le nombre est **petit**, plus le livre se vend. Sous 10 000 : très bon. Au-delà de 100 000 : faible. |
| **Rayon** | L'endroit d'Amazon où le livre est classé : la boutique Kindle ou les livres papier. Les classements des deux ne se comparent pas. |
| **Trio** | La recette d'un roman : un sous-genre + un ou deux thèmes + un décor. Exemple : cosy mystery + enquêtrice amatrice + village breton. |
| **Trope** | Un ressort d'intrigue que le lecteur attend et recherche. Exemple : « ennemis devenus amants », « mariage arrangé ». |
| **Profondeur** | Est-ce que les livres de ce rayon **se vendent** ? Proche de 1 : oui, franchement. Proche de 0 : non. |
| **Ouverture** | Reste-t-il de la **place** ? Proche de 1 : oui. Proche de 0 : les places sont tenues par des livres bien installés. |
| **Saturation du trio** | Part des livres qui promettent **déjà la même chose que vous**. 0,7 = 7 livres sur 10 : mieux vaut changer d'angle. |
| **Part séries** | Proportion de livres qui font partie d'une série. Élevée = un tome unique sera désavantagé. |
| **Sonde autocomplete** | Est-ce que les lecteurs tapent vraiment ces mots dans la recherche Amazon ? |
| **Sponso écartés** | Livres sponsorisés (publicité) retirés du calcul : ils fausseraient la mesure de la concurrence. |

- [ ] **Step 1 : Test (échoue)** — `tests/test_ux_glossaire.py`, sur le HTML servi :
```python
def test_chaque_terme_technique_a_son_explication():
    """Sans ancrage, « Profondeur 0,96 » ne veut rien dire pour un non-initié."""
    html = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text("utf-8")
    for terme in ("BSR", "Saturation du trio", "Profondeur", "Ouverture", "Part séries"):
        assert terme in html
    for extrait in ("Plus le nombre est", "promettent", "se vendent", "reste-t-il"):
        assert extrait.lower() in html.lower(), f"explication manquante : {extrait}"
```

- [ ] **Step 2-3 : Implémenter** — infobulles accessibles : lisibles au survol **et** au clic (un utilisateur sur tablette ne survole pas), contraste suffisant, jamais coupées par le bord de l'écran.
- [ ] **Step 4-5 : Commit** `feat(ux): glossaire au survol sur chaque terme technique`

---

## Task U2 : les chiffres disent s'ils sont bons

**Files:** Modify `web/index.html` · Test `tests/test_ux_glossaire.py`

Aujourd'hui : `Profondeur 0.96`. Demain : **`Profondeur : forte (0,96)`**, avec la couleur qui va avec.

- [ ] Seuils d'habillage (alignés sur `SEUILS` de `fiction_scoring.py`) : profondeur/ouverture ≥ 0,6 « forte » (vert) · 0,3-0,6 « moyenne » (ambre) · < 0,3 « faible » (rouge). Saturation **inversée** — c'est le seul score où **haut = mauvais** : ≥ 0,6 « déjà très couvert » (rouge) · < 0,3 « peu couvert » (vert).
- [ ] **Virgule décimale française** partout (0,96 et non 0.96).
- [ ] Les coûts en clair : `0,15 $` plutôt que `0.1532`, avec l'équivalent en euros.
- [ ] Test : le HTML contient les mots d'habillage (« forte », « déjà très couvert »…).
- [ ] **Commit** `feat(ux): les scores annoncent leur niveau, pas seulement leur valeur`

---

## Task U3 : chaque fiche dit quoi faire

**Files:** Modify `web/index.html` · Test `tests/test_ux_glossaire.py`

La matrice sort une valeur technique (`porteur_encombre`). L'utilisateur doit lire une **conclusion**, mot pour mot :

| Valeur | Titre affiché | Ce qu'on lui dit |
|---|---|---|
| `pepite` | 🟢 **Pépite** | Ça se vend, il reste de la place, et personne ne raconte encore tout à fait ça. À creuser en priorité. |
| `porteur_encombre` | 🟠 **Porteur mais encombré** | Ça se vend et il reste de la place, mais beaucoup de livres promettent déjà la même chose. Gardez le sous-genre, changez de thème ou de décor. |
| `mur_installe` | 🔴 **Mur installé** | Ça se vend, mais les places sont tenues par des livres bien installés. Difficile d'entrer sans un angle très différent. |
| `desert` | 🟠 **Désert** | Il reste de la place, mais rien ne prouve que ces livres se vendent. Risqué. |
| `mort` | 🔴 **Sans intérêt** | Peu de ventes et peu de place. Passez à autre chose. |
| `non_mesurable` | ⚪ **Non mesuré** | Impossible de conclure : le rayon était vide ou tous les livres ont été écartés. Reformulez la requête ou changez de rayon. **Ce n'est pas un mauvais résultat, c'est une absence de résultat.** |

- [ ] Test : les 6 libellés et leurs conseils sont présents dans le HTML.
- [ ] **Commit** `feat(ux): chaque fiche annonce une conclusion actionnable, pas un code technique`

---

## Task U4 : « Comment lire ces résultats » + attentes de durée

**Files:** Modify `web/index.html` · Test `tests/test_ux_glossaire.py`

- [ ] Un panneau **repliable** en tête, ouvert la première fois : à quoi sert l'outil, ce qu'est un bon résultat, et l'ordre de lecture des colonnes.
- [ ] **Annoncer la durée réelle** : « Une analyse fiction prend 10 à 15 minutes. Vous pouvez fermer cette page, le travail continue et vous le retrouverez ici. » — mesuré à 869 s, et c'est désormais vrai grâce aux travaux asynchrones. Un utilisateur qui ignore ça croit à un plantage.
- [ ] Afficher la **consommation du mois** (via `GET /api/usage`) : un plafond qui bloque sans qu'on ait pu voir où on en était se vit comme une panne.
- [ ] **Commit** `feat(ux): panneau d'aide, durée annoncée et consommation visible`

---

## Self-Review
- On explique les données, on ne les appauvrit pas : le BSR reste, sa signification apparaît. ✓
- Le seul score où « haut = mauvais » (saturation) est signalé comme tel — sinon contresens garanti. ✓
- « Non mesuré » est présenté comme une absence de résultat, jamais comme un mauvais résultat. ✓
- La durée réelle est annoncée : sans ça, 15 minutes d'attente passent pour une panne. ✓
- Design existant étendu, pas remplacé ; 260 tests verts. ✓
