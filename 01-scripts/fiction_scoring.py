"""fiction_scoring.py — M5 : transforme un rayon lu (M2) + ses étiquettes (M4) + la sonde
(M3) en métriques puis en verdict. Calcul pur, aucun réseau, aucun LLM.

Le différenciateur du module est `saturation_trio` : c'est la seule métrique qui répond
à « combien de livres promettent DÉJÀ exactement ce trio ? », une question impossible à
poser sans avoir lu les quatrièmes de couverture (M4). Le reste (BSR, avis, prix) est
disponible à n'importe qui grattant Amazon.

Les seuils sont des CONSTANTES NOMMÉES en un seul endroit (`SEUILS`) : ce sont des repères
marché mesurés en live, pas des vérités absolues, et un produit vendu devra pouvoir les
exposer/les ajuster. Les enfouir dans des `if` les rendrait intouchables."""
import statistics

from fiction_taxonomy import label_rayon
from models import (AutocompleteSignal, EnrichedBook, FictionNiche, FictionNicheReport,
                    FictionShelf, TropeClassification)

SEUILS = {
    # --- Profondeur (depth_score) : BSR Kindle FR, calés sur les rayons mesurés en live
    # (thriller psy actif : 1960/2168/7422/14924/47262 ; cosy village faible : 62230/
    # 95309/150766/156045/204800 — cf. plan M5 « Faits mesurés »).
    "bsr_kindle_excellent": 5_000,     # meilleur BSR d'un rayon actif mesuré
    "bsr_kindle_correct": 20_000,      # au-delà, la profondeur décroche nettement
    "bsr_kindle_faible": 100_000,      # zone du rayon mesuré « faible »
    # --- Ouverture (openness_score)
    "avis_leader_mur": 500,            # au-delà (médiane), le rayon est un mur installé
    # --- 25 % du top Kindle mesuré = titres gratuits (classement distinct, hors scoring).
    "part_gratuits_mesuree": 0.25,
    # --- Lecture de la matrice de demande (M5-2) : coupures haute/basse par métrique.
    "depth_haute": 0.6,
    "openness_haute": 0.5,
    "saturation_haute": 0.6,           # recouvrement moyen du trio : sujet déjà traité partout
    # --- Mesure suffisante : sous ce nombre de livres MESURABLES, aucune conclusion de marché.
    # HYPOTHÈSE posée le 2026-10-05, pas une mesure : relevé sur les deux runs fiction enregistrés
    # (8 niches, rayon papier), 7 livres scorables sur 47 payés, jamais plus de 4 par niche — et
    # « Mur installé » rendu sur UN livre, « Mort » sur un livre, deux fois. 3 est le plus petit
    # nombre pour lequel « la médiane » (depth_score) et « le leader » (openness_score) désignent
    # des livres différents ; aucun jeu étiqueté ne l'a confronté. À discuter, pas à citer.
    "livres_mesures_min": 3,
}

# Les deux états où rien ne se conclut : zéro livre mesurable, ou trop peu pour que les chiffres
# veuillent dire quoi que ce soit. L'écran, le tri, l'historique et le verdict éditorial les
# traitent ENSEMBLE — un état oublié dans une de ces listes laisserait un zéro, ou un livre
# unique, se lire comme une mesure.
NON_CONCLUANTES = ("non_mesurable", "mesure_mince")


def livres_scorables(livres: list[EnrichedBook], classifications: dict[str, TropeClassification],
                     rayon: str, version: str = "fr_v1") -> list[EnrichedBook]:
    """Les trois exclusions mesurées au spike, appliquées AVANT tout calcul :
    1) titre gratuit (`bsr_gratuit`, classement distinct — pas des ventes) ;
    2) non-roman (`est_roman=False` sur la classification, quand elle existe) ;
    3) mauvais rayon (rang « Livres » incomparable à rang « Boutique Kindle »).

    `rayon` est le paramètre INTERNE de FictionNiche ("kindle"/"papier") : on le traduit
    en libellé Amazon via `label_rayon()` avant de comparer à `bsr_rayon`. Comparer
    `niche.rayon` brut à `EnrichedBook.bsr_rayon` ne matche jamais rien (piège M5 déjà
    désamorcé une fois : `est_payant_dans("kindle")` vaut False pour TOUS les livres).

    Un livre non classé reste scorable : l'absence de classification n'est pas une preuve
    que ce n'est pas un roman, on ne l'invente pas."""
    label = label_rayon(rayon, version)
    out = []
    for b in livres:
        if not b.est_payant_dans(label):
            continue
        cl = classifications.get(b.asin)
        if cl is not None and not cl.est_roman:
            continue
        out.append(b)
    return out


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _score_from_bsr(bsr: int) -> float:
    """Mappe un BSR sur [0, 1], BSR-first : décroissance douce, jamais brutalement à 0
    (un BSR très dégradé reste un signal faible, pas un signal nul)."""
    ex, co, fa = SEUILS["bsr_kindle_excellent"], SEUILS["bsr_kindle_correct"], SEUILS["bsr_kindle_faible"]
    if bsr <= ex:
        return 1.0
    if bsr <= co:
        return _lerp(1.0, 0.6, (bsr - ex) / (co - ex))
    if bsr <= fa:
        return _lerp(0.6, 0.15, (bsr - co) / (fa - co))
    return max(0.0, 0.15 * fa / bsr)     # décroissance asymptotique au-delà du seuil faible


def depth_score(livres: list[EnrichedBook]) -> float:
    """BSR-first : combine le MEILLEUR BSR (0.4) et la MÉDIANE (0.6, poids dominant) —
    un rayon porté par un seul best-seller isolé n'est pas un rayon profond, la médiane
    doit suivre. 0.0 sur liste vide (rayon vide -> pas de demande prouvée)."""
    bsrs = [b.bsr for b in livres if b.bsr]
    if not bsrs:
        return 0.0
    best = min(bsrs)
    med = statistics.median(bsrs)
    return 0.4 * _score_from_bsr(best) + 0.6 * _score_from_bsr(med)


def openness_score(livres: list[EnrichedBook]) -> float:
    """Peu d'avis médians = places prenables ; forte dispersion de BSR = un livre mal
    positionné traîne dans le rayon (signal « place à prendre », §4.1) ; leaders anciens
    = ouvert, mais seulement quand la date est exploitable (sinon on ne pénalise pas, on
    ignore juste ce facteur). 0.0 sur liste vide."""
    if not livres:
        return 0.0
    avis = [b.reviews_count for b in livres if b.reviews_count is not None]
    bsrs = [b.bsr for b in livres if b.bsr]

    avis_component = 0.5  # neutre si aucun avis connu
    if avis:
        med_avis = statistics.median(avis)
        mur = SEUILS["avis_leader_mur"]
        avis_component = max(0.0, min(1.0, 1 - med_avis / mur))

    dispersion_component = 0.0
    if len(bsrs) >= 2 and statistics.mean(bsrs) > 0:
        cv = statistics.pstdev(bsrs) / statistics.mean(bsrs)   # coeff. de variation
        dispersion_component = max(0.0, min(1.0, cv))

    # Ancienneté : non exploitée tant que M2 ne fournit pas de date fiable dans les tests ;
    # ignorée (pas pénalisée) plutôt que traitée comme 0 quand elle manque.
    return 0.6 * avis_component + 0.4 * dispersion_component


def saturation_trio(niche: FictionNiche, livres: list[EnrichedBook],
                    classifications: dict[str, TropeClassification]) -> float:
    """LE différenciateur du module : moyenne, sur les livres CLASSÉS uniquement, de la
    COUVERTURE du trio visé par les tropes du livre (|trio ∩ tropes_livre| / |trio|).

    Couverture plutôt que Jaccard : on veut mesurer « combien de MON trio ce livre a-t-il
    déjà pris », pas une ressemblance symétrique. Jaccard pénaliserait un livre truffé de
    tropes annexes alors que, du point de vue de la saturation, il a déjà capté 100% de ce
    qu'on visait — le pénaliser masquerait le vrai signal de sursaturation.

    0.0 si rien n'est classé : l'absence de preuve n'est PAS une preuve d'absence (rayon
    libre) — c'est juste qu'on n'a rien mesuré. Ne compte que les livres passés dans
    `livres` (donc déjà filtrés par `livres_scorables`) qui ont une classification."""
    trio = set(niche.tropes)
    if not trio:
        return 0.0
    couvertures = []
    for b in livres:
        cl = classifications.get(b.asin)
        if cl is None:
            continue
        couvertures.append(len(trio & set(cl.tropes)) / len(trio))
    if not couvertures:
        return 0.0
    return sum(couvertures) / len(couvertures)


def series_share(livres: list[EnrichedBook]) -> float:
    if not livres:
        return 0.0
    return sum(1 for b in livres if b.est_serie) / len(livres)


def price_band(livres: list[EnrichedBook]) -> list[float]:
    """[min, médiane, max] sur les prix connus. Liste vide si aucun prix connu."""
    prix = sorted(b.price for b in livres if b.price is not None)
    if not prix:
        return []
    return [prix[0], statistics.median(prix), prix[-1]]


def _demand_matrix(depth: float, openness: float, saturation: float,
                   n_scorables: int | None = None) -> str:
    """Aucun livre scorable -> `non_mesurable`, JAMAIS « mort » : les deux se ressemblent
    dans les chiffres (tout à zéro) mais disent le contraire à l'utilisateur — l'un
    l'invite à écarter la niche, l'autre à re-mesurer.

    Trop peu de livres (sous `SEUILS["livres_mesures_min"]`) -> `mesure_mince`, pour la même
    raison : « mort » ou « mur installé » rendu sur un livre unique est une conclusion de marché
    tirée d'une absence de mesure. Le seuil est lu ICI, à chaque appel, dans `SEUILS`.
    `n_scorables=None` = nombre inconnu de l'appelant : aucune de ces deux gardes ne joue."""
    if n_scorables is not None:
        if n_scorables == 0:
            return "non_mesurable"
        if n_scorables < SEUILS["livres_mesures_min"]:
            return "mesure_mince"
    return _matrix_mesuree(depth, openness, saturation)


def _matrix_mesuree(depth: float, openness: float, saturation: float) -> str:
    """La matrice croise profondeur (y a-t-il de l'argent ?) et ouverture (reste-t-il de
    la place ?). La saturation du trio n'arbitre QUE le cas haute/haute — profond ET
    ouvert peut être une pépite ou un sujet déjà couvert par tout le monde, et seule la
    lecture des blurbs (donc `saturation_trio`) tranche. L'autocomplete n'apparaît nulle
    part ici : le spike M0 §V3 est formel, il ne gate jamais seul."""
    depth_haute = depth >= SEUILS["depth_haute"]
    openness_haute = openness >= SEUILS["openness_haute"]
    saturation_haute = saturation >= SEUILS["saturation_haute"]
    if depth_haute and openness_haute:
        return "porteur_encombre" if saturation_haute else "pepite"
    if depth_haute:                     # openness basse -> peu de place malgré l'argent
        return "mur_installe"
    if openness_haute:                  # depth basse -> de la place mais pas d'argent prouvé
        return "desert"
    return "mort"


def _verdict(shelf: FictionShelf, ok: list[EnrichedBook],
            classifications: dict[str, TropeClassification], matrix: str, depth: float,
            openness: float, saturation: float, signal: AutocompleteSignal) -> str:
    """Verdict court et tranché qui signale explicitement (CLAUDE.md §10 + spike M0 §V3) :
    un rayon incomplet (jamais lu comme un désert), un sous-genre fantôme sur
    l'autocomplete, une part de livres non classés, et le périmètre réel de la saturation
    (mesurée SEULEMENT sur les livres classés)."""
    bits = [f"{matrix} — depth={depth:.2f}, openness={openness:.2f}, "
            f"saturation_trio={saturation:.2f}."]
    # Zéro livre scorable = RIEN n'a été mesuré. Sans ce signalement, ce cas rendait
    # « mort » exactement comme un rayon plein de livres qui se vendent mal — et « mort »
    # dit à l'utilisateur d'écarter la niche. Vu en live sur « romance captif huis clos ».
    if not ok:
        if not shelf.books:
            bits.append("Rayon VIDE : la SERP n'a rendu aucun livre — niche NON MESURÉE, "
                        "surtout pas une niche morte. Vérifier la requête ou le rayon.")
        else:
            bits.append(f"AUCUN livre scorable sur {len(shelf.books)} au rayon : tous "
                        f"écartés (titre gratuit, non-roman, ou rang d'un autre rayon) — "
                        f"niche NON MESURÉE, pas une niche morte.")
    if ok and len(ok) < SEUILS["livres_mesures_min"]:
        bits.append(f"Mesure TROP MINCE : {len(ok)} livre(s) mesuré(s) sur {len(shelf.books)} — "
                    f"aucune conclusion de marché, ce n'est pas une niche morte.")
    if shelf.n_echecs > 0:
        bits.append(f"Rayon INCOMPLET : {shelf.n_echecs}/{shelf.asins_demandes} ASIN non "
                    f"enrichis — ne pas lire comme un désert.")
    if signal.mesure and signal.sous_genre_cherche is False:
        bits.append("Alerte : le sous-genre lui-même n'est pas cherché sur l'autocomplete "
                    "(sous-genre fantôme).")
    n_non_classes = sum(1 for b in ok if b.asin not in classifications)
    if n_non_classes:
        bits.append(f"{n_non_classes}/{len(ok)} livres scorables non classés.")
    bits.append("Saturation du trio mesurée uniquement sur les livres classés.")
    return " ".join(bits)


def build_report(niche: FictionNiche, shelf: FictionShelf,
                 classifications: dict[str, TropeClassification], signal: AutocompleteSignal,
                 version: str = "fr_v1", cost=None) -> FictionNicheReport:
    """Assemble le `FictionNicheReport` : applique les trois exclusions (`livres_scorables`)
    AVANT tout calcul de métrique, porte l'`AutocompleteSignal` ENTIER (jamais son seul
    float — dette réglée le 2026-07-20, sinon `mesure`/`sous_genre_cherche` se perdent et
    0.0 redevient indiscernable d'un « absent » mesuré), et ne laisse JAMAIS l'autocomplete
    arbitrer `demand_matrix`."""
    ok = livres_scorables(shelf.books, classifications, niche.rayon, version)
    depth = depth_score(ok)
    openness = openness_score(ok)
    saturation = saturation_trio(niche, ok, classifications)
    matrix = _demand_matrix(depth, openness, saturation, len(ok))
    verdict = _verdict(shelf, ok, classifications, matrix, depth, openness, saturation, signal)
    return FictionNicheReport(
        niche=niche,
        books=shelf.books,
        classifications=list(classifications.values()),
        depth_score=depth,
        openness_score=openness,
        saturation_trio=saturation,
        autocomplete=signal,
        demand_matrix=matrix,
        series_share=series_share(ok),
        price_band=price_band(ok),
        verdict=verdict,
        cost_run=cost.total_usd() if cost is not None else 0.0,
        n_echecs=shelf.n_echecs,
        asins_demandes=shelf.asins_demandes,
        n_livres_mesures=len(ok),
    )




def _relire_une(entree):
    """Une entrée de résultat sous la règle d'aujourd'hui, ou elle-même si rien n'est à changer.
    Ne lève jamais : une entrée illisible est rendue telle quelle."""
    if not isinstance(entree, dict) or entree.get("n_livres_mesures") is not None:
        return entree
    niche = entree.get("niche")
    livres = entree.get("books")
    if not isinstance(niche, dict) or not isinstance(livres, list):
        return entree
    try:
        books = [EnrichedBook.model_validate(b) for b in livres]
        classes = {c["asin"]: TropeClassification.model_validate(c)
                   for c in (entree.get("classifications") or [])}
        n = len(livres_scorables(books, classes, niche.get("rayon", "kindle")))
    except (ValueError, TypeError, KeyError):
        return entree
    relu = dict(entree)
    relu["n_livres_mesures"] = n
    if relu.get("demand_matrix") not in NON_CONCLUANTES:
        etat = _demand_matrix(0.0, 0.0, 0.0, n)
        if etat in NON_CONCLUANTES:                 # ne fait que DÉGRADER, jamais remonter
            relu["demand_matrix"] = etat
    return relu


def relire_resultat_fiction(resultat):
    """Un résultat fiction ENREGISTRÉ avant `mesure_mince`, relu sous la règle d'aujourd'hui.

    Un travail déjà dans `jobs.db` porte `demand_matrix = "mort"` ou `"mur_installe"` bâti sur UN
    livre, et pas de `n_livres_mesures` (les deux runs réels de Baptiste, au 2026-10-05). Rouvert,
    il affichait la conclusion rouge et un bouton d'analyse que le serveur refusait ensuite. On le
    relit donc À LA LECTURE avec la MÊME fonction que le moteur (`livres_scorables`) : une seconde
    définition de « mesuré » côté JS divergerait (§5.32). Le brut reste en base.

    Ne fait que DÉGRADER (jamais un état non concluant remonté), ne touche pas un résultat qui
    porte déjà son compteur, rend une copie, et ne lève jamais : ce qui n'est pas une liste, ou
    n'a pas la forme d'un rapport, est rendu tel quel."""
    if not isinstance(resultat, list):
        return resultat
    return [_relire_une(e) for e in resultat]
