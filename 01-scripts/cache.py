"""cache.py — cache clé/valeur SQLite partagé (cross-user), avec TTL.
Sûr en concurrence (le serveur lance des scouts en threads) : connexion par appel + WAL.
Valeurs JSON-sérialisables. Helpers dédiés BSR (par ASIN) et search (par mot-clé normalisé)."""
import json
import sqlite3
import time
from pathlib import Path

from models import BsrInfo, SearchResult


class Cache:
    def __init__(self, path, now=None):
        self.path = str(path)
        self.now = now or time.time
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as cx:
            cx.execute("CREATE TABLE IF NOT EXISTS kv "
                       "(key TEXT PRIMARY KEY, value TEXT NOT NULL, expires REAL NOT NULL)")

    def _conn(self):
        cx = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        cx.execute("PRAGMA journal_mode=WAL")
        return cx

    def get(self, key: str):
        with self._conn() as cx:
            row = cx.execute("SELECT value, expires FROM kv WHERE key=?", (key,)).fetchone()
        if not row or row[1] < self.now():
            return None
        return json.loads(row[0])

    def set(self, key: str, value, ttl_s: float) -> None:
        with self._conn() as cx:
            cx.execute("INSERT OR REPLACE INTO kv (key, value, expires) VALUES (?, ?, ?)",
                       (key, json.dumps(value, ensure_ascii=False), self.now() + ttl_s))

    # ── helpers métier ──
    @staticmethod
    def _bsr_key(asin: str, location: int) -> str:
        return f"bsr:{location}:{asin}"

    @staticmethod
    def _search_key(keyword: str, location: int, language: str) -> str:
        return f"search:{location}:{language}:{(keyword or '').lower().strip()}"

    def get_bsr(self, asin: str, location: int) -> BsrInfo | None:
        d = self.get(self._bsr_key(asin, location))
        return BsrInfo.model_validate(d) if d else None

    def set_bsr(self, asin: str, location: int, info: BsrInfo, ttl_s: float) -> None:
        self.set(self._bsr_key(asin, location), info.model_dump(), ttl_s)

    def get_search(self, keyword: str, location: int, language: str) -> SearchResult | None:
        d = self.get(self._search_key(keyword, location, language))
        return SearchResult.model_validate(d) if d else None

    def set_search(self, keyword: str, location: int, language: str,
                   result: SearchResult, ttl_s: float) -> None:
        self.set(self._search_key(keyword, location, language), result.model_dump(), ttl_s)
