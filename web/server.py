"""server.py — backend FastAPI de l'UI IA-Niches.
Sert la page unique et expose le scout en SSE (progression live + résultats).

Lancer :  uvicorn server:app --reload   (depuis le dossier web/)
   ou     python web/server.py
"""
import json
import os
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse

# rend le moteur (01-scripts) importable + charge les secrets quel que soit le cwd
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "01-scripts"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(_ROOT / ".env")
from scout_master import run_scout  # noqa: E402
from fiction_master import run_fiction_scout  # noqa: E402
from niche_verdict import generate_verdict  # noqa: E402
from kdp_keywords import generer_mots_cles  # noqa: E402
from fiction_taxonomy import load_taxonomy  # noqa: E402
from cost_tracker import CostTracker  # noqa: E402
from models import ScoredNiche  # noqa: E402
from positioning_pdf import build_positioning_pdf  # noqa: E402
from jobs import JobStore  # noqa: E402
from usage import UsageMeter  # noqa: E402

app = FastAPI(title="IA-Niches")
_HERE = Path(__file__).resolve().parent

# Chemins des magasins asynchrones (plan SaaS S2/S3). De simples constantes Path : la
# construction du JobStore/UsageMeter (et donc la création du fichier) est différée à
# l'intérieur de chaque endpoint — jamais à l'import du module, sinon importer server.py
# en test écrirait déjà des fichiers réels dans le dépôt (cf. cache.py, même principe :
# connexion/instance par appel, jamais une instance partagée figée à l'import).
_JOBS_DB = _ROOT / "99-logs" / "jobs.db"
_USAGE_DB = _ROOT / "99-logs" / "usage.db"


def _plafond_analyses_mensuel() -> int | None:
    """Plafond mensuel glissant PAR utilisateur — garde-fou contre la queue de distribution
    (l'utilisateur à 500 analyses), pas une grille tarifaire. Défaut prudent : pas de
    plafond configuré -> illimité (mais journalisé, cf. usage.py)."""
    raw = os.getenv("PLAFOND_ANALYSES_MENSUEL")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse((_HERE / "index.html").read_text(encoding="utf-8"))


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/scout")
def scout(seed: str = "", ideas: int = 10, search: int = 4):
    """Lance le scout dans un thread et streame la progression + le résultat en SSE."""
    q: "queue.Queue" = queue.Queue()

    def progress(msg: str) -> None:
        q.put(("progress", msg))

    def worker() -> None:
        cost = CostTracker()
        try:
            results = run_scout(seed=(seed or None), n_ideas=ideas, n_search=search,
                                progress=progress, cost=cost)
            q.put(("result", [r.model_dump() for r in results]))
            q.put(("cost", cost.breakdown()))
        except Exception as e:  # noqa: BLE001
            q.put(("error", f"{type(e).__name__}: {e}"))
        finally:
            q.put(("done", None))

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        yield _sse("progress", "Démarrage du scout…")
        while True:
            kind, payload = q.get()
            if kind == "done":
                yield _sse("done", {})
                break
            yield _sse(kind, payload)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/fiction/sous-genres")
def fiction_sous_genres():
    """Peuple le sélecteur fiction de l'UI depuis la taxonomie (source de vérité unique) —
    jamais une liste dupliquée en dur côté JS, qui se périmerait à la moindre taxo v2."""
    sgs = load_taxonomy().get("sous_genres", {})
    return [{"cle": cle, "label": sg.get("label", cle)} for cle, sg in sorted(sgs.items())]


@app.get("/api/fiction")
def fiction(sous_genre: str = "", n_niches: int = 8, rayon: str = "kindle"):
    """Lance le scout fiction dans un thread, streame en SSE — même contrat que /api/scout
    (progress / result / cost / error / done)."""
    # Validation AVANT de lancer quoi que ce soit : un sous-genre inconnu (ou absent) doit
    # rendre une 400 explicite, jamais la KeyError 500 que lèverait fiction_taxonomy.sous_genre().
    sgs = load_taxonomy().get("sous_genres", {})
    if sous_genre not in sgs:
        raise HTTPException(status_code=400,
                            detail=f"sous-genre inconnu : « {sous_genre} » (dispo : {sorted(sgs)})")

    q: "queue.Queue" = queue.Queue()

    def progress(msg: str) -> None:
        q.put(("progress", msg))

    def worker() -> None:
        cost = CostTracker()
        try:
            rapports = run_fiction_scout(sous_genre, n_niches=n_niches, rayon=rayon,
                                         progress=progress, cost=cost)
            payload = []
            for r in rapports:
                d = r.model_dump()
                # autocomplete_score est une @property (non sérialisée par model_dump) :
                # None tant que la sonde n'a rien mesuré — ne JAMAIS la laisser retomber à
                # 0 par omission, un utilisateur lirait ça comme un verdict (CLAUDE.md §10).
                d["autocomplete_score"] = r.autocomplete_score
                payload.append(d)
            q.put(("result", payload))
            q.put(("cost", cost.breakdown()))
        except Exception as e:  # noqa: BLE001
            q.put(("error", f"{type(e).__name__}: {e}"))
        finally:
            q.put(("done", None))

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        yield _sse("progress", "Démarrage du scout fiction…")
        while True:
            kind, payload = q.get()
            if kind == "done":
                yield _sse("done", {})
                break
            yield _sse(kind, payload)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Travaux asynchrones (plan SaaS S4) ──────────────────────────────────────────────────
# LE point de ce bloc : /api/scout et /api/fiction ci-dessus streament la progression dans
# une queue.Queue qui ne vit QUE le temps de la requête HTTP — rien n'est persisté nulle
# part, donc un client qui se déconnecte perd toute trace exploitable du run (résultat ET
# coût). Ici le run est écrit dans le magasin de travaux (SQLite, jobs.db) à chaque étape :
# POST rend un id tout de suite, le thread continue seul, GET peut être interrogé n'importe
# quand ensuite — y compris après une déconnexion complète du client d'origine.

def _run_scout_job(params: dict, progress, cost) -> list:
    # `ideas`/`search` sont les noms de l'endpoint SSE historique : les accepter aussi,
    # sinon un client qui reprend ces noms voit son plafond silencieusement ignoré et paie
    # les défauts (6 recherches au lieu de 2 demandées). Divergence constatée en live.
    n_ideas = params.get("n_ideas", params.get("ideas", 12))
    n_search = params.get("n_search", params.get("search", 6))
    results = run_scout(seed=params.get("seed") or None, n_ideas=n_ideas,
                        n_search=n_search, progress=progress, cost=cost)
    return [r.model_dump() for r in results]


def _run_fiction_job(params: dict, progress, cost) -> list:
    sous_genre = params.get("sous_genre", "")
    sgs = load_taxonomy().get("sous_genres", {})
    if sous_genre not in sgs:
        # Échoue AVANT tout appel payant : capté par le worker comme un échec de job
        # normal (coût nul imputé), jamais une 500 opaque.
        raise ValueError(f"sous-genre inconnu : « {sous_genre} » (dispo : {sorted(sgs)})")
    rapports = run_fiction_scout(sous_genre, n_niches=params.get("n_niches", 8),
                                 rayon=params.get("rayon", "kindle"),
                                 progress=progress, cost=cost)
    payload = []
    for r in rapports:
        d = r.model_dump()
        d["autocomplete_score"] = r.autocomplete_score       # cf. /api/fiction : property non sérialisée
        payload.append(d)
    return payload


_JOB_RUNNERS = {"scout": _run_scout_job, "fiction": _run_fiction_job}


@app.post("/api/jobs", status_code=202)
async def post_job(request: Request):
    """Lance un travail asynchrone : le client reçoit un id IMMÉDIATEMENT (jamais 15 min
    d'attente HTTP bloquante). Le thread du job est détaché de CETTE requête : il persiste
    sa progression/son résultat/son coût dans le magasin, pas dans une queue en mémoire liée
    à la connexion — fermer l'onglet ne l'arrête pas et ne perd pas l'argent déjà dépensé."""
    body = await request.json()
    type_ = body.get("type")
    runner = _JOB_RUNNERS.get(type_)
    if runner is None:
        raise HTTPException(
            status_code=400,
            detail=f"type de job inconnu : « {type_} » (dispo : {sorted(_JOB_RUNNERS)})")
    user_id = body.get("user_id") or "local"

    # Le plafond est vérifié AVANT de dépenser (§4 du plan SaaS), jamais après coup.
    usage = UsageMeter(_USAGE_DB, plafond_analyses=_plafond_analyses_mensuel())
    if not usage.autorise(user_id, n_analyses=1):
        raise HTTPException(
            status_code=429,
            detail=f"plafond mensuel atteint pour l'utilisateur « {user_id} »")

    params = {k: v for k, v in body.items() if k not in ("type", "user_id")}
    store = JobStore(_JOBS_DB)
    job_id = store.create(type_, params, user_id=user_id)

    def worker() -> None:
        # Connexion/instance par appel (même pattern que cache.py) : sûr en concurrence,
        # ce thread ne partage aucun objet Python avec la requête qui l'a lancé.
        job_store = JobStore(_JOBS_DB)
        job_store.start(job_id)
        cost = CostTracker()

        def progress(msg: str) -> None:
            job_store.append_progress(job_id, msg)

        try:
            resultat = runner(params, progress, cost)
            b = cost.breakdown()
            job_store.finish(job_id, resultat, b)
            UsageMeter(_USAGE_DB).enregistrer(user_id, type_, b["usd"], n_analyses=1)
        except Exception as e:  # noqa: BLE001 — l'argent déjà dépensé doit rester imputé
            b = cost.breakdown()
            job_store.fail(job_id, f"{type(e).__name__}: {e}", cout=b)
            UsageMeter(_USAGE_DB).enregistrer(user_id, type_, b["usd"], n_analyses=1)

    threading.Thread(target=worker, daemon=True).start()
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = JobStore(_JOBS_DB).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job inconnu")
    return job.model_dump()


@app.get("/api/jobs")
def list_jobs(user_id: str = "local", limit: int = 20):
    return [j.model_dump() for j in JobStore(_JOBS_DB).list_jobs(user_id=user_id, limit=limit)]


@app.get("/api/usage")
def usage(user_id: str = "local"):
    """Consommation du mois glissant. Un plafond qui bloque sans que l'utilisateur ait pu
    voir où il en était serait vécu comme une panne, pas comme une limite."""
    r = UsageMeter(_USAGE_DB).resume(user_id)
    return r.model_dump() if hasattr(r, "model_dump") else dict(r)


@app.get("/api/jobs/{job_id}/stream")
def stream_job(job_id: str):
    """SSE branché sur la progression du magasin — RECONNECTABLE : contrairement à
    /api/scout et /api/fiction (queue en mémoire propre à une connexion), l'état lu ici
    vient du magasin persistant, donc une reconnexion peut relire la progression à tout
    moment, y compris longtemps après la requête POST d'origine."""
    def stream():
        store = JobStore(_JOBS_DB)
        envoyes = 0
        while True:
            job = store.get(job_id)
            if job is None:
                yield _sse("error", "job inconnu")
                yield _sse("done", {})
                return
            for msg in job.progression[envoyes:]:
                yield _sse("progress", msg)
            envoyes = len(job.progression)
            if job.statut == "termine":
                yield _sse("result", job.resultat)
                yield _sse("cost", job.cout)
                yield _sse("done", {})
                return
            if job.statut == "echec":
                yield _sse("error", job.erreur)
                yield _sse("done", {})
                return
            time.sleep(0.3)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _content_disposition(name: str) -> str:
    """En-tête Content-Disposition sûr : nom ASCII (fallback) + filename* RFC 5987 (UTF-8).
    Garantit un en-tête encodable en latin-1 (exigence Starlette) même avec « œ », accents, etc."""
    base = (name or "niche").strip()
    ascii_name = "".join(c for c in base if c.isascii() and (c.isalnum() or c in " -_")).strip()
    ascii_name = ascii_name[:40] or "niche"
    utf8 = quote((base[:60] or "niche") + ".pdf")
    return f"attachment; filename=\"{ascii_name}.pdf\"; filename*=UTF-8''{utf8}"


@app.post("/api/verdict")
async def api_verdict(request: Request):
    """Analyse éditoriale d'UNE niche, à la demande (sans état : la niche arrive entière
    dans le body). Mesuré à 0,0283 $ pièce : les générer d'avance pour le top-3 pesait
    78 % du coût d'un run, pour des analyses que l'utilisateur ne lisait pas. On ne paie
    donc que la niche sur laquelle il clique."""
    try:
        scored = ScoredNiche.model_validate(await request.json())
    except Exception:  # noqa: BLE001 — body invalide -> 400 propre (jamais un 500)
        raise HTTPException(status_code=400, detail="niche invalide")
    cost = CostTracker()
    verdict = generate_verdict(scored, on_usage=lambda i, o, m: cost.add_llm(m, i, o))
    UsageMeter(_USAGE_DB).enregistrer("local", "verdict", cost.total_usd(), n_analyses=0)
    return {**verdict.model_dump(), "_cout": cost.breakdown()}


@app.post("/api/kdp-keywords")
async def api_kdp_keywords(request: Request):
    """Les 7 mots-clés backend KDP d'une niche, à la demande (sans état, ~0,006 $).

    Les candidats sont confirmés gratuitement par l'autocomplete Amazon : le coût imputé
    ne couvre que l'appel LLM, la vérification ne coûte rien."""
    try:
        scored = ScoredNiche.model_validate(await request.json())
    except Exception:  # noqa: BLE001 — body invalide -> 400 propre (jamais un 500)
        raise HTTPException(status_code=400, detail="niche invalide")
    cost = CostTracker()
    mots = generer_mots_cles(scored, titre=scored.niche,
                             on_usage=lambda i, o, m: cost.add_llm(m, i, o))
    UsageMeter(_USAGE_DB).enregistrer("local", "kdp_keywords", cost.total_usd(), n_analyses=0)
    return {**mots.model_dump(), "_cout": cost.breakdown()}


@app.post("/api/pdf")
async def api_pdf(request: Request):
    """Rend le one-pager PDF d'une niche à la volée (stateless : la niche est fournie
    en entier dans le body, aucune persistance côté serveur)."""
    try:
        data = await request.json()
        scored = ScoredNiche.model_validate(data)
    except Exception:  # noqa: BLE001 — body invalide -> 400 propre (jamais un 500)
        raise HTTPException(status_code=400, detail="niche invalide")
    with tempfile.TemporaryDirectory() as d:
        p = build_positioning_pdf(scored, f"{d}/positioning.pdf")
        pdf_bytes = p.read_bytes()
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": _content_disposition(scored.niche)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
