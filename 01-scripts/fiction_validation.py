"""fiction_validation.py — protocole de mesure de l'accord IA/humain sur le classifieur
de blurb (M4). Le brief « ≥ 80 % d'accord sur 50 livres » ne définissait pas *accord* :
la définition est ici, assumée explicitement (cf. plan M4, tâche M4-3) :
- tropes : indice de Jaccard IA vs humain (deux ensembles vides = accord parfait) ;
- décor : égalité stricte, None compris ;
- un livre est en accord si jaccard(tropes) >= 0.5 ET décor identique ET est_roman identique.
Sous la porte des 80 %, ce n'est pas le classifieur qu'on corrige mais la TAXONOMIE
(clés ambiguës) — d'où `cles_litigieuses`, qui dit QUELLES clés divergent."""
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment
from pydantic import BaseModel, Field

from fiction_taxonomy import valid_keys
from models import EnrichedBook, TropeClassification

_SEUIL_ACCORD = 0.8            # la porte des 80 % (plan M4)
_BLURB_TRONQUE = 600           # lisibilité du xlsx, pas une limite de contenu

# Colonnes de la feuille "Validation", dans l'ordre exact du plan M4 (les 4 dernières
# vides = ce que Baptiste remplit).
_HEADERS = ["asin", "titre", "auteur", "blurb", "tropes_ia", "decor_ia", "est_roman_ia",
           "confiance", "tropes_ok", "decor_ok", "est_roman_ok", "notes"]


def jaccard(a: set, b: set) -> float:
    """Deux ensembles vides = accord parfait : s'accorder sur « aucun trope » est un accord,
    pas une absence de mesure (sinon toute niche sans trope détecté casserait le taux)."""
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def accord(ia: TropeClassification, humain: TropeClassification) -> bool:
    """Les 3 critères sont ET, pas OU : un décor juste avec des tropes à côté de la plaque
    n'est pas une classification utilisable."""
    return (jaccard(set(ia.tropes), set(humain.tropes)) >= 0.5
            and ia.decor == humain.decor
            and ia.est_roman == humain.est_roman)


class AgreementReport(BaseModel):
    n_livres: int
    n_accord: int
    taux: float
    porte_franchie: bool
    cles_litigieuses: dict[str, dict[str, int]] = Field(default_factory=dict)
    desaccords: list[str] = Field(default_factory=list)     # ASIN en désaccord


def agreement_report(paires: list[tuple[TropeClassification, TropeClassification]]) -> AgreementReport:
    """Mesure le taux d'accord et, pour chaque désaccord, quelles clés de tropes divergent
    (vue seulement par l'IA -> `ia_seule`, vue seulement par l'humain -> `humain_seul`).
    Une paire en accord ne contribue à aucune clé litigieuse : elle ne pose pas problème."""
    n = len(paires)
    n_accord = 0
    desaccords: list[str] = []
    cles_litigieuses: dict[str, dict[str, int]] = {}
    for ia, humain in paires:
        if accord(ia, humain):
            n_accord += 1
            continue
        desaccords.append(ia.asin)
        for cle in set(ia.tropes) - set(humain.tropes):
            cles_litigieuses.setdefault(cle, {"ia_seule": 0, "humain_seul": 0})
            cles_litigieuses[cle]["ia_seule"] += 1
        for cle in set(humain.tropes) - set(ia.tropes):
            cles_litigieuses.setdefault(cle, {"ia_seule": 0, "humain_seul": 0})
            cles_litigieuses[cle]["humain_seul"] += 1
    taux = (n_accord / n) if n else 0.0    # défaut pessimiste : rien mesuré != porte franchie
    return AgreementReport(n_livres=n, n_accord=n_accord, taux=taux,
                           porte_franchie=taux >= _SEUIL_ACCORD,
                           cles_litigieuses=cles_litigieuses, desaccords=desaccords)


def export_validation(livres: list[EnrichedBook], classifications: list[TropeClassification],
                      sous_genre_cle: str, path, version: str = "fr_v1") -> None:
    """xlsx à 2 feuilles : la feuille de saisie (étiquettes IA pré-remplies, colonnes *_ok
    vides pour Baptiste) et les clés autorisées à copier-coller. La version de taxonomie est
    stampée dans les propriétés du classeur (pas une colonne visible) pour que
    `load_corrections` sache reconstruire des TropeClassification valides."""
    by_asin = {c.asin: c for c in classifications}

    wb = Workbook()
    wb.properties.keywords = version           # relu par load_corrections
    wb.properties.subject = sous_genre_cle

    ws = wb.active
    ws.title = "Validation"
    ws.append(_HEADERS)
    for b in livres:
        c = by_asin.get(b.asin)
        ws.append([
            b.asin, b.title, b.author or "",
            (b.blurb or "")[:_BLURB_TRONQUE],
            ", ".join(c.tropes) if c else "",
            c.decor if c and c.decor else "",
            (c.est_roman if c else True),
            (c.confidence if c else 0.0),
            "", "", "", "",                      # tropes_ok / decor_ok / est_roman_ok / notes
        ])
    widths = [14, 30, 20, 70, 30, 18, 12, 10, 30, 18, 12, 30]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    for row in ws.iter_rows(min_row=2, min_col=4, max_col=4):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    ws2 = wb.create_sheet("Clés autorisées")
    tropes, decors = valid_keys(sous_genre_cle, version)
    ws2.append(["tropes"])
    for t in tropes:
        ws2.append([t])
    ws2.append([])
    ws2.append(["decors"])
    for d in decors:
        ws2.append([d])

    wb.save(str(path))


def _rempli(v) -> bool:
    return v is not None and str(v).strip() != ""


def load_corrections(path) -> list[TropeClassification]:
    """Ne rend QUE les lignes effectivement corrigées par Baptiste (au moins une colonne
    *_ok remplie). Une ligne laissée vide n'est pas un avis « d'accord » : la compter
    gonflerait artificiellement le taux d'accord mesuré."""
    wb = load_workbook(str(path))
    ws = wb["Validation"] if "Validation" in wb.sheetnames else wb.active
    version = wb.properties.keywords or ""
    idx = {h: i for i, h in enumerate(next(ws.iter_rows(min_row=1, max_row=1, values_only=True)))}

    out: list[TropeClassification] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row is None or not any(row):
            continue
        tropes_ok = row[idx["tropes_ok"]]
        decor_ok = row[idx["decor_ok"]]
        est_roman_ok = row[idx["est_roman_ok"]]
        notes = row[idx["notes"]]
        if not (_rempli(tropes_ok) or _rempli(decor_ok) or _rempli(est_roman_ok) or _rempli(notes)):
            continue                    # rien de corrigé -> pas un avis, on ignore la ligne
        tropes = [t.strip() for t in str(tropes_ok).split(",") if t.strip()] if _rempli(tropes_ok) else []
        est_roman = True
        if _rempli(est_roman_ok):
            est_roman = str(est_roman_ok).strip().lower() not in ("false", "faux", "0", "non")
        out.append(TropeClassification(
            asin=row[idx["asin"]],
            taxonomy_version=version,
            tropes=tropes,
            decor=str(decor_ok).strip() if _rempli(decor_ok) else None,
            est_roman=est_roman,
        ))
    return out
