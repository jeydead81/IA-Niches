"""positioning_pdf.py — one-pager PDF de positionnement d'une niche (verdict + angles).
fpdf2, police core Helvetica + assainisseur latin-1 (portable, sans fichier de police)."""
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from models import ScoredNiche

_BLUE = (30, 64, 175)
_AMBER = (217, 119, 6)
_DARK = (30, 41, 59)
_MUTED = (100, 116, 139)
_LIGHT = (241, 245, 249)
_GREEN = (22, 163, 74)
_RED = (220, 38, 38)

_REPL = {"€": "EUR", "œ": "oe", "Œ": "OE", "’": "'", "‘": "'", "“": '"', "”": '"',
         "–": "-", "—": "-", "…": "...", "\xa0": " ", "•": "-"}


def _safe(s) -> str:
    s = "" if s is None else str(s)
    for k, v in _REPL.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _verdict_color(verdict: str):
    v = (verdict or "").lower()
    return _GREEN if v == "go" else _RED if v == "no-go" else _AMBER


def build_positioning_pdf(scored: ScoredNiche, out_path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    W = pdf.w - 20  # largeur utile (marges 10)

    # -- Bandeau titre --
    pdf.set_fill_color(*_BLUE)
    pdf.rect(0, 0, pdf.w, 26, "F")
    pdf.set_xy(10, 7)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 17)
    pdf.cell(W - 45, 8, _safe(scored.niche), ln=0)
    v = scored.verdict
    if v:
        pdf.set_fill_color(*_verdict_color(v.verdict))
        pdf.set_xy(pdf.w - 55, 6)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(45, 10, _safe(f"{v.verdict}  {v.confiance}/10"), border=0, align="C", fill=True)
    pdf.set_xy(10, 16)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(W, 6, _safe(f"Requete : « {scored.requete_amazon or scored.niche} »  ·  "
                         f"{scored.categorie}  ·  score global {scored.global_score}/10"), ln=1)

    pdf.ln(6)
    pdf.set_text_color(*_DARK)

    def h(txt):
        pdf.set_text_color(*_BLUE)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, _safe(txt), ln=1)
        pdf.set_text_color(*_DARK)

    def kv(label, value):
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(52, 5.5, _safe(label), ln=0)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(W - 52, 5.5, _safe(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # -- Chiffres cles --
    h("Chiffres cles (organique, sponsorises ecartes)")
    bsr41 = "OUI — place à prendre" if scored.criteres_bsr_ok else "non"
    kv("BSR Livres", f"meilleur {scored.bsr_best} · moyenne {scored.bsr_top5_avg} · "
                     f"plus haut {scored.bsr_worst_top10}  |  criteres §4.1 : {bsr41}")
    kv("Concurrence", f"{scored.n_organic} résultats · {scored.n_concurrents_cibles} concurrents "
                      f"ciblés · {scored.n_sponsored} sponsorisés écartés")
    kv("Demande", f"{scored.demand_autocomplete} complétions Amazon · note {scored.avg_rating} · "
                  f"{scored.total_reviews} avis cumulés")
    pdf.ln(2)

    if not v:
        pdf.set_text_color(*_MUTED)
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(0, 5, _safe("Verdict IA non disponible pour cette niche "
                                   "(hors top-3 analysé ou échec de génération)."),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.output(str(out_path))
        return out_path

    # -- Facteur decisif --
    h("Le facteur decisif")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5.5, _safe(v.facteur_decisif), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    # -- Angle recommande --
    if v.angles:
        a = v.angles[0]
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*_AMBER)
        pdf.cell(0, 7, _safe("Angle recommande"), ln=1)
        pdf.set_text_color(*_DARK)
        pdf.set_font("Helvetica", "B", 14)
        pdf.multi_cell(0, 7, _safe(a.titre), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(0, 6, _safe(a.sous_titre), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(*_DARK)
        kv("Pourquoi", a.pourquoi)
        kv("Risque", a.risque)
        kv("Couverture", a.direction_couverture)
        kv("Prix", a.prix_suggere)
        kv("Requetes", a.requete_principale + " · " + " · ".join(a.requetes_secondaires))
        pdf.ln(2)

    # -- Angles alternatifs --
    if len(v.angles) > 1:
        h("Angles alternatifs")
        for a in v.angles[1:]:
            pdf.set_font("Helvetica", "B", 10)
            pdf.multi_cell(0, 5.5, _safe(f"« {a.titre} » — {a.sous_titre}"),
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*_MUTED)
            pdf.multi_cell(0, 5, _safe(f"{a.angle} (risque : {a.risque})"),
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(*_DARK)
        pdf.ln(1)

    # -- Critique strategique --
    h("Critique strategique")
    kv("Saturation", v.saturation)
    kv("Faux concurrent", v.faux_concurrent)
    kv("Differenciation", v.differenciation)

    # -- Pied de page --
    pdf.set_y(-14)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*_MUTED)
    pdf.cell(0, 5, _safe("IA-Niches — analyse indicative, à valider par tes propres "
                         "screenshots Amazon."), align="C")

    pdf.output(str(out_path))
    return out_path
