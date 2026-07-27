"""jobs.py — magasin de travaux asynchrones (SQLite, même pattern que cache.py : connexion
par appel + WAL, sûr en concurrence car le serveur lance un thread par run).

LE point du module : aujourd'hui (M6/M7) un scout vit dans le thread de la connexion SSE —
fermer l'onglet tue le run ET perd l'argent déjà dépensé. Ici le job vit dans la base, pas
dans la requête HTTP : un client qui se déconnecte peut revenir lire l'état plus tard.

`user_id` partout dès maintenant (défaut "local") : brancher l'authentification plus tard
devient un remplissage de colonne, pas une migration (cf. plan SaaS 2026-07-21, décision §)."""
import json
import sqlite3
import time
import uuid
from pathlib import Path

from pydantic import BaseModel, Field

STATUTS = ("en_attente", "en_cours", "termine", "echec")
DEFAULT_MAX_PROGRESS = 200      # un run de 15 min log beaucoup : borne la table, pas la RAM seule


class Job(BaseModel):
    """Un travail asynchrone (scout non-fiction ou fiction). `resultat`/`cout` restent des
    dict/list JSON-génériques : jobs.py ne connaît pas la forme de ScoredNiche/FictionNicheReport,
    seul l'appelant (web/server.py) sait ce qu'il y met."""
    id: str
    user_id: str = "local"
    type: str
    params: dict = Field(default_factory=dict)
    statut: str = "en_attente"          # ∈ STATUTS
    progression: list[str] = Field(default_factory=list)
    resultat: list | dict | None = None
    cout: dict | None = None
    erreur: str | None = None
    cree_le: float
    fini_le: float | None = None


class JobStore:
    def __init__(self, path, now=None, max_progress: int = DEFAULT_MAX_PROGRESS):
        self.path = str(path)
        self.now = now or time.time
        self.max_progress = max_progress
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as cx:
            cx.execute(
                "CREATE TABLE IF NOT EXISTS jobs ("
                " id TEXT PRIMARY KEY,"
                " user_id TEXT NOT NULL,"
                " type TEXT NOT NULL,"
                " params TEXT NOT NULL,"
                " statut TEXT NOT NULL,"
                " progression TEXT NOT NULL,"
                " resultat TEXT,"
                " cout TEXT,"
                " erreur TEXT,"
                " cree_le REAL NOT NULL,"
                " fini_le REAL"
                ")"
            )

    def _conn(self):
        cx = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        cx.execute("PRAGMA journal_mode=WAL")
        return cx

    # ── écriture ──
    def create(self, type: str, params: dict, user_id: str = "local") -> str:
        jid = uuid.uuid4().hex
        with self._conn() as cx:
            cx.execute(
                "INSERT INTO jobs (id, user_id, type, params, statut, progression, "
                "resultat, cout, erreur, cree_le, fini_le) "
                "VALUES (?, ?, ?, ?, 'en_attente', '[]', NULL, NULL, NULL, ?, NULL)",
                (jid, user_id, type, json.dumps(params, ensure_ascii=False), self.now()),
            )
        return jid

    def start(self, job_id: str) -> None:
        with self._conn() as cx:
            cx.execute("UPDATE jobs SET statut='en_cours' WHERE id=?", (job_id,))

    def append_progress(self, job_id: str, msg: str) -> None:
        """Ajoute un message et borne la liste aux `max_progress` derniers — un run de
        15 min qui log beaucoup ne doit pas gonfler la base sans fin."""
        with self._conn() as cx:
            row = cx.execute("SELECT progression FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                return
            prog = json.loads(row[0])
            prog.append(msg)
            prog = prog[-self.max_progress:]
            cx.execute("UPDATE jobs SET progression=? WHERE id=?",
                       (json.dumps(prog, ensure_ascii=False), job_id))

    def finish(self, job_id: str, resultat, cout: dict) -> None:
        with self._conn() as cx:
            cx.execute(
                "UPDATE jobs SET statut='termine', resultat=?, cout=?, fini_le=? WHERE id=?",
                (json.dumps(resultat, ensure_ascii=False),
                 json.dumps(cout, ensure_ascii=False), self.now(), job_id),
            )

    def fail(self, job_id: str, erreur: str, cout: dict | None = None) -> None:
        """L'argent dépensé avant l'échec reste imputé — sinon on facture dans le vide."""
        with self._conn() as cx:
            cx.execute(
                "UPDATE jobs SET statut='echec', erreur=?, cout=?, fini_le=? WHERE id=?",
                (erreur, json.dumps(cout, ensure_ascii=False) if cout is not None else None,
                 self.now(), job_id),
            )

    # ── lecture ──
    @staticmethod
    def _row_to_job(row: tuple) -> Job:
        (jid, user_id, type_, params, statut, progression, resultat, cout, erreur,
         cree_le, fini_le) = row
        return Job(
            id=jid, user_id=user_id, type=type_, params=json.loads(params),
            statut=statut, progression=json.loads(progression),
            resultat=json.loads(resultat) if resultat is not None else None,
            cout=json.loads(cout) if cout is not None else None,
            erreur=erreur, cree_le=cree_le, fini_le=fini_le,
        )

    def get(self, job_id: str) -> Job | None:
        with self._conn() as cx:
            row = cx.execute(
                "SELECT id, user_id, type, params, statut, progression, resultat, cout, "
                "erreur, cree_le, fini_le FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, user_id: str = "local", limit: int | None = None) -> list[Job]:
        """Les plus récents d'abord (recence = cree_le décroissant)."""
        sql = ("SELECT id, user_id, type, params, statut, progression, resultat, cout, "
               "erreur, cree_le, fini_le FROM jobs WHERE user_id=? ORDER BY cree_le DESC")
        params: tuple = (user_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (user_id, limit)
        with self._conn() as cx:
            rows = cx.execute(sql, params).fetchall()
        return [self._row_to_job(r) for r in rows]
