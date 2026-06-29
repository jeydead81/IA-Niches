"""
report_builder.py
-----------------
Génère le rapport Excel scout avec 3 onglets et mise en forme conditionnelle.
"""

from pathlib import Path
from datetime import datetime

import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.formatting.rule import ColorScaleRule, CellIsRule


# Couleurs
GREEN = "C6EFCE"
ORANGE = "FFEB9C"
RED = "FFC7CE"
HEADER_BG = "1F3864"
HEADER_FG = "FFFFFF"


def _header_style(ws, row: int, cols: int):
    """Applique le style d'en-tête sur une ligne."""
    for col in range(1, cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = PatternFill("solid", fgColor=HEADER_BG)
        cell.font = Font(bold=True, color=HEADER_FG)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _auto_width(ws):
    """Ajuste la largeur des colonnes."""
    for col in ws.columns:
        max_len = 0
        for cell in col:
            try:
                val = str(cell.value or "")
                max_len = max(max_len, len(val))
            except Exception:
                pass
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 45)


def build_excel_report(scored_niches: list[dict], meta: dict, output_path: Path):
    """Génère le rapport Excel complet."""
    wb = openpyxl.Workbook()

    # ── ONGLET 1 : Synthèse ───────────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "Synthèse"

    headers = [
        "Rang", "Niche (requête Amazon)", "Score global /10",
        "Demande /10", "Pénétration /10", "Compatibilité /10",
        "Bonus pharmacien", "Suggestions autocomplete Amazon",
        "BSR", "Nb sponsorisés écartés",
        "Sources signal", "Verdict",
    ]
    ws1.append(headers)
    _header_style(ws1, 1, len(headers))
    ws1.row_dimensions[1].height = 35

    for i, n in enumerate(scored_niches, 1):
        row = [
            i,
            n.get("keyword", ""),
            n.get("global_score"),
            n.get("demand_score"),
            n.get("penetre_score"),
            n.get("compat_score"),
            "✓ +1" if n.get("pharma_bonus") else "",
            n.get("nb_autocomplete_suggestions", "N/A"),
            n.get("bsr_note", "À valider en Phase 2"),
            n.get("nb_sponsored", 0),
            n.get("sources_signal", ""),
            n.get("verdict", ""),
        ]
        ws1.append(row)

    # Mise en forme conditionnelle sur Score global (colonne C)
    last_row = len(scored_niches) + 1
    score_col = "C"
    ws1.conditional_formatting.add(
        f"{score_col}2:{score_col}{last_row}",
        CellIsRule(operator="greaterThanOrEqual", formula=["7.5"],
                   fill=PatternFill("solid", fgColor=GREEN))
    )
    ws1.conditional_formatting.add(
        f"{score_col}2:{score_col}{last_row}",
        CellIsRule(operator="between", formula=["6", "7.49"],
                   fill=PatternFill("solid", fgColor=ORANGE))
    )
    ws1.conditional_formatting.add(
        f"{score_col}2:{score_col}{last_row}",
        CellIsRule(operator="lessThan", formula=["6"],
                   fill=PatternFill("solid", fgColor=RED))
    )

    # Dégradé de couleur sur Demande et Pénétration (D et E)
    for col in ["D", "E", "F"]:
        ws1.conditional_formatting.add(
            f"{col}2:{col}{last_row}",
            ColorScaleRule(
                start_type="num", start_value=1, start_color="FFC7CE",
                mid_type="num", mid_value=5, mid_color="FFEB9C",
                end_type="num", end_value=10, end_color="C6EFCE",
            )
        )

    ws1.freeze_panes = "A2"
    _auto_width(ws1)

    # ── ONGLET 2 : Métadonnées du run ─────────────────────────────────────────
    ws2 = wb.create_sheet("Métadonnées")

    ws2.append(["Paramètre", "Valeur"])
    _header_style(ws2, 1, 2)

    meta_rows = [
        ("Date du run", meta.get("date", "")),
        ("Sources OK", ", ".join(meta.get("sources_ok", []))),
        ("Sources KO (échecs)", ", ".join(meta.get("sources_ko", [])) or "Aucune"),
        ("Input TikTok manuel", ", ".join(meta.get("tiktok_input", [])) or "Non fourni"),
        ("Mots-clés candidats (avant filtrage)", meta.get("candidates_before_filter", 0)),
        ("Finalistes analysés en profondeur", meta.get("candidates_after_filter", 0)),
        ("Crédits Scrapingdog consommés ce run", meta.get("credits_this_run", 0)),
        ("Crédits Scrapingdog restants estimés", meta.get("credits_remaining_estimate", 0)),
        ("Top 1 verdict", scored_niches[0]["keyword"] if scored_niches else ""),
        ("Top 2 verdict", scored_niches[1]["keyword"] if len(scored_niches) > 1 else ""),
        ("Top 3 verdict", scored_niches[2]["keyword"] if len(scored_niches) > 2 else ""),
    ]

    for row in meta_rows:
        ws2.append(list(row))

    _auto_width(ws2)

    # ── ONGLET 3 : Sponsorisés détectés ───────────────────────────────────────
    ws3 = wb.create_sheet("Sponsorisés écartés")

    ws3.append(["Mot-clé", "Position", "Titre", "Auteur", "ASIN", "Raison identification"])
    _header_style(ws3, 1, 6)

    for n in scored_niches:
        kw = n.get("keyword", "")
        for sp in n.get("sponsored_list", []):
            ws3.append([
                kw,
                sp.get("position", ""),
                sp.get("title", ""),
                sp.get("author", ""),
                sp.get("asin", ""),
                sp.get("sponsored_reason", "badge/field"),
            ])

    _auto_width(ws3)

    wb.save(output_path)
    print(f"[report_builder] ✓ Rapport Excel généré : {output_path}")
