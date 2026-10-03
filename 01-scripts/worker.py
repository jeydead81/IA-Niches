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
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "01-scripts"))
sys.path.insert(0, str(_ROOT / "web"))

import server  # noqa: E402  — voir l'écart assumé ci-dessus
from cost_tracker import CostTracker  # noqa: E402
# `recuperer_orphelins` vit dans `jobs.py` depuis que le SERVEUR en a besoin lui aussi :
# en `JOBS_MODE=thread` — le défaut — il n'existe aucun worker pour la faire, et un run
# coupé par un redémarrage resterait `en_cours` pour toujours. Ce module l'importe au lieu
# de la porter : `worker` importe `server`, donc `server` ne peut pas importer `worker`,
# et la recopier des deux côtés aurait créé deux implémentations qui divergent.
from jobs import ORPHELIN_APRES_S, JobStore, recuperer_orphelins  # noqa: E402,F401
import annulation  # noqa: E402
from annulation import Annulation, controle_du_travail  # noqa: E402

# Alias de module : les tests les remplacent pour exercer la boucle sans moteur réel.
_RUNNERS = server._JOB_RUNNERS
_imputer = server._imputer

# `ORPHELIN_APRES_S` (30 min) est importé de `jobs` : une constante dupliquée dans deux
# modules est un défaut invisible par construction (§5.32).
# Repos entre deux sondages de la file. La file n'est pas un flux temps réel : un job qui
# démarre 2 s plus tard ne change rien à un run de 5 minutes, et sonder en boucle serrée
# ferait tourner un CPU pour rien.
REPOS_S = 2.0

# Nombre de travaux traites DE FRONT. Un worker sequentiel fait attendre la dixieme
# analyse fiction deux heures et demie ; a 5 creneaux elle demarre au bout d'un tour.
# Les runs sont domines par l'ATTENTE reseau (la file ASIN de DataForSEO met ~250 s quel
# que soit le lot) : des fils y sont peu couteux, ils passent leur temps bloques.
# ATTENTION, limite NON MESUREE : le vrai plafond depend des quotas DataForSEO et
# Anthropic du compte, qu'aucun test du depot ne connait. A revoir avec des chiffres le
# jour ou plusieurs clients tournent vraiment.
CONCURRENCE_DEFAUT = 5


def concurrence_configuree() -> int:
    """Lue a chaque appel, jamais figee a l'import. Une saisie fautive retombe sur le
    defaut plutot que de faire planter le service -- meme posture que partout ailleurs."""
    try:
        n = int(os.getenv("WORKER_CONCURRENCE", "") or CONCURRENCE_DEFAUT)
    except ValueError:
        return CONCURRENCE_DEFAUT
    return max(1, n)




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
        annulation.verifier()          # arret demande par l'utilisateur : meme point de controle
        store.append_progress(job.id, msg)

    if runner is None:
        # Un type retiré du code laisserait sinon le job `en_cours` pour toujours, et le
        # worker tournerait dessus à chaque tour de boucle.
        store.fail(job.id, f"type de travail inconnu : « {job.type} »",
                   cout=cost.breakdown())
        journal(f"[worker] job {job.id} : type inconnu « {job.type} »")
        return True

    journal(f"[worker] job {job.id} ({job.type}) démarré")
    annulation.installer(controle_du_travail(store, job.id))
    try:
        resultat = runner(job.params, progress, cost, job.user_id)
        b = cost.breakdown()
        # La place a ete prise a la CREATION du job (reservation atomique cote
        # serveur) : ici on n'inscrit que le cout, sans recompter l'analyse.
        _imputer(job.user_id, job.type, b["usd"], 0)
        if store.est_annule(job.id):
            # Arrete JUSTE avant la fin : le resultat est jete, le cout reste compte.
            store.enregistrer_cout_annule(job.id, b)
            journal(f"[worker] job {job.id} arrêté par l'utilisateur")
        else:
            store.finish(job.id, resultat, b)
            server._notifier(job.user_id, job.type, "termine", job.id, journal=journal)
            journal(f"[worker] job {job.id} terminé ({b['dataforseo_calls']} recherches)")
    except Annulation:
        # BaseException : l'utilisateur a arrete cette analyse. L'argent deja engage reste impute ;
        # aucune notification (il l'a arretee lui-meme).
        b = cost.breakdown()
        _imputer(job.user_id, job.type, b["usd"], 0)
        store.enregistrer_cout_annule(job.id, b)
        journal(f"[worker] job {job.id} arrêté par l'utilisateur")
    except Exception as e:  # noqa: BLE001 — l'argent déjà dépensé doit rester imputé
        b = cost.breakdown()
        _imputer(job.user_id, job.type, b["usd"], 0)
        # MÊME assainissement qu'en ligne (A3) : le message d'exception peut porter les
        # identifiants DataForSEO, et le worker écrit dans le MÊME champ que le serveur.
        # Le corriger d'un seul côté laisserait la fuite entière sur l'autre.
        store.fail(job.id, server._erreur_publique(e), cout=b)
        server._notifier(job.user_id, job.type, "echec", job.id, journal=journal)
        journal(f"[worker] job {job.id} en échec")
    finally:
        annulation.retirer()
    return True


def _fil(store: JobStore, repos_s: float, max_tours: int | None, journal) -> None:
    """Un fil du pool : reclame, execute, recommence. `claim_next` etant atomique, N fils
    (ou N processus) ne prendront jamais le meme travail."""
    tours = 0
    while max_tours is None or tours < max_tours:
        tours += 1
        if not executer_un_job(store, journal=journal):
            time.sleep(repos_s)


def boucle(store: JobStore | None = None, repos_s: float = REPOS_S,
           max_tours: int | None = None, journal=print,
           concurrence: int | None = None) -> None:
    """Pool de `concurrence` fils. `max_tours` sert aux tests ; en production, sans fin.

    La recuperation des orphelins tourne AU DEMARRAGE, avant d'ouvrir les fils : c'est le
    moment ou l'on sait qu'un redemarrage vient d'avoir lieu, donc que des travaux peuvent
    etre restes en l'air. La faire plus tard les laisserait visibles "en cours" pendant
    que le pool travaille a cote."""
    store = store or JobStore(server._JOBS_DB)
    k = concurrence if concurrence is not None else concurrence_configuree()
    n = recuperer_orphelins(store, journal=journal)
    journal(f"[worker] demarre · {k} creneau(x) · {n} travail(aux) orphelin(s) recupere(s)")

    if k == 1:
        _fil(store, repos_s, max_tours, journal)
        return
    fils = [threading.Thread(target=_fil, args=(store, repos_s, max_tours, journal),
                             daemon=True) for _ in range(k)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()


if __name__ == "__main__":
    boucle(repos_s=float(os.getenv("WORKER_REPOS_S", REPOS_S)))
