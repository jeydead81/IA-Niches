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

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse

# rend le moteur (01-scripts) importable + charge les secrets quel que soit le cwd
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "01-scripts"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(_ROOT / ".env")
from scout_master import run_scout  # noqa: E402
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


@app.post("/api/pdf")
async def api_pdf(request: Request):
    """Rend le one-pager PDF d'une niche à la volée (stateless : la niche est fournie
    en entier dans le body, aucune persistance côté serveur)."""
    data = await request.json()
    scored = ScoredNiche.model_validate(data)
    with tempfile.TemporaryDirectory() as d:
        p = build_positioning_pdf(scored, f"{d}/positioning.pdf")
        pdf_bytes = p.read_bytes()
    name = "".join(c for c in (scored.niche or "niche") if c.isalnum() or c in " -_")[:40].strip()
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name or "niche"}.pdf"'})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
