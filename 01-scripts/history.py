"""history.py — historique des niches et évolution entre deux passages.

C'est la seule fonction du produit qui répond à « est-ce que ça bouge ? ». Sans elle,
chaque run est un cliché isolé : un auteur ne peut pas voir qu'une niche qu'il visait
depuis trois mois s'est refermée entre-temps.

Deux exigences guident tout le module :
- un point unique n'est JAMAIS une tendance (on ne fabrique pas une évolution) ;
- une variation doit se lire en français, pas en delta brut : « +0,23 » ne fait pas agir,
  « la niche s'est densifiée » si.

Même motif SQLite que cache.py : connexion par appel + WAL, sûr en concurrence.
"""
import json
import sqlite3
import time
import unicodedata
from pathlib import Path

from pydantic import BaseModel, Field

# Métriques où une HAUSSE est une mauvaise nouvelle pour l'auteur. Le BSR est le piège
# classique : plus le nombre est grand, moins le livre se vend. La saturation aussi —
# c'est le seul score du scoring fiction dont le sens est inversé.
METRIQUES_INVERSEES = frozenset({"bsr_best", "bsr_top5_avg", "bsr_worst_top10",
                                 "saturation_trio", "n_concurrents_cibles"})

# En deçà, la variation est du bruit de mesure et non un mouvement de marché : l'annoncer
# ferait réagir un auteur sur du vent.
SEUIL_SIGNIFICATIF = 0.10


def cle_niche(libelle: str) -> str:
    """Clé stable : casse, espaces et accents dépouillés.

    Si « Cosy Mystery » et « cosy mystery » produisaient deux clés, on ne comparerait
    jamais deux passages sur la même niche et le module entier serait inopérant."""
    plat = unicodedata.normalize("NFKD", libelle or "")
    plat = "".join(c for c in plat if not unicodedata.combining(c))
    return " ".join(plat.split()).casefold()


class DeltaNiche(BaseModel):
    """Ce qui a changé entre les deux derniers passages sur une niche."""
    cle: str
    n_passages: int
    jours_ecoules: int
    variations: dict[str, float] = Field(default_factory=dict)   # métrique -> écart signé
    lecture: str = ""                                            # ce que ça veut dire


class NicheHistory:
    def __init__(self, path, now=None):
        self.path = str(path)
        self.now = now or time.time
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as cx:
            cx.execute("CREATE TABLE IF NOT EXISTS passages ("
                       "user_id TEXT NOT NULL, type TEXT NOT NULL, cle TEXT NOT NULL, "
                       "metriques TEXT NOT NULL, vu_le REAL NOT NULL)")
            cx.execute("CREATE INDEX IF NOT EXISTS idx_passages "
                       "ON passages (user_id, cle, vu_le)")

    def _conn(self):
        cx = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        cx.execute("PRAGMA journal_mode=WAL")
        return cx

    def enregistrer(self, user_id: str, type_: str, niche: str, metriques: dict) -> None:
        """Consigne un passage. `niche` est normalisé : c'est ce qui permet de retrouver
        la même niche d'un run à l'autre."""
        propres = {k: float(v) for k, v in (metriques or {}).items()
                   if isinstance(v, (int, float)) and not isinstance(v, bool)}
        with self._conn() as cx:
            cx.execute("INSERT INTO passages (user_id, type, cle, metriques, vu_le) "
                       "VALUES (?, ?, ?, ?, ?)",
                       (user_id, type_, cle_niche(niche),
                        json.dumps(propres, ensure_ascii=False), self.now()))

    def supprimer_utilisateur(self, user_id: str) -> int:
        """Efface tout ce qu'un compte a produit ici. Rend le nombre de lignes supprimées.

        Appelé par la clôture de compte (§2.1) : supprimer le compte sans ses données
        laisserait des lignes orphelines, rattachées à un `user_id` dont plus personne ne
        connaît l'adresse. Un compte qui n'a rien produit rend 0, sans lever — une clôture
        ne doit pas échouer sur une absence."""
        with self._conn() as cx:
            return cx.execute("DELETE FROM passages WHERE user_id=?", (user_id,)).rowcount

    def historique(self, user_id: str, niche: str) -> list[dict]:
        """Tous les passages sur cette niche, du plus ancien au plus récent."""
        with self._conn() as cx:
            lignes = cx.execute(
                "SELECT metriques, vu_le FROM passages WHERE user_id=? AND cle=? "
                "ORDER BY vu_le", (user_id, cle_niche(niche))).fetchall()
        return [{"metriques": json.loads(m), "vu_le": t} for m, t in lignes]

    def delta(self, user_id: str, niche: str) -> DeltaNiche | None:
        """Écart entre les DEUX derniers passages. None s'il n'y en a qu'un : un point
        unique n'est pas une tendance, et en inventer une serait exactement le travers
        qu'on combat partout ailleurs (CLAUDE.md §10)."""
        passages = self.historique(user_id, niche)
        if len(passages) < 2:
            return None
        avant, apres = passages[-2], passages[-1]

        # Seules les métriques présentes DES DEUX CÔTÉS sont comparables : en comparer une
        # qui n'existe que d'un côté fabriquerait une variation fictive.
        communes = set(avant["metriques"]) & set(apres["metriques"])
        variations = {k: apres["metriques"][k] - avant["metriques"][k] for k in communes}
        jours = int(round((apres["vu_le"] - avant["vu_le"]) / 86400))
        return DeltaNiche(cle=cle_niche(niche), n_passages=len(passages),
                          jours_ecoules=jours, variations=variations,
                          lecture=_lire(variations, jours))


def _lire(variations: dict, jours: int) -> str:
    """Traduit les écarts en français. « +0,23 » ne fait pas agir un auteur ; « la niche
    s'est densifiée » si.

    Le sens du signe dépend de la métrique : sur le BSR et la saturation, une HAUSSE est
    une mauvaise nouvelle. Lire le signe naïvement annoncerait « en hausse » à propos d'un
    marché en train de s'effondrer."""
    bouts = []
    for cle, ecart in sorted(variations.items(), key=lambda kv: -abs(kv[1])):
        if abs(ecart) < SEUIL_SIGNIFICATIF:
            continue
        pire = (ecart > 0) if cle in METRIQUES_INVERSEES else (ecart < 0)
        if cle == "saturation_trio":
            bouts.append("la niche s'est densifiée : plus de livres promettent la même chose"
                         if ecart > 0 else "la niche s'est dégagée")
        elif cle.startswith("bsr"):
            bouts.append("les meilleures ventes du rayon se vendent MOINS bien qu'avant"
                         if ecart > 0 else "les ventes du rayon se sont renforcées")
        elif cle == "n_concurrents_cibles":
            bouts.append("davantage de concurrents ciblent la requête"
                         if ecart > 0 else "moins de concurrents ciblent la requête")
        else:
            bouts.append(f"{cle} {'en recul' if pire else 'en progrès'} "
                         f"({ecart:+.2f})".replace(".", ","))
    if not bouts:
        return (f"Aucun mouvement significatif en {jours} jour(s) — "
                "la niche est stable.")
    return f"En {jours} jour(s) : " + " ; ".join(bouts) + "."
