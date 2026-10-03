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


def test_le_guide_utilisateur_se_genere(tmp_path):
    from tutoriel_pdf import build_guide_utilisateur_pdf
    p = build_guide_utilisateur_pdf(tmp_path / "guide.pdf")
    assert p.exists() and p.stat().st_size > 5000 and p.read_bytes()[:4] == b"%PDF"


def test_le_guide_utilisateur_previent_du_score_inverse():
    """Le lecteur du guide n'est pas développeur : il ne déduira pas tout seul qu'un
    chiffre élevé est mauvais alors que tous les autres disent l'inverse."""
    from tutoriel_pdf import U_GLOSSAIRE, U_PIEGES
    txt = (" ".join(e for _, e in U_GLOSSAIRE) + " ".join(e for _, e in U_PIEGES)).lower()
    assert "seul chiffre" in txt and "mauvais" in txt


def test_le_guide_utilisateur_distingue_non_mesure_de_mauvais():
    from tutoriel_pdf import U_VERDICTS
    c = next(c for nom, _, c in U_VERDICTS if nom.startswith("Non mesur"))
    assert "absence" in c.lower() and "excellente" in c.lower()


def test_les_deux_documents_ont_des_textes_DISTINCTS():
    """Même fond métier, deux publics : recopier les textes du dossier développeur dans le
    guide donnerait à l'auteur des consignes d'implémentation (label_rayon(), n_echecs...)
    qui ne lui servent à rien."""
    from tutoriel_pdf import GLOSSAIRE, U_GLOSSAIRE
    dev = dict(GLOSSAIRE)["Rayon"]
    usr = dict(U_GLOSSAIRE)["Rayon"]
    assert dev != usr
    assert "label_rayon" in dev and "label_rayon" not in usr


def test_le_guide_dit_qu_on_peut_fermer_la_page():
    from tutoriel_pdf import U_ETAPES_FIC
    assert any("fermer la page" in e.lower() for e in U_ETAPES_FIC)


def test_le_dossier_de_passation_couvre_TOUS_les_endpoints_reels():
    """Ce PDF est remis au developpeur charge de l'implantation : s'il decrit 11 endpoints
    sur 13, celui qui reprend le projet ignorera l'historique et les mots-cles KDP. Le test
    lit web/server.py comme source de verite au lieu de figer une liste, sinon il se
    perimerait exactement comme le document qu'il protege."""
    import re
    from pathlib import Path
    from tutoriel_pdf import ENDPOINTS

    # Le nom du parametre de chemin est cosmetique ({id} se lit mieux que {job_id} dans
    # un document) : on compare la FORME de la route, pas le nom de sa variable.
    norm = lambda c: re.sub(r"\{[^}]+\}", "{}", c)
    src = (Path(__file__).resolve().parent.parent / "web" / "server.py").read_text("utf-8")
    reels = {(m, norm(c)) for m, c in re.findall(r'@app\.(get|post|delete)\("([^"]+)"', src)}
    documentes = {(m.split()[0].lower(), norm(m.split()[1])) for m, _ in ENDPOINTS}
    assert reels == documentes, f"manquants : {reels - documentes} ; en trop : {documentes - reels}"


def test_le_dossier_de_passation_ne_cite_que_des_variables_encore_lues():
    """ENV_VARS listait encore les REDDIT_*, disparues avec reddit_fr.py. Une variable
    fantome dans la doc d'implantation fait perdre du temps a la configurer."""
    import re
    from pathlib import Path
    from tutoriel_pdf import ENV_VARS

    racine = Path(__file__).resolve().parent.parent
    lues = set()
    for f in list((racine / "01-scripts").glob("*.py")) + [racine / "web" / "server.py"]:
        lues |= set(re.findall(r'getenv\("([A-Z_]+)"', f.read_text("utf-8")))
    for nom, _ in ENV_VARS:
        # « DATAFORSEO_LOGIN / _PASSWORD » est un raccourci de lecture : le second terme
        # se recompose sur le prefixe du premier.
        termes = [t.strip() for t in nom.split("/")]
        prefixe = termes[0].split("_")[0]
        for t in termes:
            v = (prefixe + t) if t.startswith("_") else t
            assert v in lues, f"{v} (« {nom} ») n'est lue nulle part dans le code"
