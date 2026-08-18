"""cache.py — cache clé/valeur SQLite partagé (cross-user), avec TTL.
Sûr en concurrence (le serveur lance des scouts en threads) : connexion par appel + WAL.
Valeurs JSON-sérialisables. Helpers dédiés BSR (par ASIN) et search (par mot-clé normalisé)."""
import hashlib
import json
import sqlite3
import time
from functools import lru_cache
from pathlib import Path

from models import BsrInfo, EnrichedBook, SearchResult, TropeClassification

BOOK_TTL_S = 7 * 24 * 3600     # 7 jours : rayon fiction, moins volatil que le BSR seul
AUTOCOMPLETE_TTL_S = 7 * 24 * 3600  # arbre de completions : bouge a l'echelle de la saison
# Une classification de blurb est DÉTERMINISTE pour un (livre, taxonomie, modèle, prompt)
# donné : le texte de la quatrième de couverture ne bouge quasiment jamais. TTL long — la
# clé porte déjà tout ce qui peut invalider le résultat.
CLASSIFICATION_TTL_S = 30 * 24 * 3600


def _fields_fingerprint(model) -> str:
    """Empreinte des NOMS de champs d'un modèle pydantic — le même piège (cache qui sert
    des données amputées en silence après un ajout de champ) menace TOUT modèle mis en
    cache, pas seulement EnrichedBook : `book:` l'a appris à ses dépens en M4 (blurb ajouté
    pendant que des livres étaient déjà en cache), `bsr:` et `search:` restaient exposés."""
    noms = ",".join(sorted(model.model_fields))
    return hashlib.sha1(noms.encode("utf-8")).hexdigest()[:8]


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
    return _fields_fingerprint(EnrichedBook)


@lru_cache(maxsize=1)
def _bsr_schema_tag() -> str:
    """Même empreinte que `_schema_tag`, mais pour BsrInfo (clé `bsr:`) — le piège était
    resté armé pour ce modèle-là aussi."""
    return _fields_fingerprint(BsrInfo)


@lru_cache(maxsize=1)
def _prompt_tag() -> str:
    """Empreinte du prompt système du classifieur, injectée dans la clé de cache.

    Le prompt a été durci en cours de route (le modèle inventait des décors) : sans cette
    empreinte, le cache resservirait indéfiniment des étiquettes produites par l'ANCIENNE
    consigne, et le durcissement n'aurait aucun effet sur les livres déjà vus. Même leçon
    que `_schema_tag` — un compteur de version manuel s'oublie exactement au moment où il
    compte, l'empreinte se met à jour toute seule."""
    from fiction_classifier import SYSTEM_PROMPT
    return hashlib.sha1(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:8]


@lru_cache(maxsize=1)
def _search_schema_tag() -> str:
    """Même empreinte que `_schema_tag`, mais pour SearchResult (clé `search:`)."""
    return _fields_fingerprint(SearchResult)


@lru_cache(maxsize=1)
def _clf_schema_tag() -> str:
    """Même empreinte, pour TropeClassification (clé `clf:`) — le dernier modèle mis en
    cache qui restait sans garde-fou.

    La clé portait déjà la taxonomie, le modèle et le prompt : tout ce qui change le
    RAISONNEMENT. Il manquait ce qui change la FORME du résultat. Ajouter un champ à
    TropeClassification aurait donc resservi des classifications amputées pendant
    CLASSIFICATION_TTL_S, soit 30 jours — quatre fois plus longtemps que les 7 jours de
    fiches sans blurb qui ont déjà piégé M4."""
    from models import TropeClassification
    return _fields_fingerprint(TropeClassification)


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
        return f"bsr:{_bsr_schema_tag()}:{location}:{asin}"

    @staticmethod
    def _search_key(keyword: str, location: int, language: str) -> str:
        return f"search:{_search_schema_tag()}:{location}:{language}:{(keyword or '').lower().strip()}"

    @staticmethod
    def _book_key(asin: str, location: int) -> str:
        return f"book:{_schema_tag()}:{location}:{asin}"

    @staticmethod
    def _autocomplete_key(prefixe: str, marketplace: str) -> str:
        """Pas d'empreinte de schema ici, contrairement aux quatre autres cles : la valeur
        est une liste de CHAINES, pas un modele pydantic. Il n'y a pas de champ a ajouter,
        donc rien qui puisse servir un objet ampute en silence (5.14)."""
        return f"ac:{marketplace}:{' '.join((prefixe or '').lower().split())}"

    def get_autocomplete(self, prefixe: str, marketplace: str = "fr") -> list[str] | None:
        """None = jamais sonde. Une liste VIDE est une reponse : Amazon a ete interroge
        et n'a rien complete. Confondre les deux ferait re-payer la sonde a chaque run
        sur toutes les feuilles de l'arbre -- c'est-a-dire sur la majorite des noeuds."""
        return self.get(self._autocomplete_key(prefixe, marketplace))

    def set_autocomplete(self, prefixe: str, suggestions: list[str], ttl_s: float,
                         marketplace: str = "fr") -> None:
        self.set(self._autocomplete_key(prefixe, marketplace), list(suggestions), ttl_s)

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

    @staticmethod
    def _classification_key(asin: str, version: str, model: str) -> str:
        # Taxonomie + modèle + prompt : ce qui change le RAISONNEMENT pour un même livre.
        # Empreinte de schéma : ce qui change la FORME du résultat. Les quatre sont
        # nécessaires — en omettre une resservirait soit une étiquette produite autrement,
        # soit un objet amputé, et pendant 30 jours (CLASSIFICATION_TTL_S).
        return f"clf:{version}:{model}:{_prompt_tag()}:{_clf_schema_tag()}:{asin}"

    def get_classification(self, asin: str, version: str,
                           model: str) -> TropeClassification | None:
        d = self.get(self._classification_key(asin, version, model))
        return TropeClassification.model_validate(d) if d else None

    def set_classification(self, asin: str, version: str, model: str,
                           classification: TropeClassification, ttl_s: float) -> None:
        self.set(self._classification_key(asin, version, model),
                 classification.model_dump(), ttl_s)

    def get_book(self, asin: str, location: int) -> EnrichedBook | None:
        d = self.get(self._book_key(asin, location))
        return EnrichedBook.model_validate(d) if d else None

    def set_book(self, asin: str, location: int, book: EnrichedBook, ttl_s: float) -> None:
        self.set(self._book_key(asin, location), book.model_dump(), ttl_s)
