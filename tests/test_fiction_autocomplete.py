import json
from pathlib import Path

from fiction_autocomplete import probe_niche, score_suggestions
from models import FictionNiche

_LIVE = json.loads((Path(__file__).parent / "fixtures" / "fiction" /
                    "v3_autocomplete.json").read_text(encoding="utf-8"))


def _niche(query, sg="cosy_mystery"):
    return FictionNiche(sous_genre=sg, tropes=["enquetrice_amatrice"], rayon="kindle",
                        query=query)


def test_bareme_cale_sur_les_mesures_live():
    # 4 suggestions dont l'écho -> 3 extras -> signal franc
    assert score_suggestions("romance milliardaire", _LIVE["romance milliardaire"]) == 1.0
    # écho seul -> le terme existe mais rien ne s'y greffe
    assert score_suggestions("polar breton", _LIVE["polar breton"]) == 0.5
    # rien -> trio trop précis (ou terme inexistant) : c'est le barreau 2 qui tranchera
    assert score_suggestions("romantasy ennemis", _LIVE["romantasy ennemis"]) == 0.0


def test_deux_barreaux_trio_precis_mais_sous_genre_cherche():
    appels = []

    def fake(prefix):
        appels.append(prefix)
        return {"cosy mystery": [{"value": "cosy mystery"},
                                 {"value": "cosy mystery francais"}]}.get(prefix, [])

    sig = probe_niche(_niche("cosy mystery libraire village"),
                      fetch_json=lambda p: {"suggestions": fake(p)}, pause=0)
    assert appels == ["cosy mystery libraire village", "cosy mystery"]   # spécifique -> large
    assert sig.score == 0.0                 # le trio n'est pas tapé…
    assert sig.sous_genre_cherche is True   # …mais le sous-genre l'est : pas d'alerte
    assert sig.mesure is True


def test_sous_genre_fantome_est_signale():
    sig = probe_niche(_niche("x"), fetch_json=lambda p: {"suggestions": []}, pause=0)
    assert sig.score == 0.0 and sig.sous_genre_cherche is False


def test_echec_de_sonde_nest_pas_un_zero():
    from amazon_autocomplete import AutocompleteError

    def ko(prefix):
        raise AutocompleteError("HTTP 503")

    sig = probe_niche(_niche("cosy mystery libraire"), fetch_json=ko, pause=0)
    assert sig.mesure is False                     # <- la distinction qui compte
    assert sig.score == 0.0
    assert "non mesuré" in sig.libelle
    assert sig.probes[0].echec is True and "503" in (sig.probes[0].erreur or "")


def test_barreau_2_saute_si_le_trio_suffit():
    """Économie de requêtes : un trio déjà positif n'a pas besoin du contexte."""
    appels = []

    def fake(prefix):
        appels.append(prefix)
        return {"suggestions": [{"value": prefix}, {"value": prefix + " 2"},
                                {"value": prefix + " 3"}]}

    sig = probe_niche(_niche("cosy mystery libraire"), fetch_json=fake, pause=0)
    assert sig.score == 1.0 and len(appels) == 1


def test_panne_reseau_reelle_nest_pas_un_zero():
    """util.http_get re-lève requests.RequestException après ses retries : sur le chemin
    de production, un timeout DNS tuait le run au lieu de rendre mesure=False."""
    import requests

    def ko(prefix):
        raise requests.ConnectionError("DNS")

    sig = probe_niche(_niche("cosy mystery libraire"), fetch_json=ko, pause=0)
    assert sig.mesure is False and sig.score == 0.0
    assert sig.probes[0].echec is True


def test_requete_vide_ne_donne_pas_le_score_maximal():
    """FictionNiche.query a un défaut vide et n'est jamais vérifiée côté code : un trio
    dont le LLM a omis la requête décrochait 1.0 (toute suggestion compte comme extra)."""
    appels = []
    sig = probe_niche(_niche("   "), fetch_json=lambda p: appels.append(p) or {}, pause=0)
    assert sig.score == 0.0 and sig.mesure is False
    assert appels == []                      # on ne sonde même pas


def test_sous_genre_fantome_quand_la_requete_est_deja_canonique():
    """Si le barreau 1 EST la requête canonique et rend 0, le sous-genre vient d'être
    mesuré à zéro : c'est l'alerte, pas une absence d'information."""
    for q in ("cosy mystery", "  Cosy   Mystery "):
        sig = probe_niche(_niche(q), fetch_json=lambda p: {"suggestions": []}, pause=0)
        assert sig.sous_genre_cherche is False, q
        assert sig.mesure is True, q
