"""worker.py — exécute les travaux de la file, hors du processus serveur.

Le job SURVIT déjà à la fermeture de l'onglet : il vit dans `jobs.db`, pas dans la requête
HTTP. Ce qu'il ne survit PAS, c'est au redémarrage du serveur — le thread meurt, et le job
reste `en_cours` pour toujours. L'utilisateur voit une analyse éternellement en cours, son
unité de plafond est consommée, et rien ne le lui dit. C'est ce trou-là que ce module ferme.

Deux mécanismes, deux invariants distincts :

- `JobStore.claim_next` est ATOMIQUE (BEGIN IMMEDIATE). Deux workers qui prendraient le même
  job le paieraient DEUX fois : deux fois les SERP, deux fois les tokens. C'est le seul
  endroit du dépôt où une course coûte de l'argent réel.

- `recuperer_orphelins` distingue « interrompu » de « long ». Un run fiction dure 10 à 15
  minutes : trier sur l'ancienneté tuerait des runs vivants. C'est l'ABSENCE DE PROGRESSION
  qui fait l'orphelin — même famille d'invariant que « une absence de mesure n'est pas une
  mesure ».

ÉCART ASSUMÉ AVEC LE PLAN 2026-08-18. Il prévoyait d'extraire les runners de `server.py`
vers un `job_runners.py` partagé, pour que ce module n'importe pas FastAPI. Non fait, et
délibérément : les runners lisent les chemins de bases (`_HISTORY_DB`…), que les tests
isolent en monkeypatchant `server`. Les déplacer créerait une SECONDE source de vérité pour
ces chemins, et un helper d'isolation qui en oublierait une ferait écrire les tests dans les
vraies bases de Baptiste — c'est déjà arrivé une fois (45 lignes fabriquées dans
`history.db`, cf. `test_isolation_bases.py`). Importer FastAPI dans le worker coûte quelques
mégaoctets ; une seconde source pour un chemin de base coûte des données corrompues.

Bonus de cet import : `server.py` exécute `_verifier_config_prod()` à l'import, donc un
worker lancé en production sans `BSR_SOURCE=dataforseo` refuse de démarrer lui aussi.

Lancer :  python 01-scripts/worker.py
"""
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "01-scripts"))
sys.path.insert(0, str(_ROOT / "web"))

import server  # noqa: E402  — voir l'écart assumé ci-dessus
from cost_tracker import CostTracker  # noqa: E402
from jobs import JobStore  # noqa: E402

# Alias de module : les tests les remplacent pour exercer la boucle sans moteur réel.
_RUNNERS = server._JOB_RUNNERS
_imputer = server._imputer

# 30 min sans le moindre signe de vie. Le run le plus long du produit (fiction, 8 trios)
# tient en 10 à 15 minutes, batch ASIN compris : le double laisse la marge d'une file
# DataForSEO lente sans laisser un zombie une journée entière.
ORPHELIN_APRES_S = 30 * 60
# Repos entre deux sondages de la file. La file n'est pas un flux temps réel : un job qui
# démarre 2 s plus tard ne change rien à un run de 5 minutes, et sonder en boucle serrée
# ferait tourner un CPU pour rien.
REPOS_S = 2.0


def recuperer_orphelins(store: JobStore, depuis_s: float = ORPHELIN_APRES_S,
                        journal=print) -> int:
    """Passe en échec les travaux interrompus. Rend combien ont été récupérés.

    Le coût déjà mesuré est CONSERVÉ (§5.29) : le remettre à zéro ferait croire qu'un run
    interrompu était gratuit. La progression est conservée aussi — ce qui a été fait avant
    la coupure reste lisible, et c'est la seule chose qui dit à l'utilisateur où il en
    était."""
    n = 0
    for job in store.orphelins(depuis_s=depuis_s):
        store.fail(job.id,
                   "Analyse interrompue (redémarrage du service). Le travail déjà "
                   "effectué est conservé ci-dessus ; relancez pour terminer.",
                   cout=job.cout)
        journal(f"[worker] job {job.id} ({job.type}) récupéré : interrompu")
        n += 1
    return n


def executer_un_job(store: JobStore, journal=print) -> bool:
    """Réserve et exécute UN travail. Rend False si la file est vide.

    Le corps reproduit celui du thread de `POST /api/jobs`, y compris ses deux invariants :
    l'usage est imputé AVANT de marquer le job terminé (« terminé » doit impliquer
    « compté »), et le coût déjà engagé reste imputé même en cas d'échec."""
    job = store.claim_next()
    if job is None:
        return False

    runner = _RUNNERS.get(job.type)
    cost = CostTracker()

    def progress(msg: str) -> None:
        store.append_progress(job.id, msg)

    if runner is None:
        # Un type retiré du code laisserait sinon le job `en_cours` pour toujours, et le
        # worker tournerait dessus à chaque tour de boucle.
        store.fail(job.id, f"type de travail inconnu : « {job.type} »",
                   cout=cost.breakdown())
        journal(f"[worker] job {job.id} : type inconnu « {job.type} »")
        return True

    journal(f"[worker] job {job.id} ({job.type}) démarré")
    try:
        resultat = runner(job.params, progress, cost, job.user_id)
        b = cost.breakdown()
        _imputer(job.user_id, job.type, b["usd"], 1)
        store.finish(job.id, resultat, b)
        journal(f"[worker] job {job.id} terminé ({b['dataforseo_calls']} recherches)")
    except Exception as e:  # noqa: BLE001 — l'argent déjà dépensé doit rester imputé
        b = cost.breakdown()
        _imputer(job.user_id, job.type, b["usd"], 1)
        # MÊME assainissement qu'en ligne (A3) : le message d'exception peut porter les
        # identifiants DataForSEO, et le worker écrit dans le MÊME champ que le serveur.
        # Le corriger d'un seul côté laisserait la fuite entière sur l'autre.
        store.fail(job.id, server._erreur_publique(e), cout=b)
        journal(f"[worker] job {job.id} en échec")
    return True


def boucle(store: JobStore | None = None, repos_s: float = REPOS_S,
           max_tours: int | None = None, journal=print) -> None:
    """Boucle principale. `max_tours` sert aux tests ; en production elle ne s'arrête pas.

    La récupération des orphelins tourne AU DÉMARRAGE : c'est le moment où l'on sait qu'un
    redémarrage vient d'avoir lieu, donc que des jobs peuvent être restés en l'air."""
    store = store or JobStore(server._JOBS_DB)
    n = recuperer_orphelins(store, journal=journal)
    journal(f"[worker] démarré · {n} travail(aux) orphelin(s) récupéré(s)")

    tours = 0
    while max_tours is None or tours < max_tours:
        tours += 1
        if not executer_un_job(store, journal=journal):
            time.sleep(repos_s)


if __name__ == "__main__":
    boucle(repos_s=float(os.getenv("WORKER_REPOS_S", REPOS_S)))
