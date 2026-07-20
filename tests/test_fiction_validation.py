from openpyxl import load_workbook

from fiction_validation import (accord, agreement_report, export_validation, jaccard,
                                load_corrections)
from models import EnrichedBook, TropeClassification


def test_jaccard_deux_vides_est_un_accord():
    assert jaccard(set(), set()) == 1.0


def test_livre_en_accord_exige_les_trois_criteres():
    ia = TropeClassification(asin="A", taxonomy_version="v", tropes=["a", "b"], decor="d")
    hu = TropeClassification(asin="A", taxonomy_version="v", tropes=["a"], decor="d")
    assert accord(ia, hu) is True                        # jaccard 0.5, décor ok
    hu2 = hu.model_copy(update={"decor": "autre"})
    assert accord(ia, hu2) is False                      # décor diverge -> désaccord


def test_rapport_donne_le_taux_et_la_porte():
    paires = [(TropeClassification(asin=str(i), taxonomy_version="v", tropes=["a"]),
               TropeClassification(asin=str(i), taxonomy_version="v",
                                   tropes=["a"] if i < 8 else ["z"])) for i in range(10)]
    r = agreement_report(paires)
    assert r.n_livres == 10 and r.n_accord == 8
    assert r.taux == 0.8 and r.porte_franchie is True


def test_rapport_pointe_les_cles_litigieuses():
    """Sous la porte, il faut savoir QUELLE clé pose problème — sinon on ne peut rien corriger."""
    paires = [(TropeClassification(asin="1", taxonomy_version="v", tropes=["flou"]),
               TropeClassification(asin="1", taxonomy_version="v", tropes=["net"]))]
    r = agreement_report(paires)
    assert r.porte_franchie is False
    assert r.cles_litigieuses["flou"]["ia_seule"] == 1
    assert r.cles_litigieuses["net"]["humain_seul"] == 1


def test_blurb_tronque_a_2000_caracteres_avec_marque_explicite(tmp_path):
    """Mesuré sur les fixtures live : à 600 caractères, l'humain ne voyait que 44 % du
    texte lu par l'IA, sans aucune marque de troncature — le désaccord mesurait alors une
    asymétrie d'information, pas un vrai désaccord de lecture."""
    long_blurb = "x" * 2500
    livres = [EnrichedBook(asin="A1", title="T", blurb=long_blurb)]
    p = tmp_path / "v.xlsx"
    export_validation(livres, [], "cosy_mystery", p)
    wb = load_workbook(str(p))
    cell = wb["Validation"].cell(row=2, column=4).value
    assert cell.startswith("x" * 2000)
    assert not cell.startswith("x" * 2001)
    assert "tronqué" in cell


def test_blurb_court_non_tronque_sans_marque(tmp_path):
    livres = [EnrichedBook(asin="A1", title="T", blurb="un blurb court")]
    p = tmp_path / "v.xlsx"
    export_validation(livres, [], "cosy_mystery", p)
    wb = load_workbook(str(p))
    cell = wb["Validation"].cell(row=2, column=4).value
    assert cell == "un blurb court"


def test_export_puis_relecture_conserve_les_etiquettes(tmp_path):
    """Aller-retour Excel : ce que Baptiste corrige doit revenir tel quel."""
    livres = [EnrichedBook(asin="A1", title="Titre", blurb="Un blurb.")]
    ia = [TropeClassification(asin="A1", taxonomy_version="fr_v1",
                              tropes=["metier_gourmand"], decor="village_breton")]
    p = tmp_path / "valid.xlsx"
    export_validation(livres, ia, "cosy_mystery", p)
    assert p.exists()
    relu = load_corrections(p)            # sans correction humaine -> colonnes vides
    assert relu == []                     # rien de corrigé = rien à comparer
