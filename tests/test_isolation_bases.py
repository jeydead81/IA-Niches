"""test_isolation_bases.py — aucun test ne doit écrire dans les bases réelles du dépôt.

Ce test est né d'une fuite constatée : avant l'ajout de `isoler_bases`, le test SSE fiction
n'isolait pas `_HISTORY_DB`, et chaque exécution de la suite écrivait « cosy mystery
village » dans la VRAIE `99-logs/history.db`. 45 lignes s'y étaient accumulées. Ce n'est pas
une gêne cosmétique : au moment de créer son compte, Baptiste aurait hérité d'un historique
fabriqué par des tests, et donc d'un delta qui ne mesure rien.

Le test vérifie la seule chose qui compte vraiment : chaque helper de client de test isole
les QUATRE bases, celle des comptes comprise."""
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
BASES = ("_JOBS_DB", "_USAGE_DB", "_HISTORY_DB", "_USERS_DB")


def test_le_helper_partage_isole_les_quatre_bases():
    """Si une base manque ici, tous les tests qui passent par le helper écrivent dedans."""
    src = (RACINE / "tests" / "conftest.py").read_text("utf-8")
    for nom in BASES:
        assert nom in src, f"{nom} n'est pas isolée par tests/conftest.py"


def test_aucun_test_ne_construit_un_client_sans_isoler_les_bases():
    """Un `TestClient(server.app)` construit à la main, sans passer par `isoler_bases`,
    rouvre exactement la fuite qu'on vient de fermer."""
    fautifs = []
    for f in (RACINE / "tests").glob("test_*.py"):
        src = f.read_text("utf-8")
        if "TestClient(server.app)" not in src and "TestClient(app)" not in src:
            continue
        # Le fichier construit un client : il doit isoler les bases, soit par le helper
        # partagé, soit en monkeypatchant les quatre constantes lui-même.
        via_helper = "isoler_bases" in src
        via_soi = all(nom in src for nom in BASES)
        if not (via_helper or via_soi):
            fautifs.append(f.name)
    assert not fautifs, f"clients de test sans isolation des bases : {fautifs}"


def test_les_chemins_de_bases_du_serveur_restent_des_constantes_de_module():
    """L'isolation en test repose entièrement sur le monkeypatch de ces constantes. Les
    remplacer par un magasin construit à l'import rendrait tout test impossible à isoler —
    et créerait de vrais fichiers dès qu'un test importe server.py."""
    src = (RACINE / "web" / "server.py").read_text("utf-8")
    for nom in BASES:
        assert re.search(rf"^{nom} = _ROOT / ", src, re.M), \
            f"{nom} doit rester une constante Path au niveau du module"


def test_le_helper_reinitialise_aussi_l_etat_global_de_module():
    """Les bases ne sont pas le seul etat partage entre tests. Le cache de semaphores de
    `server` en est un autre : un test qui se termine pendant qu'un fil detient encore un
    creneau laissait la place prise pour les suivants, qui echouaient alors par
    intermittence -- sur des tests sans aucun rapport avec la concurrence.

    Ce test existe parce que ca EST arrive : six echecs sur une execution, zero sur la
    suivante."""
    src = (RACINE / "tests" / "conftest.py").read_text("utf-8")
    assert "_CRENEAUX" in src, "l'etat global des creneaux n'est pas reinitialise"
