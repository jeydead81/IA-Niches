from models import ScoredNiche, NicheVerdict, AngleAttaque
from positioning_pdf import build_positioning_pdf, _safe


def test_safe_sanitizes_non_latin1():
    assert _safe("prix 19,90 € — l'œuvre") == "prix 19,90 EUR - l'oeuvre"


def _scored():
    a = AngleAttaque(angle="stoïcisme pour débutants", pourquoi="demande forte",
                     risque="niche connue", titre="Stoïcisme facile",
                     sous_titre="le guide du quotidien", direction_couverture="sobre, ocre",
                     prix_suggere="14,90-19,90 €", requete_principale="stoïcisme",
                     requetes_secondaires=["marc aurèle", "sénèque"])
    v = NicheVerdict(verdict="Go", confiance=8, facteur_decisif="une couverture pro",
                     angles=[a], saturation="moyenne", faux_concurrent="aucun",
                     differenciation="exécution")
    return ScoredNiche(niche="stoïcisme pratique", requete_amazon="stoïcisme",
                       categorie="philosophie", global_score=8.0, demande=9.0, penetration=6.0,
                       compatibilite=8.0, n_organic=16, n_concurrents_cibles=12, n_sponsored=4,
                       avg_rating=4.4, total_reviews=8000, bsr_best=2279, bsr_top5_avg=21445,
                       bsr_worst_top10=120000, criteres_bsr_ok=True, verdict=v)


def test_build_pdf_writes_file(tmp_path):
    out = build_positioning_pdf(_scored(), tmp_path / "p.pdf")
    assert out.exists() and out.stat().st_size > 800
    assert out.read_bytes()[:5] == b"%PDF-"


def test_build_pdf_without_verdict(tmp_path):
    sc = _scored()
    sc.verdict = None
    out = build_positioning_pdf(sc, tmp_path / "n.pdf")
    assert out.exists() and out.read_bytes()[:5] == b"%PDF-"
