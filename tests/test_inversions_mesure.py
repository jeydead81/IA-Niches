"""Inversions de mesure — la faute cardinale du produit, et un arbitrage conservé.

CLAUDE.md règle 3 : « ne jamais présenter une absence de mesure comme un verdict de
marché ». Les deux cas ci-dessous la violaient d'une façon particulièrement sournoise :
l'absence de mesure y produisait la MEILLEURE note possible, pas la pire. Un rayon dont
rien n'avait été mesuré ressortait en tête.

1. UNE SERP QUI RÉPOND SANS AUCUN ORGANIQUE — signalée par l'audit, puis NON corrigée.
   Le dépôt avait déjà tranché : une SERP qui répond EST une mesure, et « il ne faut pas
   punir la mesure sous prétexte de corriger l'absence de mesure ». J'avais écrit la
   correction avant de trouver ce test ; je l'ai retirée. Un audit qui ignore une
   décision documentée ne la périme pas.

2. `n_enfants=0` CONFOND « sondé, rien trouvé » et « jamais sondé ». Une requête au fond
   de l'arbre n'est jamais sondée : son compteur reste à zéro, comme une feuille qu'on a
   vraiment interrogée. Or ce compteur DÉCIDE de ce qu'on paie — c'est le premier critère
   de tri de la shortlist. Une requête très affinée mais non sondée perd sa place au
   profit d'une feuille stérile.
"""
import pytest

from autocomplete_expand import expand
from models import NicheValidation, SearchResult
from scoring import score_niche


def _validation(demand=6):
    return NicheValidation(niche="tarot", requete_amazon="tarot debutant",
                           categorie="eso", demand_score=demand, validated=True)


# ── 1. La SERP vide : un arbitrage DÉJÀ pris, et qui tient ────────────────────
#
# L'audit signalait qu'une SERP répondant sans aucun organique déclenche le bonus
# « moins de 10 concurrents ». C'est exact. Mais le dépôt avait DÉJÀ tranché ce point,
# dans un test explicite et argumenté (`test_un_rayon_mesure_et_reellement_vide_reste_une
# _bonne_nouvelle`, tests/test_scoring.py) : « une SERP qui répond et ne montre aucun
# concurrent ciblé est une VRAIE place à prendre ; il ne faut pas punir la mesure sous
# prétexte de corriger l'absence de mesure ».
#
# L'argument tient : une SERP qui RÉPOND est une mesure. La corriger reviendrait à
# traiter une mesure défavorable au concurrent comme une non-mesure — l'erreur
# symétrique de celle qu'on combat.
#
# La correction a donc été RETIRÉE après l'avoir écrite. Ce qui reste ici, ce sont les
# deux garde-fous à ne pas défaire, et la trace de l'arbitrage pour qu'il ne soit pas
# re-tranché à l'aveugle au prochain audit.

def test_une_panne_de_SERP_reste_une_absence_de_mesure():
    """Le garde de 60e405a, celui qui compte : `search is None` = la SERP n'a pas
    répondu. Là, le zéro n'est pas une mesure."""
    s = score_niche(_validation(), None, [3000])
    assert s.concurrence_mesuree is False
    assert "non mesur" in s.priorite.lower()


def test_une_SERP_qui_REPOND_vide_reste_une_mesure_ASSUMEE():
    """ARBITRAGE DU DÉPÔT, conservé. Zéro organique sur une SERP qui a répondu est traité
    comme une place à prendre, pas comme une absence de mesure.

    Le risque connu et accepté : une anomalie de parsing produirait le même signal qu'un
    rayon réellement vide, et ce signal est le plus FLATTEUR possible. Si un jour une
    telle anomalie est observée en live, c'est ce test-là qu'il faudra retourner — pas le
    découvrir par surprise."""
    vide = SearchResult(keyword="q", sponsored=[], organic=[])
    assert score_niche(_validation(), vide, [3000]).concurrence_mesuree is True


def test_la_panne_note_moins_bien_que_le_rayon_vide_mesure():
    """La hiérarchie qui compte : ne pas savoir doit noter MOINS BIEN que savoir que
    c'est dégagé. C'est ce que le garde de 60e405a garantit."""
    vide = SearchResult(keyword="q", sponsored=[], organic=[])
    assert (score_niche(_validation(), None, [3000]).penetration
            < score_niche(_validation(), vide, [3000]).penetration)


# ── 2. « jamais sondé » n'est pas « sondé, rien trouvé » ───────────────────────

def _fetch(arbre):
    def f(prefixe):
        return list(arbre.get(prefixe, []))
    return f


def test_une_feuille_sondee_rend_zero_enfant_MESURE():
    """Sondée, sans complétion : c'est un zéro qui vaut mesure."""
    out = expand("carnet", fetch=_fetch({"carnet": ["carnet glycemie"],
                                         "carnet glycemie": []}),
                 depth=2, alphabet=False, pause=0)
    feuille = next(s for s in out if s.requete == "carnet glycemie")
    assert feuille.n_enfants == 0


def test_une_requete_JAMAIS_sondee_rend_None_et_non_zero():
    """Au fond de l'arbre, la requête n'est jamais interrogée. Rendre 0 la ferait passer
    pour une feuille stérile alors qu'on n'en sait rien — et ce compteur DÉCIDE de ce
    qu'on paie : c'est le premier critère de tri de la shortlist."""
    out = expand("carnet", fetch=_fetch({"carnet": ["carnet glycemie"],
                                         "carnet glycemie": ["carnet glycemie 120 pages"]}),
                 depth=1, alphabet=False, pause=0)
    jamais = next(s for s in out if s.requete == "carnet glycemie")
    assert jamais.n_enfants is None, "une requête non sondée passe pour une feuille"


def test_le_budget_epuise_laisse_aussi_un_None():
    """Même raison, autre cause : le plafond de sondes coupe la descente. Ce qui n'a pas
    été sondé faute de budget n'a pas été mesuré."""
    arbre = {"carnet": [f"carnet {i}" for i in range(5)]}
    out = expand("carnet", fetch=_fetch(arbre), depth=2, alphabet=False,
                 max_probes=1, pause=0)
    assert all(s.n_enfants is None for s in out)


def test_le_scoring_n_accorde_aucun_bonus_sur_un_None():
    """Ni bonus ni malus : `None` ne se convertit pas en mesure défavorable non plus."""
    from lowcontent_scoring import score_lowcontent
    from models import LowContentNiche, SearchItem

    def _n(**kw):
        base = dict(niche="c", requete_amazon="c", rationale="r", categorie="c",
                    format_cle="journal_suivi", theme="t", public="adulte")
        base.update(kw)
        return LowContentNiche(**base)

    serp = SearchResult(keyword="q", sponsored=[], organic=[
        SearchItem(title="T", asin="A1")])
    inconnu = score_lowcontent(_n(n_enfants_autocomplete=None), _validation(), serp, [],
                               [3000])
    mesure_zero = score_lowcontent(_n(n_enfants_autocomplete=0), _validation(), serp, [],
                                   [3000])
    assert inconnu.demande == mesure_zero.demande


def test_le_tri_de_la_shortlist_ne_prefere_pas_un_zero_mesure_a_un_inconnu():
    """C'est là que ça coûte de l'argent : ce compteur décide de QUELLES niches on paie.
    Un inconnu ne doit pas être classé derrière une feuille dont on sait qu'elle est
    stérile — on ne sait rien de lui, ce n'est pas la même chose que savoir qu'il est
    mauvais."""
    from lowcontent_master import _rang_shortlist
    # La requête est passée depuis le 2026-09-30 : le nombre de mots est devenu le premier
    # terme de la clé (cf. tests/test_shortlist_specificite.py). L'invariant testé ici est
    # inchangé, il se vérifie donc à requête ÉGALE.
    assert (_rang_shortlist("carnet de suivi bebe", None, 2, 5)
            >= _rang_shortlist("carnet de suivi bebe", 0, 2, 5))
