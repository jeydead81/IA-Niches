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
from datetime import date

from dotenv import load_dotenv

from autocomplete_expand import expand as _expand
from bsr_source import resolve_bsrs
from cache import Cache
from cost_tracker import CostTracker, PlafondCoutAtteint, dataforseo_cost_usd
from fiction_serp_provider import enrich_asins as _enrich_asins
from ip_filter import filtrer_ip
from lowcontent_ideator import generate_lowcontent_niches as _generate
from lowcontent_scoring import score_lowcontent
from fiction_taxonomy import label_rayon
from lowcontent_taxonomy import est_saisonnier, format_
from marketplace import ACTIF
from models import LowContentScored
from niche_validator import validate_niches as _validate_niches
from search_providers import RefusCompte, TaskPostRefuse, get_provider

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


def _fiche_en_cache(cache, asin: str, loc: int) -> bool:
    """Une fiche illisible en cache compte comme ABSENTE : le devis prend le pire cas,
    jamais une économie supposée (règle 2)."""
    if cache is None:
        return False
    try:
        return cache.get_book(asin, loc) is not None
    except Exception:  # noqa: BLE001
        return False


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
                         enrich_fn=None,
                         classer_toutes: bool = False,
                         journal_rejets: list | None = None,
                         journal_brut: list | None = None,
                         journal_entrees: list | None = None) -> list[LowContentScored]:
    """Scout low-content complet. Rend les niches triées par score décroissant.

    `journal_brut` (crochet de capture de la calibration) est transmis au classement, au
    fournisseur construit ici et au batch ASIN ; il n'est PAS posé sur un fournisseur
    injecté. Absent, rien n'est transmis : les `ideate`/`enrich_fn` injectés gardent leur
    signature.

    `journal_entrees` (calibration) reçoit, par niche scorée, les ENTRÉES exactes de
    `score_lowcontent` : niche (format, risques, `n_enfants`), validation, SERP, fiches, BSR,
    sous-catégories et la date du jour passée explicitement. Le rapport du run 4 n'en gardait
    rien : un réglage de seuil ne pouvait s'essayer qu'en repayant un run."""
    _jb = {"journal_brut": journal_brut} if journal_brut is not None else {}
    progress = progress or _noop
    expand_fn = expand_fn or _expand
    ideate = ideate or _generate
    validate = validate or _validate_niches
    enrich_fn = enrich_fn or _enrich_asins
    cost = cost if cost is not None else CostTracker()
    load_dotenv()

    # La shortlist est prise PARMI les niches classees : si le modele n'en garde que
    # `n_ideas`, `n_search` ne peut pas en rendre davantage. Un client qui demandait 20
    # recherches en obtenait 12, sans message — le contraire exact de `_borner`, qui refuse
    # plutot que de rogner en silence. C'est toujours UN seul appel LLM, mais sa reponse
    # grandit avec n — et elle se paie : le devis low-content la compte (`devis._MODELES`).
    n_ideas = max(n_ideas, n_search)

    if format_cle:
        format_(format_cle, version)          # lève AVANT toute dépense

    import storage
    cache = Cache(cache_path or storage.base("df-cache.db")) if use_cache else None

    # ── Phase 0 — arbre d'autocomplete (gratuit) ──
    suggestions = []
    graine = _graine(seed, format_cle, version)
    if graine:
        progress(f"Lecture de ce qu'Amazon complète autour de « {graine} » (gratuit)…")
        try:
            suggestions = expand_fn(graine, depth=depth, alphabet=alphabet,
                                    max_probes=max_probes, cache=cache, progress=progress)
        except Exception as e:  # noqa: BLE001
            # `expand` absorbe déjà une panne PAR sonde ; il ne lève que si AUCUNE n'a
            # abouti. Continuer basculerait en idéation sur la graine, c'est-à-dire sur une
            # demande inventée — et payée. On s'arrête AVANT toute dépense, et on le DIT :
            # le texte de l'exception, lui, n'atteindra pas l'écran (`_erreur_publique`).
            progress(f"⚠ Autocomplete Amazon indisponible ({type(e).__name__}) — rien "
                     f"n'a été dépensé. Relancer dans quelques minutes.")
            raise RuntimeError("autocomplete Amazon indisponible, aucune dépense") from e
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
                    progress=progress, classer_toutes=classer_toutes,
                    journal_rejets=journal_rejets, cache=cache, **_jb)
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
            try:
                arbre = expand_fn(n.requete_amazon, depth=1, alphabet=False,
                                  max_probes=6, cache=cache, progress=_noop)
                n.n_enfants_autocomplete = len(arbre)
            except Exception as e:  # noqa: BLE001
                # APRÈS l'appel LLM payé : une panne ici tuait le run et perdait les jetons.
                # `None` = jamais sondée (neutre au scoring) — jamais 0, qui serait une
                # mesure défavorable.
                n.n_enfants_autocomplete = None
                progress(f"  ⚠ sonde en panne sur « {n.requete_amazon} » "
                         f"({type(e).__name__}) — demande non mesurée.")
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

    provider = provider or get_provider("dataforseo", **_jb)
    loc = getattr(provider, "location_code", ACTIF.location_code)
    lang = getattr(provider, "language_code", ACTIF.language_code)

    # ── Phase 3 — SERP par niche (payant) ──
    par_niche = []
    tous_asins: list[str] = []
    n_non_traitees = 0
    prio = getattr(provider, "priority", 2)
    # Refus de COMPTE : toutes les requêtes suivantes seraient refusées de même. On cesse
    # d'appeler le fournisseur — 31 `task_post` en rafale au premier run réel — mais on
    # continue de LIRE le cache : une SERP déjà achetée reste une mesure, la jeter pour
    # « arrêter proprement » perdrait gratuitement ce qui est su.
    compte_refuse: str | None = None
    n_non_mesurees_compte = 0
    n_serp_cache = 0
    for i, v in enumerate(shortlist, 1):
        q = v.requete_amazon or v.niche
        sr = cache.get_search(q, loc, lang) if cache else None
        if sr is not None:
            n_serp_cache += 1
        if sr is None and compte_refuse is not None:
            n_non_mesurees_compte += 1
            par_niche.append((v, None, []))
            continue
        if sr is None:
            try:
                cost.verifier(dataforseo_cost_usd(1, prio))
            except PlafondCoutAtteint as e:
                n_non_traitees = len(shortlist) - i + 1
                progress(f"  ⚠ {e}")
                break
            progress(f"[{i}/{len(shortlist)}] Concurrence Amazon « {q} »…")
            try:
                sr = provider.search(q, books_only=True)
            except RefusCompte as e:
                compte_refuse = str(e)
                n_non_mesurees_compte += 1
                progress(f"  ⚠ {e} — plus aucun appel au fournisseur, cache seul.")
                sr = None
            except BaseException as e:  # noqa: BLE001 — un échec ne coule jamais le run
                # Tâche CRÉÉE puis non lue : facturée (seul un refus explicite ne l'est
                # pas). Un Ctrl-C est imputé de même, puis relancé.
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
        asins = [o.asin for o in (sr.organic if sr else []) if o.asin][:n_enrich_per_niche]
        par_niche.append((v, sr, asins))
        tous_asins.extend(asins)

    if cache is not None and shortlist:
        # Une SERP servie par le cache n'a pas été relue : elle dit le rayon tel qu'il était
        # au jour de l'achat. Le taire faisait lire une donnée de 15 jours comme une mesure
        # du jour. Jamais « à payer » : ligne à l'écran du client (§5.27).
        progress(f"{n_serp_cache}/{len(shortlist)} recherche(s) Amazon servie(s) par le "
                 f"cache — non relue(s).")

    # ── Phase 4 — UN SEUL batch ASIN ──
    enrichis: dict = {}
    union = list(dict.fromkeys(tous_asins))
    if union:
        # PRÉDICTIF, comme la boucle SERP : le poste le plus lourd du run était vérifié à 0,
        # donc ne refusait qu'APRÈS avoir dépassé. Mais il ne compte que les fiches ABSENTES
        # du cache : compter l'union refusait, sous un plafond calé au plus juste, un batch
        # qui ne coûtait rien — puis le canal BSR repartait sonder chaque ASIN « non
        # enrichi ». Compte refusé : rien ne partira chez le fournisseur, rien n'est prévu.
        en_cache = [a for a in union if _fiche_en_cache(cache, a, loc)]
        deja = set(en_cache)
        a_relire = [] if compte_refuse else [a for a in union if a not in deja]
        lot = union
        if a_relire:
            try:
                cost.verifier(dataforseo_cost_usd(len(a_relire), prio))
            except PlafondCoutAtteint as e:
                progress(f"  ⚠ {e} — éditeurs et pagination non lus pour {len(a_relire)} "
                         f"ASIN absent(s) du cache.")
                # Les fiches en cache ne coûtent rien et restent une mesure : `enrich_fn`
                # est appelé quand même, sur elles seules — c'est lui qui SERT le cache.
                lot = en_cache
        if lot:
            try:
                economises = len(tous_asins) - len(union)
                progress(f"Enrichissement de {len(lot)} ASIN uniques en UN seul batch "
                         f"({economises} économisé(s) par dédup inter-niches)…")
                # `cache_seul` n'est passé QUE sur refus : les `enrich_fn` injectés ailleurs
                # gardent leur signature.
                enrichis = enrich_fn(lot, provider=provider, cache=cache, cost=cost,
                                     progress=progress,
                                     **({"cache_seul": True} if compte_refuse else {}),
                                     **_jb) or {}
            except Exception as e:  # noqa: BLE001
                progress(f"  ⚠ enrichissement indisponible ({e}) — éditeurs non lus.")

    # ── BSR : LU DANS L'ENRICHISSEMENT, jamais re-payé ──
    # `enrich_asins` parse déjà le BSR de chaque fiche (`parse_enriched_book`). Appeler
    # `resolve_bsrs` sur la même union re-facturait CHAQUE ASIN une seconde fois quand
    # BSR_SOURCE=dataforseo : à la borne serveur, 240 ASIN au lieu de 120, soit 0,80 $ au
    # lieu de 0,44 $ sur un plafond de 0,60 $. Le gaspillage était invisible — rien dans le
    # rapport ne montrait qu'un ASIN avait été payé deux fois.
    # Le rang du RAYON LIVRES seulement. Un carnet est souvent classé « en Fournitures de
    # bureau » : le parseur LIT ce rang (parse_bsr_rank rend le rang quel que soit le
    # rayon), et il entrait tel quel dans des seuils calés sur des rangs Livres — deux
    # classements qui ne se comparent pas (§5.5). Mesuré hors ligne : +0,70 sur le score
    # global d'un rayon de partitions, assez pour faire passer une « morte » en vert.
    # Même règle que `EnrichedBook.est_payant_dans` en fiction : rayon + pas de gratuit.
    rayon_livres = label_rayon("papier", version)
    rangs = {a: b.bsr for a, b in enrichis.items()
             if b and b.est_payant_dans(rayon_livres)}
    hors_livres = [a for a, b in enrichis.items()
                   if b and b.bsr and not b.est_payant_dans(rayon_livres)]
    if hors_livres:
        progress(f"  ⚠ {len(hors_livres)} livre(s) classé(s) hors du rayon Livres (ex. "
                 f"Fournitures de bureau) ou en gratuit : rang NON comparable, écarté des "
                 f"seuils BSR.")
    # Les sous-catégories étaient LUES dans l'enrichissement — et facturées — puis jetées :
    # le dossier annonçait ensuite « donnée non mesurée ». Converties au schéma que lit
    # `categories.py` ({category, rank}) ; le parseur des fiches écrit {rang, categorie},
    # et une recopie brute se ferait écarter en silence. Rayon Livres seulement : une
    # sous-catégorie de Fournitures de bureau n'est pas une catégorie KDP.
    subcats = {a: [{"category": s.get("categorie"), "rank": s.get("rang")}
                   for s in (b.bsr_subcats or []) if s.get("categorie")]
               for a, b in enrichis.items()
               if b and b.bsr_subcats and b.est_payant_dans(rayon_livres)}

    # Seuls les ASIN que l'enrichissement n'a PAS rendus valent un second passage : un
    # payload atypique est absent du dict (jamais une entrée factice), et leur classement
    # reste récupérable par le canal BSR — gratuit en local. Renoncer pour eux perdrait une
    # mesure encore atteignable ; les redemander TOUS ferait payer deux fois les autres.
    # `not in enrichis`, et NON `not in rangs`. Un livre rendu par l'enrichissement mais
    # sans rang du rayon Livres (un carnet classe « en Fournitures de bureau » : son rang
    # est LU, mais ne se compare pas, cf. plus haut) repartait en facturation pour un
    # second appel qui, sur le MEME payload, ne
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
            _payant = fetch_bsr_fn is None and _src == "dataforseo"
            if compte_refuse and _payant:
                # Même compte : ce canal serait refusé à l'identique.
                raise RefusCompte(compte_refuse)
            _prevu = dataforseo_cost_usd(len(manquants), prio) if _payant else 0.0
            cost.verifier(_prevu)
            progress(f"Classement de {len(manquants)} livre(s) non enrichi(s)…")
            bsr_map = resolve_bsrs(manquants, source=bsr_source, provider=provider,
                                   fetch_bsr_fn=fetch_bsr_fn, cache=cache, location=loc,
                                   cost=cost, bsr_pause=bsr_pause, progress=progress)
            rangs.update({a: info.rank_livres for a, info in (bsr_map or {}).items()
                          if info and info.rank_livres})
            subcats.update({a: (info.subcategories or [])
                            for a, info in (bsr_map or {}).items() if info})
        except PlafondCoutAtteint as e:
            progress(f"  ⚠ {e} — classement des livres non enrichis abandonné.")
        except RefusCompte:
            progress(f"  ⚠ classement de {len(manquants)} livre(s) non enrichi(s) non "
                     f"demandé : compte DataForSEO refusé.")
        except Exception as e:  # noqa: BLE001
            progress(f"  ⚠ classement indisponible ({e}).")

    # ── Phase 5 — scoring ──
    out: list[LowContentScored] = []
    n_other = 0
    # UNE date pour tout le run, passée explicitement : c'est elle que le journal archive.
    aujourdhui = date.today()
    for v, sr, asins in par_niche:
        niche = par_requete.get(v.requete_amazon)
        if niche is None:
            continue
        if niche.format_cle == "other":
            n_other += 1
        livres = [enrichis[a] for a in asins if a in enrichis]
        bsrs = [rangs[a] for a in asins if a in rangs]
        if journal_entrees is not None:
            # Seuls les ASIN organiques de CETTE niche : le scoring ne lit les deux tables
            # que pour ses meilleurs organiques.
            organiques = {o.asin for o in (sr.organic if sr else []) if o.asin}
            journal_entrees.append({
                "type": "niche", "requete": v.requete_amazon,
                "niche": niche.model_dump(mode="json"),
                "validation": v.model_dump(mode="json"),
                "search": sr.model_dump(mode="json") if sr else None,
                "asins": list(asins),
                "livres": [b.model_dump(mode="json") for b in livres],
                "bsrs": list(bsrs),
                "bsr_map": {a: r for a, r in rangs.items() if a in organiques},
                "subcats_map": {a: sc for a, sc in subcats.items() if a in organiques},
                "aujourdhui": aujourdhui.isoformat()})
        out.append(score_lowcontent(niche, v, sr, livres, bsrs, bsr_map=rangs,
                                    subcats_map=subcats, aujourdhui=aujourdhui))
    out.sort(key=lambda s: s.global_score, reverse=True)

    if n_other:
        progress(f"{n_other} niche(s) hors taxonomie (« other ») — matériau de la "
                 f"prochaine version de la taxonomie.")
    if n_non_mesurees_compte:
        # Dire le NOMBRE et la cause : une niche ⚪ faute de compte ne se lit pas comme une
        # SERP tombée par hasard, et relancer sans régler le compte reproduirait le refus.
        progress(f"⚠ {n_non_mesurees_compte} niche(s) non mesurée(s) : compte DataForSEO "
                 f"refusé ({compte_refuse}).")
    b = cost.breakdown()
    if n_non_traitees:
        progress(f"Scout low-content terminé — RAPPORT PARTIEL sur {len(out)} niche(s) : "
                 f"{n_non_traitees} niche(s) non traitée(s), plafond de coût atteint "
                 f"({b['dataforseo_calls']} recherches Amazon).")
    else:
        progress(f"Scout low-content terminé ({b['dataforseo_calls']} recherches Amazon).")
    return out
