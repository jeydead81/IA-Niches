"""auth.py — comptes email/mot de passe et sessions.

C'est le seul module du dépôt dont un défaut ne produit pas un mauvais chiffre mais une
COMPROMISSION. Les autres modules se trompent ; celui-ci fuit. D'où les partis pris
ci-dessous, tous testés dans `tests/test_auth.py` avec la menace qu'ils ferment.

**Aucune dépendance ajoutée.** `hashlib.scrypt` est dans la bibliothèque standard depuis
Python 3.6 et figure parmi les fonctions de dérivation recommandées par l'OWASP quand
argon2id n'est pas disponible. Ajouter `bcrypt` ou `argon2-cffi` aurait été défendable,
mais pas au prix d'une dépendance native de plus dans un produit qu'un client devra
installer — et scrypt correctement paramétré n'est pas le maillon faible ici.

Ce qu'on ne stocke JAMAIS :
- le mot de passe (évidemment) — seulement scrypt(mot de passe, sel propre au compte) ;
- le jeton de session en clair — seulement son SHA-256. Sans cela, lire la base suffirait
  à voler une session sans connaître le moindre mot de passe.

Ce que `verifier()` ne révèle jamais : si l'email existe. Ni par le message (il rend
`None` dans les deux cas), ni par le TEMPS DE RÉPONSE — un email inconnu déclenche quand
même une dérivation sur un leurre, sinon la rapidité de la réponse trahirait l'absence de
compte et permettrait d'énumérer les clients avec une simple liste d'adresses.

Même motif SQLite que `cache.py` / `usage.py` : connexion par appel + WAL, sûr en
concurrence (le serveur lance un thread par run).

RAPPEL D'ARCHITECTURE (CLAUDE.md) : `user_id` cloisonne `history.py`, `usage.py` et
`jobs.py` — JAMAIS `cache.py`. Le cache de scraping reste mutualisé entre tous les
comptes : c'est ce qui évite de repayer deux fois la même donnée DataForSEO, et c'est
l'économie principale à l'échelle. Y introduire un `user_id` « par cohérence » serait une
régression économique silencieuse.
"""
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

from pydantic import BaseModel

LONGUEUR_MIN_MOT_DE_PASSE = 10
SESSION_TTL_S = 30 * 24 * 3600          # 30 jours : au-delà, on redemande le mot de passe

# Paramètres scrypt. n=2^14 -> 128*r*n = 16 Mo de mémoire par vérification et ~45 ms sur le
# poste de mesure : assez coûteux pour rendre une attaque par dictionnaire pénible, assez
# rapide pour ne pas transformer une connexion en attente. Ils sont ÉCRITS DANS LA BASE avec
# chaque empreinte (colonne `params`) : les durcir plus tard ne doit pas invalider les
# comptes existants, c'est la raison d'être de cette colonne.
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN = 2 ** 14, 8, 1, 32

# Volontairement permissif : le seul juge de la validité d'une adresse est le serveur de
# messagerie. On écarte ce qui est manifestement faux (pas d'arobase, pas de point dans le
# domaine, partie vide) plutôt que d'inventer une grammaire RFC 5322 qui rejetterait des
# adresses légitimes — un client qui ne peut pas s'inscrire ne se plaint pas, il part.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailInvalide(ValueError):
    pass


class EmailDejaPris(ValueError):
    pass


class MotDePasseFaible(ValueError):
    pass


class Compte(BaseModel):
    """Un compte, sans rien de secret : ce type est sérialisable vers l'interface."""
    user_id: str
    email: str
    cree_le: float = 0.0


def normaliser_email(email: str) -> str:
    """Casse et espaces retirés. « Baptiste@Example.COM » et « baptiste@example.com » sont
    le même compte : sinon un client se crée un doublon sans comprendre où est passé son
    historique. On ne touche PAS à la partie locale au-delà de la casse (pas de retrait des
    points ni du +suffixe) : ce serait un choix de fournisseur, pas une règle générale."""
    return (email or "").strip().lower()


class UserStore:
    def __init__(self, path, now=None):
        self.path = str(path)
        self.now = now or time.time
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as cx:
            cx.execute(
                "CREATE TABLE IF NOT EXISTS comptes ("
                " user_id TEXT PRIMARY KEY,"
                " email TEXT NOT NULL UNIQUE,"
                " sel BLOB NOT NULL,"
                " empreinte BLOB NOT NULL,"
                " params TEXT NOT NULL,"          # durcir scrypt plus tard sans tout casser
                " cree_le REAL NOT NULL"
                ")"
            )
            cx.execute(
                "CREATE TABLE IF NOT EXISTS sessions ("
                " jeton_empreinte TEXT PRIMARY KEY,"   # SHA-256, jamais le jeton en clair
                " user_id TEXT NOT NULL,"
                " cree_le REAL NOT NULL,"
                " expire_le REAL NOT NULL"
                ")"
            )
            cx.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user "
                       "ON sessions (user_id)")

    def _conn(self):
        cx = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        cx.execute("PRAGMA journal_mode=WAL")
        return cx

    # ── Mots de passe ───────────────────────────────────────────────────────────────

    def _deriver(self, mot_de_passe: str, sel: bytes,
                 n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> bytes:
        """Dérivation scrypt. Extraite en méthode pour deux raisons : elle est appelée sur
        un leurre quand le compte n'existe pas (cf. `verifier`), et un test vérifie qu'elle
        l'est bien — c'est ce qui garantit l'égalité des temps de réponse."""
        return hashlib.scrypt(mot_de_passe.encode("utf-8"), salt=sel,
                              n=n, r=r, p=p, dklen=SCRYPT_DKLEN,
                              maxmem=132 * r * n + 1024)

    # ── Comptes ─────────────────────────────────────────────────────────────────────

    def creer_compte(self, email: str, mot_de_passe: str) -> Compte:
        propre = normaliser_email(email)
        if not _EMAIL.match(propre):
            raise EmailInvalide(f"adresse e-mail invalide : « {email} »")
        if len(mot_de_passe or "") < LONGUEUR_MIN_MOT_DE_PASSE:
            raise MotDePasseFaible(
                f"le mot de passe doit faire au moins {LONGUEUR_MIN_MOT_DE_PASSE} caractères")

        sel = secrets.token_bytes(16)          # sel PAR COMPTE : une table pré-calculée ne
        empreinte = self._deriver(mot_de_passe, sel)   # casse alors qu'un seul compte
        compte = Compte(user_id=uuid.uuid4().hex, email=propre, cree_le=self.now())
        params = f"scrypt:{SCRYPT_N}:{SCRYPT_R}:{SCRYPT_P}"
        try:
            with self._conn() as cx:
                cx.execute("INSERT INTO comptes (user_id, email, sel, empreinte, params, "
                           "cree_le) VALUES (?, ?, ?, ?, ?, ?)",
                           (compte.user_id, propre, sel, empreinte, params, compte.cree_le))
        except sqlite3.IntegrityError as e:
            raise EmailDejaPris(f"un compte existe déjà pour « {propre} »") from e
        return compte

    def verifier(self, email: str, mot_de_passe: str) -> Compte | None:
        """Rend le compte, ou None. NE DIT JAMAIS lequel des deux a échoué — ni par le
        message, ni par le temps de réponse (voir le leurre ci-dessous)."""
        propre = normaliser_email(email)
        with self._conn() as cx:
            ligne = cx.execute(
                "SELECT user_id, sel, empreinte, params, cree_le FROM comptes WHERE email=?",
                (propre,)).fetchone()

        if ligne is None:
            # Leurre : sans cette dérivation, répondre à un email inconnu serait
            # instantané et à un email connu lent — le temps de réponse suffirait à
            # énumérer les clients. On paie donc le même prix dans les deux cas.
            self._deriver(mot_de_passe or "", b"leurre-de-temps-constant")
            return None

        user_id, sel, empreinte, params, cree_le = ligne
        n, r, p = _lire_params(params)
        candidat = self._deriver(mot_de_passe or "", sel, n=n, r=r, p=p)
        # compare_digest et non « == » : une comparaison qui s'arrête au premier octet
        # différent laisse deviner l'empreinte octet par octet.
        if not hmac.compare_digest(candidat, empreinte):
            return None
        return Compte(user_id=user_id, email=propre, cree_le=cree_le)

    def compte(self, user_id: str) -> Compte | None:
        with self._conn() as cx:
            ligne = cx.execute("SELECT user_id, email, cree_le FROM comptes WHERE user_id=?",
                               (user_id,)).fetchone()
        return Compte(user_id=ligne[0], email=ligne[1], cree_le=ligne[2]) if ligne else None

    def n_comptes(self) -> int:
        with self._conn() as cx:
            return cx.execute("SELECT COUNT(*) FROM comptes").fetchone()[0]

    # ── Sessions ────────────────────────────────────────────────────────────────────

    def creer_session(self, user_id: str, ttl_s: float = SESSION_TTL_S) -> str:
        """Rend le jeton EN CLAIR (à poser dans un cookie) et n'en garde que l'empreinte.
        Le jeton ne pourra plus jamais être relu depuis la base : c'est voulu."""
        jeton = secrets.token_urlsafe(32)
        maintenant = self.now()
        with self._conn() as cx:
            cx.execute("INSERT INTO sessions (jeton_empreinte, user_id, cree_le, expire_le) "
                       "VALUES (?, ?, ?, ?)",
                       (_empreinte_jeton(jeton), user_id, maintenant, maintenant + ttl_s))
        return jeton

    def session_valide(self, jeton: str) -> str | None:
        """Rend le user_id, ou None si le jeton est inconnu, vide ou expiré."""
        if not (jeton or "").strip():
            return None
        with self._conn() as cx:
            ligne = cx.execute("SELECT user_id, expire_le FROM sessions WHERE "
                               "jeton_empreinte=?", (_empreinte_jeton(jeton),)).fetchone()
        if ligne is None or ligne[1] <= self.now():
            return None
        return ligne[0]

    def fermer_session(self, jeton: str) -> None:
        """Ne ferme QUE cette session : se déconnecter du téléphone ne doit pas déconnecter
        l'ordinateur."""
        with self._conn() as cx:
            cx.execute("DELETE FROM sessions WHERE jeton_empreinte=?",
                       (_empreinte_jeton(jeton),))

    def purger_sessions_expirees(self) -> int:
        with self._conn() as cx:
            cur = cx.execute("DELETE FROM sessions WHERE expire_le<=?", (self.now(),))
            return cur.rowcount


def _empreinte_jeton(jeton: str) -> str:
    """SHA-256 nu, sans sel ni étirement — et c'est correct ici : le jeton est déjà 256 bits
    d'aléa cryptographique, pas un secret choisi par un humain. L'étirer coûterait du temps
    à chaque requête sans rien gagner (il n'existe pas de dictionnaire de jetons)."""
    return hashlib.sha256((jeton or "").encode("utf-8")).hexdigest()


def _lire_params(params: str) -> tuple[int, int, int]:
    """Relit les paramètres scrypt écrits avec l'empreinte, pour pouvoir les durcir un jour
    sans invalider les comptes déjà créés. Format inconnu -> défauts courants."""
    try:
        algo, n, r, p = (params or "").split(":")
        if algo != "scrypt":
            raise ValueError(algo)
        return int(n), int(r), int(p)
    except (ValueError, AttributeError):
        return SCRYPT_N, SCRYPT_R, SCRYPT_P
