"""Les bases de la suite ne sont JAMAIS celles du dépôt (2026-10-06).

Le 2026-10-06, des fils détachés lancés par des tests ont écrit dans le vrai `99-logs/usage.db`
(18 lignes de règlement) et le vrai `history.db` (36 lignes) APRÈS la fin du test, quand
`isoler_bases` avait déjà restauré les chemins réels. Ce fichier tient le filet posé dans
`conftest.py` : DATA_DIR pointe un dossier temporaire dès l'import, avant tout `import server`.
"""
import os
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
VRAI = (RACINE / "99-logs").resolve()


def _hors_du_depot(chemin) -> bool:
    return VRAI not in Path(chemin).resolve().parents


def test_data_dir_pointe_un_dossier_temporaire_pour_toute_la_session():
    assert _hors_du_depot(os.environ["DATA_DIR"]) and "ia-niches-tests-" in os.environ["DATA_DIR"]


def test_les_chemins_par_defaut_du_serveur_ne_sont_pas_ceux_du_depot():
    """Lus SANS `isoler_bases` : c'est exactement ce que voit un fil qui survit à son test."""
    import server
    for attr in ("_JOBS_DB", "_USAGE_DB", "_HISTORY_DB", "_USERS_DB"):
        assert _hors_du_depot(getattr(server, attr)), attr


def test_le_cache_des_orchestrateurs_n_est_pas_celui_du_depot():
    import storage
    assert _hors_du_depot(storage.base("df-cache.db"))
