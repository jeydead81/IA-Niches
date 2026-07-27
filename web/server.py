"""server.py — backend FastAPI de l'UI IA-Niches.
Sert la page unique et expose le scout en SSE (progression live + résultats).

Lancer :  uvicorn server:app --reload   (depuis le dossier web/)
   ou     python web/server.py
"""
import json
import queue
import sys
import tempfile
import threading
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
from fiction_taxonomy import load_taxonomy  # noqa: E402
from cost_tracker import CostTracker  # noqa: E402
from models import ScoredNiche  # noqa: E402
from positioning_pdf import build_positioning_pdf  # noqa: E402

app = FastAPI(title="IA-Niches")
_HERE = Path(__file__).resolve().parent


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


def _content_disposition(name: str) -> str:
    """En-tête Content-Disposition sûr : nom ASCII (fallback) + filename* RFC 5987 (UTF-8).
    Garantit un en-tête encodable en latin-1 (exigence Starlette) même avec « œ », accents, etc."""
    base = (name or "niche").strip()
    ascii_name = "".join(c for c in base if c.isascii() and (c.isalnum() or c in " -_")).strip()
    ascii_name = ascii_name[:40] or "niche"
    utf8 = quote((base[:60] or "niche") + ".pdf")
    return f"attachment; filename=\"{ascii_name}.pdf\"; filename*=UTF-8''{utf8}"


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
