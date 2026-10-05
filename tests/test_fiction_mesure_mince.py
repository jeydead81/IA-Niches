"""« Mesure trop mince » : pas de verdict de marché sur un ou deux livres.

Mesuré le 2026-10-05 sur les deux runs fiction enregistrés (8 niches, rayon papier) : 7 livres
SCORABLES sur 47 payés, et aucune niche n'en a plus de 4 — 4, 1, 1, 0, 0, 1, 0, 0. Pourtant
l'écran rendait « Mur installé » sur UN livre (les sept autres de la carte étaient des livres de
développement personnel classés hors roman) et « Mort » sur un livre, deux fois. Rien n'en disait
la fragilité : exactement ce que la règle 3 interdit — une conclusion de marché tirée d'une mesure
insuffisante.

Sous `SEUILS["livres_mesures_min"]` livres mesurables, la niche sort `mesure_mince` : ni « mort »
ni « mur installé » ni « pépite ». C'est un état voisin de `non_mesurable` (zéro livre), pour la
même raison : l'absence de mesure ne se lit pas comme un verdict.

LE SEUIL (3) EST UNE HYPOTHÈSE, pas une mesure : posé de notre propre chef, il n'a été confronté à
aucun jeu étiqueté. Il vit dans `SEUILS`, avec les autres, pour être discutable (§4.2).

FIXTURES : les rayons sont construits à la main pour contrôler le nombre de livres mesurables ; le
chiffre « 7 sur 47 » vient des deux runs réels de `jobs.db`.
"""
import pytest

import fiction_scoring
from cost_tracker import CostTracker
from fiction_master import run_fiction_scout
from fiction_scoring import SEUILS, build_report
from fiction_taxonomy import label_rayon
from fiction_verdict import (RayonNonMesure, generate_fiction_verdict, raison_non_mesure,
                             rayon_non_mesure)
from models import (AutocompleteSignal, EnrichedBook, FictionNiche, FictionShelf,
                    TropeClassification)
from tests.test_fiction_verdict import _Client, _livre, _payload, _rapport

SIGNAL = AutocompleteSignal(niche_query="q", score=0.5, mesure=True)


def _niche(rayon="kindle", query="roman feel good village"):
    return FictionNiche(sous_genre="feel_good", tropes=["deuil_lumineux"], decor="village",
                        rayon=rayon, query=query)


def _etagere(n_mesurables, n_total=None, rayon="kindle", bsr=3000,
             query="roman feel good village"):
    """`n_mesurables` livres au rang du rayon visé, complétés par des livres SANS rang."""
    lib = label_rayon(rayon)
    livres = [EnrichedBook(asin=f"A{i}", title=f"T{i}", bsr=bsr + i, bsr_rayon=lib,
                           price=5.0, serp_position=i + 1) for i in range(n_mesurables)]
    livres += [EnrichedBook(asin=f"X{i}", title=f"X{i}", serp_position=100 + i)
               for i in range((n_total or n_mesurables) - n_mesurables)]
    return FictionShelf(niche=_niche(rayon, query), search_param="i=digital-text", books=livres,
                        asins_demandes=len(livres), n_echecs=0)


def _classes(shelf):
    return {b.asin: TropeClassification(asin=b.asin, taxonomy_version="fr_v1",
                                        tropes=["deuil_lumineux"], decor="village")
            for b in shelf.books}


def _rapport_de(n_mesurables, n_total=None, **kw):
    s = _etagere(n_mesurables, n_total, **kw)
    return build_report(s.niche, s, _classes(s), SIGNAL)


# ── Le scoring ──────────────────────────────────────────────────────────────────

def test_le_seuil_est_dans_SEUILS_et_vaut_trois():
    assert SEUILS["livres_mesures_min"] == 3


def test_zero_livre_mesure_reste_non_mesurable():
    assert _rapport_de(0, 4).demand_matrix == "non_mesurable"


@pytest.mark.parametrize("n", [1, 2])
def test_un_ou_deux_livres_donnent_une_mesure_mince(n):
    r = _rapport_de(n, 12)
    assert r.demand_matrix == "mesure_mince"


@pytest.mark.parametrize("n", [3, 4, 8])
def test_a_partir_du_seuil_la_niche_se_lit_normalement(n):
    r = _rapport_de(n, 12)
    assert r.demand_matrix in {"pepite", "porteur_encombre", "mur_installe", "desert", "mort"}


def test_la_valeur_PASSEE_est_celle_de_SEUILS(monkeypatch):
    """§5.32 : tester la valeur réellement lue, pas la présence d'une constante."""
    monkeypatch.setitem(SEUILS, "livres_mesures_min", 2)
    assert _rapport_de(2, 12).demand_matrix != "mesure_mince"
    monkeypatch.setitem(SEUILS, "livres_mesures_min", 5)
    assert _rapport_de(4, 12).demand_matrix == "mesure_mince"


def test_le_rapport_porte_le_nombre_de_livres_mesures():
    assert _rapport_de(4, 12).n_livres_mesures == 4
    assert _rapport_de(0, 3).n_livres_mesures == 0


def test_un_resultat_anterieur_au_compteur_ne_pretend_pas_savoir():
    """Défaut `None` = inconnu, pas zéro : l'écran n'affiche alors aucune ligne de mesure."""
    from models import FictionNicheReport
    assert FictionNicheReport(niche=_niche()).n_livres_mesures is None


def test_le_texte_du_moteur_dit_que_la_mesure_est_mince_et_n_est_pas_un_verdict():
    t = _rapport_de(1, 12).verdict
    assert "TROP MINCE" in t and "1 livre(s) mesuré(s) sur 12" in t
    assert "pas une niche morte" in t


def test_une_mesure_suffisante_ne_porte_pas_cette_mention():
    assert "TROP MINCE" not in _rapport_de(4, 12).verdict


# ── Le tri : une mesure mince ne passe pas devant une mesure solide ──────────────

def _ideate(sg, n=8, **kw):
    return [FictionNiche(sous_genre=sg, tropes=["t"], decor="d", rayon="kindle",
                         query=f"roman feel good requete {i}") for i in range(2)]


def _serp(niche, **kw):
    # niche 0 : UN seul livre, au meilleur rang possible ; niche 1 : quatre livres moyens
    return ("i=digital-text", ["SOLO"] if niche.query.endswith("0")
            else ["M1", "M2", "M3", "M4"])


def _enrich(asins, **kw):
    rangs = {"SOLO": 100, "M1": 40000, "M2": 41000, "M3": 42000, "M4": 43000}
    return {a: EnrichedBook(asin=a, title=a, blurb="b", bsr=rangs[a],
                            bsr_rayon="Boutique Kindle") for a in asins}


def _classify(books, sg, **kw):
    return [TropeClassification(asin=b.asin, taxonomy_version="fr_v1", est_roman=True)
            for b in books]


def _probe(niche, **kw):
    return AutocompleteSignal(niche_query=niche.query, mesure=True, score=0.0)


def test_une_mesure_mince_passe_apres_une_mesure_solide_meme_si_sa_profondeur_est_plus_haute():
    rapports = run_fiction_scout("feel_good", n_niches=2, ideate=_ideate, serp_fn=_serp,
                                 enrich_fn=_enrich, classify=_classify, probe=_probe,
                                 progress=lambda m: None, use_cache=False)
    assert [r.demand_matrix == "mesure_mince" for r in rapports] == [False, True]
    assert rapports[1].depth_score > rapports[0].depth_score, \
        "fixture : la niche mince doit avoir la PLUS HAUTE profondeur, sinon le tri ne prouve rien"


# ── L'historique : un point qu'on sait faux n'y entre pas ────────────────────────

def test_l_historique_ne_garde_ni_le_non_mesurable_ni_la_mesure_mince(monkeypatch, tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))
    pytest.importorskip("httpx")
    import server
    from history import NicheHistory
    from tests.conftest import isoler_bases
    isoler_bases(monkeypatch, server, tmp_path)
    mince = _rapport_de(1, 12, query="q mince")
    vide = _rapport_de(0, 3, query="q vide")
    bon = _rapport_de(4, 12, query="q bon")
    server._consigner_fiction([mince, vide, bon], "u1")
    h = NicheHistory(server._HISTORY_DB)
    assert len(h.historique("u1", bon.niche.cle)) == 1
    assert h.historique("u1", mince.niche.cle) == [] and h.historique("u1", vide.niche.cle) == [], \
        "des zéros ou un seul livre, enregistrés, feraient lire un faux delta au passage suivant"


# ── Le verdict éditorial refuse ce qu'il ne peut pas conclure ────────────────────

def test_une_mesure_mince_est_refusee_comme_un_rayon_non_mesure():
    assert rayon_non_mesure(_rapport(demand_matrix="mesure_mince")) is True


def test_un_resultat_ancien_est_juge_sur_ses_livres_pas_sur_son_etiquette():
    """Un « mort » enregistré avant ce seuil, bâti sur 2 livres mesurables : l'étiquette dit
    « mort », les livres disent « trop mince »."""
    deux = [_livre("B000000001", "A", 1200), _livre("B000000002", "B", 4500),
            _livre("B000000003", "C", None)]
    assert rayon_non_mesure(_rapport(books=deux, demand_matrix="mort")) is True


def test_trois_livres_mesures_suffisent_au_verdict():
    trois = [_livre("B000000001", "A", 1200), _livre("B000000002", "B", 4500),
             _livre("B000000003", "C", 9800)]
    assert rayon_non_mesure(_rapport(books=trois)) is False
    assert raison_non_mesure(_rapport(books=trois)) is None


def test_la_raison_distingue_zero_livre_et_trop_peu_de_livres():
    zero = raison_non_mesure(_rapport(demand_matrix="non_mesurable"))
    deux = raison_non_mesure(_rapport(books=[_livre("B000000001", "A", 1200),
                                             _livre("B000000002", "B", 4500),
                                             _livre("B000000003", "C", None)],
                                      demand_matrix="mesure_mince"))
    assert "n'a pas été mesuré" in zero
    assert "trop peu" in deux.lower() and "2 livre(s) mesuré(s) sur 3" in deux


def test_aucune_des_deux_raisons_ne_conclut_a_un_marche_mort():
    """Règle 3 : ni « No-Go », ni « mort » affirmé. La mesure mince DIT que ce n'est pas un rayon
    mort (la négation est la phrase attendue) ; le non-mesuré n'en parle pas du tout."""
    zero = raison_non_mesure(_rapport(demand_matrix="non_mesurable"))
    deux = raison_non_mesure(_rapport(demand_matrix="mesure_mince"))
    for t in (zero, deux):
        assert "no-go" not in t.lower()
    assert "mort" not in zero.lower()
    assert "n'est pas un rayon mort" in deux


def test_le_conseil_kindle_n_est_donne_qu_a_un_run_papier():
    """Donné à un run déjà en Kindle (le défaut du formulaire), « essayez Kindle » serait
    circulaire (revue adverse du 2026-10-05)."""
    def _avec(rayon, libelle):
        livres = [_livre(f"B00000000{i}", f"T{i}", 1000 + i).model_copy(
            update={"bsr_rayon": libelle}) for i in range(2)]
        r = _rapport(demand_matrix="mesure_mince", books=livres)
        r.niche = FictionNiche(sous_genre="feel_good", rayon=rayon, query="q")
        return r

    papier, kindle = _avec("papier", "Livres"), _avec("kindle", "Boutique Kindle")
    assert "Trop peu" in raison_non_mesure(papier) and "Trop peu" in raison_non_mesure(kindle)
    assert "Kindle" in raison_non_mesure(papier)
    assert "Kindle" not in raison_non_mesure(kindle)
    assert "moins de mots" in raison_non_mesure(kindle)


def test_une_mesure_mince_ne_declenche_aucun_appel():
    client = _Client(_payload())
    with pytest.raises(RayonNonMesure, match="(?i)trop peu"):
        generate_fiction_verdict(_rapport(demand_matrix="mesure_mince",
                                          books=[_livre("B000000001", "A", 1200)]),
                                 client=client)
    assert client.appels == []
