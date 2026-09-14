"""conftest.py — outillage partagé des tests de serveur.

Depuis que l'authentification est branchée, tout endpoint autre que `/` et `/api/auth/*`
rend 401 sans session. Chaque test de serveur doit donc ouvrir un compte. Le faire dans un
helper unique évite deux dérives : recopier la séquence d'inscription dans cinq fichiers, et
surtout la tentation de désactiver l'authentification en test « pour simplifier » — ce qui
reviendrait à ne plus jamais tester le chemin réel."""
import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RACINE / "web"))

MDP_TEST = "un-mot-de-passe-solide"


def isoler_bases(monkeypatch, server, tmp_path) -> None:
    """Toutes les bases en tmp_path — jamais les fichiers réels du dépôt. Le magasin de
    comptes en fait partie : un test qui écrirait dans `99-logs/comptes.db` créerait de
    vrais comptes sur le poste de Baptiste."""
    for attr, nom in (("_JOBS_DB", "jobs.db"), ("_USAGE_DB", "usage.db"),
                      ("_HISTORY_DB", "history.db"), ("_USERS_DB", "comptes.db")):
        monkeypatch.setattr(server, attr, tmp_path / nom)
    _reinitialiser_creneaux(server)


def _reinitialiser_creneaux(server) -> None:
    """Vide le cache de semaphores de `server`.

    Ces semaphores sont un ETAT GLOBAL DE MODULE, exactement comme les chemins de bases :
    ils survivent d'un test a l'autre. Un test qui se termine pendant qu'un fil detient
    encore un creneau laissait la place prise pour les tests SUIVANTS, qui attendaient
    alors le leur jusqu'a expiration -- des echecs INTERMITTENTS, sur des tests sans
    rapport avec la concurrence.

    Un test rouge une fois sur dix erode plus la confiance dans la suite qu'il ne protege
    de quoi que ce soit : c'est deja la lecon de `_attendre_job`."""
    server._CRENEAUX.clear()


def ouvrir_inscriptions(monkeypatch) -> None:
    """Les inscriptions sont FERMÉES par défaut depuis la revue de sécurité : le plafond
    mensuel étant par utilisateur, un compte de plus est un plafond neuf. Seul le premier
    compte passe (amorçage). Tout test qui a besoin d'un SECOND compte doit donc ouvrir la
    porte explicitement — ce qui rend la contrainte visible dans le test plutôt que de la
    contourner en douce depuis un helper partagé."""
    monkeypatch.setenv("INSCRIPTIONS_OUVERTES", "1")


def ouvrir_session(client, email: str = "test@example.com") -> str:
    """Crée un compte et laisse le cookie de session sur le client. Rend le user_id, dont
    plusieurs tests ont besoin pour vérifier le cloisonnement."""
    r = client.post("/api/auth/inscription",
                    json={"email": email, "mot_de_passe": MDP_TEST})
    assert r.status_code == 201, r.text
    return r.json()["user_id"]


@pytest.fixture(autouse=True)
def _calibration_hors_des_donnees_reelles(monkeypatch, tmp_path):
    """Deux gardes de COMPORTEMENT pour la CLI de calibration, posés sur TOUS les tests.

    - Les captures de run partent sous `tmp_path`, jamais dans le vrai `99-logs/captures/`.
    - Une purge dont le cache résolu est le vrai `99-logs/df-cache.db` LÈVE avant d'ouvrir
      quoi que ce soit. L'ancien garde cherchait `--cache` dans les 160 caractères précédant
      l'option, dans un seul fichier : une liste d'arguments rangée dans une variable, ou un
      appel écrit ailleurs, passait. Le garde vit ici, dans le harnais de TEST — dans le code
      de production il interdirait à Baptiste la purge qu'il a décidée (R2, voie A)."""
    import build_lowcontent_validation_set as cli
    monkeypatch.setattr(cli, "RACINE_CAPTURES", tmp_path / "captures", raising=False)
    vrai = (_RACINE / "99-logs" / "df-cache.db").resolve()
    reelle = cli.purger_fiches_sans_pages

    def purge_gardee(requetes, chemin_cache, *a, **k):
        if Path(chemin_cache).resolve() == vrai:
            raise AssertionError(f"un test vise le vrai cache mutualisé : {vrai}")
        return reelle(requetes, chemin_cache, *a, **k)
    monkeypatch.setattr(cli, "purger_fiches_sans_pages", purge_gardee)

