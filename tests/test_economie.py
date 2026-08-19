"""Quatre gaspillages confirmés par l'audit de dépense du 2026-08-19.

Ils ont une chose en commun : aucun ne se voyait. Pas d'erreur, pas d'avertissement, pas
de ligne dans le rapport — juste des appels facturés en plus. C'est la forme la plus
coûteuse d'un défaut, parce que rien ne pousse à le chercher.

Le premier est le mien, et il est instructif : mon commit « cache à 15 jours » n'avait pas
eu lieu. `fiction_serp_provider` gardait sa PROPRE constante à 7 jours, et mon test
d'harmonisation surveillait `cache.BOOK_TTL_S`, que plus personne ne lisait. Un test qui
regarde une constante morte passe au vert en garantissant le contraire de ce qu'il annonce.
D'où la règle appliquée ici : tester la valeur RÉELLEMENT PASSÉE au cache, jamais la
présence d'une constante.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from models import BsrInfo, EnrichedBook

JOUR = 24 * 3600


class _CacheEspion:
    """Capture ce qui est réellement écrit, TTL compris."""

    def __init__(self):
        self.ecritures = []

    def get_book(self, *a, **k):
        return None

    def set_book(self, asin, location, book, ttl_s):
        self.ecritures.append(("book", asin, ttl_s))

    def get_bsr(self, *a, **k):
        return None

    def set_bsr(self, asin, location, info, ttl_s):
        self.ecritures.append(("bsr", asin, ttl_s))

    def bsr_absent(self, asin, location):
        return any(k == "bsr-absent" and a == asin for k, a, _ in self.ecritures)

    def set_bsr_absent(self, asin, location, ttl_s):
        self.ecritures.append(("bsr-absent", asin, ttl_s))


# ── 1. Le TTL réellement appliqué aux fiches livre ─────────────────────────────

def test_le_cache_livre_est_ecrit_avec_QUINZE_jours():
    """Testé sur la valeur PASSÉE au cache, pas sur une constante. La version précédente
    vérifiait `cache.BOOK_TTL_S`, que `fiction_serp_provider` ne lisait pas : le test
    passait au vert pendant que les fiches expiraient en 7 jours."""
    from fiction_serp_provider import enrich_asins

    class _P:
        priority = 2
        location_code = 2250

        def product_raw_batch(self, asins, **kw):
            return {a: {"asin": a, "items": [{"type": "amazon_product_info",
                                              "data_asin": a, "title": "T"}]}
                    for a in asins}

    espion = _CacheEspion()
    enrich_asins(["A1", "A2"], provider=_P(), cache=espion)
    ttls = {t for kind, _, t in espion.ecritures if kind == "book"}
    assert ttls == {15 * JOUR}, f"TTL écrits : {ttls}"


def test_il_n_existe_qu_une_seule_definition_du_TTL_livre():
    """Deux constantes du même nom dans deux modules, c'est exactement ce qui a permis au
    défaut de vivre : l'une était documentée et testée, l'autre appliquée."""
    src = (Path(__file__).resolve().parent.parent
           / "01-scripts" / "fiction_serp_provider.py").read_text("utf-8")
    assert "BOOK_TTL_S = " not in src, "TTL redéfini localement au lieu d'être importé"
    assert "BOOK_TTL_S" in src and "from cache import" in src


# ── 2. Le second passage BSR ───────────────────────────────────────────────────

def test_un_livre_enrichi_SANS_BSR_n_est_jamais_re_paye():
    """Le code testait `a not in rangs` là où son propre docstring disait « absent du
    dict ». Un carnet classé « en Fournitures de bureau » est rendu par l'enrichissement
    sans BSR exploitable — et repartait en facturation pour un second appel qui, sur le
    MÊME payload, ne pouvait rien rendre de plus. Gaspillage garanti stérile, et récurrent
    puisque `resolve_bsrs` ne mettait en cache que les succès."""
    from lowcontent_master import run_lowcontent_scout
    from tests.test_lowcontent_master import (_expand_fige, _ideate_fige, _niche,
                                              _Provider)

    redemandes = []

    def bsr_espion(asin):
        redemandes.append(asin)
        return BsrInfo(rank_livres=1, asin=asin)

    def enrich_sans_bsr(asins, **kw):
        # rendus par l'enrichissement, mais sans BSR lisible
        return {a: EnrichedBook(asin=a, title="T", bsr=None) for a in asins}

    run_lowcontent_scout(
        seed="carnet", n_search=1, bsr_pause=0, use_cache=False,
        expand_fn=_expand_fige(["carnet suivi glycemie diabete"]),
        ideate=_ideate_fige([_niche("carnet suivi glycemie diabete")]),
        provider=_Provider(), enrich_fn=enrich_sans_bsr, fetch_bsr_fn=bsr_espion)
    assert redemandes == [], f"ASIN re-payés pour rien : {redemandes}"


def test_un_ASIN_absent_de_l_enrichissement_reste_re_sondable():
    """La correction ne doit pas emporter le cas légitime : un ASIN que l'enrichissement
    n'a pas rendu du tout (payload inexploitable, batch perdu) garde un classement
    récupérable par l'autre canal."""
    from lowcontent_master import run_lowcontent_scout
    from tests.test_lowcontent_master import (_expand_fige, _ideate_fige, _niche,
                                              _Provider)

    redemandes = []

    def bsr_espion(asin):
        redemandes.append(asin)
        return BsrInfo(rank_livres=4242, asin=asin)

    out = run_lowcontent_scout(
        seed="carnet", n_search=1, bsr_pause=0, use_cache=False,
        expand_fn=_expand_fige(["carnet suivi glycemie diabete"]),
        ideate=_ideate_fige([_niche("carnet suivi glycemie diabete")]),
        provider=_Provider(), enrich_fn=lambda asins, **kw: {},
        fetch_bsr_fn=bsr_espion)
    assert redemandes, "un ASIN jamais enrichi doit rester récupérable"
    assert out[0].bsr_best == 4242


# ── 3. Les échecs de BSR ne sont plus re-payés à chaque run ────────────────────

def test_un_ASIN_sans_BSR_est_memorise_pour_ne_pas_etre_re_paye():
    """`resolve_bsrs` ne mettait en cache que les SUCCES : les memes ASIN sans classement
    repartaient en facturation a chaque run, indefiniment. Memoriser l'echec coute une
    ligne et le supprime -- un echec MESURE est une information, pas un trou.

    Le test verifie l'ECONOMIE, pas l'ecriture : memoriser sans relire ne ferait rien
    gagner, et un test qui ne regarderait que l'ecriture passerait quand meme au vert."""
    from bsr_source import resolve_bsrs

    class _PCompteur:
        priority = 2

        def __init__(self):
            self.lots = []

        def product_info_batch(self, asins):
            self.lots.append(list(asins))
            return {a: None for a in asins}

    prov = _PCompteur()
    espion = _CacheEspion()
    resolve_bsrs(["A1"], source="dataforseo", provider=prov, cache=espion, bsr_pause=0)
    assert any(kind == "bsr-absent" for kind, _, _ in espion.ecritures), (
        "l'echec n'est pas memorise : il sera re-paye au prochain run")

    resolve_bsrs(["A1"], source="dataforseo", provider=prov, cache=espion, bsr_pause=0)
    assert len(prov.lots) == 1, f"ASIN re-paye malgre la memorisation : {prov.lots}"


def test_un_echec_memorise_ne_se_lit_pas_comme_un_BSR_a_zero():
    """L'économie ne doit pas coûter l'invariant : « pas de classement » reste `None`,
    jamais un rang. Un ASIN mémorisé comme sans BSR doit ressortir sans BSR."""
    from bsr_source import resolve_bsrs

    class _P:
        priority = 2

        def product_info_batch(self, asins):
            return {a: None for a in asins}

    out = resolve_bsrs(["A1"], source="dataforseo", provider=_P(),
                       cache=_CacheEspion(), bsr_pause=0)
    assert out["A1"] is None


# ── 4. Les textes libres bornés avant d'atteindre le LLM ───────────────────────

@pytest.mark.parametrize("corps", [
    {"type": "scout", "seed": "x" * 5000},
    {"type": "fiction", "sous_genre": "cosy_mystery", "libre": "y" * 5000},
])
def test_un_texte_libre_demesure_est_refuse_avant_tout_appel_LLM(corps, tmp_path,
                                                                 monkeypatch):
    """`seed` n'était borné QUE sur le chemin low-content. Un texte de plusieurs milliers
    de caractères part dans le prompt d'idéation et se facture au token : mesuré jusqu'à
    ~2 $ pour un run dont le devis annonçait 0,08 $. Le devis ne modélise pas la taille
    des textes de l'utilisateur, donc c'est la borne qui doit la tenir."""
    from tests.test_server_jobs import _client_with_isolated_dbs
    client, _ = _client_with_isolated_dbs(monkeypatch, tmp_path)
    r = client.post("/api/jobs", json=corps)
    assert r.status_code == 400
    assert "80" in r.json()["detail"]


def test_un_texte_de_taille_normale_passe(tmp_path, monkeypatch):
    from tests.test_server_jobs import _client_with_isolated_dbs
    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "run_scout",
                        lambda seed=None, progress=None, cost=None, **kw: [])
    assert client.post("/api/jobs",
                       json={"type": "scout", "seed": "ésotérisme"}).status_code == 202
