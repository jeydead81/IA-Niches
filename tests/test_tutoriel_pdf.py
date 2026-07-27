"""test_tutoriel_pdf.py — le dossier de passation doit se générer sans planter et porter
les mises en garde qui évitent un contresens en réimplémentation (saturation inversée,
« non mesuré » != « mauvais »), ainsi que des coûts dont l'origine est déclarée."""
from pathlib import Path

from tutoriel_pdf import (COUTS, DEPLOIEMENT, ENDPOINTS, ENV_VARS, GLOSSAIRE, PIEGES,
                          VERDICTS, build_tutoriel_pdf)


def test_le_dossier_se_genere(tmp_path):
    p = build_tutoriel_pdf(tmp_path / "passation.pdf")
    assert p.exists() and p.stat().st_size > 5000
    assert p.read_bytes()[:4] == b"%PDF"


def test_la_saturation_inversee_est_signalee():
    """LE contresens possible : sur tous les autres scores, haut = bon. Un développeur qui
    l'ignore colore la jauge en vert et fait recommander les pires niches."""
    txt = (" ".join(e for _, e in GLOSSAIRE) + " ".join(e for _, e in PIEGES)).lower()
    assert "seul score" in txt and "mauvais" in txt


def test_non_mesure_est_distingue_de_mort():
    conseil = next(c for nom, _, c in VERDICTS if nom.startswith("Non mesur"))
    assert "absence" in conseil.lower()


def test_les_six_verdicts_sont_couverts():
    assert len(VERDICTS) == 6


def test_chaque_cout_declare_son_origine():
    """Un chiffre extrapolé présenté comme mesuré fausserait la tarification bâtie
    dessus. L'origine est donc une colonne, pas une note de bas de page."""
    origines = {c[3] for c in COUTS}
    assert {"mesuré", "extrapolé"} <= origines
    assert all(len(c) == 4 and c[1] for c in COUTS)


def test_le_piege_du_bsr_scrape_en_production_est_documente():
    """C'est la surprise la plus coûteuse au déploiement : le BSR gratuit vient d'une IP
    résidentielle et cesse de fonctionner sur un serveur, ce qui triple le coût d'un run."""
    txt = " ".join(e for _, e in DEPLOIEMENT).lower()
    assert "datacenter" in txt and "bsr_source=dataforseo" in txt


def test_les_endpoints_et_variables_sont_listes():
    assert any("/api/jobs" in e for e, _ in ENDPOINTS)
    assert any("BSR_SOURCE" in v for v, _ in ENV_VARS)


def test_le_dossier_est_ecrit_en_francais_accentue():
    """Le latin-1 gère é/è/à/ç/ô : seuls oe, EUR, tirets longs passent par _REPL."""
    from tutoriel_pdf import _safe
    txt = " ".join(e for _, e in GLOSSAIRE)
    assert any(a in txt for a in "éèàêç")
    assert "é" in _safe("développement")


def test_aucun_caractere_ne_casse_le_pdf(tmp_path):
    build_tutoriel_pdf(tmp_path / "g2.pdf")     # ne doit pas lever
