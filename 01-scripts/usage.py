"""usage.py — compteur d'usage par utilisateur + plafond (SQLite, même pattern que cache.py :
connexion par appel + WAL, sûr en concurrence).

Le compteur est un GARDE-FOU, pas une grille tarifaire (cf. plan SaaS 2026-07-21) : à
30 analyses/mois la marge est de 88 %, le coût unitaire n'est pas le risque — le risque est
la queue de distribution (un utilisateur à 500 analyses). Le plafond, quand il est configuré,
est donc PAR utilisateur et MENSUEL GLISSANT (un plafond cumulatif à vie bloquerait un client
fidèle au bout de quelques mois) ; sans plafond configuré, l'usage reste illimité mais reste
journalisé (transparence, jamais un silence sur la dépense)."""
import sqlite3
import time
from pathlib import Path

from pydantic import BaseModel

FENETRE_GLISSANTE_S = 30 * 24 * 3600     # mensuel glissant, pas calendaire ni cumulatif à vie


class UsageResume(BaseModel):
    """Usage cumulé d'un utilisateur sur la fenêtre considérée."""
    n_analyses: int = 0
    cout_usd: float = 0.0


class UsageMeter:
    def __init__(self, path, now=None, plafond_analyses: int | None = None,
                 fenetre_s: float = FENETRE_GLISSANTE_S):
        self.path = str(path)
        self.now = now or time.time
        self.plafond_analyses = plafond_analyses
        self.fenetre_s = fenetre_s
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as cx:
            cx.execute(
                "CREATE TABLE IF NOT EXISTS usage ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " user_id TEXT NOT NULL,"
                " type TEXT NOT NULL,"
                " cout_usd REAL NOT NULL,"
                " n_analyses INTEGER NOT NULL,"
                " horodatage REAL NOT NULL"
                ")"
            )

    def _conn(self):
        cx = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        cx.execute("PRAGMA journal_mode=WAL")
        return cx

    def enregistrer(self, user_id: str, type: str, cout_usd: float, n_analyses: int) -> None:
        """Impute une dépense déjà faite à un utilisateur. Appelé après coup (le run est
        terminé ou en échec) : jamais bloquant, c'est `autorise()` qui protège en amont."""
        with self._conn() as cx:
            cx.execute(
                "INSERT INTO usage (user_id, type, cout_usd, n_analyses, horodatage) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, type, cout_usd, n_analyses, self.now()),
            )

    def resume(self, user_id: str, depuis: float | None = None) -> UsageResume:
        """Somme l'usage d'un utilisateur depuis `depuis` (par défaut : début de la fenêtre
        glissante courante)."""
        cutoff = depuis if depuis is not None else self.now() - self.fenetre_s
        with self._conn() as cx:
            row = cx.execute(
                "SELECT COALESCE(SUM(n_analyses), 0), COALESCE(SUM(cout_usd), 0.0) "
                "FROM usage WHERE user_id=? AND horodatage>=?", (user_id, cutoff),
            ).fetchone()
        return UsageResume(n_analyses=row[0], cout_usd=row[1])

    def compter(self, user_id: str, types, fenetre_s: float) -> int:
        """Nombre d'appels d'un des `types` sur la fenetre GLISSANTE.

        Glissante et non calendaire : un seau qui se vide a heure fixe se contourne en
        attendant l'heure ronde. Aucun stockage nouveau -- la table porte deja `type` et
        `horodatage`, il suffisait de les lire."""
        types = tuple(types)
        if not types:
            return 0
        cutoff = self.now() - fenetre_s
        trous = ",".join("?" * len(types))
        with self._conn() as cx:
            row = cx.execute(
                f"SELECT COUNT(*) FROM usage WHERE user_id=? AND horodatage>=? "
                f"AND type IN ({trous})", (user_id, cutoff, *types)).fetchone()
        return int(row[0])

    def reserver(self, user_id: str, type: str) -> int:
        """Inscrit l'appel AVANT qu'il ne soit paye, a cout nul. Rend l'identifiant de
        ligne, a solder ensuite.

        Sans reservation, dix requetes concurrentes passent toutes le controle avant que
        la premiere ne soit enregistree : le limiteur ne brideait que le rythme d'un
        client sequentiel, c'est-a-dire personne. `n_analyses=0` reste juste -- ces appels
        COMPLETENT une analyse deja comptee, ils n'en consomment pas une seconde."""
        with self._conn() as cx:
            cur = cx.execute(
                "INSERT INTO usage (user_id, type, cout_usd, n_analyses, horodatage) "
                "VALUES (?, ?, 0.0, 0, ?)", (user_id, type, self.now()))
            return int(cur.lastrowid)

    def solder(self, ligne_id: int, cout_usd: float) -> None:
        """Inscrit le cout REEL sur une reservation. Une reservation jamais soldee reste a
        zero dollar : elle consomme du debit (l'appel a bien eu lieu) sans facturer ce qui
        n'a pas ete depense."""
        with self._conn() as cx:
            cx.execute("UPDATE usage SET cout_usd=? WHERE id=?", (cout_usd, ligne_id))

    def autorise(self, user_id: str, n_analyses: int = 1) -> bool:
        """Vérifié AVANT de dépenser. Sans plafond configuré : toujours autorisé (mais
        l'usage reste journalisé via enregistrer(), jamais un silence sur la dépense)."""
        if self.plafond_analyses is None:
            return True
        r = self.resume(user_id)
        return (r.n_analyses + n_analyses) <= self.plafond_analyses
