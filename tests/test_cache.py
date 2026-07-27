from cache import Cache
from models import EnrichedBook


def test_set_get_roundtrip(tmp_path):
    c = Cache(tmp_path / "c.db")
    c.set("k", {"n": 1}, ttl_s=100)
    assert c.get("k") == {"n": 1}


def test_miss_returns_none(tmp_path):
    assert Cache(tmp_path / "c.db").get("absent") is None


def test_ttl_expiry(tmp_path):
    clock = {"t": 1000.0}
    c = Cache(tmp_path / "c.db", now=lambda: clock["t"])
    c.set("k", {"v": 1}, ttl_s=10)
    clock["t"] = 1005.0
    assert c.get("k") == {"v": 1}          # encore valide
    clock["t"] = 1020.0
    assert c.get("k") is None              # expiré


def test_bsr_helpers(tmp_path):
    from models import BsrInfo
    c = Cache(tmp_path / "c.db")
    c.set_bsr("A1", 2250, BsrInfo(rank_livres=194, asin="A1"), ttl_s=100)
    got = c.get_bsr("A1", 2250)
    assert got.rank_livres == 194 and got.asin == "A1"
    assert c.get_bsr("A2", 2250) is None


def test_search_helpers(tmp_path):
    from models import SearchResult, SearchItem
    c = Cache(tmp_path / "c.db")
    sr = SearchResult(keyword="tarot", organic=[SearchItem(title="x", asin="A1")])
    c.set_search("Tarot ", 2250, "fr_FR", sr, ttl_s=100)   # clé normalisée (lower+strip)
    got = c.get_search("tarot", 2250, "fr_FR")
    assert got.keyword == "tarot" and got.organic[0].asin == "A1"


def test_book_helpers(tmp_path):
    from models import EnrichedBook
    c = Cache(tmp_path / "c.db")
    b = EnrichedBook(asin="A1", title="T", bsr=20, bsr_rayon="Boutique Kindle", serp_position=3)
    c.set_book("A1", 2250, b, ttl_s=100)
    got = c.get_book("A1", 2250)
    assert got.asin == "A1" and got.bsr == 20 and got.bsr_rayon == "Boutique Kindle"
    assert c.get_book("A2", 2250) is None


def test_cle_livre_change_quand_le_modele_gagne_un_champ(tmp_path, monkeypatch):
    """Le blurb a été ajouté à EnrichedBook APRÈS que des livres soient entrés en cache :
    sans empreinte de schéma dans la clé, le cache aurait servi 7 jours durant des livres
    amputés du nouveau champ, et le classifieur aurait lu « pas de blurb » comme un fait."""
    from cache import _schema_tag

    avant = _schema_tag()
    _schema_tag.cache_clear()
    monkeypatch.setitem(EnrichedBook.model_fields, "champ_neuf", None)
    apres = _schema_tag()
    _schema_tag.cache_clear()
    assert avant != apres


def test_entree_ecrite_sous_un_ancien_schema_est_ignoree(tmp_path):
    c = Cache(tmp_path / "c.db")
    # simule une entrée écrite par une version antérieure du modèle
    c.set("book:vieux:2250:A1", {"asin": "A1", "title": "AMPUTÉ"}, ttl_s=100)
    assert c.get_book("A1", 2250) is None


def test_cle_bsr_change_quand_le_modele_gagne_un_champ(monkeypatch):
    """Même piège que pour EnrichedBook (cf. test_cle_livre_...) mais sur BsrInfo : sans
    empreinte de schéma dans la clé `bsr:`, un champ ajouté à BsrInfo servirait des BSR
    amputés 7 jours durant sans que rien ne le signale."""
    from cache import _bsr_schema_tag
    from models import BsrInfo

    avant = _bsr_schema_tag()
    _bsr_schema_tag.cache_clear()
    monkeypatch.setitem(BsrInfo.model_fields, "champ_neuf", None)
    apres = _bsr_schema_tag()
    _bsr_schema_tag.cache_clear()
    assert avant != apres


def test_cle_search_change_quand_le_modele_gagne_un_champ(monkeypatch):
    """Même piège que pour EnrichedBook mais sur SearchResult, sous la clé `search:`."""
    from cache import _search_schema_tag
    from models import SearchResult

    avant = _search_schema_tag()
    _search_schema_tag.cache_clear()
    monkeypatch.setitem(SearchResult.model_fields, "champ_neuf", None)
    apres = _search_schema_tag()
    _search_schema_tag.cache_clear()
    assert avant != apres


def test_bsr_amputee_sans_empreinte_serait_relue_comme_valide(tmp_path):
    """Preuve directe du piège : une valeur écrite sous l'ancienne forme de clé SANS
    empreinte (`bsr:{location}:{asin}`, le format actuel avant correctif) doit devenir
    injoignable une fois l'empreinte ajoutée — sinon un BsrInfo amputé par un futur champ
    resterait lisible 7 jours comme si de rien n'était."""
    c = Cache(tmp_path / "c.db")
    c.set("bsr:2250:A1", {"rank_livres": 194, "asin": "A1"}, ttl_s=100)
    assert c.get_bsr("A1", 2250) is None


def test_search_amputee_sans_empreinte_serait_relue_comme_valide(tmp_path):
    c = Cache(tmp_path / "c.db")
    c.set("search:2250:fr_FR:tarot", {"keyword": "tarot"}, ttl_s=100)
    assert c.get_search("tarot", 2250, "fr_FR") is None


def test_cache_de_classification_depend_du_modele_de_la_taxo_ET_du_prompt(tmp_path):
    """Une classification est déterministe pour un (livre, taxonomie, modèle, prompt) donné :
    la re-payer à chaque run est du gaspillage pur. Mais la clé doit dépendre du PROMPT
    aussi — on l'a durci aujourd'hui même (décors inventés), et un cache qui l'ignorerait
    resservirait des étiquettes produites par l'ancienne consigne. Même leçon que
    `_schema_tag` : un compteur de version manuel s'oublie, une empreinte non."""
    from cache import _prompt_tag
    from models import TropeClassification

    c = Cache(tmp_path / "c.db")
    cl = TropeClassification(asin="A1", taxonomy_version="fr_v1", tropes=["mafia"])
    c.set_classification("A1", "fr_v1", "claude-sonnet-5", cl, ttl_s=100)

    assert c.get_classification("A1", "fr_v1", "claude-sonnet-5").tropes == ["mafia"]
    assert c.get_classification("A1", "fr_v2", "claude-sonnet-5") is None      # autre taxo
    assert c.get_classification("A1", "fr_v1", "claude-haiku-4-5") is None     # autre modèle
    assert c.get_classification("A2", "fr_v1", "claude-sonnet-5") is None      # autre livre
    assert len(_prompt_tag()) == 8                                            # empreinte courte
