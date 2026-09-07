"""Ce qu'il faut pour qu'un hébergeur (Railway) sache construire et lancer ce dépôt.

Trois manques, tous silencieux — c'est ce qui les rend dangereux :

1. **Rien ne dit comment construire ni démarrer.** Pas de `requirements.txt` à la racine
   (le nôtre est dans `01-scripts/`), pas de commande de démarrage. Un constructeur
   automatique ne détecte pas un projet Python et échoue à la construction — bruyamment,
   celui-là, mais sans indiquer quoi corriger.

2. **`HOST` vaut `127.0.0.1`.** Dans un conteneur, écouter la boucle locale rend le
   service injoignable de l'extérieur : le déploiement « réussit », les journaux sont
   propres, et rien ne répond. Même raisonnement que `_cookie_securise` : ce qui s'oublie
   doit se DÉDUIRE. `APP_ENV=prod` est déjà la variable qui dit « je suis en exposition »
   (`_verifier_config_prod`), c'est elle qui décide.

3. **Le répertoire des bases est en dur.** Le disque d'un conteneur est éphémère : sans
   volume monté, `comptes.db`, `usage.db`, `history.db`, `jobs.db` et `df-cache.db`
   disparaissent au prochain déploiement. Les clients, la consommation qui porte le
   plafond ET la future facturation, l'antériorité de l'historique, et le cache mutualisé
   qui est l'économie principale du modèle. Perte TOTALE et SILENCIEUSE : le service
   redémarre sur des bases vides et se comporte comme une installation neuve.

Le troisième point est le seul qui détruit des données, donc le seul où l'on refuse de
démarrer plutôt que de déduire un défaut (§6.3 : une absence ne doit jamais se lire comme
une mesure — ici, un répertoire vide ne doit jamais se lire comme « pas encore de client »).
"""
import subprocess
import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RACINE / "web"))


# ── 1. Construction et démarrage ────────────────────────────────────────────────────────

def test_un_requirements_existe_a_la_racine():
    """Les constructeurs automatiques (Nixpacks chez Railway) détectent un projet Python
    en cherchant `requirements.txt` ou `pyproject.toml` À LA RACINE. Le nôtre est dans
    `01-scripts/` : sans fichier racine, la construction ne sait pas quoi installer."""
    assert (_RACINE / "requirements.txt").exists()


def test_le_requirements_racine_ne_duplique_aucune_dependance():
    """Il doit se contenter d'INCLURE celui de `01-scripts/`, jamais recopier des paquets.

    Deux listes de dépendances divergent — c'est le défaut de §5.32 (`BOOK_TTL_S` à 15 j
    d'un côté, 7 j de l'autre, le test surveillant la constante morte). Ici la divergence
    serait pire : la liste installée en PRODUCTION ne serait plus celle qu'on teste."""
    lignes = [l.strip() for l in (_RACINE / "requirements.txt").read_text(
        encoding="utf-8").splitlines()]
    utiles = [l for l in lignes if l and not l.startswith("#")]
    assert utiles == ["-r 01-scripts/requirements.txt"], (
        f"le requirements racine doit UNIQUEMENT inclure celui de 01-scripts/, "
        f"jamais redéclarer un paquet (trouvé : {utiles})")


def test_le_requirements_racine_est_installable():
    """`pip install -r` doit savoir résoudre l'inclusion depuis la racine : un chemin
    relatif se résout par rapport au fichier qui l'écrit, pas au répertoire courant."""
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--dry-run",
                        "--no-deps", "-r", "requirements.txt"],
                       cwd=_RACINE, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr[-2000:]


def test_une_commande_de_demarrage_est_declaree():
    """Sans elle, l'hébergeur devine — et il devine mal sur un dépôt dont le point
    d'entrée n'est ni `main.py` ni `app.py` à la racine."""
    assert (_RACINE / "Procfile").exists()


def test_la_commande_de_demarrage_lance_LE_point_d_entree_du_produit():
    """`python web/server.py`, et pas un second chemin de lancement.

    Le dépôt a déjà payé la leçon (§2.6) : deux chemins pour le même travail, dont un seul
    exercé, divergent. Lancer par `uvicorn server:app` en production alors que tout le
    monde lance `python web/server.py` en local ferait exactement ça — et au passage,
    `HOST` et `PORT`, lus sous `if __name__ == "__main__"`, cesseraient d'être lus."""
    procfile = (_RACINE / "Procfile").read_text(encoding="utf-8")
    assert "web:" in procfile, "un processus « web » doit être déclaré"
    assert "web/server.py" in procfile, (
        "la commande doit lancer web/server.py — le point d'entrée réel du produit, "
        "celui qu'IA-Niches-Web.bat lance aussi")
    assert "uvicorn " not in procfile, (
        "pas d'invocation uvicorn directe : elle court-circuite le __main__ qui lit "
        "HOST et PORT, et crée un second chemin de lancement (§2.6)")


# ── 2. HOST déduit de l'environnement ───────────────────────────────────────────────────

def test_en_local_le_serveur_n_ecoute_que_la_boucle_locale(monkeypatch):
    """Défaut inchangé pour Baptiste : rien de ce dépôt ne doit devenir joignable depuis
    le réseau local parce qu'on a préparé un hébergement."""
    import server
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("HOST", raising=False)
    assert server._hote() == "127.0.0.1"


def test_en_production_le_serveur_ecoute_toutes_les_interfaces(monkeypatch):
    """Dans un conteneur, le routeur de l'hébergeur parle au service depuis l'extérieur
    du processus : écouter 127.0.0.1 rend le déploiement muet, sans la moindre erreur."""
    import server
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("HOST", raising=False)
    assert server._hote() == "0.0.0.0"


def test_un_HOST_explicite_prime_toujours(monkeypatch):
    """La déduction est un défaut, pas une décision imposée — un opérateur qui nomme une
    interface précise doit l'obtenir, y compris en production."""
    import server
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("HOST", "10.0.0.7")
    assert server._hote() == "10.0.0.7"


# ── 3. Répertoire des données ───────────────────────────────────────────────────────────

def test_par_defaut_les_donnees_restent_dans_99_logs(monkeypatch):
    """L'usage local ne bouge pas : `DATA_DIR` absent = le dossier historique du dépôt."""
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    import storage
    assert storage.data_dir() == _RACINE / "99-logs"


def test_DATA_DIR_deplace_les_donnees(tmp_path, monkeypatch):
    """C'est ce qui permet de pointer un volume persistant sans toucher au code."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "volume"))
    import storage
    assert storage.data_dir() == tmp_path / "volume"


def test_le_repertoire_est_cree_s_il_manque(tmp_path, monkeypatch):
    """Un volume fraîchement monté est vide : ne pas créer le dossier ferait échouer la
    première écriture, donc la première inscription, sur une installation neuve."""
    cible = tmp_path / "pas-encore-la"
    monkeypatch.setenv("DATA_DIR", str(cible))
    import storage
    assert storage.data_dir().is_dir()


def test_en_production_DATA_DIR_est_EXIGEE(monkeypatch):
    """LE garde de ce fichier. Sur un disque éphémère, ne rien exiger fait perdre les
    comptes et la consommation à chaque déploiement, SANS AUCUN SIGNAL — le service
    repart sur des bases vides et se comporte comme une installation neuve.

    Refuser de démarrer est la seule issue lisible, exactement comme pour BSR_SOURCE :
    s'en apercevoir au premier client perdu arriverait trop tard."""
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("DATA_DIR", raising=False)
    import storage
    with pytest.raises(RuntimeError) as e:
        storage.data_dir()
    message = str(e.value)
    assert "DATA_DIR" in message
    # Le message doit dire ce qu'on PERD, pas seulement qu'il manque une variable.
    assert "volume" in message.lower()


def test_les_cinq_bases_vivent_dans_le_repertoire_de_donnees(monkeypatch):
    """Les quatre bases du serveur ET le cache doivent suivre `DATA_DIR` ensemble.

    Une seule qui resterait en dur suffirait à perdre exactement ce qu'elle porte, et
    c'est la plus discrète qui ferait le plus de dégâts : `df-cache.db` perdu, c'est
    l'économie du cache mutualisé qui repart de zéro, sans erreur nulle part."""
    import storage
    import server
    attendu = storage.data_dir()
    for attr in ("_JOBS_DB", "_USAGE_DB", "_HISTORY_DB", "_USERS_DB"):
        assert getattr(server, attr).parent == attendu, attr


# ── 4. Travaux interrompus par un redéploiement ─────────────────────────────────────────
#
# En local, un redémarrage du serveur est un événement rare. Sur un hébergeur, c'est le
# cas NOMINAL : chaque `git push` reconstruit et relance le service. Or `recuperer_orphelins`
# n'avait qu'un seul appelant — `worker.boucle()` —, et le mode par défaut est `thread`.
# Sans le worker, un run coupé par un déploiement restait `en_cours` POUR TOUJOURS :
# l'utilisateur voit une analyse éternellement en cours, son unité de plafond est
# consommée, et rien ne le lui dit.

def _store_isole(tmp_path, horloge=None):
    import jobs
    return jobs.JobStore(tmp_path / "jobs.db", now=horloge) if horloge else \
        jobs.JobStore(tmp_path / "jobs.db")


def test_le_serveur_recupere_les_travaux_interrompus_a_son_demarrage(tmp_path, monkeypatch):
    """Le démarrage est le seul moment où l'on SAIT qu'un redémarrage vient d'avoir lieu."""
    import server
    monkeypatch.delenv("JOBS_MODE", raising=False)
    t = [1000.0]
    store = _store_isole(tmp_path, horloge=lambda: t[0])
    jid = store.create("scout", {}, user_id="u1")
    store.start(jid)
    t[0] += 3600                                  # une heure sans le moindre signe de vie
    monkeypatch.setattr(server, "_JOBS_DB", tmp_path / "jobs.db")

    n = server._recuperer_travaux_interrompus(store=store)

    assert n == 1
    job = store.get(jid)
    assert job.statut == "echec"
    assert "interrompue" in job.erreur.lower()


def test_un_run_vivant_n_est_JAMAIS_tue_au_demarrage(tmp_path, monkeypatch):
    """Un run fiction dure 10 à 15 minutes et peut appartenir à une autre instance encore
    vivante. C'est l'ABSENCE DE PROGRESSION qui fait l'orphelin, jamais l'âge : tuer un run
    en cours coûterait l'argent déjà dépensé ET l'analyse que le client attend."""
    import server
    monkeypatch.delenv("JOBS_MODE", raising=False)
    t = [1000.0]
    store = _store_isole(tmp_path, horloge=lambda: t[0])
    jid = store.create("fiction", {}, user_id="u1")
    store.start(jid)
    t[0] += 120
    store.append_progress(jid, "SERP 3/8…")       # il donne signe de vie

    server._recuperer_travaux_interrompus(store=store)

    assert store.get(jid).statut == "en_cours"


def test_en_mode_worker_le_serveur_ne_touche_a_rien(tmp_path, monkeypatch):
    """C'est le worker qui exécute, donc c'est lui qui récupère — il le fait déjà au
    démarrage de sa boucle. Que les deux s'en chargent ferait passer en échec, depuis le
    serveur, un run que le worker vient de reprendre."""
    import server
    monkeypatch.setenv("JOBS_MODE", "worker")
    t = [1000.0]
    store = _store_isole(tmp_path, horloge=lambda: t[0])
    jid = store.create("scout", {}, user_id="u1")
    store.start(jid)
    t[0] += 3600

    assert server._recuperer_travaux_interrompus(store=store) == 0
    assert store.get(jid).statut == "en_cours"


def test_une_base_illisible_ne_bloque_pas_le_demarrage(tmp_path, monkeypatch):
    """Refuser de démarrer parce qu'un vieux travail traîne serait pire que le mal : le
    service entier tomberait pour une ligne de ménage. La récupération est un CONFORT,
    servir les clients est le service (même arbitrage que `_adopter_donnees_locales`)."""
    import server
    monkeypatch.delenv("JOBS_MODE", raising=False)

    class StoreCasse:
        def orphelins(self, depuis_s=0):
            raise OSError("base verrouillée")

    assert server._recuperer_travaux_interrompus(store=StoreCasse()) == 0


def test_le_DEMARRAGE_REEL_du_serveur_declenche_la_recuperation(tmp_path, monkeypatch):
    """Le test qui compte : une fonction correcte branchée sur un hook qui ne se déclenche
    pas, c'est le défaut central de ce dépôt (§5.26, §2.16 — du travail écrit, testé, et
    jamais exécuté). On démarre donc l'application POUR DE VRAI (`with TestClient(...)`,
    qui exécute le cycle de vie) et on regarde le job."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    import server
    from tests.conftest import isoler_bases
    monkeypatch.delenv("JOBS_MODE", raising=False)
    isoler_bases(monkeypatch, server, tmp_path)

    import jobs
    t = [1000.0]
    store = jobs.JobStore(server._JOBS_DB, now=lambda: t[0])
    jid = store.create("scout", {}, user_id="u1")
    store.start(jid)
    t[0] += 3600

    with TestClient(server.app):                  # exécute le cycle de vie de l'app
        pass

    assert store.get(jid).statut == "echec"


def test_une_seule_implementation_de_la_recuperation():
    """`worker.py` importe `server`, donc `server` ne peut pas importer `worker` : la
    tentation serait de recopier les huit lignes. Deux implémentations divergeraient — et
    celle qui divergerait est celle qui ne tourne PAS sur le poste où l'on teste."""
    import jobs
    import worker
    assert worker.recuperer_orphelins is jobs.recuperer_orphelins


def test_aucun_module_ne_construit_le_chemin_d_une_BASE_en_dur():
    """Cliquet, même esprit que `test_launcher.py` : le chemin ne doit exister qu'à UN
    endroit. Il était écrit dans quatre modules ; un cinquième ajouté par distraction ne
    suivrait pas le volume et écrirait sur le disque éphémère.

    Ne surveille QUE les `.db`, délibérément. Les autres fichiers de `99-logs/` sont de
    l'outillage local — le classeur de calibration et son rapport, versionnés ou
    régénérables. Les faire suivre un volume de production n'aurait aucun sens, et un
    cliquet qui interdit plus que nécessaire finit par être contourné."""
    fautifs = []
    for py in sorted((_RACINE / "01-scripts").glob("*.py")) + [_RACINE / "web/server.py"]:
        if py.name == "storage.py":
            continue          # storage.py EST la source du chemin
        for ligne in py.read_text(encoding="utf-8").splitlines():
            if "99-logs" in ligne and ".db" in ligne:
                fautifs.append(f"{py.name}: {ligne.strip()}")
    assert not fautifs, (
        "ces modules construisent le répertoire des bases eux-mêmes au lieu de passer "
        "par storage.data_dir() :\n" + "\n".join(fautifs))
