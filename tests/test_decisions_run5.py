"""Trois décisions de Baptiste après le run 5 de calibration (2026-09-18).

Le run 5 (51 requêtes étiquetées, 51/51 mesurées, Spearman +0,358) a montré trois défauts de
DÉFINITION du score low-content, que le seul fichier de critères ne pouvait pas corriger :

1. **Le bonus « place à prendre » (crit3, +1,5 en pénétration) pointait à l'envers.** Il se
   déclenche quand le PIRE BSR du top dépasse 50 000 — ce qui arrive surtout dans un rayon
   mort : 14 mortes sur 14, 20 mauvaises sur 25, 10 bonnes sur 12. Décision : il ne pèse
   plus sur le score. crit3 reste calculé pour le drapeau « critères BSR remplis ».
2. **Le malus « saisonnier » (−1 sur le global) était pris au LLM sans vérification**, et
   appliqué même quand l'utilisateur inclut les niches saisonnières : il frappait 2 bonnes
   sur 12. Décision : le risque reste affiché (drapeau), sans malus.
3. **Les seuils des pastilles 🟢 / 🟡 (7,5 / 6,0) étaient écrits dans le code** — et aucune
   « bonne » ne dépassait 6,31. Décision : ils vivent dans `data/lowcontent_criteres.json`,
   fixés à 6,0 / 5,0 — hypothèse lue sur le run 5, à vérifier sur un lot neuf.
4. **Le nombre d'affinages comptait deux fois dans la demande** : via `demand_score` et via
   un bonus « au moins 3 affinages ». Il ne compte plus qu'une fois.
5. **Deux compteurs au rapport**, hors porte : niches vertes, meilleur score d'une bonne.
"""
from lowcontent_scoring import charger_criteres, score_lowcontent
from lowcontent_validation import rapport_calibration
from models import (EnrichedBook, LowContentNiche, LowContentScored, NicheValidation,
                    SearchItem, SearchResult)


def _niche(**kw) -> LowContentNiche:
    base = dict(niche="carnet", requete_amazon="carnet de suivi", rationale="r",
                categorie="c", format_cle="journal_suivi", theme="t", public="adulte",
                source="autocomplete")
    base.update(kw)
    return LowContentNiche(**base)


def _v() -> NicheValidation:
    return NicheValidation(niche="carnet", requete_amazon="carnet de suivi", categorie="c",
                           demand_score=5, validated=True)


def _serp() -> SearchResult:
    return SearchResult(keyword="q", sponsored=[], organic=[
        SearchItem(title=f"Carnet {i}", asin=f"A{i}", price=11.99) for i in range(4)])


def _livres() -> list[EnrichedBook]:
    return [EnrichedBook(asin=f"A{i}", title="T", publisher="Independently published",
                         price=11.99, pages=120) for i in range(4)]


# ── 1. crit3 ne pèse plus sur le score ─────────────────────────────────────────

def test_le_bonus_place_a_prendre_ne_pese_plus_sur_le_score():
    """Même meilleur BSR (3 000), même moyenne sous 50 000 ; seul le pire BSR franchit
    50 000. Avant : +1,5 en pénétration pour le rayon au pire BSR le plus haut."""
    avec = score_lowcontent(_niche(), _v(), _serp(), _livres(), [3000, 60000])
    sans = score_lowcontent(_niche(), _v(), _serp(), _livres(), [3000, 40000])
    assert avec.penetration == sans.penetration
    assert avec.global_score == sans.global_score


def test_crit3_reste_dans_le_drapeau_criteres_bsr():
    """Le drapeau affiché (et lu par le brief du verdict) garde sa définition : seul le
    poids dans le score disparaît."""
    avec = score_lowcontent(_niche(), _v(), _serp(), _livres(), [3000, 60000])
    sans = score_lowcontent(_niche(), _v(), _serp(), _livres(), [3000, 40000])
    assert avec.criteres_bsr_ok is True and sans.criteres_bsr_ok is False


# ── 2. saisonnier : drapeau sans malus ─────────────────────────────────────────

def test_le_risque_saisonnier_est_un_drapeau_sans_malus():
    propre = score_lowcontent(_niche(), _v(), _serp(), _livres(), [3000])
    saison = score_lowcontent(_niche(risques=["saisonnier"]), _v(), _serp(), _livres(),
                              [3000])
    assert saison.global_score == propre.global_score
    assert "saisonnier" in saison.risques


def test_un_risque_de_marque_garde_son_malus():
    """Seul le saisonnier change : une marque (ip_marque) ou un risque TOS coûte toujours
    2 points, c'est un retrait de publication qui est en jeu."""
    propre = score_lowcontent(_niche(), _v(), _serp(), _livres(), [3000])
    marque = score_lowcontent(_niche(risques=["ip_marque"]), _v(), _serp(), _livres(),
                              [3000])
    assert marque.global_score == round(propre.global_score - 2, 2)


# ── 3. les seuils de verdict vivent dans le fichier de critères ────────────────

def test_les_seuils_de_verdict_sont_dans_le_fichier_de_criteres():
    """Valeurs choisies par Baptiste le 2026-09-18 : 6,0 / 5,0. À 7,5 / 6,0, le run 5 rejoué
    sortait 50 niches rouges sur 51. HYPOTHÈSE lue sur le run 5 (rouge = probablement mort,
    jaune = vivant, à examiner) : à vérifier sur un lot neuf, jamais réglée dessus."""
    c = charger_criteres()
    assert c["seuil_verdict_vert"] == 6.0 and c["seuil_verdict_jaune"] == 5.0


def test_le_verdict_suit_les_seuils_du_fichier():
    c = charger_criteres()
    base = score_lowcontent(_niche(), _v(), _serp(), _livres(), [3000], criteres=c)
    vert = dict(c, seuil_verdict_vert=base.global_score)
    jaune = dict(c, seuil_verdict_vert=10.0, seuil_verdict_jaune=base.global_score)
    assert score_lowcontent(_niche(), _v(), _serp(), _livres(), [3000],
                            criteres=vert).priorite.startswith("🟢")
    assert score_lowcontent(_niche(), _v(), _serp(), _livres(), [3000],
                            criteres=jaune).priorite.startswith("🟡")


def test_la_calibration_lit_le_seuil_vert_du_fichier():
    """Une constante recopiée dans lowcontent_validation (SEUIL_VERT) divergeait du scoring
    dès qu'on touchait le fichier (§5.32). Le repli sans priorité lit le même seuil."""
    n = _niche()
    s = LowContentScored(niche=n, global_score=7.0, priorite="", concurrence_mesuree=True)
    c = dict(charger_criteres(), seuil_verdict_vert=6.5)
    r = rapport_calibration([("morte", s)], criteres=c)
    assert r.morts_en_vert
    r2 = rapport_calibration([("morte", s)], criteres=dict(c, seuil_verdict_vert=7.5))
    assert not r2.morts_en_vert


# ── 4. le nombre d'affinages ne compte qu'une fois dans la demande ─────────────

def test_le_nombre_d_affinages_ne_compte_qu_une_fois_dans_la_demande():
    """En mode classement, `demand_score = max(1, n_enfants)` (lowcontent_master) : le
    même compte d'affinages portait AUSSI un bonus +1 dès 3 affinages. Deux fois la même
    mesure — relevé par l'analyse du run 5, corrigé sur décision de Baptiste. À demande
    égale, le nombre d'affinages ne doit plus rien ajouter."""
    peu = score_lowcontent(_niche(n_enfants_autocomplete=0), _v(), _serp(), _livres(), [3000])
    beaucoup = score_lowcontent(_niche(n_enfants_autocomplete=5), _v(), _serp(), _livres(),
                                [3000])
    assert beaucoup.demande == peu.demande


# ── 5. deux compteurs au rapport de calibration ────────────────────────────────

def _scored(score: float, priorite: str) -> LowContentScored:
    return LowContentScored(niche=_niche(n_enfants_autocomplete=2), global_score=score,
                            priorite=priorite, concurrence_mesuree=True)


def test_le_rapport_compte_les_verts_et_le_meilleur_score_d_une_bonne():
    """« 0 morte en vert » se lisait comme une preuve de sûreté alors qu'une seule niche
    sur 51 était verte au run 5. Deux compteurs, SANS effet sur la porte, le rendent
    visible : combien de niches sont vertes, et jusqu'où monte la meilleure « bonne »."""
    paires = [("bonne", _scored(5.8, "🟡 Intéressant")), ("bonne", _scored(4.9, "🔴 Faible")),
              ("mauvaise", _scored(7.0, "🟢 À analyser en priorité")),
              ("morte", _scored(3.0, "🔴 Faible"))]
    r = rapport_calibration(paires)
    assert r.n_verts == 1
    assert r.meilleur_score_bonne == 5.8


def test_sans_bonne_calibree_le_meilleur_score_est_absent_pas_zero():
    r = rapport_calibration([("morte", _scored(3.0, "🔴 Faible"))])
    assert r.meilleur_score_bonne is None


def test_la_cli_affiche_les_deux_compteurs(capsys):
    import build_lowcontent_validation_set as cli
    from lowcontent_validation import RapportCalibration
    cli._imprimer(RapportCalibration(n_requetes=51, n_calibrees=51, spearman=0.46,
                                     n_verts=0, meilleur_score_bonne=5.79))
    out = capsys.readouterr().out
    assert "niches en 🟢" in out and "meilleure « bonne »" in out and "5.79" in out
