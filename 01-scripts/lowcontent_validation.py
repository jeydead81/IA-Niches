"""lowcontent_validation.py — protocole de calibration du scoring low-content (G1).

Les seuils de `data/lowcontent_criteres.json` sont des HYPOTHÈSES : `variantes_max=6`,
`part_indie_bonne=0.5`, `redevance_min_bonne=2.0` n'ont été confrontés à aucun rayon
réel. Le moteur tourne et rend des chiffres cohérents entre eux ; rien ne dit qu'ils
correspondent à ce que Baptiste sait du terrain. Ce module produit la mesure qui manque.

**Le protocole INVERSE celui du classifieur fiction, et c'est le point.** En fiction,
Baptiste CORRIGE des étiquettes que l'IA a produites (`fiction_validation.py`). Ici il
étiquette des requêtes AVANT toute analyse : son jugement est la référence, pas la
retouche d'une sortie. Si l'IA proposait les requêtes à juger, on calibrerait le scoring
sur lui-même et la corrélation serait garantie sans rien prouver.

Critère de sortie, conjoint : **Spearman ≥ 0,5 ET aucune requête « morte » en 🟢**.
Une corrélation honnête qui recommande quand même un rayon mort ferait publier dans le
vide — la faute la plus chère du produit (règle 3), et elle ne se compense pas par une
bonne moyenne d'ensemble.

Trois décisions de mesure, toutes dans le même esprit que §5.10 :
- Spearman et non Pearson : les étiquettes sont ORDINALES (morte < mauvaise < bonne),
  pas numériques. L'écart « morte → mauvaise » n'a aucune raison de valoir l'écart
  « mauvaise → bonne », et Pearson supposerait que si.
- Rangs MOYENS sur les ex aequo : avec trois étiquettes il y en aura partout, et un
  départage arbitraire mesurerait l'ordre de saisie du fichier.
- Les niches dont la concurrence n'a PAS été mesurée sortent du calcul. Leur score a été
  produit sans le moindre bonus ni malus de SERP : les corréler mesurerait l'écart entre
  un humain qui a vu le rayon et un score qui ne l'a pas vu. Elles sont comptées et
  annoncées (`n_non_mesurees`), jamais jetées en silence.

En cas d'échec, on corrige `data/lowcontent_criteres.json` — **jamais le code**. Un seuil
qui migre dans `lowcontent_scoring.py` redevient invisible et non discutable.
"""
from __future__ import annotations

from pathlib import Path
from statistics import median

from pydantic import BaseModel, Field

from lowcontent_taxonomy import load_taxonomy
from models import LowContentScored

# Ordre volontairement croissant : c'est la valeur ordinale corrélée au score.
ETIQUETTES: tuple[str, ...] = ("morte", "mauvaise", "bonne")
_ORDINAL: dict[str, int] = {e: i for i, e in enumerate(ETIQUETTES)}

SEUIL_SPEARMAN = 0.5           # porte du plan G1
MIN_PAR_FAMILLE = 3            # en deçà, la famille n'est pas calibrée, elle est frôlée
SEUIL_VERT = 7.5               # miroir de lowcontent_scoring : « 🟢 À analyser en priorité »

_ENTETES = ["requete", "famille", "etiquette", "note"]


# ── Spearman ───────────────────────────────────────────────────────────────────

def _rangs(valeurs: list[float]) -> list[float]:
    """Rangs 1..n, MOYENNÉS sur les ex aequo.

    Sans cette moyenne, `[bonne, bonne, mauvaise]` recevrait les rangs 1, 2, 3 : le
    premier « bonne » du fichier serait déclaré meilleur que le second alors que Baptiste
    les a jugés identiques. La corrélation mesurerait l'ordre des lignes."""
    ordre = sorted(range(len(valeurs)), key=lambda i: valeurs[i])
    out = [0.0] * len(valeurs)
    i = 0
    while i < len(ordre):
        j = i
        while j + 1 < len(ordre) and valeurs[ordre[j + 1]] == valeurs[ordre[i]]:
            j += 1
        moyen = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[ordre[k]] = moyen
        i = j + 1
    return out


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Corrélation de rangs. `None` quand elle est INDÉFINIE, jamais 0.0.

    Deux cas d'indéfinition, et les confondre avec « aucune corrélation » serait la même
    faute que partout ailleurs dans ce dépôt (§5.10) :
    - moins de deux points : il n'y a pas de classement ;
    - une série constante (toutes les étiquettes identiques, ou tous les scores égaux) :
      l'écart-type des rangs est nul, il n'y a rien à corréler. Rendre 0,0 se lirait
      « le scoring ne suit pas Baptiste » alors que le jeu ne permet pas de le dire."""
    if len(xs) != len(ys):
        raise ValueError(f"séries de longueurs différentes : {len(xs)} vs {len(ys)}")
    n = len(xs)
    if n < 2:
        return None
    rx, ry = _rangs(list(xs)), _rangs(list(ys))
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx)
    dy = sum((b - my) ** 2 for b in ry)
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy) ** 0.5


# ── Le gabarit que Baptiste remplit ────────────────────────────────────────────

class RequeteEtiquetee(BaseModel):
    requete: str
    famille: str = ""
    etiquette: str
    note: str = ""


def familles_taxonomie(version: str = "fr_v1") -> list[str]:
    """Source unique : les familles viennent de la taxo, jamais d'une liste en dur.
    Une famille ajoutée en v2 apparaît alors d'elle-même dans le gabarit."""
    taxo = load_taxonomy(version)
    vues: dict[str, None] = {}
    for f in taxo["formats"].values():
        vues.setdefault(f["famille"], None)
    return list(vues)


def exporter_gabarit(path: str | Path, n_par_famille: int = MIN_PAR_FAMILLE + 1,
                     version: str = "fr_v1") -> Path:
    """Écrit le classeur vide, pré-découpé PAR FAMILLE.

    Une page blanche produirait vingt requêtes de carnets et zéro registre : on
    calibrerait le rayon que Baptiste connaît le mieux, et on croirait avoir calibré le
    produit. Les lignes sont donc déjà attribuées, et le rapport redira lesquelles sont
    restées vides."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "Validation"

    ws.append(["Jeu de validation low-content — étiquetez AVANT toute analyse"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"Étiquettes autorisées : {' | '.join(ETIQUETTES)}"])
    ws.append([f"Au moins {MIN_PAR_FAMILLE} requêtes par famille — en deçà, cette famille "
               f"n'est pas calibrée."])
    ws.append(["« morte » = personne n'achète · « mauvaise » = demandé mais impénétrable "
               "ou non rentable · « bonne » = j'y publierais"])
    ws.append([])
    ws.append(list(_ENTETES))
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)

    premiere = ws.max_row + 1
    for famille in familles_taxonomie(version):
        for _ in range(n_par_famille):
            ws.append(["", famille, "", ""])

    dv = DataValidation(type="list", formula1='"' + ",".join(ETIQUETTES) + '"',
                        allow_blank=True, showDropDown=False)
    ws.add_data_validation(dv)
    dv.add(f"C{premiere}:C{ws.max_row}")

    for col, largeur in zip("ABCD", (52, 16, 14, 46)):
        ws.column_dimensions[col].width = largeur
    for ligne in ws.iter_rows(min_row=1, max_row=4, max_col=1):
        ligne[0].alignment = Alignment(wrap_text=False)

    out = Path(path)
    wb.save(out)
    return out


def charger_etiquettes(path: str | Path) -> list[RequeteEtiquetee]:
    """Relit le classeur corrigé. Une ligne non remplie est IGNORÉE (c'est l'état normal
    d'un gabarit fraîchement créé) ; une étiquette inconnue LÈVE.

    L'asymétrie est voulue : une ligne vide est un travail pas encore fait, une étiquette
    « bof » est un travail fait de travers. L'avaler amputerait le jeu de validation sans
    que personne s'en aperçoive — et un jeu amputé en silence mesure faux."""
    from openpyxl import load_workbook

    ws = load_workbook(Path(path), data_only=True).active
    lignes = [[(c.value if c.value is not None else "") for c in r]
              for r in ws.iter_rows(max_col=4)]

    debut = None
    for i, l in enumerate(lignes):
        if [str(v).strip().lower() for v in l[:4]] == _ENTETES:
            debut = i + 1
            break
    if debut is None:
        raise ValueError(f"aucune ligne d'en-tête {_ENTETES} dans {path}")

    out: list[RequeteEtiquetee] = []
    for i, l in enumerate(lignes[debut:], start=debut + 1):
        requete = str(l[0]).strip()
        etiquette = str(l[2]).strip().lower()
        if not requete and not etiquette:
            continue
        if etiquette not in ETIQUETTES:
            raise ValueError(
                f"ligne {i} : étiquette « {etiquette or '(vide)'} » inconnue pour "
                f"« {requete or '(sans requête)'} » — attendu {' | '.join(ETIQUETTES)}")
        if not requete:
            raise ValueError(f"ligne {i} : étiquette « {etiquette} » sans requête")
        out.append(RequeteEtiquetee(requete=requete, famille=str(l[1]).strip(),
                                    etiquette=etiquette, note=str(l[3]).strip()))
    return out


# ── Le rapport ─────────────────────────────────────────────────────────────────

class RapportCalibration(BaseModel):
    """Ce qui s'archive dans `99-logs/`, à côté du rapport du classifieur fiction.

    `porte_franchie` ne dépend QUE des deux critères du plan. Les `avertissements` — une
    famille sous-représentée, des SERP tombées — ne la ferment pas : ils disent sur quoi
    la mesure ne porte pas, ce qui est une information distincte de « le scoring a tort »."""
    n_requetes: int = 0
    n_calibrees: int = 0
    n_non_mesurees: int = 0
    n_par_etiquette: dict[str, int] = Field(default_factory=dict)

    spearman: float | None = None
    seuil_spearman: float = SEUIL_SPEARMAN
    morts_en_vert: list[str] = Field(default_factory=list)
    porte_franchie: bool = False

    # Distribution des signaux par étiquette — c'est CE tableau qui sert à régler
    # `lowcontent_criteres.json`. Sans lui on ajusterait un seuil au hasard.
    signaux: dict[str, dict[str, float | int | None]] = Field(default_factory=dict)
    familles: dict[str, int] = Field(default_factory=dict)

    # Requêtes perdues AVANT toute dépense (filtre IP, filtre saisonnier, gate gratuit).
    # Séparées par étiquette parce qu'elles ne disent pas la même chose : une « morte »
    # écartée là est le gate qui fait son travail pour zéro centime ; une « bonne »
    # écartée là est un faux négatif que l'utilisateur ne peut PAS voir, puisque la niche
    # n'apparaît nulle part. Les additionner effacerait exactement cette différence.
    ecartees_correctement: list[str] = Field(default_factory=list)
    bonnes_perdues_avant_analyse: list[str] = Field(default_factory=list)
    hors_taxonomie: list[dict[str, str]] = Field(default_factory=list)
    avertissements: list[str] = Field(default_factory=list)


def _est_vert(s: LowContentScored) -> bool:
    """La priorité fait foi quand elle est renseignée ; à défaut on retombe sur le seuil.
    Se fier au seul score raterait le cas « ⚪ non mesurée » qui peut porter un score
    élevé sans jamais s'afficher en vert."""
    if s.priorite:
        return s.priorite.startswith("🟢")
    return s.global_score >= SEUIL_VERT


def _mediane(valeurs: list[float | None]) -> float | None:
    """Les `None` sont EXCLUS, jamais comptés zéro. Moyenner une part indie non mesurée à
    zéro fausserait exactement le seuil qu'on cherche à régler (§5.10)."""
    connus = [v for v in valeurs if v is not None]
    return median(connus) if connus else None


def rapport_calibration(paires: list[tuple[str, LowContentScored]],
                        familles: list[str] | None = None,
                        ecartees: list[tuple[str, str]] | None = None,
                        version: str = "fr_v1") -> RapportCalibration:
    """`paires` = (étiquette de Baptiste, niche scorée par le moteur), dans le même ordre
    que `familles` si elle est fournie. `ecartees` = (requête, étiquette) des requêtes
    perdues avant la moindre dépense."""
    r = RapportCalibration(n_requetes=len(paires) + len(ecartees or []))
    if familles is not None and len(familles) != len(paires):
        raise ValueError(f"{len(familles)} familles pour {len(paires)} paires")

    for e, _ in paires:
        if e not in ETIQUETTES:
            raise ValueError(f"étiquette « {e} » inconnue — attendu {ETIQUETTES}")
        r.n_par_etiquette[e] = r.n_par_etiquette.get(e, 0) + 1

    # Le signal terrain qui fera la taxonomie v2 : indépendant de la SERP, donc lu sur
    # TOUTES les paires, y compris celles dont la concurrence n'a pas pu être mesurée.
    for _, s in paires:
        if s.niche.format_cle == "other":
            r.hors_taxonomie.append({"requete": s.niche.requete_amazon,
                                     "libelle_observe": s.niche.other_libelle})

    r.morts_en_vert = [s.niche.requete_amazon for e, s in paires
                       if e == "morte" and _est_vert(s)]

    for requete, e in (ecartees or []):
        if e not in ETIQUETTES:
            raise ValueError(f"étiquette « {e} » inconnue — attendu {ETIQUETTES}")
        r.n_par_etiquette[e] = r.n_par_etiquette.get(e, 0) + 1
        (r.bonnes_perdues_avant_analyse if e == "bonne"
         else r.ecartees_correctement).append(requete)
    if r.bonnes_perdues_avant_analyse:
        r.avertissements.append(
            f"{len(r.bonnes_perdues_avant_analyse)} requête(s) jugée(s) « bonne » "
            f"perdue(s) AVANT toute analyse : "
            f"{', '.join(r.bonnes_perdues_avant_analyse)}. Faux négatif invisible — "
            f"la niche n'apparaît nulle part à l'écran. Vérifier le filtre IP, le filtre "
            f"saisonnier et le gate gratuit. N'entre PAS dans la porte du plan.")
    if r.ecartees_correctement:
        r.avertissements.append(
            f"{len(r.ecartees_correctement)} requête(s) non « bonne(s) » écartée(s) pour "
            f"zéro centime : le gate gratuit a fait son travail.")

    calibrables = [(e, s) for e, s in paires if s.concurrence_mesuree]
    r.n_calibrees = len(calibrables)
    r.n_non_mesurees = len(paires) - len(calibrables)
    if r.n_non_mesurees:
        r.avertissements.append(
            f"{r.n_non_mesurees} requête(s) écartée(s) du calcul : concurrence non "
            f"mesurée (SERP tombée). Leur score n'a reçu ni bonus ni malus de "
            f"concurrence — les corréler mesurerait du bruit. À relancer.")

    r.spearman = spearman([float(_ORDINAL[e]) for e, _ in calibrables],
                          [s.global_score for _, s in calibrables])

    for etiquette in ETIQUETTES:
        lot = [s for e, s in calibrables if e == etiquette]
        if not lot:
            continue
        r.signaux[etiquette] = {
            "n": len(lot),
            "score": _mediane([s.global_score for s in lot]),
            "part_indie": _mediane([s.part_indie for s in lot]),
            "n_part_indie_mesuree": sum(1 for s in lot if s.part_indie is not None),
            "n_variantes": _mediane([float(s.n_variantes_quasi_identiques) for s in lot]),
            "n_concurrents_cibles": _mediane([float(s.n_concurrents_cibles) for s in lot]),
            "prix_median": _mediane([s.prix_median for s in lot]),
            "redevance": _mediane([s.redevance_estimee for s in lot]),
            "n_redevance_mesuree": sum(1 for s in lot if s.redevance_estimee is not None),
            "bsr_best": _mediane([float(s.bsr_best) for s in lot
                                  if s.bsr_best is not None]),
            "part_bsr_ok": sum(1 for s in lot if s.criteres_bsr_ok) / len(lot),
        }

    if familles is not None:
        for f in familles_taxonomie(version):
            r.familles[f] = 0
        for f in familles:
            r.familles[f] = r.familles.get(f, 0) + 1
        maigres = [f for f, n in r.familles.items() if n < MIN_PAR_FAMILLE]
        if maigres:
            r.avertissements.append(
                f"famille(s) sous-représentée(s) (< {MIN_PAR_FAMILLE} requêtes) : "
                f"{', '.join(f'{f} ({r.familles[f]})' for f in maigres)} — la "
                f"calibration ne porte pas sur ces rayons, elle les frôle.")

    r.porte_franchie = (r.spearman is not None
                        and r.spearman >= SEUIL_SPEARMAN
                        and not r.morts_en_vert)
    return r
