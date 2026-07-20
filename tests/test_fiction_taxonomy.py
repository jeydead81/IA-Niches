import pytest
from fiction_taxonomy import load_taxonomy, sous_genre, node_for, search_param_for, valid_keys


def test_load_and_shape():
    t = load_taxonomy()
    assert t["version"] == "fr_v1" and t["rayon_defaut"] == "kindle"
    assert len(t["sous_genres"]) == 6
    for k, sg in t["sous_genres"].items():
        assert sg["label"] and sg["query_fr"]
        assert sg["tropes"] and sg["decors"]
        assert all(x == x.lower() and " " not in x for x in sg["tropes"] + sg["decors"])


def test_node_for_rayon_et_repli_requete():
    assert node_for("cosy_mystery", "kindle") == "205566725031"
    assert node_for("cosy_mystery", "papier") == "9691472031"
    assert node_for("feel_good", "kindle") is None
    assert node_for("romantasy", "papier") is None


def test_search_param_par_rayon():
    assert search_param_for("kindle") == "i=digital-text"
    assert search_param_for("papier") == "i=stripbooks"
    with pytest.raises(ValueError):
        search_param_for("audio")


def test_valid_keys_contraint_le_classifieur():
    tropes, decors = valid_keys("cosy_mystery")
    assert "enquetrice_amatrice" in tropes and "village_breton" in decors
    assert "mafia" not in tropes


def test_sous_genre_inconnu_leve():
    with pytest.raises(KeyError):
        sous_genre("space_opera")
