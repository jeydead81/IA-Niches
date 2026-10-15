"""Alerte par e-mail quand le solde du fournisseur de données passe sous un seuil (2026-10-15).

Le contrôle de solde AVANT lancement (2026-10-05) refuse un run quand le compte est à sec : le client
voit « service momentanément indisponible » et l'exploitant ne sait rien. Le compte DataForSEO se
recharge à la main (le dépôt n'a, et ne doit avoir, aucun moyen de payer) : sans alerte, la première
nouvelle d'un compte vide est un client qui ne peut plus rien lancer. Seuil par défaut : 5 $.

Règles tenues par ces tests :

1. **Un solde illisible n'est pas un solde bas** (règle 3) : aucune alerte sur `None`.
2. **Une alerte par jour au plus** : un compte qui reste bas ne doit pas remplir une boîte à chaque
   run. Mais une recharge RÉARME l'alerte : le prochain creux sera signalé le jour même.
3. **Sans destinataire, rien ne part — et on le DIT** (journal) plutôt que de laisser croire que
   l'alerte est câblée. Le destinataire vient de `ALERTE_SOLDE_EMAIL`.
4. **Un envoi qui échoue sera retenté** au contrôle suivant (aucune marque posée).
5. **Le message ne porte ni identifiant ni clé du fournisseur**, seulement le solde et le seuil.
6. **Jamais une alerte ne fait échouer un run.**
"""
import pytest

from alerte_solde import (INTERVALLE_S, SEUIL_DEFAUT_USD, destinataire, seuil_usd,
                          verifier_et_alerter)
from cache import Cache


class _Journal:
    def __init__(self):
        self.lignes = []

    def error(self, msg, *a):
        self.lignes.append(msg % a if a else msg)

    warning = info = error


def _cache(tmp_path, now=None):
    return Cache(tmp_path / "c.db", now=now)


def _envoi(ok=True):
    partis = []

    def envoyer(dest, sujet, corps):
        partis.append((dest, sujet, corps))
        return ok

    envoyer.partis = partis
    return envoyer


def _env(monkeypatch, dest="moi@example.com", seuil=None):
    if dest is None:
        monkeypatch.delenv("ALERTE_SOLDE_EMAIL", raising=False)
    else:
        monkeypatch.setenv("ALERTE_SOLDE_EMAIL", dest)
    if seuil is None:
        monkeypatch.delenv("ALERTE_SOLDE_USD", raising=False)
    else:
        monkeypatch.setenv("ALERTE_SOLDE_USD", str(seuil))


# ── Réglages ────────────────────────────────────────────────────────────────────────

def test_le_seuil_par_defaut_est_de_cinq_dollars(monkeypatch):
    _env(monkeypatch)
    assert SEUIL_DEFAUT_USD == 5.0 and seuil_usd() == 5.0


def test_le_seuil_se_regle_et_une_valeur_illisible_retombe_sur_le_defaut(monkeypatch):
    _env(monkeypatch, seuil="12.5")
    assert seuil_usd() == 12.5
    for mauvais in ("beaucoup", "", "-3", "0"):
        monkeypatch.setenv("ALERTE_SOLDE_USD", mauvais)
        assert seuil_usd() == 5.0, mauvais


def test_le_destinataire_est_nettoye_ou_absent(monkeypatch):
    _env(monkeypatch, dest="  moi@example.com  ")
    assert destinataire() == "moi@example.com"
    _env(monkeypatch, dest="")
    assert destinataire() is None
    _env(monkeypatch, dest=None)
    assert destinataire() is None


# ── La décision ─────────────────────────────────────────────────────────────────────

def test_sous_le_seuil_un_message_part(tmp_path, monkeypatch):
    _env(monkeypatch)
    envoyer = _envoi()
    assert verifier_et_alerter(3.2, _cache(tmp_path), envoyer, _Journal()) == "envoye"
    (dest, sujet, corps), = envoyer.partis
    assert dest == "moi@example.com" and "3,20" in sujet + corps and "5" in corps


def test_au_dessus_du_seuil_rien_ne_part(tmp_path, monkeypatch):
    _env(monkeypatch)
    envoyer = _envoi()
    assert verifier_et_alerter(5.0, _cache(tmp_path), envoyer, _Journal()) == "ok"
    assert verifier_et_alerter(40.0, _cache(tmp_path), envoyer, _Journal()) == "ok"
    assert envoyer.partis == []


def test_un_solde_illisible_n_alerte_jamais(tmp_path, monkeypatch):
    """Règle 3 : un contrôle qui n'a pas pu se faire n'est pas un compte vide."""
    _env(monkeypatch)
    envoyer = _envoi()
    assert verifier_et_alerter(None, _cache(tmp_path), envoyer, _Journal()) == "illisible"
    assert envoyer.partis == []


def test_un_solde_negatif_alerte(tmp_path, monkeypatch):
    _env(monkeypatch)
    envoyer = _envoi()
    assert verifier_et_alerter(-0.002, _cache(tmp_path), envoyer, _Journal()) == "envoye"
    assert len(envoyer.partis) == 1


def test_une_seule_alerte_par_jour(tmp_path, monkeypatch):
    _env(monkeypatch)
    horloge = [1000.0]
    c, envoyer = _cache(tmp_path, now=lambda: horloge[0]), _envoi()
    assert verifier_et_alerter(3.0, c, envoyer, _Journal()) == "envoye"
    for _ in range(5):
        assert verifier_et_alerter(2.0, c, envoyer, _Journal()) == "deja_alerte"
    assert len(envoyer.partis) == 1
    horloge[0] += INTERVALLE_S + 1
    assert verifier_et_alerter(1.0, c, envoyer, _Journal()) == "envoye"
    assert len(envoyer.partis) == 2


def test_une_recharge_rearme_l_alerte(tmp_path, monkeypatch):
    """Le compte repasse au-dessus du seuil, puis rechute le lendemain MÊME jour : l'alerte doit
    repartir, pas attendre la fin d'un délai posé pour la crise précédente."""
    _env(monkeypatch)
    horloge = [1000.0]
    c, envoyer = _cache(tmp_path, now=lambda: horloge[0]), _envoi()
    verifier_et_alerter(3.0, c, envoyer, _Journal())
    horloge[0] += 60
    assert verifier_et_alerter(50.0, c, envoyer, _Journal()) == "ok"
    horloge[0] += 60
    assert verifier_et_alerter(2.0, c, envoyer, _Journal()) == "envoye"
    assert len(envoyer.partis) == 2


def test_sans_destinataire_rien_ne_part_et_le_journal_le_dit(tmp_path, monkeypatch):
    _env(monkeypatch, dest=None)
    envoyer, journal = _envoi(), _Journal()
    assert verifier_et_alerter(1.0, _cache(tmp_path), envoyer, journal) == "sans_destinataire"
    assert envoyer.partis == []
    assert any("ALERTE_SOLDE_EMAIL" in l for l in journal.lignes)


def test_le_destinataire_defini_plus_tard_declenche_l_alerte_tout_de_suite(tmp_path, monkeypatch):
    """Sans destinataire aucune marque n'est posée : l'alerte ne doit pas être « consommée » par un
    envoi qui n'a pas eu lieu."""
    _env(monkeypatch, dest=None)
    c, envoyer = _cache(tmp_path), _envoi()
    verifier_et_alerter(1.0, c, envoyer, _Journal())
    _env(monkeypatch)
    assert verifier_et_alerter(1.0, c, envoyer, _Journal()) == "envoye"


def test_un_envoi_en_echec_sera_retente_au_controle_suivant(tmp_path, monkeypatch):
    _env(monkeypatch)
    c = _cache(tmp_path)
    assert verifier_et_alerter(1.0, c, _envoi(ok=False), _Journal()) == "echec_envoi"
    assert verifier_et_alerter(1.0, c, _envoi(ok=True), _Journal()) == "envoye"


def test_un_envoi_qui_leve_ne_leve_pas(tmp_path, monkeypatch):
    _env(monkeypatch)

    def casse(*a):
        raise OSError("réseau")

    assert verifier_et_alerter(1.0, _cache(tmp_path), casse, _Journal()) == "echec_envoi"


def test_le_message_ne_porte_aucun_secret(tmp_path, monkeypatch):
    _env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "login-secret@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "mot-de-passe-api-secret")
    envoyer = _envoi()
    verifier_et_alerter(1.0, _cache(tmp_path), envoyer, _Journal())
    texte = " ".join(envoyer.partis[0])
    assert "secret" not in texte and "login" not in texte.lower()


# ── Le câblage dans le serveur ──────────────────────────────────────────────────────

def _serveur(monkeypatch, tmp_path, solde):
    pytest.importorskip("httpx")
    import server
    from tests.conftest import isoler_bases
    isoler_bases(monkeypatch, server, tmp_path)
    # Le cache partagé (qui porte la marque « déjà alerté ») suit DATA_DIR : un dossier par test,
    # sans quoi la marque d'un test serait lue par le suivant.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _env(monkeypatch)
    monkeypatch.setattr(server, "_en_arriere_plan", lambda fn, *a: fn(*a))
    partis = []
    monkeypatch.setattr(server, "_envoyer_alerte",
                        lambda dest, sujet, corps: partis.append((dest, sujet, corps)) or True)
    monkeypatch.setattr(server._sp, "lire_solde", lambda *a, **k: solde)
    return server, partis


def test_une_lecture_du_solde_sous_le_seuil_declenche_l_alerte(monkeypatch, tmp_path):
    server, partis = _serveur(monkeypatch, tmp_path, solde=2.5)
    assert server._lire_solde() == 2.5
    assert len(partis) == 1 and partis[0][0] == "moi@example.com"


def test_la_lecture_en_cache_ne_relance_pas_l_alerte(monkeypatch, tmp_path):
    server, partis = _serveur(monkeypatch, tmp_path, solde=2.5)
    server._lire_solde()
    server._lire_solde()
    server._lire_solde()
    assert len(partis) == 1


def test_un_solde_correct_ne_declenche_rien(monkeypatch, tmp_path):
    server, partis = _serveur(monkeypatch, tmp_path, solde=60.0)
    server._lire_solde()
    assert partis == []


def test_apres_un_run_le_solde_est_relu_frais(monkeypatch, tmp_path):
    """Un run dépense : c'est LE moment où le compte peut passer sous le seuil. Le cache de 30 s ne
    doit pas masquer la lecture d'après-run."""
    server, partis = _serveur(monkeypatch, tmp_path, solde=60.0)
    server._lire_solde()                       # amorce le cache à 60 $
    monkeypatch.setattr(server._sp, "lire_solde", lambda *a, **k: 3.0)
    server._alerter_apres_run()
    assert len(partis) == 1


def test_l_alerte_ne_fait_jamais_echouer_un_run(monkeypatch, tmp_path):
    server, partis = _serveur(monkeypatch, tmp_path, solde=1.0)

    def casse(*a):
        raise RuntimeError("boum")

    monkeypatch.setattr(server, "_envoyer_alerte", casse)
    server._alerter_apres_run()                # ne lève pas
    server._lire_solde()


def test_un_run_de_bout_en_bout_verifie_le_solde_a_la_fin(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from tests.conftest import ouvrir_session
    from tests.test_server_jobs import _attendre_job
    server, partis = _serveur(monkeypatch, tmp_path, solde=60.0)
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", lambda params, progress, cost, uid: [])
    c = TestClient(server.app)
    ouvrir_session(c)
    jid = c.post("/api/jobs", json={"type": "scout", "n_search": 1}).json()["id"]
    monkeypatch.setattr(server._sp, "lire_solde", lambda *a, **k: 2.0)   # le run a vidé le compte
    server._SOLDE_CACHE.update(t=0.0, v=None)
    _attendre_job(c, jid)
    import time
    for _ in range(100):
        if partis:
            break
        time.sleep(0.02)
    assert len(partis) == 1


def test_le_worker_verifie_aussi_le_solde_apres_un_job(monkeypatch, tmp_path):
    import worker
    from jobs import JobStore
    server, partis = _serveur(monkeypatch, tmp_path, solde=1.5)
    store = JobStore(tmp_path / "jobs.db")
    store.create("scout", {"n_search": 1}, user_id="u")
    monkeypatch.setattr(worker, "_RUNNERS", {"scout": lambda params, progress, cost, uid: []})
    monkeypatch.setattr(worker, "_imputer", lambda *a, **k: None)
    worker.executer_un_job(store)
    assert len(partis) == 1


def test_la_production_previent_qu_aucun_destinataire_n_est_defini(monkeypatch, caplog):
    import logging
    import server
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("BASE_URL", "https://niches.example.test")
    monkeypatch.delenv("ALERTE_SOLDE_EMAIL", raising=False)
    with caplog.at_level(logging.WARNING, logger="ia-niches"):
        server._verifier_courriel_prod()
    assert any("ALERTE_SOLDE_EMAIL" in r.getMessage() for r in caplog.records)


def test_le_serveur_s_importe_en_production_correctement_configuree(tmp_path):
    """Le garde de démarrage s'exécute À L'IMPORT : une fonction qu'il appelle et qui serait définie
    plus bas dans le fichier lèverait un NameError, et seulement en production — là où aucun test
    d'une fonction isolée ne le verrait (cela a failli arriver le 2026-10-15)."""
    import subprocess
    import sys
    from pathlib import Path
    racine = Path(__file__).resolve().parent.parent
    env = {"PATH": __import__("os").environ.get("PATH", ""), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
           "APP_ENV": "prod", "BSR_SOURCE": "dataforseo", "DATA_DIR": str(tmp_path),
           "SMTP_HOST": "smtp.example.test", "BASE_URL": "https://niches.example.test",
           "ANTHROPIC_API_KEY": "", "DATAFORSEO_LOGIN": "", "DATAFORSEO_PASSWORD": ""}
    r = subprocess.run([sys.executable, "-c",
                        "import sys; sys.path[:0] = ['web', '01-scripts']; import server; print('importe')"],
                       cwd=racine, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "importe" in r.stdout, r.stderr[-800:]
