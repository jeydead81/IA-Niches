"""test_tutoriel_pdf.py — le guide doit se générer sans planter et contenir les mises en
garde qui évitent un contresens (saturation inversée, « non mesuré » ≠ « mauvais »)."""
from pathlib import Path

from tutoriel_pdf import GLOSSAIRE, PIEGES, VERDICTS, build_tutoriel_pdf


def test_le_guide_se_genere(tmp_path):
    p = build_tutoriel_pdf(tmp_path / "guide.pdf")
    assert p.exists() and p.stat().st_size > 5000
    assert p.read_bytes()[:4] == b"%PDF"


def test_la_saturation_inversee_est_signalee():
    """C'est LE contresens possible : sur tous les autres scores, haut = bon. Un guide qui
    ne le dit pas laisse l'utilisateur choisir exactement la pire niche."""
    txt = " ".join(e for _, e in GLOSSAIRE).lower()
    assert "seul chiffre" in txt and "mauvais" in txt


def test_non_mesure_est_distingue_de_mauvais():
    """« Non mesuré » = aucune donnée exploitable, pas un verdict négatif. Les confondre
    fait renoncer à une niche qui n'a jamais été évaluée."""
    conseil = next(c for nom, _, c in VERDICTS if nom.startswith("Non mesur"))
    assert "absence" in conseil.lower()


def test_les_six_verdicts_sont_couverts():
    assert len(VERDICTS) == 6


def test_le_guide_annonce_qu_on_peut_fermer_la_page():
    """15 min d'attente sans cette phrase passent pour un plantage."""
    from tutoriel_pdf import ETAPES_FIC
    assert any("fermer la page" in e.lower() for e in ETAPES_FIC)


def test_aucun_caractere_ne_casse_le_pdf(tmp_path):
    """fpdf2 en police core est en latin-1 : un caractère non convertible lève à la
    génération. Les textes du guide contiennent des accents et des guillemets français."""
    build_tutoriel_pdf(tmp_path / "g2.pdf")     # ne doit pas lever


def test_le_guide_est_ecrit_en_francais_accentue():
    """Un guide destiné à des auteurs francophones écrit « developpement » et « idees »
    fait négligé. Le latin-1 gère é/è/à/ç/ô : seuls œ, €, – et … passent par _REPL."""
    txt = " ".join(e for _, e in GLOSSAIRE) + " ".join(c for _, _, c in VERDICTS)
    assert any(a in txt for a in "éèàêç"), "contenu sans accents"
    from tutoriel_pdf import _safe
    assert "é" in _safe("développement")      # l'assainisseur ne doit PAS manger les accents
