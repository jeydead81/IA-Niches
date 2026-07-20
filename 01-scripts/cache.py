"""cache.py — cache clé/valeur SQLite partagé (cross-user), avec TTL.
Sûr en concurrence (le serveur lance des scouts en threads) : connexion par appel + WAL.
Valeurs JSON-sérialisables. Helpers dédiés BSR (par ASIN) et search (par mot-clé normalisé)."""
import hashlib
import json
import sqlite3
import time
from functools import lru_cache
from pathlib import Path

from models import BsrInfo, EnrichedBook, SearchResult

BOOK_TTL_S = 7 * 24 * 3600     # 7 jours : rayon fiction, moins volatil que le BSR seul


@lru_cache(maxsize=1)
def _schema_tag() -> str:
    """Empreinte des champs d'EnrichedBook, injectée dans la clé de cache.

    Sans elle, enrichir le modèle sert des livres périmés en silence : le blurb a été
    ajouté en M4 alors que des livres étaient déjà en cache, et pendant 7 jours le
    classifieur aurait reçu des fiches sans blurb — puis M5 aurait lu « aucun trope
    identifié » comme un fait mesuré. Un compteur de version manuel se serait oublié
    exactement de la même façon ; l'empreinte, elle, se met à jour toute seule.

    Limite assumée : elle suit les NOMS des champs, pas leurs types. Changer la
    sémantique d'un champ sans le renommer demande toujours de vider le cache."""
    noms = ",".join(sorted(EnrichedBook.model_fields))
    return hashlib.sha1(noms.encode("utf-8")).hexdigest()[:8]


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

    @staticmethod
    def _book_key(asin: str, location: int) -> str:
        return f"book:{_schema_tag()}:{location}:{asin}"

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

    def get_book(self, asin: str, location: int) -> EnrichedBook | None:
        d = self.get(self._book_key(asin, location))
        return EnrichedBook.model_validate(d) if d else None

    def set_book(self, asin: str, location: int, book: EnrichedBook, ttl_s: float) -> None:
        self.set(self._book_key(asin, location), book.model_dump(), ttl_s)
