"""L'identité d'un trio n'est PAS sa requête Amazon : `FictionNiche.cle`.

Revue adverse du 2026-10-05, constat confirmé : avec des requêtes courtes ancrées sur « tête +
décor », deux trios de même décor partagent la MÊME requête. Or la requête servait d'identité :
- l'historique d'évolution (`_consigner_fiction`) : deux runs, deux trios différents au même décor,
  même clé -> `delta()` annonçait « la niche s'est dégagée » alors que seule la saturation, qui
  dépend des tropes, avait changé (mesuré : 1,0 puis 0,0 sur les mêmes quatre livres) ;
- la conservation de l'analyse éditoriale dans le travail (`JobStore._est_la_niche`) : rangée sous
  la PREMIÈRE carte qui porte la requête, jamais sous la bonne.

La clé du trio = sous-genre + requête + tropes (sans ordre) + décor. Elle est calculée UNE fois,
côté Python, et lue telle quelle par l'historique, par l'écran et par la conservation : trois
recalculs divergeraient (§5.32). Un résultat ANTÉRIEUR (sans `cle`) la reçoit à la validation, et
l'écran retombe sur la requête quand il n'a pas de `cle` à lire.
"""
import pytest

from models import FictionNiche, FictionNicheReport


def _n(tropes=("deuil_lumineux",), decor="village", query="roman feel good village",
       sous_genre="feel_good", **kw):
    return FictionNiche(sous_genre=sous_genre, tropes=list(tropes), decor=decor, query=query, **kw)


def test_le_meme_trio_a_toujours_la_meme_cle():
    assert _n().cle == _n().cle and _n().cle


def test_deux_trios_de_meme_requete_mais_de_tropes_differents_ont_deux_cles():
    a, b = _n(("deuil_lumineux",)), _n(("retour_aux_sources",))
    assert a.query == b.query and a.cle != b.cle


def test_l_ordre_des_tropes_ne_change_pas_la_cle():
    assert _n(("a", "b")).cle == _n(("b", "a")).cle


def test_la_requete_est_comparee_sans_casse_ni_accents():
    assert _n(query="Roman Feel Good Éclair").cle == _n(query="roman feel good eclair").cle


@pytest.mark.parametrize("champ", [{"decor": "montagne"}, {"sous_genre": "cosy_mystery"},
                                   {"query": "roman feel good montagne"}])
def test_chaque_composante_compte(champ):
    assert _n(**champ).cle != _n().cle


def test_une_cle_fournie_est_conservee():
    assert _n(cle="imposee").cle == "imposee"


def test_la_cle_est_serialisee_pour_l_ecran():
    d = _n().model_dump()
    assert d["cle"] == _n().cle


def test_un_resultat_anterieur_sans_cle_la_recoit_a_la_validation():
    d = _n().model_dump()
    d.pop("cle")
    assert FictionNiche.model_validate(d).cle == _n().cle
    r = FictionNicheReport.model_validate({"niche": d})
    assert r.niche.cle == _n().cle


# ── L'historique ────────────────────────────────────────────────────────────────

def _rapport(niche, saturation):
    return FictionNicheReport(niche=niche, depth_score=0.7, openness_score=0.6,
                              saturation_trio=saturation, series_share=0.2,
                              demand_matrix="pepite")


@pytest.fixture
def serveur(monkeypatch, tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))
    pytest.importorskip("httpx")
    import server
    from tests.conftest import isoler_bases
    isoler_bases(monkeypatch, server, tmp_path)
    return server


def test_deux_trios_de_meme_requete_ont_chacun_leur_serie_d_historique(serveur):
    from history import NicheHistory
    a, b = _n(("deuil_lumineux",)), _n(("retour_aux_sources",))
    serveur._consigner_fiction([_rapport(a, 1.0), _rapport(b, 0.0)], "u1")
    h = NicheHistory(serveur._HISTORY_DB)
    assert len(h.historique("u1", a.cle)) == 1 and len(h.historique("u1", b.cle)) == 1
    assert h.delta("u1", a.cle) is None and h.delta("u1", b.cle) is None


def test_un_trio_relance_a_un_autre_run_alimente_la_meme_serie(serveur):
    from history import NicheHistory
    a = _n()
    serveur._consigner_fiction([_rapport(a, 0.5)], "u1")
    serveur._consigner_fiction([_rapport(_n(), 0.4)], "u1")
    assert len(NicheHistory(serveur._HISTORY_DB).historique("u1", a.cle)) == 2


def test_deux_trios_differents_au_meme_decor_ne_se_comparent_plus(serveur):
    """Le scénario exact de la revue : run 1 trio A, run 2 trio B, même requête, même rayon,
    saturation 1,0 puis 0,0. Avant : « la niche s'est dégagée ». Maintenant : aucune comparaison."""
    from history import NicheHistory
    serveur._consigner_fiction([_rapport(_n(("deuil_lumineux",)), 1.0)], "u1")
    serveur._consigner_fiction([_rapport(_n(("retour_aux_sources",)), 0.0)], "u1")
    h = NicheHistory(serveur._HISTORY_DB)
    assert h.delta("u1", _n(("deuil_lumineux",)).cle) is None
    assert h.delta("u1", _n(("retour_aux_sources",)).cle) is None


# ── La conservation de l'analyse dans le travail ─────────────────────────────────

def test_l_analyse_est_rangee_sous_le_bon_trio_quand_deux_partagent_la_requete():
    from jobs import JobStore
    a, b = _n(("deuil_lumineux",)), _n(("retour_aux_sources",))
    entrees = [{"niche": a.model_dump()}, {"niche": b.model_dump()}]
    assert JobStore._est_la_niche(entrees[0], b.cle) is False
    assert JobStore._est_la_niche(entrees[1], b.cle) is True


def test_un_resultat_ancien_sans_cle_se_retrouve_encore_par_sa_requete():
    from jobs import JobStore
    ancien = {"niche": {"sous_genre": "feel_good", "query": "roman feel good village"}}
    assert JobStore._est_la_niche(ancien, "roman feel good village") is True


def test_la_cle_cote_ecran_est_celle_du_trio_et_retombe_sur_la_requete():
    from tests.js_harness import appeler
    assert appeler("cleNiche", {"niche": {"cle": "K", "query": "q"}}) == "K"
    assert appeler("cleNiche", {"niche": {"query": "q"}}) == "q"
    assert appeler("cleNiche", {"niche": "tarot"}) == "tarot"
    assert appeler("cleNiche", {"niche": {"niche": "n", "requete_amazon": "rq"}}) == "rq"
