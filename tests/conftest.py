"""conftest.py — outillage partagé des tests de serveur.

Depuis que l'authentification est branchée, tout endpoint autre que `/` et `/api/auth/*`
rend 401 sans session. Chaque test de serveur doit donc ouvrir un compte. Le faire dans un
helper unique évite deux dérives : recopier la séquence d'inscription dans cinq fichiers, et
surtout la tentation de désactiver l'authentification en test « pour simplifier » — ce qui
reviendrait à ne plus jamais tester le chemin réel."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

MDP_TEST = "un-mot-de-passe-solide"


def isoler_bases(monkeypatch, server, tmp_path) -> None:
    """Toutes les bases en tmp_path — jamais les fichiers réels du dépôt. Le magasin de
    comptes en fait partie : un test qui écrirait dans `99-logs/comptes.db` créerait de
    vrais comptes sur le poste de Baptiste."""
    for attr, nom in (("_JOBS_DB", "jobs.db"), ("_USAGE_DB", "usage.db"),
                      ("_HISTORY_DB", "history.db"), ("_USERS_DB", "comptes.db")):
        monkeypatch.setattr(server, attr, tmp_path / nom)


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
