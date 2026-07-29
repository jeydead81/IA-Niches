"""fiction_master.py — run_fiction_scout : orchestrateur fiction en 6 étapes.

A. ideator            -> N trios                       (1 appel LLM)
B. N x SERP           -> ASIN par niche                (rapide, pas de file)
C. UN batch ASIN      -> tous les livres, dédupliqués  (la file, payée UNE fois)
D. classification     -> groupée (un seul sous-genre pour tout le run)
E. sonde autocomplete -> par niche                      (gratuit)
F. scoring            -> rapports triés

LE point du module : la file DataForSEO (~250 s quel que soit le nb d'ASIN dans le lot)
est payée UNE SEULE FOIS pour tout le run, jamais une fois par niche (42 min -> 5 min sur
10 niches, cf. plan M6). Bonus : la dédup des ASIN devient inter-niches — deux trios du
même sous-genre partagent souvent des livres.

Mêmes conventions que scout_master.run_scout : dépendances injectables (aucun réseau en
unit-test), callback progress(str), CostTracker optionnel, CLI main()."""
import argparse

from dotenv import load_dotenv

from cache import CLASSIFICATION_TTL_S
from cost_tracker import CostTracker
from fiction_autocomplete import probe_niche as _probe_niche
from fiction_classifier import DEFAULT_MODEL as _CLASSIFIER_MODEL
from fiction_classifier import classify_books as _classify_books
from fiction_ideator import generate_trios as _generate_trios
from fiction_scoring import build_report
from fiction_serp_provider import enrich_asins as _enrich_asins
from fiction_serp_provider import fetch_shelf_asins as _fetch_shelf_asins
from models import FictionNicheReport, FictionShelf


def _noop(_msg: str) -> None:
    pass


def run_fiction_scout(sous_genre_cle: str, n_niches: int = 8, rayon: str = "kindle",
                      version: str = "fr_v1", n_top: int = 12, depth: int = 30,
                      model: str | None = None,
                      ideate=None, serp_fn=None, enrich_fn=None, classify=None, probe=None,
                      cache=None, use_cache: bool = True, cache_path: str | None = None,
                      cost=None, progress=None) -> list[FictionNicheReport]:
    """Scout fiction complet pour UN sous-genre (plusieurs trios). Rend les rapports
    triés par intérêt (profondeur décroissante, saturation croissante à profondeur égale).

    Coût mesurable via `cost` (CostTracker fourni par l'appelant, ou créé ici)."""
    progress = progress or _noop
    ideate = ideate or _generate_trios
    classify = classify or _classify_books
    probe = probe or _probe_niche
    cost = cost if cost is not None else CostTracker()
    load_dotenv()

    # serp_fn/enrich_fn par défaut : provider réel construit UNE fois, partagé par les deux
    # (jamais atteint en test, ils y sont toujours injectés).
    if serp_fn is None or enrich_fn is None:
        from search_providers import DataForSEOProvider
        _provider = DataForSEOProvider()
        if serp_fn is None:
            serp_fn = lambda niche, **kw: _fetch_shelf_asins(niche, _provider, **kw)  # noqa: E731
        if enrich_fn is None:
            enrich_fn = lambda asins, **kw: _enrich_asins(asins, _provider, **kw)  # noqa: E731

    if use_cache and cache is None:
        from pathlib import Path

        from cache import Cache
        _root = Path(__file__).resolve().parent.parent
        cache = Cache(cache_path or (_root / "99-logs" / "df-cache.db"))

    # A) Ideator — 1 seul appel LLM pour tous les trios de ce sous-genre.
    progress(f"Génération de {n_niches} trios pour « {sous_genre_cle} »…")
    niches = ideate(sous_genre_cle, n=n_niches, rayon=rayon, version=version, model=model,
                    on_usage=lambda i, o, m: cost.add_llm(m, i, o))
    progress(f"{len(niches)} trios générés.")

    # B) N x SERP — rapide, isolée par niche : une niche qui lève est ÉCARTÉE, les rayons
    # DÉJÀ PAYÉS des niches précédentes ne sont pas perdus (CLAUDE.md §10.11).
    par_niche: list[tuple] = []          # [(niche, search_param, [asins])]
    n_niches_echouees = 0
    for i, niche in enumerate(niches, 1):
        progress(f"[{i}/{len(niches)}] SERP « {niche.query} »…")
        try:
            sp, asins = serp_fn(niche, n_top=n_top, depth=depth, cost=cost, version=version)
        except Exception as e:  # noqa: BLE001 — une niche en échec ne coule pas le run
            n_niches_echouees += 1
            progress(f"  ⚠ échec SERP sur « {niche.query} » : {e} — niche écartée, "
                     f"rayons déjà payés conservés.")
            continue
        par_niche.append((niche, sp, asins))

    if not par_niche:
        progress("Scout fiction terminé : aucun rayon exploitable.")
        return []

    # C) UN SEUL batch ASIN sur l'union DÉDUPLIQUÉE de toutes les niches — LE point du
    # module. dict.fromkeys préserve l'ordre en dédupliquant.
    all_asins = list(dict.fromkeys(a for _, _, asins in par_niche for a in asins))
    total_demande = sum(len(asins) for _, _, asins in par_niche)
    economises = total_demande - len(all_asins)
    progress(f"Enrichissement de {len(all_asins)} ASIN uniques en UN seul batch "
             f"({economises} économisé(s) par dédup inter-niches, sur {total_demande} "
             f"demandés)…")
    enriched = enrich_fn(all_asins, cache=cache, cost=cost, progress=progress)

    # D) Classification groupée — un seul sous-genre pour tout le run, donc un seul appel
    # (par lots de LOT_MAX côté classify_books), pas un groupement par sous-genre comme
    # build_validation_set (qui, lui, mélange plusieurs sous-genres).
    livres_avec_blurb = {a: b for a, b in enriched.items() if b.blurb}

    # Cache des classifications : une étiquette est DÉTERMINISTE pour un (livre, taxonomie,
    # modèle, prompt) donné — la clé porte les quatre. Sans ça, explorer deux fois le même
    # sous-genre (le cas normal) repaie les mêmes blurbs, et en SaaS chaque client repaie
    # ceux de tous les autres. C'est le poste LLM dominant d'un run fiction.
    modele_clf = model or _CLASSIFIER_MODEL
    classifications: dict = {}
    a_classer = []
    for asin, livre in livres_avec_blurb.items():
        connue = cache.get_classification(asin, version, modele_clf) if cache else None
        if connue is not None:
            classifications[asin] = connue
        else:
            a_classer.append(livre)

    deja = len(classifications)
    if deja:
        progress(f"{deja} quatrième(s) de couverture déjà classée(s) — non repayée(s).")
    if a_classer:
        progress(f"Classification de {len(a_classer)} quatrièmes de couverture…")
        for c in classify(a_classer, sous_genre_cle, version=version, model=model,
                          on_usage=lambda i, o, m: cost.add_llm(m, i, o),
                          progress=progress) or []:
            classifications[c.asin] = c
            if cache:
                cache.set_classification(c.asin, version, modele_clf, c,
                                         CLASSIFICATION_TTL_S)

    # E) Sonde autocomplete (gratuite, par niche) + reconstruction du rayon depuis la table
    # globale + F) scoring.
    rapports: list[FictionNicheReport] = []
    for niche, sp, asins in par_niche:
        books = []
        for pos, a in enumerate(asins, 1):
            b = enriched.get(a)
            if b is not None:
                b.serp_position = pos        # position propre à CETTE niche, pas au batch global
                books.append(b)
        n_echecs = len(asins) - len(books)
        if n_echecs:
            progress(f"  ⚠ « {niche.query} » : {n_echecs}/{len(asins)} ASIN non enrichis — "
                     f"rayon incomplet, ne pas lire comme une niche déserte.")
        shelf = FictionShelf(niche=niche, search_param=sp, books=books,
                             asins_demandes=len(asins), n_echecs=n_echecs)

        progress(f"Sonde autocomplete « {niche.query} »…")
        signal = probe(niche, version=version)

        rapports.append(build_report(niche, shelf, classifications, signal,
                                     version=version, cost=cost))

    # Tri par intérêt : profondeur décroissante, saturation croissante à profondeur égale.
    rapports.sort(key=lambda r: (r.depth_score, -r.saturation_trio), reverse=True)

    if n_niches_echouees:
        progress(f"{n_niches_echouees} niche(s) en échec sur {len(niches)} — rayons déjà "
                 f"payés conservés.")
    b = cost.breakdown()
    progress(f"Scout fiction terminé. Coût ~{b['usd']:.4f} $ "
             f"({b['dataforseo_calls']} appels DataForSEO + LLM).")
    return rapports


def main() -> None:
    ap = argparse.ArgumentParser(description="Scout fiction KDP — un sous-genre, N trios, "
                                             "un seul batch ASIN pour tout le run.")
    ap.add_argument("--sous-genre", required=True, help="clé de sous-genre (ex. cosy_mystery)")
    ap.add_argument("--n-niches", type=int, default=8, help="nombre de trios générés par l'IA")
    ap.add_argument("--rayon", default="kindle", help="kindle | papier")
    args = ap.parse_args()

    cost = CostTracker()
    rapports = run_fiction_scout(args.sous_genre, n_niches=args.n_niches, rayon=args.rayon,
                                 progress=print, cost=cost)
    print("\n=== NICHES FICTION CLASSÉES ===")
    for r in rapports:
        print(f"  {r.demand_matrix:<18} depth={r.depth_score:.2f}  "
              f"openness={r.openness_score:.2f}  saturation_trio={r.saturation_trio:.2f}  "
              f"« {r.niche.query} »")
    b = cost.breakdown()
    print(f"\nCoût du run : ~{b['usd']:.4f} $  "
          f"(DataForSEO {b['dataforseo_usd']:.4f} $ / LLM {b['llm_usd']:.4f} $)")


if __name__ == "__main__":
    main()
