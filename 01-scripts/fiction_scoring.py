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
}


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


def _demand_matrix(depth: float, openness: float, saturation: float) -> str:
    """La matrice croise profondeur (y a-t-il de l'argent ?) et ouverture (reste-t-il de
    la place ?), la saturation du trio n'arbitrant QUE le cas haute/haute (pépite vs sujet
    déjà couvert par tout le monde) — jamais l'autocomplete, qui ne gate jamais seul."""
    depth_haute = depth >= SEUILS["depth_haute"]
    openness_haute = openness >= SEUILS["openness_haute"]
    saturation_haute = saturation >= SEUILS["saturation_haute"]
    if depth_haute and openness_haute:
        return "porteur_encombre" if saturation_haute else "pepite"
    if depth_haute:
        return "mur_installe"
    if openness_haute:
        return "desert"
    return "mort"


def _verdict(shelf: FictionShelf, ok: list[EnrichedBook],
            classifications: dict[str, TropeClassification], matrix: str, depth: float,
            openness: float, saturation: float, signal: AutocompleteSignal) -> str:
    """Verdict court et tranché qui signale explicitement (CLAUDE.md §10 + spike M0 §V3) :
    un rayon incomplet (jamais lu comme un désert), un sous-genre fantôme sur
    l'autocomplete, une part de livres non classés, et le périmètre réel de la saturation."""
    bits = [f"{matrix} — depth={depth:.2f}, openness={openness:.2f}, "
            f"saturation_trio={saturation:.2f}."]
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
    AVANT tout calcul de métrique, porte l'AutocompleteSignal ENTIER (jamais son seul
    float — dette réglée le 2026-07-20, sinon `mesure`/`sous_genre_cherche` se perdent et
    0.0 redevient indiscernable d'un « absent » mesuré), et ne laisse JAMAIS l'autocomplete
    arbitrer `demand_matrix`."""
    ok = livres_scorables(shelf.books, classifications, niche.rayon, version)
    depth = depth_score(ok)
    openness = openness_score(ok)
    saturation = saturation_trio(niche, ok, classifications)
    matrix = _demand_matrix(depth, openness, saturation)
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
    )
