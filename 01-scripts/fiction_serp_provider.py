"""fiction_serp_provider.py — reconstitue le « rayon » d'une niche fiction.
SERP contrainte au browse node (ou à la requête si le sous-genre n'a pas de rayon),
puis enrichissement BATCHÉ des n_top premiers ASIN, avec cache inter-runs et coût mesuré."""
import inspect

from fiction_books import parse_enriched_book
from fiction_taxonomy import node_for, search_param_for
from marketplace import ACTIF
from models import EnrichedBook, FictionNiche, FictionShelf
from cache import BOOK_TTL_S
from cost_tracker import PlafondCoutAtteint, dataforseo_cost_usd

# TTL IMPORTE, jamais redefini. Il l'etait ici a 7 jours pendant que cache.py
# documentait 15 : deux constantes du meme nom dans deux modules, l'une testee et
# l'autre appliquee. C'est ce qui a permis au defaut de vivre -- et au test
# d'harmonisation de passer au vert en surveillant la constante morte.


def search_param_for_niche(niche: FictionNiche, version: str = "fr_v1") -> str:
    """Contrainte de rayon : le browse node si le sous-genre en a un, sinon le filtre
    de rayon (mode « rayon requête »)."""
    node = node_for(niche.sous_genre, niche.rayon, version)
    return f"rh=n:{node}" if node else search_param_for(niche.rayon, version)


def fetch_shelf_asins(niche: FictionNiche, provider, n_top: int = 10, depth: int = 30,
                      cost=None, version: str = "fr_v1") -> tuple[str, list[str]]:
    """Moitié SERP (quelques secondes à quelques minutes ; une requête sans résultat rend un rayon
    vide, `(sp, [])`, dès le premier relevé) : SERP contrainte au rayon -> n_top
    premiers ASIN dédupliqués. AUCUN enrichissement ici — c'est cette moitié qu'on veut
    appeler N fois (une par niche) avant de payer UNE seule fois la file ASIN via
    `enrich_asins` (cf. M6-2 : la file DataForSEO met ~250 s quel que soit le nb d'ASIN).

    n_top=10 par défaut (12 jusqu'au 2026-10-05, 20 à l'origine : -50 % de coût ASIN) : le signal
    concurrentiel de M5 (depth,
    openness, saturation_trio) est porté par les tout premiers résultats, les ASIN 13-20
    coûtent 0,024 $ chacun pour peu d'apport."""
    from search_providers import AucunResultat, TaskPostRefuse
    sp = search_param_for_niche(niche, version)
    prio = getattr(provider, "priority", 2)
    try:
        sr = provider.search(niche.query, depth=depth, search_param=sp)
    except AucunResultat:
        # Amazon ne rend RIEN pour cette requête : un rayon VIDE, pas un échec. L'orchestrateur
        # en fait une carte « non mesuré » (« la requête ne rend aucun livre, ce n'est pas une
        # niche morte ») au lieu de la laisser disparaître. La tâche a été créée : imputée.
        if cost is not None:
            cost.add_dataforseo(1, prio)
        return sp, []
    except BaseException as e:
        # Une tâche CRÉÉE puis non lue (poll épuisé, relecture illisible, Ctrl-C) est
        # facturée : seul un refus explicite ne l'est pas. On impute, puis on relance —
        # l'orchestrateur écarte la niche comme avant.
        if cost is not None and not isinstance(e, TaskPostRefuse):
            cost.add_dataforseo(1, prio)
        raise
    if cost is not None:
        cost.add_dataforseo(1, prio)
    # dict.fromkeys préserve l'ordre en dédupliquant : une SERP qui répète un ASIN ne doit
    # ni le facturer deux fois, ni le rendre deux fois, ni écraser sa position par la
    # DERNIÈRE occurrence au lieu de la première.
    asins = list(dict.fromkeys(o.asin for o in sr.organic if o.asin))[:n_top]
    return sp, asins


def _accepte_parametre(fn, nom: str) -> bool:
    """Le paramètre NOMMÉ, jamais un `**kw` : un faux fournisseur qui avale tout sans rien
    journaliser ferait croire que le brut est gardé."""
    try:
        return nom in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def enrich_asins(asins: list[str], provider, cache=None, cost=None,
                 progress=None, cache_seul: bool = False,
                 journal_brut: list | None = None) -> dict[str, EnrichedBook]:
    """Moitié « lente » (LA file DataForSEO, ~250 s quel que soit le nb d'ASIN) : batch
    ASIN unique, cache inter-runs, coût mesuré. Rend un dict {asin: EnrichedBook} qui ne
    contient QUE les ASIN effectivement enrichis — un payload absent ou inexploitable est
    simplement absent du dict, jamais une entrée factice. Cette fonction ne connaît que le
    lot qu'on lui passe : c'est à l'appelant (fetch_fiction_shelf, ou l'orchestrateur M6-2
    qui reconstruit un rayon par niche depuis la table globale) de comparer aux ASIN
    demandés PAR NICHE pour compter les échecs — comptage impossible à faire ici sans
    connaître ce découpage.

    `journal_brut` reçoit chaque payload BRUT avant parsing (crochet de capture de la
    calibration) ; les fiches servies par le cache n'y figurent pas, leur brut n'existe
    plus."""
    loc = getattr(provider, "location_code", ACTIF.location_code)
    out: dict[str, EnrichedBook] = {}
    misses: list[str] = []
    for a in asins:
        cached = cache.get_book(a, loc) if cache else None
        if cached is not None:
            out[a] = cached
        else:
            misses.append(a)
    if progress and cache is not None and asins:
        # Après le run 4, « 185/185 servies par le cache » était exactement l'alerte qui
        # manquait : ces fiches avaient été lues par un parseur fautif, et le cache les
        # resservait telles quelles. Jamais « à payer » : cette ligne est à l'écran du
        # client, qui ne voit aucun montant (§5.27).
        progress(f"{len(asins) - len(misses)}/{len(asins)} fiche(s) servie(s) par le cache, "
                 f"{len(misses)} à relire chez Amazon.")

    if misses and cache_seul:
        # Compte DataForSEO refusé : un envoi serait refusé à l'identique. Ce que le cache
        # tient est rendu ; le reste est annoncé, ni envoyé ni facturé.
        if progress:
            progress(f"⚠ {len(misses)} ASIN non enrichis : compte DataForSEO refusé — ni "
                     f"envoyés, ni facturés ({len(out)} servi(s) par le cache).")
        return out

    if misses:
        prio = getattr(provider, "priority", 2)
        if cost is not None:
            # PRÉDICTIF, ICI et pas seulement chez l'appelant : le master low-content chiffrait
            # « à relire » sur SA lecture du cache, puis on relit ici. Les 185 fiches du run 4
            # expirent dans la même seconde : une phase 4 à cheval sur cet instant voyait 0 à
            # payer, et 0,555 $ partaient sans vérification. En fiction, rien ne vérifiait le
            # batch. Refus = on rend ce que le cache sert, sans lever (§5.29), comme
            # `cache_seul`. Aucun montant dans la ligne : écran client (§5.27).
            try:
                cost.verifier(dataforseo_cost_usd(len(misses), prio))
            except PlafondCoutAtteint:
                if progress:
                    progress(f"⚠ plafond de coût atteint : {len(misses)} ASIN non envoyés, ni "
                             f"facturés, ni enrichis ({len(out)} servi(s) par le cache).")
                return out
        # Le fournisseur réel journalise à la LECTURE (survit à un Ctrl-C en plein poll) ;
        # un fournisseur qui ne le sait pas est journalisé ici, avant parsing. Jamais les
        # deux : une fiche en double dans la capture fausserait un rejeu.
        journal_fournisseur = (journal_brut is not None
                               and _accepte_parametre(provider.product_raw_batch,
                                                      "journal_brut"))
        try:
            raw = (provider.product_raw_batch(misses, journal_brut=journal_brut)
                   if journal_fournisseur else provider.product_raw_batch(misses))
        except BaseException:
            # Une panne pendant la RELECTURE laisse des tâches créées, donc facturées : on
            # impute le pire cas plutôt que rien (règle 2 : ne jamais arrondir un coût vers
            # le bas), puis on laisse remonter. Ctrl-C compris (BaseException) : au rejeu du
            # 2026-09-14, 185 tâches créées puis interrompues étaient imputées 0 $. Le
            # nombre réellement créé n'est pas accessible ici — le pire cas l'est.
            if cost is not None:
                cost.add_dataforseo(len(misses), prio)
            raise
        if cost is not None:
            # Les tâches créées, PLUS celles dont on ne sait pas si elles l'ont été (lot dont
            # le task_post a levé) : un refus EXPLICITE ne crée rien, une exception ne dit
            # rien. Imputer le pire cas est la règle 2 (ne jamais arrondir vers le bas) ; le
            # contraire faisait relancer un run en croyant le batch gratuit. Un fournisseur
            # qui ne dit ni l'un ni l'autre impute tout, par prudence.
            cost.add_dataforseo(getattr(raw, "taches_creees", len(misses))
                                + getattr(raw, "taches_incertaines", 0), prio)
        for n_lot, cause in getattr(raw, "lots_en_echec", []):
            if progress:
                progress(f"⚠ {n_lot} ASIN non envoyés : lot refusé à l'envoi ({cause}) — "
                         f"ni facturés, ni enrichis.")
        for n_lot, cause in getattr(raw, "lots_exception", []):
            if progress:
                progress(f"⚠ {n_lot} ASIN non relus : l'envoi du lot a levé ({cause}) — "
                         f"peut-être facturés côté fournisseur, imputés au pire cas.")
        lectures = getattr(raw, "lectures_en_echec", None) or {}
        if lectures and progress:
            detail = ", ".join(f"{nom}×{n}" for nom, n in lectures.items())
            progress(f"⚠ {sum(lectures.values())} relecture(s) de résultat illisible(s) "
                     f"pendant le poll ({detail}) — tâches relues au cycle suivant, lot "
                     f"conservé.")
        n_echecs = n_non_ecrites = 0
        for a in misses:
            payload = raw.get(a)
            if journal_brut is not None and not journal_fournisseur and payload is not None:
                journal_brut.append({"type": "asin", "asin": a, "payload": payload})
            b = parse_enriched_book(payload or {})
            if b is not None:
                out[a] = b
                if cache:
                    # Le batch est PAYÉ : une écriture refusée (`database is locked` au-delà
                    # de 10 s sur le cache mutualisé, disque plein) levait au milieu de la
                    # boucle, le dict n'était jamais rendu, et le low-content rachetait toute
                    # l'union par le canal BSR (§5.31). La fiche reste rendue pour ce run.
                    try:
                        cache.set_book(a, loc, b, BOOK_TTL_S)
                    except Exception:  # noqa: BLE001
                        n_non_ecrites += 1
            else:
                n_echecs += 1
        if n_echecs and progress:
            progress(f"⚠ {n_echecs}/{len(misses)} ASIN non enrichis dans ce batch "
                     f"(payload absent ou inexploitable).")
        if n_non_ecrites and progress:
            progress(f"⚠ {n_non_ecrites}/{len(misses)} fiche(s) lue(s) mais non écrite(s) en "
                     f"cache (écriture refusée) — utilisées pour ce run, à relire au prochain.")
    return out


def fetch_fiction_shelf(niche: FictionNiche, provider, n_top: int = 10, depth: int = 30,
                        cache=None, cost=None, version: str = "fr_v1",
                        progress=None) -> FictionShelf:
    """Contrat M2 inchangé pour les appelants existants (tests M2, build_validation_set) :
    devient la composition de `fetch_shelf_asins` (SERP) + `enrich_asins` (la file). Rend
    un FictionShelf qui porte asins_demandes/n_echecs : un ASIN qui ne s'enrichit pas est
    COMPTÉ, jamais droppé en silence — un rayon amputé se lirait en aval comme « niche
    déserte = place à prendre », faux signal interdit par CLAUDE.md §10."""
    sp, asins = fetch_shelf_asins(niche, provider, n_top=n_top, depth=depth, cost=cost,
                                  version=version)
    enriched = enrich_asins(asins, provider, cache=cache, cost=cost)

    out: list[EnrichedBook] = []
    for i, a in enumerate(asins, 1):
        b = enriched.get(a)
        if b is not None:
            b.serp_position = i          # la position dépend du run, pas du cache
            out.append(b)

    n_echecs = len(asins) - len(out)
    if n_echecs and progress:
        progress(f"⚠ {n_echecs}/{len(asins)} ASIN non enrichis (payload absent ou "
                 f"inexploitable) — rayon incomplet, ne pas lire comme une niche déserte.")
    return FictionShelf(niche=niche, search_param=sp, books=out,
                        asins_demandes=len(asins), n_echecs=n_echecs)
