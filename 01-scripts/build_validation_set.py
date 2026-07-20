"""build_validation_set.py — CLI qui enchaîne rayon -> classification -> export xlsx pour
constituer le set de ~50 livres que Baptiste corrige (protocole M4-3). fetch_shelf et
classify sont injectables (aucun réseau en unit-test) ; sans eux, l'usage réel (main())
branche le provider DataForSEO et le classifieur LLM réels."""
from pathlib import Path

from fiction_classifier import classify_books
from fiction_validation import export_validation
from models import EnrichedBook, FictionNiche, TropeClassification


def build_set(niches: list[FictionNiche], path, fetch_shelf=None, classify=None,
             n_top: int = 20, cache=None, cost=None, version: str = "fr_v1") -> int:
    """Pour chaque niche : rayon -> livres. Déduplique par ASIN ENTRE niches (une même
    fiche vue sur deux trios ne compte, ni ne se fait classer, qu'une fois). Ignore les
    livres sans blurb (rien à classifier, cf. classify_books). Classe par lots groupés par
    sous-genre (la taxonomie autorisée dépend du sous-genre), exporte, affiche le coût
    réel. Rend le nombre de livres effectivement retenus dans le set."""
    fetch_shelf = fetch_shelf or _default_fetch_shelf
    classify = classify or classify_books

    vus: dict[str, EnrichedBook] = {}
    groupes: dict[str, list[EnrichedBook]] = {}     # sous_genre -> livres (1re niche vue)
    for niche in niches:
        shelf = fetch_shelf(niche, n_top=n_top, cache=cache, cost=cost, version=version)
        for b in shelf.books:
            if not b.blurb or b.asin in vus:
                continue                            # sans blurb : rien à classifier
            vus[b.asin] = b
            groupes.setdefault(niche.sous_genre, []).append(b)

    classifications: list[TropeClassification] = []
    for sous_genre_cle, livres in groupes.items():
        classifications.extend(classify(livres, sous_genre_cle, version=version) or [])

    livres_finaux = list(vus.values())
    sous_genre_export = niches[0].sous_genre if niches else ""
    export_validation(livres_finaux, classifications, sous_genre_export, path, version=version)

    if cost is not None:
        print(f"Coût réel du run : {cost.total_usd():.4f} $")
    return len(livres_finaux)


def _default_fetch_shelf(niche, **kw):
    """Provider réel (DataForSEO), construit paresseusement — jamais atteint en test,
    fetch_shelf y est toujours injecté."""
    from fiction_serp_provider import fetch_fiction_shelf
    from search_providers import DataForSEOProvider
    return fetch_fiction_shelf(niche, DataForSEOProvider(), **kw)


def main() -> None:
    """Usage réel : génère des trios pour un sous-genre (ideator), reconstitue leurs rayons,
    classe les blurbs et exporte le xlsx de validation."""
    import argparse
    from datetime import date

    from cost_tracker import CostTracker
    from fiction_ideator import generate_trios

    ap = argparse.ArgumentParser(description="Constitue un set de livres classifiés pour "
                                             "la validation manuelle du classifieur (M4).")
    ap.add_argument("--sous-genre", required=True, help="clé de sous-genre (ex. cosy_mystery)")
    ap.add_argument("--n-niches", type=int, default=5, help="nombre de trios à générer")
    ap.add_argument("--out", default=None, help="chemin du xlsx de sortie")
    args = ap.parse_args()

    cost = CostTracker()
    niches = generate_trios(args.sous_genre, n=args.n_niches,
                            on_usage=lambda i, o, m: cost.add_llm(m, i, o))
    classify_avec_cout = lambda bks, sg, **kw: classify_books(
        bks, sg, on_usage=lambda i, o, m: cost.add_llm(m, i, o), **kw)

    out = Path(args.out) if args.out else Path(f"validation-fiction-{date.today().isoformat()}.xlsx")
    n = build_set(niches, out, classify=classify_avec_cout, cost=cost)
    print(f"{n} livres exportés vers {out}")


if __name__ == "__main__":
    main()
