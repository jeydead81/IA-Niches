"""scout_master.py — orchestrateur du scout v2. Enchaîne toutes les briques :
ideator (niches IA) → validation demande (autocomplete, gratuit) → search (DataForSEO, gaté)
→ BSR réel (fiches produit, gratuit) → scoring 3 axes (§4.1) → niches classées.

`run_scout()` est appelable par la CLI ET par l'UI. `progress(msg)` = callback de suivi
(affichage CLI ou stream UI). Toutes les dépendances lourdes sont injectables (tests hors-ligne).
"""
import argparse
import time

from dotenv import load_dotenv

from amazon_product import fetch_bsr as _fetch_bsr
from models import ScoredNiche
from niche_ideator import generate_niches as _generate_niches
from niche_validator import validate_niches as _validate_niches
from scoring import score_niche
from search_providers import get_provider


def _noop(_msg: str) -> None:
    pass


def run_scout(seed: str | None = None, signals: dict | None = None,
              n_ideas: int = 12, n_search: int = 6, n_bsr_per_niche: int = 5,
              model: str | None = None, provider=None, progress=None,
              bsr_pause: float = 0.5,
              ideate=None, validate=None, fetch_bsr_fn=None) -> list[ScoredNiche]:
    """Lance le scout complet et renvoie les niches scorées (triées par score global).

    Coût : ~n_search appels DataForSEO (~0,003 $ chacun) ; ideator ~0,02 € ; le reste gratuit.
    """
    progress = progress or _noop
    ideate = ideate or _generate_niches
    validate = validate or _validate_niches
    fetch_bsr_fn = fetch_bsr_fn or _fetch_bsr
    load_dotenv()

    # 1) Ideator
    progress(f"Génération de niches par l'IA (graine : {seed or 'aucune'})…")
    candidates = ideate(seed=seed, signals=signals, n=n_ideas, model=model)
    progress(f"{len(candidates)} niches proposées par l'IA.")

    # 2) Validation de la demande (gratuit, autocomplete)
    progress("Validation de la demande sur Amazon (autocomplete, gratuit)…")
    validations = validate(candidates, pause=0.4, max_queries=3)
    validated = [v for v in validations if v.validated]
    progress(f"{len(validated)}/{len(validations)} niches avec demande confirmée.")

    # 3) Search payant, GATÉ au top-demande ; 4) BSR gratuit ; 5) Scoring
    shortlist = validated[:n_search]
    if shortlist:
        provider = provider or get_provider("dataforseo")
    scored: list[ScoredNiche] = []
    for i, v in enumerate(shortlist, 1):
        q = v.requete_amazon or v.niche
        progress(f"[{i}/{len(shortlist)}] Concurrence Amazon « {q} »…")
        try:
            sr = provider.search(q)
        except Exception as e:  # noqa: BLE001 — on n'interrompt jamais le run
            progress(f"  ⚠ search échec ({e}) — niche scorée sans concurrence.")
            sr = None
        bsrs: list[int] = []
        asins = [o.asin for o in (sr.organic if sr else []) if o.asin][:n_bsr_per_niche]
        for asin in asins:
            info = fetch_bsr_fn(asin)
            if info and info.rank_livres:
                bsrs.append(info.rank_livres)
            if bsr_pause:
                time.sleep(bsr_pause)
        scored.append(score_niche(v, sr, bsrs))

    scored.sort(key=lambda s: s.global_score, reverse=True)
    progress("Scout terminé.")
    return scored


def _print_row(s: ScoredNiche) -> None:
    crit = "✓§4.1" if s.criteres_bsr_ok else "  -  "
    print(f"  {s.global_score:>4}/10  {s.verdict}  {s.niche}  [{s.categorie}]")
    print(f"        demande {s.demande} · pénétration {s.penetration} · {crit} · "
          f"BSR top {s.bsr_best} (moy5 {s.bsr_top5_avg}) · concurrents {s.n_concurrents_cibles} · "
          f"sponso écartés {s.n_sponsored}")


def main() -> None:
    p = argparse.ArgumentParser(description="Scout de niches KDP v2")
    p.add_argument("--seed", help="graine (mot-clé). Sinon mode 'à partir de rien'.")
    p.add_argument("--ideas", type=int, default=12, help="nb de niches générées par l'IA")
    p.add_argument("--search", type=int, default=6, help="nb de niches passées au search payant")
    args = p.parse_args()
    results = run_scout(seed=args.seed, n_ideas=args.ideas, n_search=args.search, progress=print)
    print("\n=== NICHES CLASSÉES ===")
    for s in results:
        _print_row(s)


if __name__ == "__main__":
    main()
