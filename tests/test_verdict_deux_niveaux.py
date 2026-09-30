"""Le verdict low-content passe de TROIS pastilles à DEUX — décision de Baptiste, 2026-09-30.

Ce que le moteur sait faire, mesuré sur 95 requêtes étiquetées et validé sur un lot neuf :
séparer un rayon MORT d'un rayon vivant (AUC 0,816 puis 0,908). Ce qu'il ne sait pas faire :
départager une bonne d'une mauvaise (0,635 puis 0,429, les deux intervalles enjambent le
hasard). Trois pastilles promettaient donc un classement qui n'existe pas, et « À analyser
en priorité » était la promesse la plus fausse du produit.

Les deux mesures qui fixent la frontière :
- AUCUNE « morte » n'a jamais atteint 5,0 — 0 sur 24, borne haute de Wilson 13,8 % ;
- le vert à 6,0 ne sortait que 3 niches sur 95, dont DEUX « mauvaises ». La distinction
  vert/jaune ne reposait sur rien.

Le rouge n'est pas « mort » et le libellé doit le dire : il enterre 7 bonnes sur 39 au lot 1
et 12 sur 32 au lot 2. « Pas rouge ⇒ pas mort » est soutenu par la mesure ; « rouge ⇒ mort »
ne l'est pas.
"""
import json
from pathlib import Path

from lowcontent_scoring import charger_criteres

_CRITERES = Path(__file__).resolve().parents[1] / "data" / "lowcontent_criteres.json"


def test_le_fichier_ne_porte_plus_qu_UN_seuil_de_verdict():
    c = charger_criteres()
    assert c["seuil_verdict_vivant"] == 5.0
    brut = json.loads(_CRITERES.read_text(encoding="utf-8"))
    assert "seuil_verdict_vert" not in brut and "seuil_verdict_jaune" not in brut, \
        "un seuil qui ne sert plus est un seuil qui ment sur ce qui est mesuré"


def test_deux_pastilles_seulement_et_aucune_ne_promet_un_classement():
    from tests.test_lowcontent_scoring import (_livres_indie, _niche, _serp, _validation)
    from lowcontent_scoring import score_lowcontent
    c = charger_criteres()
    base = score_lowcontent(_niche(), _validation(), _serp(), _livres_indie(), [3000],
                            criteres=c)
    vivant = score_lowcontent(_niche(), _validation(), _serp(), _livres_indie(), [3000],
                              criteres=dict(c, seuil_verdict_vivant=base.global_score))
    mort = score_lowcontent(_niche(), _validation(), _serp(), _livres_indie(), [3000],
                            criteres=dict(c, seuil_verdict_vivant=10.0))
    assert vivant.priorite.startswith("🟢") and mort.priorite.startswith("🔴")
    assert "priorité" not in vivant.priorite.lower(), "le moteur ne sait pas classer"
    assert "🟡" not in vivant.priorite + mort.priorite
    assert "vivant" in vivant.priorite.lower()
    # Le rouge ne dit pas « mort » : un rouge sur trois est une bonne niche (12/32 au lot 2).
    assert "vérifier" in mort.priorite.lower()


def test_la_porte_de_calibration_lit_le_meme_seuil():
    """« Aucune morte en vert » doit se vérifier sur la frontière qu'on affiche, sinon la
    porte garantit autre chose que ce que le client voit."""
    from lowcontent_validation import _est_vert
    from tests.test_lowcontent_scoring import (_livres_indie, _niche, _serp, _validation)
    from lowcontent_scoring import score_lowcontent
    c = charger_criteres()
    base = score_lowcontent(_niche(), _validation(), _serp(), _livres_indie(), [3000],
                            criteres=c)
    args = (_niche(), _validation(), _serp(), _livres_indie(), [3000])
    vivant_c = dict(c, seuil_verdict_vivant=base.global_score)
    mort_c = dict(c, seuil_verdict_vivant=base.global_score + 0.01)
    # `_est_vert` lit la PRIORITÉ quand elle est là (c'est ce qui rattrape le cas « ⚪ non
    # mesurée » à score élevé) : on rescore donc avec chaque seuil, comme le ferait un run.
    assert _est_vert(score_lowcontent(*args, criteres=vivant_c), vivant_c) is True
    assert _est_vert(score_lowcontent(*args, criteres=mort_c), mort_c) is False
