"""Une seule source pour « sur quelle place de marché travaille-t-on ».

Aujourd'hui la réponse est écrite à neuf endroits : `location_code=2250` dans trois
orchestrateurs et dans `bsr_source`, `language_code="fr_FR"` dans deux, l'identifiant de
marketplace et l'hôte d'autocomplete dans `amazon_autocomplete`, le domaine des fiches
dans `amazon_product` et dans les deux constructeurs d'URL de `TopBook`. Changer de place
de marché voudrait dire les retrouver tous — et en oublier un ne casserait rien : ça
mélangerait deux marchés dans un même rapport, en silence.

**Le vrai risque n'est pas l'oubli, c'est la bascule qui a l'air de marcher.** Six choses
du dépôt sont irréductiblement françaises et ne suivraient pas un `MARKETPLACE=com` :
les browse nodes de la taxonomie fiction, les libellés de rayon Amazon, les barèmes
d'impression KDP relevés en euros, les mots saisonniers, le corpus du filtre IP et les
prompts. Un run `.com` avec tout ça rendrait des chiffres — faux, plausibles, et sans le
moindre message d'erreur. C'est exactement la faute que la règle 3 interdit, appliquée à
la configuration au lieu de la mesure.

Donc : une place de marché non prête **LÈVE**, avec la liste de ce qui manque.
"""
import pytest

from marketplace import (MARKETPLACES, Marketplace, MarketplaceIndisponible,
                         marketplace_actif)


def test_la_france_est_le_defaut(monkeypatch):
    monkeypatch.delenv("MARKETPLACE", raising=False)
    m = marketplace_actif()
    assert m.cle == "fr" and m.domaine == "amazon.fr"


def test_les_codes_dataforseo_sont_ceux_valides_en_live():
    """`language_code` vaut « fr_FR » et non « fr » : validé en live, une valeur courte
    rend des résultats vides sans lever."""
    fr = MARKETPLACES["fr"]
    assert fr.location_code == 2250 and fr.language_code == "fr_FR"


def test_l_identifiant_de_marketplace_autocomplete_est_porte_ici():
    assert MARKETPLACES["fr"].marketplace_id == "A13V1IB3VIYZZH"


def test_la_france_est_prete():
    assert MARKETPLACES["fr"].prete is True
    assert MARKETPLACES["fr"].manques == ()


# ── Ce qui n'est pas prêt le dit ───────────────────────────────────────────────

def test_le_com_existe_mais_n_est_PAS_pret():
    """Le décrire sans le déclarer prêt est le point du module : les codes DataForSEO
    sont justes, tout le reste du dépôt ne l'est pas."""
    com = MARKETPLACES["com"]
    assert com.domaine == "amazon.com" and com.devise == "USD"
    assert com.prete is False and com.manques


def test_basculer_sur_une_place_non_prete_LEVE(monkeypatch):
    """LE test. Sans cette levée, un `MARKETPLACE=com` rendrait un rapport complet et
    faux : browse nodes français sur une SERP américaine, barèmes d'impression en euros,
    filtre saisonnier qui cherche « noel » dans des requêtes anglaises. Aucun de ces
    défauts ne produit d'erreur — ils produisent des chiffres."""
    monkeypatch.setenv("MARKETPLACE", "com")
    with pytest.raises(MarketplaceIndisponible):
        marketplace_actif()


def test_la_levee_DIT_ce_qui_manque(monkeypatch):
    """« non supporté » enverrait chercher au hasard. La liste dit quoi faire."""
    monkeypatch.setenv("MARKETPLACE", "com")
    with pytest.raises(MarketplaceIndisponible) as e:
        marketplace_actif()
    msg = str(e.value).lower()
    assert "taxonomie" in msg and ("kdp" in msg or "impression" in msg)


def test_une_cle_inconnue_leve_avec_la_liste_des_cles(monkeypatch):
    monkeypatch.setenv("MARKETPLACE", "de")
    with pytest.raises(MarketplaceIndisponible) as e:
        marketplace_actif()
    assert "fr" in str(e.value)


def test_la_casse_et_les_espaces_ne_cassent_pas_la_selection(monkeypatch):
    monkeypatch.setenv("MARKETPLACE", "  FR ")
    assert marketplace_actif().cle == "fr"


def test_une_valeur_vide_retombe_sur_le_defaut(monkeypatch):
    """`.env` avec `MARKETPLACE=` est un oubli, pas une demande de bascule."""
    monkeypatch.setenv("MARKETPLACE", "")
    assert marketplace_actif().cle == "fr"


# ── Les URL se construisent depuis le domaine ──────────────────────────────────

def test_l_url_d_une_fiche_vient_du_marketplace():
    assert MARKETPLACES["fr"].url_fiche("B01ABCDEFG") == \
        "https://www.amazon.fr/dp/B01ABCDEFG"
    assert MARKETPLACES["com"].url_fiche("B01ABCDEFG") == \
        "https://www.amazon.com/dp/B01ABCDEFG"


def test_l_hote_d_autocomplete_vient_du_marketplace():
    assert MARKETPLACES["fr"].url_completion() == \
        "https://completion.amazon.fr/api/2017/suggestions"


# ── Les neuf sites de codage en dur lisent la source unique ────────────────────

def test_search_providers_lit_le_marketplace():
    import search_providers
    from marketplace import MARKETPLACES as M
    assert search_providers.DEFAULT_LOCATION == M["fr"].location_code
    assert search_providers.DEFAULT_LANGUAGE == M["fr"].language_code


def test_amazon_autocomplete_lit_le_marketplace():
    import amazon_autocomplete
    from marketplace import MARKETPLACES as M
    assert amazon_autocomplete._MID_FR == M["fr"].marketplace_id
    assert amazon_autocomplete._BASE == M["fr"].url_completion()


def test_les_deux_scorings_construisent_la_meme_url(monkeypatch):
    """`scoring.py` et `lowcontent_scoring.py` avaient chacun leur f-string. Deux copies
    d'une même règle divergent — c'est le motif de la suppression des endpoints doubles
    (§7)."""
    import lowcontent_scoring
    import scoring
    for mod in (scoring, lowcontent_scoring):
        src = (mod.__file__)
        texte = open(src, encoding="utf-8").read()
        assert "https://www.amazon.fr/dp/" not in texte, \
            f"{mod.__name__} construit encore l'URL en dur"


def test_amazon_product_ne_code_plus_le_domaine_en_dur():
    import amazon_product
    texte = open(amazon_product.__file__, encoding="utf-8").read()
    # Le docstring peut nommer amazon.fr ; le code, non.
    corps = texte.split('"""', 2)[-1]
    assert "https://www.amazon.fr/dp/" not in corps


def test_bsr_source_prend_son_defaut_du_marketplace():
    import inspect

    import bsr_source
    from marketplace import MARKETPLACES as M
    sig = inspect.signature(bsr_source.resolve_bsrs)
    assert sig.parameters["location"].default == M["fr"].location_code


def test_les_trois_orchestrateurs_ne_replient_plus_sur_un_2250_en_dur():
    """`getattr(provider, "location_code", 2250)` : le repli servait quand un provider
    injecté par un test n'a pas l'attribut. Le garder en dur laisse trois copies de plus
    du code France — et c'est le repli, donc celui qui s'applique justement quand rien
    d'autre ne le dit."""
    import pathlib
    racine = pathlib.Path(__file__).resolve().parent.parent / "01-scripts"
    for nom in ("scout_master.py", "fiction_serp_provider.py", "lowcontent_master.py"):
        texte = (racine / nom).read_text(encoding="utf-8")
        assert '"location_code", 2250' not in texte, f"{nom} replie encore sur 2250"
        assert '"language_code", "fr_FR"' not in texte, f"{nom} replie encore sur fr_FR"


def test_la_valeur_ACTIVE_est_celle_de_l_ENVIRONNEMENT(monkeypatch):
    """`ACTIF` est ce que TOUT le code lit — les trois orchestrateurs, `bsr_source`,
    `amazon_autocomplete`, `amazon_product` et les deux scorings. Le figer sur le défaut
    rendrait `marketplace_actif()` décoratif : la levée serait écrite, testée, et sans
    aucun appelant de production.

    C'est le piège §5.26 appliqué à la configuration : `MARKETPLACE=com` se lirait
    « bascule effectuée » alors que le produit continue sur `fr` sans rien dire."""
    import importlib

    import marketplace
    monkeypatch.setenv("MARKETPLACE", "fr")
    importlib.reload(marketplace)
    assert marketplace.ACTIF.cle == "fr"

    # On capture sur la classe de BASE, pas sur `MarketplaceIndisponible` importée en tête
    # de fichier : `reload` reconstruit le module, donc une NOUVELLE classe d'exception, et
    # `pytest.raises` compare par identité. Le message, lui, reste vérifiable.
    monkeypatch.setenv("MARKETPLACE", "com")
    with pytest.raises(RuntimeError) as e:
        importlib.reload(marketplace)
    assert "taxonomie" in str(e.value).lower()

    # Et on laisse le module dans un état sain pour les tests suivants.
    monkeypatch.delenv("MARKETPLACE", raising=False)
    importlib.reload(marketplace)
