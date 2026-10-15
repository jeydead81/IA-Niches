"""Chaque refus d'essai dit sa CAUSE dans le journal, et rien d'autre (2026-10-15).

Sans cela on ne peut pas calibrer les seuils : le visiteur lit un message volontairement unique (détailler la cause
laisserait régler le contournement) et l'opérateur n'a aucun moyen de savoir si c'est le réseau, le domaine ou le
quota du jour qui refuse des clients légitimes. Une ligne par refus, cause SEULE : jamais l'adresse e-mail, le
domaine, l'adresse IP ni un identifiant de compte — le journal d'un hébergeur est un canal en clair.

Le seuil par réseau est passé de 3 à 5 le même jour : un réseau mobile partage une adresse publique entre beaucoup
d'abonnés, et la règle ne retient de toute façon que le fraudeur paresseux (un proxy qui change d'adresse la
contourne) — 2 essais de plus pour lui coûtent moins qu'un client légitime refusé.
"""
import logging

import pytest

import essai
from tests.test_auth_essai import magasin, ouvrir
from tests.test_server_essai import _essai, _instance, _lancer, _proprietaire


# ── Le seuil par réseau ─────────────────────────────────────────────────────────────────

def test_le_seuil_par_reseau_est_cinq_et_celui_par_domaine_trois():
    assert essai.ESSAI_PAR_RESEAU == 5 and essai.ESSAI_PAR_DOMAINE == 3


def test_le_sixieme_essai_d_un_meme_reseau_est_refuse_pas_le_cinquieme(tmp_path):
    s, _ = magasin(tmp_path)
    for i in range(5):
        c = ouvrir(s, f"p{i}@gmail.com")
        assert s.reserver_recherche_essai(c.user_id, client="8.8.8.8", par_jour_max=50).demarre_ici
    sixieme = ouvrir(s, "p5@gmail.com")
    with pytest.raises(essai.EssaiRefuse):
        s.reserver_recherche_essai(sixieme.user_id, client="8.8.8.8", par_jour_max=50)


# ── La cause portée par l'exception ─────────────────────────────────────────────────────

def test_chaque_refus_porte_sa_cause(tmp_path):
    s, _ = magasin(tmp_path)

    def cause_de(email, client=None, par_jour_max=50):
        c = ouvrir(s, email)
        with pytest.raises(essai.EssaiIndisponible) as e:
            s.reserver_recherche_essai(c.user_id, client=client, par_jour_max=par_jour_max)
        return e.value.cause

    a = ouvrir(s, "jean@gmail.com")
    s.reserver_recherche_essai(a.user_id, client=None, par_jour_max=50)
    assert cause_de("jean+2@gmail.com") == "identite"
    assert cause_de("x@mailinator.com") == "jetable"
    for i in range(essai.ESSAI_PAR_DOMAINE):
        c = ouvrir(s, f"u{i}@mon-site.fr")
        s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=50)
    assert cause_de("v@mon-site.fr") == "domaine"
    for i in range(essai.ESSAI_PAR_RESEAU):
        c = ouvrir(s, f"r{i}@gmail.com")
        s.reserver_recherche_essai(c.user_id, client="8.8.8.8", par_jour_max=50)
    assert cause_de("r9@gmail.com", client="8.8.8.8") == "reseau"
    assert cause_de("q@gmail.com", par_jour_max=0) == "quota_jour"


def test_un_essai_epuise_porte_la_cause_epuise(tmp_path):
    s, _ = magasin(tmp_path)
    c = ouvrir(s, "a@gmail.com")
    for _ in range(essai.ESSAI_RECHERCHES):
        s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=50)
    with pytest.raises(essai.EssaiEpuise) as e:
        s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=50)
    assert e.value.cause == "epuise"


# ── La ligne de journal ─────────────────────────────────────────────────────────────────

def _messages(caplog):
    return [r for r in caplog.records if "essai refusé" in r.getMessage()]


def test_un_refus_d_identite_est_journalise_avec_sa_cause_et_sans_donnee_personnelle(tmp_path, monkeypatch, caplog):
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    monkeypatch.setattr(server, "_client_distant", lambda request: "8.8.8.8")
    _essai(client, monkeypatch, "jean.martin@gmail.com")
    assert _lancer(client, server, monkeypatch).status_code == 202
    _essai(client, monkeypatch, "jeanmartin+kdp@gmail.com")
    with caplog.at_level(logging.INFO, logger="ia-niches"):
        assert _lancer(client, server, monkeypatch, attendre=False).status_code == 403
    lignes = _messages(caplog)
    assert len(lignes) == 1 and "cause=identite" in lignes[0].getMessage()
    assert lignes[0].levelno >= logging.WARNING            # visible avec la configuration par défaut de Python
    tout = " ".join(r.getMessage() for r in caplog.records).lower()
    for donnee in ("jean", "martin", "gmail", "8.8.8.8"):
        assert donnee not in tout, donnee


def test_le_quota_du_jour_est_journalise(tmp_path, monkeypatch, caplog):
    client, server = _instance(monkeypatch, tmp_path, par_jour=1)
    _proprietaire(client)
    _essai(client, monkeypatch, "premier@gmail.com")
    assert _lancer(client, server, monkeypatch).status_code == 202
    _essai(client, monkeypatch, "second@gmail.com")
    with caplog.at_level(logging.INFO, logger="ia-niches"):
        assert _lancer(client, server, monkeypatch, attendre=False).status_code == 429
    lignes = _messages(caplog)
    assert len(lignes) == 1 and "cause=quota_jour" in lignes[0].getMessage()
    assert lignes[0].levelno >= logging.WARNING


def test_un_essai_epuise_est_journalise_sans_alarmer(tmp_path, monkeypatch, caplog):
    """Un visiteur qui a fini son essai et insiste n'est pas un incident : niveau INFO, invisible par défaut."""
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    _essai(client, monkeypatch)
    for _ in range(essai.ESSAI_RECHERCHES):
        assert _lancer(client, server, monkeypatch).status_code == 202
    with caplog.at_level(logging.INFO, logger="ia-niches"):
        assert _lancer(client, server, monkeypatch, attendre=False).status_code == 429
    lignes = _messages(caplog)
    assert len(lignes) == 1 and "cause=epuise" in lignes[0].getMessage()
    assert lignes[0].levelno < logging.WARNING


def test_un_essai_accorde_ne_journalise_aucun_refus(tmp_path, monkeypatch, caplog):
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    _essai(client, monkeypatch)
    with caplog.at_level(logging.INFO, logger="ia-niches"):
        assert _lancer(client, server, monkeypatch).status_code == 202
    assert not _messages(caplog)
