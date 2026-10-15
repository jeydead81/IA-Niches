"""Ce que la revue adversariale de l'essai gratuit a trouvé (2026-10-15, 41 agents, 17 constats confirmés).

Chaque test ci-dessous ferme un défaut REPRODUIT par un agent, puis réfuté sans succès par un autre. Le plus
grave tenait en une phrase : **les 4 analyses détaillées d'un essai ne passaient par aucune des gardes du
démarrage** — alias de boîte, adresse jetable, réseau, plafond du jour. Une seule boîte Gmail et ses alias `+n`
faisaient 120 verdicts payés ; fermer le compte puis le rouvrir remettait le compteur à zéro. La promesse
« le plafond du jour est la seule garde qu'un fraudeur ne contourne pas » était FAUSSE pour ces appels.

Règle qui en sort : **aucune dépense d'un compte d'essai n'a lieu avant que l'essai ait DÉMARRÉ** — et il
ne démarre que par une recherche, seul endroit où l'identité, le domaine, le réseau et le plafond du jour
sont jugés. Les analyses détaillées partent d'une carte, donc d'une recherche : l'exiger ne coûte rien à
un visiteur honnête.
"""
import logging

import pytest

import essai
from tests.conftest import MDP_TEST, ouvrir_session
from tests.test_auth_essai import JOUR, magasin, ouvrir
from tests.test_server_essai import _essai, _instance, _lancer, _proprietaire, _runner, _situation


# ── 1. Les analyses détaillées exigent un essai DÉMARRÉ ─────────────────────────────────

def _refuse(server, uid):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        server._verifier_plafond(uid)
    return e.value


def test_sans_recherche_aucune_analyse_detaillee(tmp_path, monkeypatch):
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    uid = _essai(client, monkeypatch)
    e = _refuse(server, uid)
    assert e.status_code == 403 and "recherche" in e.detail.lower() and "Rien n'a été dépensé" in e.detail
    _lancer(client, server, monkeypatch)                  # l'essai démarre, ses gardes sont passées
    server._verifier_plafond(uid)


def test_alias_jetable_et_robinet_ferme_n_ouvrent_pas_les_analyses_detaillees(tmp_path, monkeypatch):
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    _essai(client, monkeypatch, "jean@gmail.com")
    _lancer(client, server, monkeypatch)                                   # démarre : c'est la boîte de jean
    for adresse in ("jean+2@gmail.com", "j.e.a.n@gmail.com", "x@mailinator.com"):
        uid = _essai(client, monkeypatch, adresse)
        assert _refuse(server, uid).status_code == 403, adresse
    monkeypatch.setenv("ESSAIS_PAR_JOUR_MAX", "0")                         # robinet fermé : aucun nouvel essai
    uid = _essai(client, monkeypatch, "autre@gmail.com")
    assert _lancer(client, server, monkeypatch, attendre=False).status_code == 429
    assert _refuse(server, uid).status_code == 403


def test_fermer_son_compte_ne_redonne_pas_les_analyses_detaillees(tmp_path, monkeypatch):
    """`supprimer_compte` efface la consommation : sans la mémoire des essais, « fermer puis rouvrir avec la
    même adresse » donnait 4 appels payants de plus à chaque cycle (20 pour une adresse, 5 cycles)."""
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    uid = _essai(client, monkeypatch, "jean@gmail.com")
    _lancer(client, server, monkeypatch)
    server.UserStore(server._USERS_DB).supprimer_compte("jean@gmail.com", MDP_TEST)
    server.UsageMeter(server._USAGE_DB).supprimer_utilisateur(uid)
    neuf = _essai(client, monkeypatch, "jean@gmail.com")
    assert _refuse(server, neuf).status_code == 403
    assert _lancer(client, server, monkeypatch, attendre=False).status_code == 403


def test_un_abonne_n_est_pas_limite_comme_un_essai(tmp_path, monkeypatch):
    """Le plan « abonne » (posé plus tard par le paiement) n'est ni limité à 5 niches ni à 4 appels."""
    from usage import UsageMeter
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    uid = _essai(client, monkeypatch)
    server.UserStore(server._USERS_DB).definir_plan(uid, essai.PLAN_ABONNE)
    for _ in range(3):
        assert _lancer(client, server, monkeypatch, n_search=6).status_code == 202
    for _ in range(essai.ESSAI_APPELS_A_LA_PIECE + 3):
        UsageMeter(server._USAGE_DB).reserver(uid, "verdict")
    server._verifier_plafond(uid)
    assert client.get("/api/usage").json()["essai"] is None


# ── 2. Un domaine, et non un hôte ───────────────────────────────────────────────────────

@pytest.mark.parametrize("brut, attendu", [
    ("x1.mondomaine.fr", "mondomaine.fr"),
    ("a.b.c.mondomaine.fr", "mondomaine.fr"),
    ("mondomaine.fr", "mondomaine.fr"),
    ("x.maboite.co.uk", "maboite.co.uk"),             # suffixe à deux niveaux : on garde un label de plus
    ("maboite.co.uk", "maboite.co.uk"),
    ("co.uk", "co.uk"),
    ("x.asso.fr", "x.asso.fr"),                       # asso.fr est un suffixe public : chaque asso est un domaine
    ("localhost", "localhost"),
    ("", ""),
])
def test_domaine_enregistrable(brut, attendu):
    assert essai.domaine_enregistrable(brut) == attendu


def test_des_sous_domaines_d_un_meme_domaine_comptent_pour_un_seul(tmp_path):
    """Un seul domaine acheté avec un MX joker donnait des « domaines » à 0 essai en nombre illimité."""
    s, _ = magasin(tmp_path)
    for i in range(essai.ESSAI_PAR_DOMAINE):
        c = ouvrir(s, f"u@x{i}.mondomaine.fr")
        assert s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=50).demarre_ici
    dernier = ouvrir(s, "u@x99.mondomaine.fr")
    with pytest.raises(essai.EssaiRefuse):
        s.reserver_recherche_essai(dernier.user_id, client=None, par_jour_max=50)


def test_deux_domaines_co_uk_distincts_ne_sont_pas_confondus(tmp_path):
    s, _ = magasin(tmp_path)
    for i in range(essai.ESSAI_PAR_DOMAINE + 2):
        c = ouvrir(s, f"u@boite{i}.co.uk")
        assert s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=50).demarre_ici


def test_un_fournisseur_courant_reste_exempte_meme_via_un_sous_domaine_inexistant(tmp_path):
    s, _ = magasin(tmp_path)
    for i in range(essai.ESSAI_PAR_DOMAINE + 2):
        c = ouvrir(s, f"p{i}@gmail.com")
        assert s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=50).demarre_ici


# ── 3. Le point final d'un nom de domaine ───────────────────────────────────────────────

def test_un_point_final_ne_fait_pas_changer_de_domaine():
    """`x@mailinator.com.` est la même adresse que `x@mailinator.com` pour un résolveur DNS."""
    assert essai.est_jetable("mailinator.com.") and essai.est_jetable("sous.mailinator.com..")
    assert essai.est_courant("gmail.com.")
    assert essai.domaine("Jean@Gmail.COM.") == "gmail.com"
    assert essai.identite_courriel("jean@gmail.com.") == essai.identite_courriel("jean@gmail.com")
    assert essai.domaine_enregistrable("x.mondomaine.fr.") == "mondomaine.fr"


def test_les_suffixes_a_deux_niveaux_sont_un_fichier_de_donnees():
    suffixes = essai.charger_liste(essai.FICHIER_SUFFIXES)
    assert {"co.uk", "com.au", "asso.fr", "gouv.fr"} <= suffixes
    assert all(s.count(".") == 1 and s == s.lower() for s in suffixes)


# ── 4. Le plafond d'inscription par poste suit le /64 ───────────────────────────────────

def test_le_plafond_d_inscription_replie_ipv6_au_64(tmp_path, monkeypatch):
    """Un abonné IPv6 reçoit un /64 entier : sans repli, 40 adresses d'un même /64 ouvraient 40 comptes
    quand l'IPv4 en refusait 4 sur 14."""
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    monkeypatch.setenv("INSCRIPTIONS_OUVERTES", "1")
    adresses = iter(f"2a01:e0a:1:2:{i:x}::1" for i in range(1, 60))
    monkeypatch.setattr(server, "_client_distant", lambda request: next(adresses))
    codes = [client.post("/api/auth/inscription",
                         json={"email": f"p{i}@gmail.com", "mot_de_passe": MDP_TEST}).status_code
             for i in range(14)]
    assert codes.count(201) == server.MAX_INSCRIPTIONS_PAR_CLIENT and 429 in codes


# ── 5. Ce qui gonflait le prompt d'une analyse gratuite ─────────────────────────────────

def test_un_corps_enorme_est_refuse_avant_tout_appel(tmp_path, monkeypatch):
    """Une niche de 1 Mo faisait un prompt de 2 Mo (×700) : 0,49 $ pour 4 verdicts au lieu de 0,146 $."""
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    r = client.post("/api/verdict", json={"niche": "x" * (server.MAX_CORPS_JSON + 10)})
    assert r.status_code == 413
    # la plus grande carte réelle mesurée (fiction) fait 50 Ko : elle passe largement sous la borne
    assert server.MAX_CORPS_JSON >= 4 * 50_000
    assert client.post("/api/verdict", json={"niche": "x" * 50_000}).status_code != 413


def test_un_corps_sans_content_length_est_borne_lui_aussi(tmp_path, monkeypatch):
    """Un transfert par morceaux n'annonce aucune taille : la borne ne peut pas reposer sur l'en-tête seul."""
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)

    def flux():
        yield b'{"niche": "'
        for _ in range(4):
            yield b"x" * 100_000
        yield b'"}'

    r = client.post("/api/verdict", content=flux(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_un_rayon_inconnu_est_refuse_en_fiction(tmp_path, monkeypatch):
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    sg = sorted(server.load_taxonomy()["sous_genres"])[0]
    r = client.post("/api/jobs", json={"type": "fiction", "sous_genre": sg, "n_niches": 3,
                                       "rayon": "x" * 100_000})
    assert r.status_code == 400 and "rayon" in r.json()["detail"].lower()


def test_des_tropes_repetes_ne_gonflent_pas_les_contraintes(tmp_path, monkeypatch):
    client, server = _instance(monkeypatch, tmp_path)
    sg = sorted(server.load_taxonomy()["sous_genres"])[0]
    un_trope = sorted(server.valid_keys(sg)[0])[0]
    c = server._contraintes_fiction(sg, [un_trope] * 5000, None, None)
    assert c.tropes == [un_trope]


# ── 6. Un lancement qui n'aboutit pas rend TOUT ─────────────────────────────────────────

def test_un_travail_non_cree_rend_la_recherche_le_demarrage_et_les_niches(tmp_path, monkeypatch):
    """`JobStore.create` levait APRÈS les deux réservations : 500, et la recherche d'essai, le démarrage et
    cinq niches restaient pris sans qu'aucun travail n'existe. Déclenchable par un texte contenant un
    substitut Unicode isolé (JSON valide), donc par l'utilisateur lui-même."""
    from fastapi.testclient import TestClient
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    _essai(client, monkeypatch)
    tolerant = TestClient(server.app, raise_server_exceptions=False)
    tolerant.cookies.update(client.cookies)
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", _runner())

    def casse(*a, **k):
        raise OSError("disque plein")
    monkeypatch.setattr(server.JobStore, "create", casse)
    assert tolerant.post("/api/jobs", json={"type": "scout", "n_search": 5}).status_code == 500
    s = _situation(client)
    assert s["recherches_restantes"] == 2 and s["demarre"] is False
    assert client.get("/api/usage").json()["n_niches"] == 0


def test_le_remboursement_d_un_lancement_rate_ne_double_pas_la_recherche(tmp_path, monkeypatch):
    """Piège relevé par la réfutation : rembourser par `_regler_niches` PUIS par `_rendre_essai` rendait la
    recherche deux fois — et le déclencheur (le substitut isolé) est contrôlable par l'utilisateur, donc des
    recherches gratuites en boucle."""
    from fastapi.testclient import TestClient
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    _essai(client, monkeypatch)
    assert _lancer(client, server, monkeypatch).status_code == 202            # 1 recherche prise et gardée
    assert _situation(client)["recherches_restantes"] == 1
    tolerant = TestClient(server.app, raise_server_exceptions=False)
    tolerant.cookies.update(client.cookies)
    reel = server.JobStore.create
    monkeypatch.setattr(server.JobStore, "create", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert tolerant.post("/api/jobs", json={"type": "scout", "n_search": 5}).status_code == 500
    monkeypatch.setattr(server.JobStore, "create", reel)
    assert _situation(client)["recherches_restantes"] == 1                     # la première reste prise


# ── 7. Annuler en mode worker : un seul remboursement ───────────────────────────────────

def test_annuler_pendant_que_le_worker_prend_le_travail_ne_rembourse_qu_une_fois(tmp_path, monkeypatch):
    """`annuler_job` décidait du remboursement sur un statut lu AVANT l'annulation. Si le worker prend le travail
    entre les deux, le serveur ET le worker remboursaient : niches et recherche d'essai en trop."""
    monkeypatch.setenv("JOBS_MODE", "worker")
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    uid = _essai(client, monkeypatch)
    magasin_essai = server.UserStore(server._USERS_DB)
    magasin_essai.reserver_recherche_essai(uid, client=None, par_jour_max=50)   # une recherche déjà gardée
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", _runner())
    r = client.post("/api/jobs", json={"type": "scout", "n_search": 5})
    assert r.status_code == 202
    job_id = r.json()["id"]
    assert magasin_essai.situation_essai(uid)["recherches_restantes"] == 0

    vrai_get = server.JobStore.get
    pris = []

    def get_puis_le_worker_prend_le_travail(self, jid):
        job = vrai_get(self, jid)
        pris.append(server.JobStore(server._JOBS_DB).claim_next())   # le worker passe pendant l'annulation
        return job

    monkeypatch.setattr(server.JobStore, "get", get_puis_le_worker_prend_le_travail)
    assert client.post(f"/api/jobs/{job_id}/annuler").status_code == 204
    monkeypatch.setattr(server.JobStore, "get", vrai_get)
    # Si le worker a réellement pris le travail, il le règle LUI-MÊME (coût nul : tout est rendu). Quel que soit
    # l'ordre, UN seul des deux rembourse.
    for job in pris:
        if job is not None:
            server._regler_niches(uid, "scout", {"n_search": 5}, "annule", 0.0)
    assert magasin_essai.situation_essai(uid)["recherches_restantes"] == 1
    assert client.get("/api/usage").json()["n_niches"] == 0


def test_annuler_un_travail_deja_pris_par_le_worker_laisse_le_remboursement_au_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBS_MODE", "worker")
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    uid = _essai(client, monkeypatch)
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", _runner())
    job_id = client.post("/api/jobs", json={"type": "scout", "n_search": 5}).json()["id"]
    assert server.JobStore(server._JOBS_DB).claim_next() is not None        # le worker a pris le travail
    assert client.post(f"/api/jobs/{job_id}/annuler").status_code == 204
    assert client.get("/api/usage").json()["n_niches"] == 5                 # rien rendu par le serveur
    assert _situation(client)["recherches_restantes"] == 1
    server._regler_niches(uid, "scout", {"n_search": 5}, "annule", 0.0)     # le worker règle
    assert client.get("/api/usage").json()["n_niches"] == 0
    assert _situation(client)["recherches_restantes"] == 2


def test_annuler_un_travail_en_attente_est_rembourse_par_le_serveur_une_fois(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBS_MODE", "worker")
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    _essai(client, monkeypatch)
    monkeypatch.setitem(server._JOB_RUNNERS, "scout", _runner())
    job_id = client.post("/api/jobs", json={"type": "scout", "n_search": 5}).json()["id"]
    assert client.post(f"/api/jobs/{job_id}/annuler").status_code == 204
    assert server.JobStore(server._JOBS_DB).claim_next() is None            # personne ne le reprendra
    assert client.get("/api/usage").json()["n_niches"] == 0
    assert _situation(client)["recherches_restantes"] == 2


# ── 8. L'écran dit les analyses détaillées restantes ────────────────────────────────────

def test_usage_compte_les_analyses_detaillees_restantes(tmp_path, monkeypatch):
    from usage import UsageMeter
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    uid = _essai(client, monkeypatch)
    assert client.get("/api/usage").json()["essai"]["analyses_detaillees_restantes"] == 4
    UsageMeter(server._USAGE_DB).reserver(uid, "verdict")
    UsageMeter(server._USAGE_DB).reserver(uid, "kdp_keywords")
    assert client.get("/api/usage").json()["essai"]["analyses_detaillees_restantes"] == 2


def test_l_ecran_affiche_les_analyses_detaillees_restantes():
    from tests.js_harness import appeler_json
    base = {"recherches_restantes": 2, "recherches_max": 2, "niches_par_recherche": 5,
            "analyses_detaillees_max": 4, "demarre": True}
    l = appeler_json("libelleUsage", {"plan": "essai", "essai": {**base, "analyses_detaillees_restantes": 3}})
    assert "<strong>3</strong>" in l["barre"] and "détaillée" in l["barre"]
    l = appeler_json("libelleUsage", {"plan": "essai", "essai": {**base, "analyses_detaillees_restantes": 0}})
    assert "<strong>0</strong>" in l["barre"]
    l = appeler_json("libelleUsage", {"plan": "essai", "essai": base})            # champ absent : rien d'inventé
    assert "détaillée" not in l["barre"] and "NaN" not in l["barre"] and "undefined" not in l["barre"]


def test_le_compteur_est_rafraichi_apres_chaque_analyse_detaillee():
    """Sans cela le reste affiché restait figé jusqu'à la fin de la recherche suivante."""
    import re
    from pathlib import Path
    html = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text(encoding="utf-8")
    for url in ("'/api/verdict", "'/api/kdp-keywords"):
        sites = [m.start() for m in re.finditer(re.escape(url), html)]
        assert sites, url
        assert all("chargerUsage()" in html[s:s + 2500] for s in sites), url


# ── 9. Les seuils sont épinglés, pas seulement bouclés ──────────────────────────────────

def test_les_seuils_de_l_offre_sont_epingles_en_litteraux():
    """Les tests de boucle (`range(essai.ESSAI_PAR_DOMAINE)`) suivent la constante mutée : 7 mutations
    survivaient, dont le plafond du jour réduit à 60 s."""
    assert essai.ESSAI_PAR_RESEAU == 3 and essai.ESSAI_PAR_DOMAINE == 3
    assert essai.FENETRE_ESSAI_S == 30 * 24 * 3600
    assert essai.FENETRE_JOUR_S == 24 * 3600
    assert essai.CONSERVATION_IDENTITE_S == 365 * 24 * 3600
    assert essai.ESSAIS_PAR_JOUR_DEFAUT == 20
    assert essai.FENETRE_APPELS_ESSAI_S >= 5 * 365 * 24 * 3600


def test_les_fenetres_se_ferment_a_la_bonne_date(tmp_path):
    s, h = magasin(tmp_path)
    # réseau et domaine : encore refusé à +29 j, accepté à +31 j
    pris = [ouvrir(s, f"a{i}@mon-site.fr") for i in range(essai.ESSAI_PAR_DOMAINE)]
    for c in pris:
        s.reserver_recherche_essai(c.user_id, client="8.8.8.8", par_jour_max=50)
    h[0] += 29 * JOUR
    x = ouvrir(s, "x@mon-site.fr")
    with pytest.raises(essai.EssaiRefuse):
        s.reserver_recherche_essai(x.user_id, client=None, par_jour_max=50)       # domaine
    y = ouvrir(s, "y@gmail.com")
    with pytest.raises(essai.EssaiRefuse):
        s.reserver_recherche_essai(y.user_id, client="8.8.8.8", par_jour_max=50)  # réseau
    h[0] += 2 * JOUR
    assert s.reserver_recherche_essai(x.user_id, client=None, par_jour_max=50).demarre_ici
    assert s.reserver_recherche_essai(y.user_id, client="8.8.8.8", par_jour_max=50).demarre_ici


def test_le_plafond_du_jour_se_ferme_a_vingt_quatre_heures_pile(tmp_path):
    s, h = magasin(tmp_path)
    a, b = ouvrir(s, "a@gmail.com"), ouvrir(s, "b@gmail.com")
    s.reserver_recherche_essai(a.user_id, client=None, par_jour_max=1)
    h[0] += JOUR - 60
    with pytest.raises(essai.QuotaJournalier):
        s.reserver_recherche_essai(b.user_id, client=None, par_jour_max=1)
    h[0] += 120
    assert s.reserver_recherche_essai(b.user_id, client=None, par_jour_max=1).demarre_ici


def test_les_analyses_detaillees_de_l_essai_ne_se_renouvellent_pas_au_bout_d_un_mois(tmp_path, monkeypatch):
    from usage import UsageMeter
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    uid = _essai(client, monkeypatch)
    _lancer(client, server, monkeypatch)
    horloge = [1_700_000_000.0]
    meter = UsageMeter(server._USAGE_DB, now=lambda: horloge[0])
    for _ in range(essai.ESSAI_APPELS_A_LA_PIECE):
        meter.reserver(uid, "verdict")
    monkeypatch.setattr(server, "UsageMeter", lambda path, **k: UsageMeter(path, now=lambda: horloge[0] + 40 * JOUR))
    assert _refuse(server, uid).status_code == 429               # +40 jours : toujours épuisées


# ── 10. Magasin : plan, empreintes, avertissement de proxy, ordre des gardes ────────────

def test_definir_plan_valide_et_ne_touche_pas_aux_compteurs(tmp_path):
    s, _ = magasin(tmp_path)
    c = ouvrir(s, "a@gmail.com")
    s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=50)
    s.definir_plan(c.user_id, essai.PLAN_ABONNE)
    assert s.plan_de(c.user_id) == "abonne" and s.situation_essai(c.user_id) is None
    s.definir_plan(c.user_id, essai.PLAN_ESSAI)
    assert s.situation_essai(c.user_id)["recherches_restantes"] == 1
    with pytest.raises(ValueError):
        s.definir_plan(c.user_id, "gratuit-a-vie")


def test_en_production_un_reseau_prive_est_signale_une_seule_fois(tmp_path, monkeypatch, caplog):
    client, server = _instance(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "_verification_obligatoire", lambda: True)
    monkeypatch.setattr(server, "_client_distant", lambda request: "10.0.0.7")
    server._RESEAU_ESSAI_AVERTI[0] = False
    with caplog.at_level(logging.WARNING, logger="ia-niches"):
        server._reseau_pour_essai(object())
        server._reseau_pour_essai(object())
    assert sum("FORWARDED_ALLOW_IPS" in r.getMessage() for r in caplog.records) == 1
    server._RESEAU_ESSAI_AVERTI[0] = False


def test_hors_production_un_reseau_prive_ne_dit_rien(tmp_path, monkeypatch, caplog):
    client, server = _instance(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "_client_distant", lambda request: "127.0.0.1")
    server._RESEAU_ESSAI_AVERTI[0] = False
    with caplog.at_level(logging.WARNING, logger="ia-niches"):
        server._reseau_pour_essai(object())
    assert not any("FORWARDED_ALLOW_IPS" in r.getMessage() for r in caplog.records)


def test_le_volume_est_refuse_avant_de_regarder_le_solde(tmp_path, monkeypatch):
    """Une 400 de saisie n'est pas un diagnostic de service : un fournisseur à sec ne la masque pas."""
    client, server = _instance(monkeypatch, tmp_path)
    _proprietaire(client)
    _essai(client, monkeypatch)
    monkeypatch.setattr(server, "_lire_solde", lambda frais=False: 0.0)
    assert client.post("/api/jobs", json={"type": "scout", "n_search": 6}).status_code == 400


def test_le_message_de_refus_ne_pretend_pas_qu_un_essai_a_ete_utilise(tmp_path, monkeypatch):
    """Faux pour une adresse jetable (aucun essai n'a été utilisé) : la cause n'est pas détaillée."""
    client, server = _instance(monkeypatch, tmp_path)
    assert "déjà" not in server.MSG_ESSAI_REFUSE and "Rien n'a été lancé" in server.MSG_ESSAI_REFUSE


# ── 11. Minimisation : le réseau et le domaine ne servent que 30 jours ──────────────────

def test_l_empreinte_du_reseau_et_du_domaine_est_effacee_apres_30_jours_pas_l_identite(tmp_path):
    """Seule la fenêtre de 30 jours lit le réseau et le domaine ; les garder un an (durée de l'identité) serait
    conserver une donnée personnelle sans usage. L'identité, elle, reste un an : c'est elle qui interdit un
    second essai à la même boîte."""
    import sqlite3
    s, h = magasin(tmp_path)
    a = ouvrir(s, "jean@mon-site.fr")
    s.reserver_recherche_essai(a.user_id, client="8.8.8.8", par_jour_max=50)
    h[0] += 31 * JOUR
    b = ouvrir(s, "autre@gmail.com")
    s.reserver_recherche_essai(b.user_id, client=None, par_jour_max=50)       # un départ déclenche la purge
    with sqlite3.connect(s.path) as cx:
        lignes = cx.execute("SELECT identite, domaine, reseau FROM essais ORDER BY id").fetchall()
    assert lignes[0][0] != "" and lignes[0][1] == "" and lignes[0][2] is None       # l'ancien : identité seule
    assert lignes[1][1] != ""                                                         # le récent : tout est là
    c = ouvrir(s, "jean+2@mon-site.fr")
    with pytest.raises(essai.EssaiRefuse):                                            # l'identité tient toujours
        s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=50)
