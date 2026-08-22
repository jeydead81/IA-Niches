"""lowcontent_scoring.py — scoring 4 axes d'une niche low-content. PUR, sans E/S réseau.

Deux axes n'existent pas en non-fiction, et ce n'est pas un raffinement :

- RENTABILITÉ. Sous 9,99 € de prix catalogue, KDP verse 50 % au lieu de 60 %, et le coût
  d'impression se déduit ENSUITE. Un rayon très demandé à 6,99 € peut ne rien rapporter,
  voire coûter de l'argent sur un fort pagination. En non-fiction, un livre de texte à
  14,99 € ne pose jamais cette question.
- FAISABILITÉ. Un carnet quadrillé et un cahier d'activités illustré ne se produisent pas
  dans le même monde. En non-fiction tout est du texte.

Et deux signaux de pénétration propres au rayon :
- PART INDIE. Douze références peuvent toutes venir de papetiers (Exacompta, Quo Vadis,
  Clairefontaine). Un comptage de résultats ne le voit pas, et c'est pourtant ce qui décide
  si le rayon est attaquable par un auteur seul.
- VARIANTES QUASI IDENTIQUES. Dix couvertures pour un seul intérieur, ce n'est pas un rayon
  concurrentiel, c'est une ferme de variantes. Publier la onzième n'y gagne rien.

Les seuils vivent dans `data/lowcontent_criteres.json` : ce sont des HYPOTHÈSES tant que le
chunk G1 ne les a pas calibrés sur un jeu étiqueté. La règle est que G1 recalibre le
FICHIER, jamais ce module — un seuil qui migre ici redevient invisible et non discutable.

Invariant transversal, comme partout dans le dépôt : une absence de mesure ne se convertit
jamais en mesure défavorable. `part_indie` vaut `None` et pas `0.0`, et aucun bonus ni
malus ne s'applique sur un `None`.
"""
import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

from lowcontent_taxonomy import est_editeur_traditionnel, est_indie, est_norme, format_
from marketplace import ACTIF
from models import LowContentNiche, LowContentScored, TopBook
from scoring import MAX_TOP_BOOKS, count_targeted

_DATA = Path(__file__).resolve().parent.parent / "data"
_CRITERES: dict | None = None
_COUTS: dict | None = None

_MOIS_FR = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
            "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
            "decembre": 12}

# Mots qui décrivent le CONTENANT, pas le sujet. Les garder ferait de deux carnets
# distincts des variantes l'un de l'autre — « 120 pages A5 broché » est commun à tout le
# rayon low-content, c'est du bruit par construction.
_BRUIT = {"pages", "page", "format", "broche", "relie", "couverture", "souple", "rigide",
          "grand", "petit", "cahier", "carnet", "livre", "edition", "vol", "tome",
          "a4", "a5", "b5", "cm", "x", "et", "de", "du", "des", "la", "le", "les",
          "un", "une", "pour", "avec", "en", "sur", "par", "au", "aux"}


def _plat(t: str) -> str:
    s = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def charger_criteres(chemin: Path | None = None) -> dict:
    """Rend une COPIE : un appelant qui surcharge un seuil pour calibrer ne doit pas
    contaminer le reste du processus."""
    global _CRITERES
    if chemin is not None:
        return json.loads(chemin.read_text(encoding="utf-8"))
    if _CRITERES is None:
        _CRITERES = json.loads((_DATA / "lowcontent_criteres.json").read_text("utf-8"))
    return dict(_CRITERES)


def charger_couts() -> dict:
    global _COUTS
    if _COUTS is None:
        _COUTS = json.loads((_DATA / "kdp_print_costs.json").read_text("utf-8"))
    return _COUTS


def _clamp(x: float, lo: float = 1.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, x))


# ── Éditeurs ───────────────────────────────────────────────────────────────────

def _part(livres, predicat) -> tuple[float | None, int]:
    """Part des livres vérifiant `predicat`, les INCONNUS exclus du dénominateur.

    Les compter au dénominateur reviendrait à les traiter comme « ne vérifie pas le
    prédicat » — c'est-à-dire à transformer une absence de lecture en mesure défavorable.
    `n_inconnu` dit sur combien de livres la part NE porte pas : « 60 % d'indie » sur deux
    livres ne se lit pas comme sur vingt (même logique que `n_prix_connus` §4.1)."""
    connus, oui, inconnus = 0, 0, 0
    for b in livres or []:
        v = predicat(getattr(b, "publisher", None))
        if v is None:
            inconnus += 1
            continue
        connus += 1
        oui += 1 if v else 0
    if not connus:
        return None, inconnus
    return round(oui / connus, 4), inconnus


def part_indie(livres) -> tuple[float | None, int]:
    return _part(livres, est_indie)


def part_editeurs_traditionnels(livres) -> tuple[float | None, int]:
    def pred(p):
        v = est_indie(p)
        return None if v is None else est_editeur_traditionnel(p)
    return _part(livres, pred)


# ── Fraîcheur ──────────────────────────────────────────────────────────────────

def _lire_date(brut: str | None) -> date | None:
    """« 12 mars 2025 », « 2025-03-12 », « 12/03/2025 ». Rend `None` sur le reste.

    `None` et jamais une date par défaut : un livre dont la date est illisible sera EXCLU
    du calcul, pas compté comme ancien — le compter ancien ferait passer un rayon
    récemment inondé pour un rayon installé."""
    t = _plat(brut or "").strip()
    if not t:
        return None
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    m = re.match(r"(\d{1,2})\s+([a-z]+)\.?\s+(\d{4})", t)
    if m and m.group(2) in _MOIS_FR:
        try:
            return date(int(m.group(3)), _MOIS_FR[m.group(2)], int(m.group(1)))
        except ValueError:
            return None
    return None


def part_recents(livres, mois: int = 12, aujourdhui=None) -> tuple[float | None, int]:
    """Part des livres publiés dans les `mois` derniers mois.

    Un afflux récent n'est pas une bonne nouvelle : il dit qu'une tendance est déjà
    repérée et inondée. `aujourdhui` est injectable — sans ça le test se périme."""
    if aujourdhui is None:
        ref = date.today()
    elif isinstance(aujourdhui, str):
        ref = datetime.strptime(aujourdhui, "%Y-%m-%d").date()
    else:
        ref = aujourdhui
    limite = ref.toordinal() - int(mois * 30.44)
    connus, recents, inconnus = 0, 0, 0
    for b in livres or []:
        d = _lire_date(getattr(b, "publication_date", None))
        if d is None:
            inconnus += 1
            continue
        connus += 1
        recents += 1 if d.toordinal() >= limite else 0
    if not connus:
        return None, inconnus
    return round(recents / connus, 4), inconnus


# ── Variantes ──────────────────────────────────────────────────────────────────

def _tokens(titre: str) -> set[str]:
    mots = re.split(r"[^\w]+", _plat(titre))
    return {m for m in mots if m and len(m) > 1 and m not in _BRUIT and not m.isdigit()}


def variantes_quasi_identiques(titres, seuil: float = 0.6) -> int:
    """Taille du plus gros groupe de titres quasi identiques.

    Zéro sur une liste vide : ce n'est pas « aucune variante », c'est une absence de
    mesure, et l'appelant doit pouvoir faire la différence.

    LIMITE ASSUMÉE : le calcul porte sur les mots UTILES, le bruit de format (« 120
    pages », « A5 », « broché ») étant retiré. Un titre très court ne laisse donc que deux
    ou trois mots, et un seul mot différent fait tomber Jaccard sous le seuil : deux
    carnets « Carnet glycémie bleu » / « Carnet glycémie rose » ne seront PAS groupés. Les
    vraies fermes de variantes ont des titres longs et bourrés de mots-clés, où l'overlap
    est écrasant — c'est ce cas-là que le calcul vise. `seuil` est calibrable si la mesure
    en live dit le contraire (G1)."""
    titres = [t for t in (titres or []) if t]
    if not titres:
        return 0
    sacs = [_tokens(t) for t in titres]
    plus_gros = 1
    for i, a in enumerate(sacs):
        groupe = 1
        for j, b in enumerate(sacs):
            if i == j or not (a or b):
                continue
            union = a | b
            if union and len(a & b) / len(union) >= seuil:
                groupe += 1
        plus_gros = max(plus_gros, groupe)
    return plus_gros


# ── Redevance ──────────────────────────────────────────────────────────────────

def redevance_estimee(prix: float | None, pages: int | None, encre: str = "bw",
                      marketplace: str = "fr") -> float | None:
    """(taux × prix) − coût d'impression, en euros. Barèmes RELEVÉS, jamais estimés.

    Sources et date de relevé dans `data/kdp_print_costs.json`. Ces barèmes sont ceux
    d'Amazon, pas les nôtres : ils changent sans que le dépôt en soit informé.

    La grille a DEUX bandes par encre, et chacune a SON forfait : 2,05 EUR pour 24-110
    pages sans cout par page, 0,75 EUR + 0,012 EUR/page au-dela. Sous le seuil, le cout est
    un forfait PLAT propre a la bande courte -- ce n'est PAS le forfait de la bande longue
    ampute de sa part par page. Le premier relevé avait fait cette confusion : il
    sous-estimait le cout d'impression de 1,30 EUR sur toute pagination courte, donc
    surestimait la redevance d'autant, sur 35 des 36 formats de la taxonomie. Le symptome
    qui l'a trahi : passer de 110 a 111 pages coutait 1,33 EUR de plus, ce qu'aucune grille
    d'impression a la demande ne fait.

    Rend `None` si le prix ou la pagination manque — une redevance inconnue n'est pas une
    redevance nulle, et le scoring n'applique rien dessus.

    Une redevance NÉGATIVE est rendue telle quelle : un carnet de 400 pages à 6,99 € perd
    de l'argent à chaque vente, et c'est exactement ce qu'il faut montrer. La ramener à
    zéro cacherait le seul cas où la réponse est « ne publie pas ça »."""
    if prix is None or pages is None:
        return None
    couts = charger_couts()
    if marketplace != couts["marketplace"]:
        raise ValueError(f"barème d'impression non relevé pour « {marketplace} » "
                         f"(disponible : {couts['marketplace']})")
    grille = couts["encres"].get(encre)
    if grille is None:
        raise ValueError(f"encre inconnue : « {encre} » "
                         f"(dispo : {sorted(couts['encres'])})")
    if pages > grille["seuil_cout_fixe_seul"]:
        impression = grille["cout_fixe_bande_longue"] + pages * grille["cout_par_page"]
    else:
        impression = grille["cout_fixe_bande_courte"]
        if impression is None:
            # Bande courte non relevee pour cette encre : on ne DEVINE pas un forfait.
            # None remonte tel quel -- une redevance inconnue n'est pas une redevance.
            return None
    r = couts["redevance"]
    taux = r["taux_haut"] if prix >= r["seuil_taux_haut"] else r["taux_bas"]
    return round(taux * prix - impression, 4)


def _median(valeurs):
    v = sorted(x for x in valeurs if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


# ── Score ──────────────────────────────────────────────────────────────────────

def score_lowcontent(niche: LowContentNiche, validation, search, livres: list,
                     bsrs: list[int], criteres: dict | None = None,
                     bsr_map: dict[str, int] | None = None,
                     subcats_map: dict[str, list[dict]] | None = None,
                     aujourdhui=None) -> LowContentScored:
    """Les quatre axes, pondérés 0,35 / 0,35 / 0,20 / 0,10."""
    c = criteres or charger_criteres()
    organic = search.organic if search else []
    sponsored = search.sponsored if search else []
    mesuree = search is not None

    # Comme en non-fiction : les SPONSORISÉS sont écartés de tout calcul de qualité. Un
    # livre qui a payé sa place ne dit rien de ce qu'il faut battre organiquement.
    titres = [o.title for o in organic if o.title]
    prix = [o.price for o in organic if o.price is not None]
    n_cibles = count_targeted(validation.requete_amazon or validation.niche, organic)
    variantes = variantes_quasi_identiques(titres)

    p_indie, n_inconnu = part_indie(livres)
    p_trad, _ = part_editeurs_traditionnels(livres)
    p_recents, _ = part_recents(livres, aujourdhui=aujourdhui)
    prix_median = _median(prix) or _median([b.price for b in (livres or [])])
    pages_median = _median([b.pages for b in (livres or [])])
    pages_median = int(pages_median) if pages_median is not None else None

    vals = sorted(b for b in (bsrs or []) if isinstance(b, int) and b > 0)
    bsr_best = vals[0] if vals else None
    bsr_avg = int(sum(vals) / len(vals)) if vals else None
    bsr_worst = max(vals) if vals else None
    crit1 = bool(vals) and bsr_best < c["bsr_crit1_max"]
    crit2 = bool(vals) and bsr_avg < c["bsr_crit2_moyenne_max"]
    crit3 = bool(vals) and bsr_worst > c["bsr_crit3_place_a_prendre_min"]

    # ── AXE 1 — Demande (0,35) ──
    demande = _clamp(2 + min(validation.demand_score, 10) * 0.6)
    # Le signal propre au low-content : une requête que les acheteurs affinent ENCORE
    # porte une intention plus forte qu'une requête terminale. `demand_score` seul sature
    # (16 niches sur 30 au-dessus du plafond en non-fiction) ; la position dans l'arbre,
    # elle, discrimine encore.
    if (niche.profondeur_autocomplete or 0) >= 2:
        demande += 1
    # `None` = requete JAMAIS sondee (fond de l'arbre, ou budget epuise). Ni bonus ni
    # malus : une absence de mesure ne se convertit pas davantage en mesure defavorable
    # qu'en mesure favorable.
    if (niche.n_enfants_autocomplete or 0) >= 3:
        demande += 1
    if bsr_best is not None:
        demande += 2 if bsr_best < 5_000 else 1 if crit1 else 0
    # PAS de bonus sur `total_reviews`, contrairement au non-fiction : en low-content les
    # avis sont rares par nature (on ne commente pas un carnet). Un top à 12 avis avec un
    # BSR de 8 000 est une OPPORTUNITÉ, pas une faiblesse — l'y pénaliser inverserait la
    # lecture du rayon le plus intéressant.
    if p_trad is not None and p_trad > c["part_trad_alerte"]:
        demande -= 1        # demande captée par des marques, pas par des livres KDP
    demande = _clamp(demande)

    # ── AXE 2 — Pénétration (0,35) ──
    penetration = 5.0
    if mesuree:
        if n_cibles > c["cibles_max"]:
            penetration -= 2
        elif n_cibles > c["cibles_max"] * 0.75:
            penetration -= 1
        elif n_cibles < 10:
            penetration += 2
        if len(sponsored) >= 3:
            penetration += 0.5
        if variantes > c["variantes_max"]:
            penetration -= 2      # ferme de variantes : la onzième ne gagne rien
    # `p_indie is None` = aucun éditeur lu : on n'applique RIEN et on le dit via
    # n_editeur_inconnu, plutôt que de pénaliser une niche qu'on n'a pas su mesurer.
    if p_indie is not None and p_indie >= c["part_indie_bonne"]:
        penetration += 1
    if p_recents is not None and p_recents >= c["part_recents_afflux"]:
        penetration -= 1          # tendance déjà repérée et inondée
    if crit3:
        penetration += 1.5        # repose sur le BSR, pas sur la SERP
    penetration = _clamp(penetration)

    # ── AXE 3 — Rentabilité (0,20) ──
    redevance = redevance_estimee(prix_median, pages_median)
    rentabilite = 5.0
    if prix_median is not None:
        if prix_median >= c["seuil_prix_60pct"]:
            rentabilite += 2
        elif prix_median < c["prix_median_faible"]:
            rentabilite -= 2
    if redevance is not None and redevance >= c["redevance_min_bonne"]:
        rentabilite += 2
    fmt = None
    if niche.format_cle != "other":
        try:
            fmt = format_(niche.format_cle)
        except ValueError:
            fmt = None
    if fmt and pages_median is not None:
        bas, haut = fmt["pages"]
        if not (bas <= pages_median <= haut):
            rentabilite -= 0.5
    rentabilite = _clamp(rentabilite)

    # ── AXE 4 — Faisabilité (0,10) ──
    risques = list(niche.risques or [])
    if fmt is None:
        # « non évalué » n'est PAS « mauvais » (règle 3) : valeur neutre, et on le dit.
        faisabilite = 5.0
        if "format_hors_taxonomie" not in risques:
            risques.append("format_hors_taxonomie")
    else:
        faisabilite = {1: 9.0, 2: 7.0, 3: 5.0}[fmt["effort"]]
        if fmt["illustration"]:
            faisabilite -= 1
        # « Normé » ne veut pas dire « difficile » : le contenu est IMPOSÉ, donc la
        # production est simple — l'effort reste 1. C'est la CONFORMITÉ qui est exigeante,
        # et elle sort en risque, pas en malus de faisabilité.
        if est_norme(niche.format_cle) and "norme_a_verifier" not in risques:
            risques.append("norme_a_verifier")
    faisabilite = _clamp(faisabilite)

    glob = demande * 0.35 + penetration * 0.35 + rentabilite * 0.20 + faisabilite * 0.10
    if "ip_marque" in risques or "tos" in risques:
        glob -= 2
    if "saisonnier" in risques:
        glob -= 1
    glob = round(_clamp(glob, 0.0, 10.0), 2)

    verdict = ("⚪ Concurrence non mesurée — à relancer" if not mesuree
               else "🟢 À analyser en priorité" if glob >= 7.5
               else "🟡 Intéressant" if glob >= 6.0 else "🔴 Faible")

    return LowContentScored(
        niche=niche,
        global_score=glob, demande=round(demande, 2),
        penetration=round(penetration, 2), rentabilite=round(rentabilite, 2),
        faisabilite=round(faisabilite, 2), priorite=verdict,
        demand_autocomplete=validation.demand_score,
        n_organic=len(organic), n_sponsored=len(sponsored),
        n_concurrents_cibles=n_cibles,
        n_variantes_quasi_identiques=variantes,
        part_indie=p_indie, part_editeurs_traditionnels=p_trad,
        n_editeur_inconnu=n_inconnu, part_moins_12_mois=p_recents,
        prix_median=prix_median,
        prix_sous_seuil_60pct=(prix_median is not None
                               and prix_median < c["seuil_prix_60pct"]),
        redevance_estimee=redevance, pages_median=pages_median,
        bsr_best=bsr_best, bsr_top_avg=bsr_avg, bsr_worst=bsr_worst,
        criteres_bsr_ok=(crit1 and crit2 and crit3),
        total_reviews=sum(o.reviews_count for o in organic if o.reviews_count) or None,
        concurrence_mesuree=mesuree,
        top_books=[
            TopBook(asin=o.asin, title=o.title, url=ACTIF.url_fiche(o.asin),
                    price=o.price, rating=o.rating, reviews_count=o.reviews_count,
                    bsr=(bsr_map or {}).get(o.asin),
                    bsr_subcats=(subcats_map or {}).get(o.asin) or [],
                    sponsored=False)
            for o in organic[:MAX_TOP_BOOKS] if o.asin],
        risques=risques,
    )
