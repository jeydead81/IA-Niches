"""Prévenir l'auteur quand son analyse est finie, sans jamais la lui envoyer.

Un run dure de deux à douze minutes. L'interface le reprend au rechargement, mais elle ne
peut rien faire quand l'onglet est fermé — et c'est justement ce qu'on lui a dit de faire.
Le message de fin est la seule chose qui traverse l'absence.

Quatre règles, dans l'ordre de ce qu'elles coûteraient si on les cassait :

1. **Un échec d'envoi ne fait jamais échouer un run.** Le run a coûté de l'argent réel et
   son résultat est en base. Le marquer « en échec » parce qu'un serveur SMTP a refusé la
   connexion effacerait de l'écran un travail payé et réussi (§5.29).
2. **Aucun résultat dans le corps du message.** L'e-mail est un canal en clair, relayé,
   archivé, indexé chez le fournisseur. Les niches trouvées sont ce que l'auteur a payé
   pour être seul à savoir ; les recopier dans un e-mail les publie chez un tiers.
3. **Aucun secret dans les journaux.** Le mot de passe SMTP est lu du `.env` et n'apparaît
   ni dans un log, ni dans une exception remontée (règle 6).
4. **Éteint par défaut.** Rien n'est envoyé tant que `NOTIFICATIONS_EMAIL` n'est pas posé
   ET qu'un hôte SMTP n'est pas configuré. Une configuration à moitié faite n'envoie pas
   « au mieux » : elle n'envoie pas.
"""
import pytest

from notification import (Notificateur, config_smtp, corps_fin_de_job,
                          notifier_fin_de_job)


class _FauxSMTP:
    """Capture ce qui part, sans jamais ouvrir de socket."""

    def __init__(self):
        self.envois = []
        self.starttls_appele = False
        self.identifiants = None

    def __call__(self, hote, port, timeout=None):
        self.hote, self.port, self.timeout = hote, port, timeout
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, *a, **kw):
        self.starttls_appele = True

    def login(self, user, mdp):
        self.identifiants = (user, mdp)

    def send_message(self, msg):
        self.envois.append(msg)


def _env(monkeypatch, **kw):
    for c in ("NOTIFICATIONS_EMAIL", "SMTP_HOST", "SMTP_PORT", "SMTP_USER",
              "SMTP_PASSWORD", "SMTP_FROM", "SMTP_TLS", "BASE_URL"):
        monkeypatch.delenv(c, raising=False)
    for c, v in kw.items():
        monkeypatch.setenv(c, v)


def _configure(monkeypatch, **extra):
    _env(monkeypatch, NOTIFICATIONS_EMAIL="1", SMTP_HOST="smtp.exemple.fr",
         SMTP_USER="envoi@exemple.fr", SMTP_PASSWORD="s3cr3t",
         SMTP_FROM="IA-Niches <envoi@exemple.fr>", **extra)


# ── Éteint par défaut ──────────────────────────────────────────────────────────

def test_sans_configuration_rien_n_est_envoye(monkeypatch):
    _env(monkeypatch)
    assert config_smtp() is None


def test_un_hote_sans_le_drapeau_n_envoie_RIEN(monkeypatch):
    """Poser un hôte SMTP dans le `.env` n'est pas consentir à écrire aux utilisateurs.
    Les deux conditions sont exigées."""
    _env(monkeypatch, SMTP_HOST="smtp.exemple.fr")
    assert config_smtp() is None


def test_le_drapeau_sans_hote_n_envoie_RIEN(monkeypatch):
    """Une configuration à moitié faite n'envoie pas « au mieux » : elle n'envoie pas.
    Sinon l'exploitant croit avoir activé les messages et personne ne les reçoit."""
    _env(monkeypatch, NOTIFICATIONS_EMAIL="1")
    assert config_smtp() is None


def test_configuree_elle_porte_ses_valeurs(monkeypatch):
    _configure(monkeypatch)
    c = config_smtp()
    assert c.hote == "smtp.exemple.fr" and c.port == 587 and c.tls is True


def test_un_port_non_entier_retombe_sur_le_defaut(monkeypatch):
    """Même discipline que `PORT` et `DATAFORSEO_PRIORITY` : une valeur illisible ne doit
    pas empêcher le service de démarrer."""
    _configure(monkeypatch, SMTP_PORT="oui")
    assert config_smtp().port == 587


# ── Le corps du message ────────────────────────────────────────────────────────

def test_le_corps_ne_contient_AUCUN_resultat():
    """LE test. L'e-mail traverse des relais, des archives et l'indexation du
    fournisseur. Les niches trouvées sont exactement ce que l'auteur a payé pour être
    seul à savoir."""
    sujet, corps = corps_fin_de_job(
        type_="scout", statut="termine", job_id="abc123",
        base_url="https://exemple.fr",
        resultat=[{"niche": "carnet de suivi glycémie", "global_score": 8.4}])
    texte = (sujet + corps).lower()
    assert "glyc" not in texte and "8.4" not in texte and "8,4" not in texte


def test_le_corps_ne_contient_AUCUN_montant():
    """Même règle qu'à l'écran (§5.27) : le coût est mesuré et jamais montré au client."""
    sujet, corps = corps_fin_de_job(type_="scout", statut="termine", job_id="abc",
                                    base_url="https://exemple.fr", cout_usd=0.084)
    assert "0.084" not in corps and "0,084" not in corps and "$" not in corps


def test_le_corps_renvoie_vers_l_application():
    _, corps = corps_fin_de_job(type_="scout", statut="termine", job_id="abc",
                                base_url="https://exemple.fr")
    assert "https://exemple.fr" in corps


def test_sans_base_url_le_message_reste_utile():
    """Rien dans le code ne connaît le nom de domaine : il n'y a pas de déploiement. Le
    message doit rester envoyable sans lien plutôt que d'annoncer un lien mort."""
    _, corps = corps_fin_de_job(type_="scout", statut="termine", job_id="abc",
                                base_url=None)
    assert "http" not in corps and corps.strip()


def test_un_echec_le_DIT_sans_recopier_l_exception():
    """Le message d'erreur interne peut porter les identifiants DataForSEO — c'est la
    raison d'être de `_erreur_publique`. Un e-mail les diffuserait hors du service."""
    sujet, corps = corps_fin_de_job(
        type_="scout", statut="echec", job_id="abc", base_url=None,
        erreur="401 Unauthorized for user=LOGIN password=MOTDEPASSE")
    assert "MOTDEPASSE" not in corps and "LOGIN" not in corps
    assert "401" not in corps and "Unauthorized" not in corps
    # Le mot importe moins que le fait : le sujet doit se distinguer de celui d'un
    # succès, sinon l'auteur ouvre l'analyse en croyant qu'elle est complète.
    reussi, _ = corps_fin_de_job(type_="scout", statut="termine", job_id="abc",
                                 base_url=None)
    assert sujet != reussi
    assert "interrompue" in (sujet + corps).lower()


def test_le_sujet_distingue_les_trois_moteurs():
    sujets = {corps_fin_de_job(type_=t, statut="termine", job_id="a", base_url=None)[0]
              for t in ("scout", "fiction", "lowcontent")}
    assert len(sujets) == 3


# ── L'envoi ────────────────────────────────────────────────────────────────────

def test_l_envoi_passe_par_starttls_et_s_authentifie(monkeypatch):
    _configure(monkeypatch)
    faux = _FauxSMTP()
    Notificateur(smtp_factory=faux).envoyer("auteur@exemple.fr", "Sujet", "Corps")
    assert faux.starttls_appele is True
    assert faux.identifiants == ("envoi@exemple.fr", "s3cr3t")
    assert len(faux.envois) == 1
    assert faux.envois[0]["To"] == "auteur@exemple.fr"


def test_sans_destinataire_rien_ne_part(monkeypatch):
    _configure(monkeypatch)
    faux = _FauxSMTP()
    assert Notificateur(smtp_factory=faux).envoyer("", "S", "C") is False
    assert faux.envois == []


def test_un_serveur_qui_refuse_ne_LEVE_pas(monkeypatch):
    """Invariant §5.29 côté notification."""
    _configure(monkeypatch)

    def tombe(*a, **kw):
        raise OSError("connexion refusée")

    assert Notificateur(smtp_factory=tombe).envoyer("a@b.fr", "S", "C") is False


def test_le_mot_de_passe_n_apparait_dans_AUCUN_journal(monkeypatch):
    """Règle 6. Un échec SMTP est journalisé ; l'exception d'une bibliothèque peut porter
    la ligne d'authentification entière."""
    _configure(monkeypatch)
    lignes = []

    def tombe(*a, **kw):
        raise OSError("535 auth failed for envoi@exemple.fr password s3cr3t")

    Notificateur(smtp_factory=tombe, journal=lignes.append).envoyer("a@b.fr", "S", "C")
    assert lignes and all("s3cr3t" not in l for l in lignes)


# ── Le point d'appel, partagé par les deux chemins d'exécution ─────────────────

def test_notifier_ne_leve_jamais_meme_sans_configuration(monkeypatch):
    """Appelé depuis les deux exécuteurs de job. Une levée ici marquerait « en échec » un
    run payé et réussi."""
    _env(monkeypatch)
    notifier_fin_de_job(email="a@b.fr", type_="scout", statut="termine", job_id="x")


def test_notifier_transmet_le_corps_construit(monkeypatch):
    _configure(monkeypatch, BASE_URL="https://exemple.fr")
    faux = _FauxSMTP()
    notifier_fin_de_job(email="a@b.fr", type_="fiction", statut="termine", job_id="x",
                        notificateur=Notificateur(smtp_factory=faux))
    assert len(faux.envois) == 1
    assert "https://exemple.fr" in faux.envois[0].get_content()
def test_le_serveur_notifie_les_DEUX_issues(tmp_path, monkeypatch):
    """Un run qui réussit ET un run qui échoue doivent tous deux prévenir.

    Le demi-câblage probable est de ne notifier que le succès, et c'est le plus coûteux :
    l'auteur prend l'habitude d'être prévenu quand ça marche, donc l'absence de message
    se lit « toujours en cours » alors que le run est mort depuis dix minutes."""
    from tests.test_server_jobs import _attendre_job, _client_with_isolated_dbs
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    vus = []
    monkeypatch.setattr(server, "_notifier",
                        lambda uid, t, statut, jid, **kw: vus.append(statut))

    monkeypatch.setattr(server, "run_scout",
                        lambda seed=None, progress=None, cost=None, **kw: [])
    r = client.post("/api/jobs", json={"type": "scout", "seed": "ok"})
    _attendre_job(client, r.json()["id"])

    def tombe(seed=None, progress=None, cost=None, **kw):
        raise RuntimeError("fournisseur indisponible")

    monkeypatch.setattr(server, "run_scout", tombe)
    r = client.post("/api/jobs", json={"type": "scout", "seed": "ko"})
    _attendre_job(client, r.json()["id"])

    assert vus == ["termine", "echec"], vus


def test_le_worker_notifie_les_DEUX_issues(tmp_path, monkeypatch):
    """`worker.py` est l'autre exécuteur, choisi par `JOBS_MODE`. Ne brancher la
    notification que sur un des deux la rendrait dépendante d'une variable
    d'environnement — la divergence exacte qui a coûté la suppression des endpoints
    doubles (§7) — et elle serait invisible : rien à l'écran ne distingue « pas de
    message » de « message pas envoyé »."""
    import server
    import worker
    from jobs import JobStore

    store = JobStore(tmp_path / "jobs.db")
    vus = []
    monkeypatch.setattr(server, "_notifier",
                        lambda uid, t, statut, jid, **kw: vus.append(statut))
    monkeypatch.setattr(worker, "_imputer", lambda *a, **kw: None)
    monkeypatch.setitem(worker._RUNNERS, "scout", lambda p, prog, cost, uid: [])
    store.create("scout", {}, user_id="u")
    worker.executer_un_job(store, journal=lambda _m: None)

    def tombe(p, prog, cost, uid):
        raise RuntimeError("fournisseur indisponible")

    monkeypatch.setitem(worker._RUNNERS, "scout", tombe)
    store.create("scout", {}, user_id="u")
    worker.executer_un_job(store, journal=lambda _m: None)

    assert vus == ["termine", "echec"], vus


def test_la_notification_sort_du_creneau_avant_d_envoyer(tmp_path, monkeypatch):
    """Le pool ne tient que `RUNS_SIMULTANES_MAX` créneaux. Notifier à l'intérieur les
    garderait le temps du dialogue SMTP — jusqu'à 20 s de délai d'attente — au frais des
    utilisateurs qui font la queue. Le travail est fini, la place doit être rendue.

    Le run a déjà été marqué terminé en base : notifier après la sortie du créneau ne
    perd rien, l'ordre entre « compté » et « prévenu » n'ayant aucune conséquence
    (contrairement à l'ordre « imputé avant terminé », lui load-bearing)."""
    import contextlib

    from tests.test_server_jobs import _attendre_job, _client_with_isolated_dbs
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    journal = []

    @contextlib.contextmanager
    def creneau_trace():
        journal.append("creneau:entre")
        try:
            yield
        finally:
            journal.append("creneau:sort")

    monkeypatch.setattr(server, "_creneaux", creneau_trace)
    monkeypatch.setattr(server, "_notifier",
                        lambda *a, **kw: journal.append("notifie"))
    monkeypatch.setattr(server, "run_scout",
                        lambda seed=None, progress=None, cost=None, **kw: [])

    r = client.post("/api/jobs", json={"type": "scout", "seed": "s"})
    _attendre_job(client, r.json()["id"])
    assert "notifie" in journal, "aucune notification"
    assert journal.index("creneau:sort") < journal.index("notifie"), \
        f"notification envoyée DANS le créneau : {journal}"
