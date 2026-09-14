"""scout_master.py — orchestrateur du scout v2. Enchaîne toutes les briques :
ideator (niches IA) → validation demande (autocomplete, gratuit) → search (DataForSEO, gaté)
→ BSR réel (fiches produit, gratuit) → scoring 3 axes (§4.1) → niches classées.

`run_scout()` est appelable par la CLI ET par l'UI. `progress(msg)` = callback de suivi
(affichage CLI ou stream UI). Toutes les dépendances lourdes sont injectables (tests hors-ligne).
"""
import argparse
import os

from dotenv import load_dotenv

from bsr_source import resolve_bsrs
from cache import Cache
from cost_tracker import CostTracker, PlafondCoutAtteint, dataforseo_cost_usd
from marketplace import ACTIF
from models import ScoredNiche
from niche_ideator import generate_niches as _generate_niches
from niche_validator import validate_niches as _validate_niches
from niche_verdict import generate_verdict as _generate_verdict
from scoring import score_niche
from search_providers import RefusCompte, TaskPostRefuse, get_provider


def _noop(_msg: str) -> None:
    pass


_SEARCH_TTL_S = 15 * 24 * 3600


def run_scout(seed: str | None = None, signals: dict | None = None,
              n_ideas: int = 12, n_search: int = 6, n_bsr_per_niche: int = 3,
              model: str | None = None, provider=None, progress=None,
              bsr_pause: float = 0.4, books_only: bool = True,
              use_cache: bool = True, cache_path: str | None = None,
              bsr_source: str | None = None, bsr_priority: int = 2,
              n_verdict: int = 0, verdict_model: str | None = None, verdict_fn=None,
              cost=None, ideate=None, validate=None, fetch_bsr_fn=None) -> list[ScoredNiche]:
    """Scout complet, 3 phases : ideator → validation demande → [search par niche] →
    [BSR batché global : dédup + cache] → scoring §4.1. Renvoie les niches triées.

    Coût mesurable via `cost` (CostTracker fourni par l'appelant). BSR gratuit en local
    (BSR_SOURCE=scrape), payant/fiable en serveur (BSR_SOURCE=dataforseo)."""
    progress = progress or _noop
    ideate = ideate or _generate_niches
    validate = validate or _validate_niches
    verdict_fn = verdict_fn or _generate_verdict
    cost = cost if cost is not None else CostTracker()
    load_dotenv()

    cache = None
    if use_cache:
        # Le répertoire vient de `storage` : en hébergement, le cache doit suivre le
        # volume persistant comme les quatre autres bases. C'est celle dont la perte est
        # la plus discrète — rien ne lève, rien ne s'affiche, tout le monde repaie
        # simplement ce qui était déjà acheté (cache.py : magasin MUTUALISÉ).
        import storage
        cache = Cache(cache_path or storage.base("df-cache.db"))

    # 1) Ideator (coût LLM réel via on_usage)
    progress(f"Génération de niches par l'IA (graine : {seed or 'aucune'})…")
    candidates = ideate(seed=seed, signals=signals, n=n_ideas, model=model,
                        on_usage=lambda i, o, m: cost.add_llm(m, i, o))
    progress(f"{len(candidates)} niches proposées par l'IA.")

    # 2) Validation demande (gratuit, autocomplete)
    progress("Validation de la demande sur Amazon (autocomplete, gratuit)…")
    validations = validate(candidates, pause=0.4, max_queries=3)
    validated = [v for v in validations if v.validated]
    progress(f"{len(validated)}/{len(validations)} niches avec demande confirmée.")

    shortlist = validated[:n_search]
    if not shortlist:
        progress("Scout terminé.")
        return []
    provider = provider or get_provider("dataforseo")
    loc = getattr(provider, "location_code", ACTIF.location_code)
    lang = getattr(provider, "language_code", ACTIF.language_code)

    # Phase A — concurrence Amazon par niche (search, caché par mot-clé)
    per_niche = []          # (validation, SearchResult|None, [asins top-n])
    all_asins: list[str] = []
    n_non_traitees = 0
    prio = getattr(provider, "priority", 2)
    # Refus de COMPTE : même traitement que lowcontent_master — plus aucun appel au
    # fournisseur, le cache continue de servir ce qui est déjà acheté.
    compte_refuse: str | None = None
    n_non_mesurees_compte = 0
    for i, v in enumerate(shortlist, 1):
        q = v.requete_amazon or v.niche
        progress(f"[{i}/{len(shortlist)}] Concurrence Amazon « {q} »…")
        sr = cache.get_search(q, loc, lang) if cache else None
        if sr is None and compte_refuse is not None:
            n_non_mesurees_compte += 1
            per_niche.append((v, None, []))
            continue
        if sr is None:
            # Le plafond se vérifie AVANT l'appel, et seulement sur un défaut de cache :
            # une niche servie par le cache ne coûte rien, l'arrêter serait arbitraire.
            # Vérifier APRÈS coup signalerait un dépassement déjà payé.
            try:
                cost.verifier(dataforseo_cost_usd(1, prio))
            except PlafondCoutAtteint as e:
                n_non_traitees = len(shortlist) - i + 1
                progress(f"  ⚠ {e}")
                break
            try:
                sr = provider.search(q, books_only=books_only)
            except RefusCompte as e:
                compte_refuse = str(e)
                n_non_mesurees_compte += 1
                progress(f"  ⚠ {e} — plus aucun appel au fournisseur, cache seul.")
                sr = None
            except BaseException as e:  # noqa: BLE001 — on n'interrompt jamais le run
                # Tâche CRÉÉE puis non lue : facturée. Seul un refus explicite ne l'est pas.
                if not isinstance(e, TaskPostRefuse):
                    cost.add_dataforseo(1, prio)
                if not isinstance(e, Exception):
                    raise
                progress(f"  ⚠ search échec ({e}) — niche scorée sans concurrence.")
                sr = None
            else:
                cost.add_dataforseo(1, prio)
                if cache:
                    try:
                        cache.set_search(q, loc, lang, sr, _SEARCH_TTL_S)
                    except Exception as e:  # noqa: BLE001 — la SERP est lue, et payée
                        progress(f"  ⚠ SERP non mise en cache ({e}).")
        asins = [o.asin for o in (sr.organic if sr else []) if o.asin][:n_bsr_per_niche]
        per_niche.append((v, sr, asins))
        all_asins.extend(asins)

    # Phase B — BSR global (batché, dédup + cache)
    bsr_map = {}
    _src = (bsr_source or os.getenv("BSR_SOURCE", "scrape")).strip().lower()
    try:
        cost.verifier()
        progress(f"Récupération des BSR ({len(set(all_asins))} livres uniques)…")
        if compte_refuse and fetch_bsr_fn is None and _src == "dataforseo":
            # Le canal payant est le même compte : il serait refusé à l'identique.
            progress("  ⚠ BSR non récupérés : compte DataForSEO refusé.")
        else:
            bsr_map = resolve_bsrs(all_asins, source=bsr_source, provider=provider,
                                   fetch_bsr_fn=fetch_bsr_fn, cache=cache, location=loc,
                                   bsr_priority=bsr_priority, cost=cost,
                                   bsr_pause=bsr_pause, progress=progress)
    except PlafondCoutAtteint as e:
        # Sans BSR, `bsr_stats` rend crit1/2/3 à False : aucun bonus « place à prendre »
        # n'est accordé sur une absence de mesure. Le rayon ressort donc prudent, pas
        # flatteur — c'est l'invariant §5.29, pas un effet de bord.
        progress(f"  ⚠ {e} — BSR non récupérés, niches scorées sans classement.")

    # Phase C — scoring
    pairs = []          # (ScoredNiche, SearchResult|None)
    for v, sr, asins in per_niche:
        bsrs = [bsr_map[a].rank_livres for a in asins
                if bsr_map.get(a) and bsr_map[a].rank_livres]
        # bsr_map complet (pas seulement les `asins` du lot BSR) : un livre du top sans
        # classement resolu doit ressortir avec bsr=None, jamais absent de la liste.
        rangs = {a: info.rank_livres for a, info in bsr_map.items()
                 if info and info.rank_livres}
        # Les sous-categories viennent de la MEME fiche que le rang, deja payee. Les
        # laisser derriere obligerait le Dossier PDF a re-interroger Amazon pour une
        # donnee qu'on tient deja.
        subcats = {a: (info.subcategories or []) for a, info in bsr_map.items() if info}
        pairs.append((score_niche(v, sr, bsrs, bsr_map=rangs, subcats_map=subcats), sr))
    pairs.sort(key=lambda p: p[0].global_score, reverse=True)

    # Verdict IA (directeur éditorial) : n_verdict=0 PAR DÉFAUT. Mesuré à 0,0283 $ pièce
    # (85 % en tokens de sortie), 3 verdicts pesaient 78 % du coût d'un run — payés pour
    # les 3 premières niches alors que l'utilisateur n'en lit qu'une. Il se demande
    # désormais sur la niche choisie (POST /api/verdict) ; n_verdict>0 les pré-génère.
    if n_verdict:
        for sc, sr in pairs[:n_verdict]:
            progress(f"Verdict éditorial : {sc.niche}…")
            try:
                sc.verdict = verdict_fn(sc, sr, model=verdict_model,
                                        on_usage=lambda i, o, m: cost.add_llm(m, i, o))
            except Exception as e:  # noqa: BLE001 — un échec de verdict ne coule pas le run (§11.11)
                progress(f"  ⚠ verdict indisponible ({e})")

    scored = [sc for sc, _ in pairs]
    if n_non_mesurees_compte:
        progress(f"⚠ {n_non_mesurees_compte} niche(s) non mesurée(s) : compte DataForSEO "
                 f"refusé ({compte_refuse}).")
    b = cost.breakdown()
    # Le MONTANT ne passe plus par `progress` : ce canal alimente l'interface, qui ne
    # montre plus aucun coût en dollars (facturation à venir en jetons/abonnement). Le
    # coût reste intégralement mesuré dans `cost` et imputé côté serveur — c'est
    # l'AFFICHAGE qui disparaît, pas la comptabilité. La CLI, elle, l'imprime toujours
    # plus bas : c'est l'outil de contrôle du développeur, pas l'écran du client.
    if n_non_traitees:
        # Un rapport partiel MUET se lit comme un rapport complet : l'auteur croirait que
        # les niches manquantes ont été écartées sur mesure, alors qu'elles n'ont jamais
        # été regardées. On dit le nombre, pas seulement le fait.
        progress(f"Scout terminé — RAPPORT PARTIEL sur {len(scored)} niche(s) : "
                 f"{n_non_traitees} niche(s) non traitée(s), plafond de coût atteint "
                 f"({b['dataforseo_calls']} recherches Amazon).")
    else:
        progress(f"Scout terminé ({b['dataforseo_calls']} recherches Amazon).")
    return scored


def _print_row(s: ScoredNiche) -> None:
    crit = "✓§4.1" if s.criteres_bsr_ok else "  -  "
    print(f"  {s.global_score:>4}/10  {s.priorite}  {s.niche}  [{s.categorie}]")
    print(f"        demande {s.demande} · pénétration {s.penetration} · {crit} · "
          f"BSR top {s.bsr_best} (moy5 {s.bsr_top5_avg}) · concurrents {s.n_concurrents_cibles} · "
          f"sponso écartés {s.n_sponsored}")


def main() -> None:
    p = argparse.ArgumentParser(description="Scout de niches KDP v2")
    p.add_argument("--seed", help="graine (mot-clé). Sinon mode 'à partir de rien'.")
    p.add_argument("--ideas", type=int, default=12, help="nb de niches générées par l'IA")
    p.add_argument("--search", type=int, default=6, help="nb de niches passées au search payant")
    args = p.parse_args()
    cost = CostTracker()
    results = run_scout(seed=args.seed, n_ideas=args.ideas, n_search=args.search,
                        progress=print, cost=cost)
    print("\n=== NICHES CLASSÉES ===")
    for s in results:
        _print_row(s)
    b = cost.breakdown()
    print(f"\nCoût du run : ~{b['usd']:.4f} $  "
          f"(DataForSEO {b['dataforseo_usd']:.4f} $ / LLM {b['llm_usd']:.4f} $)")

    for s in results[:3]:
        if s.verdict:
            print(f"\n▸ {s.niche} — Verdict : {s.verdict.verdict} ({s.verdict.confiance}/10)")
            print(f"  Facteur décisif : {s.verdict.facteur_decisif}")
            for a in s.verdict.angles[:2]:
                print(f"  • « {a.titre} » — {a.sous_titre}")


if __name__ == "__main__":
    main()
