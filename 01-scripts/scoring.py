"""scoring.py — scoring 3 axes d'une niche, avec les critères BSR §4.1 de Baptiste.
Fonctions PURES et testées ; consomme les modèles normalisés (NicheValidation,
SearchResult, liste de BSR du top organique).

Axes : Demande (0.4) · Pénétration (0.4) · Compatibilité livre (0.2).
"""
import re

from models import NicheValidation, SearchResult, ScoredNiche


def bsr_stats(bsrs: list[int]) -> dict:
    """Statistiques BSR + critères §4.1 sur les BSR du top organique.
    §4.1 : (1) ≥1 BSR < 10 000, (2) moyenne du top < 50 000, (3) ≥1 BSR > 50 000.
    NB : le scout ne récupère que le top-3 (n_bsr_per_niche=3) pour maîtriser le coût ;
    'top5_avg' est donc la moyenne des ≤3 BSR disponibles et 'worst_top10' leur max.
    Les 3 critères restent discriminants sur 3 points."""
    vals = sorted(b for b in bsrs if isinstance(b, int) and b > 0)
    if not vals:
        return {"best": None, "top5_avg": None, "worst_top10": None,
                "crit1": False, "crit2": False, "crit3": False, "ok": False}
    top5, top10 = vals[:5], vals[:10]
    best = vals[0]
    top5_avg = int(sum(top5) / len(top5))
    worst10 = max(top10)
    crit1 = best < 10_000
    crit2 = top5_avg < 50_000
    crit3 = worst10 > 50_000
    return {"best": best, "top5_avg": top5_avg, "worst_top10": worst10,
            "crit1": crit1, "crit2": crit2, "crit3": crit3,
            "ok": crit1 and crit2 and crit3}


def _clamp(x: float, lo: float = 1.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, x))


def count_targeted(query: str, items) -> int:
    """Nb de livres organiques dont le titre CIBLE vraiment la requête (concurrents §4.2)."""
    words = re.findall(r"[a-zàâçéèêëîïôùûüæœ]{4,}", (query or "").lower())
    if not words:
        return 0
    need = max(1, len(words) // 2)
    return sum(1 for it in items
               if sum(1 for w in words if w in (it.title or "").lower()) >= need)


def score_niche(validation: NicheValidation, search: SearchResult | None,
                bsrs: list[int]) -> ScoredNiche:
    """Calcule le score 3 axes d'une niche à partir de la demande (autocomplete),
    de la concurrence (search) et du BSR réel du top organique."""
    stats = bsr_stats(bsrs)
    organic = search.organic if search else []
    sponsored = search.sponsored if search else []
    ratings = [o.rating for o in organic if o.rating]
    reviews = [o.reviews_count for o in organic if o.reviews_count]
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None
    total_reviews = sum(reviews) if reviews else None
    n_cibles = count_targeted(validation.requete_amazon or validation.niche, organic)

    # ── AXE 1 — Demande ──
    demande = _clamp(2 + min(validation.demand_score, 10) * 0.6)
    if stats["best"] is not None:
        demande = _clamp(demande + (2 if stats["best"] < 5_000 else 1 if stats["best"] < 10_000 else 0))
    if stats["ok"]:
        demande = _clamp(demande + 1)
    if total_reviews and total_reviews > 5_000:
        demande = _clamp(demande + 1)

    # ── AXE 2 — Pénétration (haut = facile à pénétrer) ──
    penetration = 5.0
    if n_cibles > 50:
        penetration -= 2
    elif n_cibles > 30:
        penetration -= 1
    elif n_cibles < 10:
        penetration += 2
    if stats["crit3"]:
        penetration += 1.5                       # "place à prendre"
    if len(sponsored) >= 3:
        penetration += 0.5                       # bcp de sponso => concurrence organique + faible
    penetration = _clamp(penetration)

    # ── AXE 3 — Compatibilité livre (l'ideator garantit déjà le format livre) ──
    compatibilite = 8.0

    glob = round(demande * 0.4 + penetration * 0.4 + compatibilite * 0.2, 2)
    verdict = ("🟢 À analyser en priorité" if glob >= 7.5
               else "🟡 Intéressant" if glob >= 6.0 else "🔴 Faible")

    return ScoredNiche(
        niche=validation.niche, requete_amazon=validation.requete_amazon,
        categorie=validation.categorie, satellite_keywords=validation.satellite_keywords,
        global_score=glob, demande=round(demande, 2), penetration=round(penetration, 2),
        compatibilite=compatibilite, verdict=verdict,
        demand_autocomplete=validation.demand_score,
        n_organic=len(organic), n_sponsored=len(sponsored), n_concurrents_cibles=n_cibles,
        avg_rating=avg_rating, total_reviews=total_reviews,
        bsr_best=stats["best"], bsr_top5_avg=stats["top5_avg"],
        bsr_worst_top10=stats["worst_top10"], criteres_bsr_ok=stats["ok"],
        top_asins=[o.asin for o in organic[:5] if o.asin],
    )
