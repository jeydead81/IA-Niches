"""Limiteur de débit sur les endpoints payants « à la pièce ».

`/api/verdict`, `/api/kdp-keywords` et `/api/dossier` imputent `n_analyses=0` : ils
complètent une analyse déjà comptée, et c'est juste. Mais la conséquence est qu'ils sont
**inatteignables par le plafond mensuel** — 200 verdicts coûtent 5,60 $ sans qu'aucun garde
ne bronche. Ils exigent une marge sous le plafond sans jamais la consommer.

CE LIMITEUR EST UN GARDE-FOU, PAS UNE GRILLE TARIFAIRE. C'est la même posture que
`PLAFOND_ANALYSES_MENSUEL`, dont le docstring dit déjà « garde-fou contre l'utilisateur à
500 analyses, pas une grille tarifaire ». Il n'engage aucune décision commerciale : quand
le modèle d'abonnement existera, il le remplacera ou le laissera comme filet.

Le défaut est ANCRÉ, pas inventé : une analyse rend jusqu'à 20 niches (MAX_RECHERCHES), et
un utilisateur peut légitimement vouloir un verdict sur chacune. 40 appels par heure, c'est
deux analyses entières décortiquées d'affilée. Au-delà, dans la même heure, ce n'est plus
quelqu'un qui lit des résultats.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from usage import UsageMeter

TYPES = ("verdict", "kdp", "dossier")


def _meter(tmp_path, now=None) -> UsageMeter:
    return UsageMeter(tmp_path / "usage.db", now=now)


# ── Le comptage ────────────────────────────────────────────────────────────────

def test_compter_ne_voit_que_les_types_demandes(tmp_path):
    """Un run de scout ne doit pas consommer le débit des appels à la pièce : ce sont deux
    garde-fous distincts, sur deux populations d'appels distinctes."""
    m = _meter(tmp_path)
    m.enregistrer("u", "verdict", 0.028, 0)
    m.enregistrer("u", "scout", 0.084, 1)
    assert m.compter("u", TYPES, fenetre_s=3600) == 1


def test_compter_ne_voit_que_l_utilisateur_demande(tmp_path):
    m = _meter(tmp_path)
    m.enregistrer("alice", "verdict", 0.028, 0)
    m.enregistrer("bob", "verdict", 0.028, 0)
    assert m.compter("alice", TYPES, fenetre_s=3600) == 1


def test_la_fenetre_est_GLISSANTE_pas_calendaire(tmp_path):
    """Un seau qui se vide à heure fixe se contourne en attendant l'heure ronde ; une
    fenêtre glissante, non."""
    horloge = [1000.0]
    m = _meter(tmp_path, now=lambda: horloge[0])
    m.enregistrer("u", "verdict", 0.028, 0)
    horloge[0] += 3599
    assert m.compter("u", TYPES, fenetre_s=3600) == 1
    horloge[0] += 2
    assert m.compter("u", TYPES, fenetre_s=3600) == 0


# ── La réservation ─────────────────────────────────────────────────────────────

def test_une_reservation_compte_AVANT_que_l_appel_ne_soit_paye(tmp_path):
    """Sans réservation, dix requêtes concurrentes passent toutes le contrôle avant que
    la première ne soit enregistrée — le limiteur ne limiterait que le rythme d'un client
    séquentiel, c'est-à-dire personne."""
    m = _meter(tmp_path)
    m.reserver("u", "verdict")
    assert m.compter("u", TYPES, fenetre_s=3600) == 1


def test_solder_inscrit_le_cout_reel_sans_compter_deux_fois(tmp_path):
    m = _meter(tmp_path)
    rid = m.reserver("u", "verdict")
    m.solder(rid, 0.0283)
    assert m.compter("u", TYPES, fenetre_s=3600) == 1
    assert m.resume("u").cout_usd == pytest.approx(0.0283)


def test_une_reservation_non_soldee_ne_facture_rien(tmp_path):
    """Un appel qui échoue avant de dépenser laisse sa réservation à zéro dollar : elle
    consomme du débit (elle a bien eu lieu) mais ne facture rien qui n'ait été dépensé."""
    m = _meter(tmp_path)
    m.reserver("u", "verdict")
    assert m.resume("u").cout_usd == 0.0
    assert m.compter("u", TYPES, fenetre_s=3600) == 1


def test_une_reservation_ne_consomme_pas_le_plafond_mensuel(tmp_path):
    """`n_analyses=0` reste juste : ces appels COMPLÈTENT une analyse déjà comptée. Le
    limiteur de débit est un second garde-fou, il ne remplace pas le premier."""
    m = UsageMeter(tmp_path / "u.db", plafond_analyses=1)
    m.reserver("u", "verdict")
    assert m.autorise("u", n_analyses=1) is True


# ── Bout en bout ───────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    from tests.test_server_jobs import _client_with_isolated_dbs
    return _client_with_isolated_dbs(monkeypatch, tmp_path)


def test_au_dela_du_debit_l_appel_est_refuse_en_429(tmp_path, monkeypatch):
    """429 et non 400 : ce n'est pas la requête qui est fautive, c'est le rythme. Le
    distinguer permet à l'utilisateur de comprendre qu'il lui suffit d'attendre."""
    client, server = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("DEBIT_APPELS_MAX", "2")
    from models import NicheVerdict
    monkeypatch.setattr(server, "generate_verdict",
                        lambda s, **k: NicheVerdict(verdict="Go", confiance=8,
                                                    facteur_decisif="x"))
    corps = {"niche": "tarot", "requete_amazon": "tarot", "categorie": "éso"}
    assert client.post("/api/verdict", json=corps).status_code == 200
    assert client.post("/api/verdict", json=corps).status_code == 200
    r = client.post("/api/verdict", json=corps)
    assert r.status_code == 429
    assert "rythme" in r.json()["detail"].lower() or "attend" in r.json()["detail"].lower()


def test_le_refus_ne_facture_rien(tmp_path, monkeypatch):
    """Un appel refusé ne doit ni dépenser, ni consommer davantage de débit — sinon un
    client qui insiste se verrouillerait tout seul plus longtemps."""
    client, server = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("DEBIT_APPELS_MAX", "1")
    appels = []
    from models import NicheVerdict
    monkeypatch.setattr(server, "generate_verdict",
                        lambda s, **k: appels.append(1) or NicheVerdict(
                            verdict="Go", confiance=8, facteur_decisif="x"))
    corps = {"niche": "tarot", "requete_amazon": "tarot", "categorie": "éso"}
    client.post("/api/verdict", json=corps)
    for _ in range(3):
        assert client.post("/api/verdict", json=corps).status_code == 429
    assert len(appels) == 1, "un appel refusé a quand même atteint le LLM"


def test_les_trois_endpoints_partagent_le_meme_debit(tmp_path, monkeypatch):
    """Trois compteurs séparés se contourneraient en alternant. C'est la DÉPENSE qu'on
    borne, pas un endpoint en particulier."""
    client, server = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("DEBIT_APPELS_MAX", "1")
    from models import MotsClesKDP, NicheVerdict
    monkeypatch.setattr(server, "generate_verdict",
                        lambda s, **k: NicheVerdict(verdict="Go", confiance=8,
                                                    facteur_decisif="x"))
    monkeypatch.setattr(server, "generer_mots_cles", lambda *a, **k: MotsClesKDP())
    corps = {"niche": "tarot", "requete_amazon": "tarot", "categorie": "éso"}
    assert client.post("/api/verdict", json=corps).status_code == 200
    assert client.post("/api/kdp-keywords", json=corps).status_code == 429


def test_le_PDF_seul_ne_consomme_pas_de_debit(tmp_path, monkeypatch):
    """Un dossier SANS mots-clés ne dépense rien : le brider serait gratuit en coût et
    coûteux en usage."""
    client, _ = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("DEBIT_APPELS_MAX", "1")
    corps = {"niche": {"niche": "tarot", "requete_amazon": "tarot", "categorie": "éso",
                       "concurrence_mesuree": True}}
    for _ in range(3):
        assert client.post("/api/dossier", json=corps).status_code == 200


def test_sans_limite_configuree_rien_n_est_bride(tmp_path, monkeypatch):
    """Le défaut doit protéger, pas gêner : une valeur absurde ou vide retombe sur le
    défaut, et `0` desactive explicitement."""
    client, server = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("DEBIT_APPELS_MAX", "0")
    from models import NicheVerdict
    monkeypatch.setattr(server, "generate_verdict",
                        lambda s, **k: NicheVerdict(verdict="Go", confiance=8,
                                                    facteur_decisif="x"))
    corps = {"niche": "tarot", "requete_amazon": "tarot", "categorie": "éso"}
    for _ in range(5):
        assert client.post("/api/verdict", json=corps).status_code == 200


def test_le_defaut_est_ancre_sur_ce_qu_une_analyse_produit():
    """40 = deux analyses entières (MAX_RECHERCHES=20) décortiquées d'affilée. Le chiffre
    doit rester lié à cette borne, pas flotter tout seul."""
    import server
    assert server.DEBIT_APPELS_MAX_DEFAUT == 2 * server.MAX_RECHERCHES
