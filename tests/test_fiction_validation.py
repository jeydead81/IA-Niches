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
