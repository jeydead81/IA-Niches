from search_providers import parse_bsr_rank


def test_rang_papier():
    assert parse_bsr_rank("1 597 en Livres ( Voir les 100 premiers en Livres )  6 en Enquêtes") \
        == (1597, "Livres", False)


def test_rang_kindle_payant():
    assert parse_bsr_rank("20 en Boutique Kindle ( Voir les 100 premiers en Boutique Kindle )  4 en Romance") \
        == (20, "Boutique Kindle", False)
    assert parse_bsr_rank("2 968 en Boutique Kindle ( Voir les 100 premiers en Boutique Kindle )") \
        == (2968, "Boutique Kindle", False)


def test_titres_gratuits_signales():
    rang, rayon, gratuit = parse_bsr_rank(
        "n°478 des titres gratuits dans la Boutique Kindle ( Voir les 100 premiers en Boutique Kindle )"
        "  5 en Livres électroniques de fiction criminelle")
    assert (rang, rayon) == (478, "Boutique Kindle") and gratuit is True


def test_sous_categorie_jamais_prise_pour_le_rayon():
    rang, rayon, _ = parse_bsr_rank(
        "n°73 des titres gratuits dans la Boutique Kindle ( … )  1 en Livres électroniques de romance")
    assert rang == 73 and rayon == "Boutique Kindle"


def test_vide():
    assert parse_bsr_rank("") == (None, None, False)
    assert parse_bsr_rank(None) == (None, None, False)
