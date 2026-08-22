"""lowcontent_master.py — orchestrateur du scout LOW-CONTENT.

Même squelette que les deux autres scouts, avec un ordre INVERSÉ en tête de chaîne :
l'autocomplete n'est plus la validation d'une idée du modèle, il en est la SOURCE.

Phases :
  0. ARBRE (gratuit)      — `expand()` depuis la graine, ou depuis un `pattern` du format.
                            Filtres IP et saisonnalité appliqués AVANT tout appel payant.
  1. CLASSEMENT (LLM)     — le modèle étiquette des requêtes réelles. Sans graine, il
                            PROPOSE, et chaque proposition repasse par l'arbre : en
                            idéation la demande est une hypothèse, pas une observation.
  2. VALIDATION (gratuit) — gate structurel (règle 9). En mode classement elle est déjà
                            acquise : re-sonder l'autocomplete pour confirmer ce qu'on
                            vient d'y lire serait payer du temps pour une tautologie.
  3. SERP par niche       — payant, gaté, plafond de coût vérifié entre deux niches.
  4. UN batch ASIN        — la file DataForSEO met ~250 s quel que soit le lot : la payer
                            une fois par niche ferait passer 6 niches de 5 à 25 min (§5.16).
  5. SCORING              — `score_lowcontent`, pur.

Invariant §5.29 : un échec n'interrompt jamais le run, il est toujours compté, et il ne se
lit jamais comme une mesure.
"""
import os

from dotenv import load_dotenv

from autocomplete_expand import expand as _expand
from bsr_source import resolve_bsrs
from cache import Cache
from cost_tracker import CostTracker, PlafondCoutAtteint, dataforseo_cost_usd
from fiction_serp_provider import enrich_asins as _enrich_asins
from ip_filter import filtrer_ip
from lowcontent_ideator import generate_lowcontent_niches as _generate
from lowcontent_scoring import score_lowcontent
from lowcontent_taxonomy import est_saisonnier, format_
from marketplace import ACTIF
from models import LowContentScored
from niche_validator import validate_niches as _validate_niches
from search_providers import get_provider

_SEARCH_TTL_S = 15 * 24 * 3600


def _noop(_msg: str) -> None:
    pass


def _graine(seed: str | None, format_cle: str | None, version: str) -> str:
    """La graine, ou le premier `pattern` du format débarrassé de son `{theme}`.

    Sans ça, choisir un format sans saisir de graine ne produirait rien du tout —
    l'utilisateur croirait à une panne alors qu'il a bien exprimé une intention."""
    if seed:
        return seed.strip()
    if format_cle:
        patron = format_(format_cle, version)["patterns"][0]
        return patron.replace("{theme}", "").strip()
    return ""


def _rang_shortlist(n_enfants: int | None, profondeur: int, demand: int) -> tuple:
    """Cle de tri de la shortlist -- c'est-a-dire de CE QU'ON PAIE.

    `n_enfants is None` = requete jamais sondee. Elle ne doit pas etre classee derriere une
    feuille dont on SAIT qu'elle est sterile : on ne sait rien d'elle, ce n'est pas la meme
    chose que savoir qu'elle est mauvaise. On la place donc au niveau d'un affinage,
    c'est-a-dire au-dessus d'un zero mesure et en dessous d'un signal reel."""
    connu = n_enfants is not None
    valeur = n_enfants if connu else 1
    return (valeur, profondeur, demand)


def run_lowcontent_scout(seed: str | None = None, format_cle: str | None = None,
                         n_ideas: int = 12, n_search: int = 6,
                         n_enrich_per_niche: int = 6, inclure_saisonnier: bool = False,
                         depth: int = 2, alphabet: bool = True, max_probes: int = 80,
                         version: str = "fr_v1", model: str | None = None,
                         provider=None, progress=None, use_cache: bool = True,
                         cache_path: str | None = None, cost=None, bsr_pause: float = 0.4,
                         bsr_source: str | None = None, fetch_bsr_fn=None,
                         expand_fn=None, ideate=None, validate=None,
                         enrich_fn=None) -> list[LowContentScored]:
    """Scout low-content complet. Rend les niches triées par score décroissant."""
    progress = progress or _noop
    expand_fn = expand_fn or _expand
    ideate = ideate or _generate
    validate = validate or _validate_niches
    enrich_fn = enrich_fn or _enrich_asins
    cost = cost if cost is not None else CostTracker()
    load_dotenv()

    if format_cle:
        format_(format_cle, version)          # lève AVANT toute dépense

    from pathlib import Path
    _root = Path(__file__).resolve().parent.parent
    cache = Cache(cache_path or (_root / "99-logs" / "df-cache.db")) if use_cache else None

    # ── Phase 0 — arbre d'autocomplete (gratuit) ──
    suggestions = []
    graine = _graine(seed, format_cle, version)
    if graine:
        progress(f"Lecture de ce qu'Amazon complète autour de « {graine} » (gratuit)…")
        suggestions = expand_fn(graine, depth=depth, alphabet=alphabet,
                                max_probes=max_probes, cache=cache, progress=progress)
        suggestions, rejets = filtrer_ip(suggestions)
        for s, terme in rejets:
            progress(f"  ⚠ écartée (marque « {terme} ») : « {s.requete} »")
        if not inclure_saisonnier:
            gardees = []
            for s in suggestions:
                if est_saisonnier(s.requete, version):
                    progress(f"  ⚠ écartée (saisonnière) : « {s.requete} »")
                else:
                    gardees.append(s)
            suggestions = gardees
        progress(f"{len(suggestions)} requête(s) réelle(s) retenue(s).")

    # ── Phase 1 — classement (ou idéation) ──
    progress("Classement des requêtes par l'IA…" if suggestions
             else "Génération de niches par l'IA (aucune graine)…")
    niches = ideate(seed=seed, format_cle=format_cle, suggestions=suggestions or None,
                    n=n_ideas, inclure_saisonnier=inclure_saisonnier, version=version,
                    model=model, on_usage=lambda i, o, m: cost.add_llm(m, i, o),
                    progress=progress)
    if not niches:
        progress("Scout low-content terminé : aucune niche exploitable.")
        return []
    progress(f"{len(niches)} niche(s) proposée(s).")

    # ── Phase 2 — validation ──
    if suggestions:
        # Déjà acquise : ces requêtes VIENNENT de l'autocomplete. Les re-sonder pour
        # « valider » ce qu'on vient d'y lire ferait attendre l'utilisateur pour confirmer
        # une tautologie. On reconstruit la validation depuis la mesure de l'arbre.
        from models import NicheValidation
        validations = [
            NicheValidation(niche=n.niche, requete_amazon=n.requete_amazon,
                            categorie=n.categorie,
                            satellite_keywords=n.satellite_keywords,
                            demand_score=max(1, n.n_enfants_autocomplete or 0),
                            validated=True)
            for n in niches]
    else:
        progress("Confrontation des propositions à Amazon (autocomplete, gratuit)…")
        # En idéation, chaque proposition doit être confrontée à l'arbre AVANT de coûter
        # une SERP : sans ça on paierait pour une demande inventée par le modèle.
        for n in niches:
            arbre = expand_fn(n.requete_amazon, depth=1, alphabet=False,
                              max_probes=6, cache=cache, progress=_noop)
            n.n_enfants_autocomplete = len(arbre)
        validations = validate(niches, pause=0.4, max_queries=3)

    par_requete = {n.requete_amazon: n for n in niches}
    validees = [v for v in validations if v.validated]
    progress(f"{len(validees)}/{len(validations)} niche(s) avec demande confirmée.")

    # Tri par ce que l'arbre a mesuré : une requête que les acheteurs affinent ENCORE
    # porte une intention plus forte. C'est le signal propre au low-content, il doit
    # décider de ce qu'on paie.
    def _rang(v):
        n = par_requete.get(v.requete_amazon)
        return _rang_shortlist(n.n_enfants_autocomplete if n else None,
                               n.profondeur_autocomplete if n else 0,
                               v.demand_score)

    shortlist = sorted(validees, key=_rang, reverse=True)[:n_search]
    if not shortlist:
        progress("Scout low-content terminé : aucune niche validée.")
        return []

    provider = provider or get_provider("dataforseo")
    loc = getattr(provider, "location_code", ACTIF.location_code)
    lang = getattr(provider, "language_code", ACTIF.language_code)

    # ── Phase 3 — SERP par niche (payant) ──
    par_niche = []
    tous_asins: list[str] = []
    n_non_traitees = 0
    for i, v in enumerate(shortlist, 1):
        q = v.requete_amazon or v.niche
        sr = cache.get_search(q, loc, lang) if cache else None
        if sr is None:
            try:
                cost.verifier(dataforseo_cost_usd(1, getattr(provider, "priority", 2)))
            except PlafondCoutAtteint as e:
                n_non_traitees = len(shortlist) - i + 1
                progress(f"  ⚠ {e}")
                break
            progress(f"[{i}/{len(shortlist)}] Concurrence Amazon « {q} »…")
            try:
                sr = provider.search(q, books_only=True)
                cost.add_dataforseo(1, getattr(provider, "priority", 2))
                if cache:
                    cache.set_search(q, loc, lang, sr, _SEARCH_TTL_S)
            except Exception as e:  # noqa: BLE001 — un échec ne coule jamais le run
                progress(f"  ⚠ search échec ({e}) — niche scorée sans concurrence.")
                sr = None
        asins = [o.asin for o in (sr.organic if sr else []) if o.asin][:n_enrich_per_niche]
        par_niche.append((v, sr, asins))
        tous_asins.extend(asins)

    # ── Phase 4 — UN SEUL batch ASIN ──
    enrichis: dict = {}
    union = list(dict.fromkeys(tous_asins))
    if union:
        try:
            cost.verifier()
            economises = len(tous_asins) - len(union)
            progress(f"Enrichissement de {len(union)} ASIN uniques en UN seul batch "
                     f"({economises} économisé(s) par dédup inter-niches)…")
            enrichis = enrich_fn(union, provider=provider, cache=cache, cost=cost,
                                 progress=progress) or {}
        except PlafondCoutAtteint as e:
            progress(f"  ⚠ {e} — éditeurs et pagination non lus.")
        except Exception as e:  # noqa: BLE001
            progress(f"  ⚠ enrichissement indisponible ({e}) — éditeurs non lus.")

    # ── BSR : LU DANS L'ENRICHISSEMENT, jamais re-payé ──
    # `enrich_asins` parse déjà le BSR de chaque fiche (`parse_enriched_book`). Appeler
    # `resolve_bsrs` sur la même union re-facturait CHAQUE ASIN une seconde fois quand
    # BSR_SOURCE=dataforseo : à la borne serveur, 240 ASIN au lieu de 120, soit 0,80 $ au
    # lieu de 0,44 $ sur un plafond de 0,60 $. Le gaspillage était invisible — rien dans le
    # rapport ne montrait qu'un ASIN avait été payé deux fois.
    rangs = {a: b.bsr for a, b in enrichis.items() if b and b.bsr}
    subcats = {}

    # Seuls les ASIN que l'enrichissement n'a PAS rendus valent un second passage : un
    # payload atypique est absent du dict (jamais une entrée factice), et leur classement
    # reste récupérable par le canal BSR — gratuit en local. Renoncer pour eux perdrait une
    # mesure encore atteignable ; les redemander TOUS ferait payer deux fois les autres.
    # `not in enrichis`, et NON `not in rangs`. Un livre rendu par l'enrichissement mais
    # sans BSR lisible (un carnet classe « en Fournitures de bureau », jamais « en
    # Livres ») repartait en facturation pour un second appel qui, sur le MEME payload, ne
    # pouvait rien rendre de plus : parse_asin_bsr est strictement plus stricte que
    # parse_bsr_rank. Gaspillage garanti sterile, et recurrent. Seuls les ASIN ABSENTS du
    # dict valent d'etre re-sondes -- ce que le docstring disait deja, et que le code
    # contredisait.
    manquants = [a for a in union if a not in enrichis]
    if manquants:
        try:
            # Plafond PREDICTIF, comme sur la boucle SERP du meme fichier. Appele a 0, il
            # laissait passer un second lot de 120 ASIN : le plafond etait franchi de
            # 0,18 $ EN SILENCE, et le devis sous-estime de 45 %. Le tarif est pourtant
            # parfaitement previsible ici. Le canal scrape reste a 0 : il est gratuit,
            # rien ne doit le brider.
            _src = (bsr_source or os.getenv("BSR_SOURCE", "scrape")).strip().lower()
            _prevu = (dataforseo_cost_usd(len(manquants),
                                          getattr(provider, "priority", 2))
                      if fetch_bsr_fn is None and _src == "dataforseo" else 0.0)
            cost.verifier(_prevu)
            progress(f"Classement de {len(manquants)} livre(s) non enrichi(s)…")
            bsr_map = resolve_bsrs(manquants, source=bsr_source, provider=provider,
                                   fetch_bsr_fn=fetch_bsr_fn, cache=cache, location=loc,
                                   cost=cost, bsr_pause=bsr_pause)
            rangs.update({a: info.rank_livres for a, info in (bsr_map or {}).items()
                          if info and info.rank_livres})
            subcats.update({a: (info.subcategories or [])
                            for a, info in (bsr_map or {}).items() if info})
        except PlafondCoutAtteint as e:
            progress(f"  ⚠ {e} — classement des livres non enrichis abandonné.")
        except Exception as e:  # noqa: BLE001
            progress(f"  ⚠ classement indisponible ({e}).")

    # ── Phase 5 — scoring ──
    out: list[LowContentScored] = []
    n_other = 0
    for v, sr, asins in par_niche:
        niche = par_requete.get(v.requete_amazon)
        if niche is None:
            continue
        if niche.format_cle == "other":
            n_other += 1
        livres = [enrichis[a] for a in asins if a in enrichis]
        bsrs = [rangs[a] for a in asins if a in rangs]
        out.append(score_lowcontent(niche, v, sr, livres, bsrs, bsr_map=rangs,
                                    subcats_map=subcats))
    out.sort(key=lambda s: s.global_score, reverse=True)

    if n_other:
        progress(f"{n_other} niche(s) hors taxonomie (« other ») — matériau de la "
                 f"prochaine version de la taxonomie.")
    b = cost.breakdown()
    if n_non_traitees:
        progress(f"Scout low-content terminé — RAPPORT PARTIEL sur {len(out)} niche(s) : "
                 f"{n_non_traitees} niche(s) non traitée(s), plafond de coût atteint "
                 f"({b['dataforseo_calls']} recherches Amazon).")
    else:
        progress(f"Scout low-content terminé ({b['dataforseo_calls']} recherches Amazon).")
    return out
