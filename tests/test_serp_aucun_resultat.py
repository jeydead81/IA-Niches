"""Une recherche Amazon qui ne rend RIEN n'est pas une file saturée.

Run fiction du 2026-10-05 (feel_good, rayon papier) : 2 niches sur 5 « écartées » avec
« résultat DataForSEO non prêt après 320 s — file DataForSEO probablement saturée ». Relues le
jour même, gratuitement (`task_get`), les deux tâches avaient été TERMINÉES en quelques centièmes
de seconde, statut de tâche **40102 « No Search Results »**, `cost` 0 : Amazon répondait « Aucun
résultat pour votre recherche dans Livres. Essayez […] d'utiliser des termes plus généraux ».

La boucle d'attente (`DataForSEOProvider.search`) n'accepte que « statut 20000 ET résultat » : un
statut TERMINAL autre la faisait poller 40 fois, 320 s, deux fois — 640 s d'un run de 915 s —
avant de lever un TimeoutError au message FAUX (« file saturée »), puis d'écarter la niche sans
carte. Ce que ce fichier tient :

1. un statut 40102 met fin à l'attente AU PREMIER relevé, avec une exception qui dit ce qui s'est
   passé (`AucunResultat`) — jamais un TimeoutError ;
2. un statut EN COURS (file, tâche prise) continue d'être attendu, et un budget épuisé lève
   toujours le TimeoutError d'origine : on ne reconnaît que ce qu'on a OBSERVÉ ;
3. en fiction, une requête sans résultat devient une carte « non mesuré » (rayon vide) et non une
   niche qui disparaît : l'auteur en demande cinq, il en voit cinq, avec la raison ;
4. la tâche créée reste imputée (borne haute : DataForSEO rapporte `cost` 0, on ne descend pas le
   coût du run en dessous du tarif sans mesure de facturation — règle 2).

FIXTURE RÉELLE : `fixtures/serp_aucun_resultat_reel.json`, capturée le 2026-10-05 (réponses de
`task_get` des deux tâches du run). Les statuts « en cours » du test 2 sont INVENTÉS : aucun n'a
été capturé dans ce dépôt.
"""
import json
from pathlib import Path

import pytest

from cost_tracker import CostTracker
from fiction_master import run_fiction_scout
from fiction_serp_provider import fetch_shelf_asins
from models import AutocompleteSignal, FictionNiche
from search_providers import AucunResultat, DataForSEOProvider, TaskPostRefuse

_REEL = json.loads((Path(__file__).parent / "fixtures" / "serp_aucun_resultat_reel.json")
                   .read_text(encoding="utf-8"))["reponses"]


def _post(url, body):
    return {"tasks": [{"status_code": 20100, "status_message": "Task Created", "id": "TID"}]}


def _prov():
    return DataForSEOProvider(login="l", password="p", priority=2)


# ── 1. La fin d'attente, sur la forme RÉELLE ─────────────────────────────────────

def test_la_fixture_est_bien_la_forme_reelle_observee():
    """Garde de fixture : le statut de TÂCHE est 40102 alors que le statut RACINE vaut 20000,
    et `result` est présent — c'est ce qui a mis la boucle en défaut."""
    for r in _REEL:
        t = r["tasks"][0]
        assert r["status_code"] == 20000 and t["status_code"] == 40102
        assert t["result"] and t["result"][0]["items"] is None
        assert t["cost"] == 0 and t["result_count"] == 0


@pytest.mark.parametrize("reponse", _REEL)
def test_un_statut_40102_met_fin_a_l_attente_au_premier_releve(reponse):
    releves = []

    def get(url):
        releves.append(url)
        return reponse

    with pytest.raises(AucunResultat) as e:
        _prov().search("roman reprise ferme famille", post_json=_post, get_json=get,
                       poll_interval=0)
    assert len(releves) == 1, "il ne faut plus poller 40 fois une tâche déjà terminée"
    assert "roman reprise ferme famille" in str(e.value)


def test_aucun_resultat_n_est_ni_un_timeout_ni_une_file_saturee():
    with pytest.raises(AucunResultat) as e:
        _prov().search("q", post_json=_post, get_json=lambda u: _REEL[0], poll_interval=0)
    assert not isinstance(e.value, TimeoutError)
    assert isinstance(e.value, RuntimeError)       # les appelants qui attrapent Exception : inchangés
    assert "saturée" not in str(e.value) and "non prêt" not in str(e.value)


def test_aucun_resultat_n_est_pas_un_refus_de_compte():
    """Sinon les orchestrateurs cesseraient d'appeler le fournisseur pour TOUTES les niches
    suivantes (RefusCompte) sur la foi d'UNE requête sans résultat."""
    assert not issubclass(AucunResultat, TaskPostRefuse)


# ── 2. Ce qu'on n'a pas observé reste attendu ────────────────────────────────────

def test_une_tache_en_cours_est_toujours_attendue_puis_lue():
    """Statuts INVENTÉS (aucune capture dans le dépôt) : seule la distinction « terminal /
    pas terminal » compte ici."""
    reponses = iter([
        {"tasks": [{"status_code": 40602, "status_message": "Task In Queue"}]},
        {"tasks": [{"status_code": 40601, "status_message": "Task Handed"}]},
        {"tasks": [{"status_code": 20000, "result": [{"keyword": "q", "items": [
            {"type": "amazon_serp", "data_asin": "A1", "title": "T"}]}]}]},
    ])
    res = _prov().search("q", post_json=_post, get_json=lambda u: next(reponses),
                         poll_interval=0)
    assert [o.asin for o in res.organic] == ["A1"]


def test_un_budget_epuise_leve_toujours_le_timeout_d_origine():
    releves = []

    def get(url):
        releves.append(url)
        return {"tasks": [{"status_code": 40602, "status_message": "Task In Queue"}]}

    with pytest.raises(TimeoutError, match="non prêt après"):
        _prov().search("q", post_json=_post, get_json=get, poll_interval=0, max_polls=3)
    assert len(releves) == 3


# ── 3. Fiction : une carte, pas une disparition ──────────────────────────────────

class _ProvAucunResultat:
    priority = 2

    def search(self, keyword, depth=100, books_only=True, search_param=None):
        raise AucunResultat(f"Amazon ne rend aucun résultat pour « {keyword} »")


def _niche(rayon="papier"):
    return FictionNiche(sous_genre="feel_good", tropes=["deuil_lumineux"], decor="village",
                        rayon=rayon, query="roman reprise ferme famille")


def test_fiction_une_requete_sans_resultat_rend_un_rayon_vide_pas_une_exception():
    cost = CostTracker()
    sp, asins = fetch_shelf_asins(_niche(), _ProvAucunResultat(), cost=cost)
    assert sp == "i=stripbooks" and asins == []


def test_fiction_la_tache_creee_reste_imputee():
    cost = CostTracker()
    fetch_shelf_asins(_niche(), _ProvAucunResultat(), cost=cost)
    assert cost.breakdown()["dataforseo_calls"] == 1


def test_fiction_un_timeout_reste_une_exception_imputee():
    class _Lent(_ProvAucunResultat):
        def search(self, *a, **k):
            raise TimeoutError("résultat DataForSEO non prêt après 320 s")

    cost = CostTracker()
    with pytest.raises(TimeoutError):
        fetch_shelf_asins(_niche(), _Lent(), cost=cost)
    assert cost.breakdown()["dataforseo_calls"] == 1


def _ideate(sous_genre_cle, n=8, **kw):
    return [FictionNiche(sous_genre=sous_genre_cle, tropes=["t"], decor="d", rayon="papier",
                         query=f"roman feel good requete {i}") for i in range(n)]


def _serp_une_sur_deux(niche, **kw):
    i = int(niche.query.rsplit(" ", 1)[-1])
    return ("i=stripbooks", []) if i % 2 else ("i=stripbooks", [f"A{i}"])


def _enrich(asins, **kw):
    from models import EnrichedBook
    return {a: EnrichedBook(asin=a, title="T", blurb="b", bsr=3000, bsr_rayon="Livres")
            for a in asins}


def _classify(books, sg, **kw):
    from models import TropeClassification
    return [TropeClassification(asin=b.asin, taxonomy_version="fr_v1", est_roman=True)
            for b in books]


def _probe(niche, **kw):
    return AutocompleteSignal(niche_query=niche.query, mesure=True, score=0.0)


def _lancer(**kw):
    messages = []
    rapports = run_fiction_scout("feel_good", n_niches=4, rayon="papier", ideate=_ideate,
                                 serp_fn=_serp_une_sur_deux, enrich_fn=_enrich,
                                 classify=_classify, probe=_probe,
                                 progress=messages.append, use_cache=False, **kw)
    return rapports, messages


def test_fiction_chaque_trio_demande_a_une_carte_meme_sans_resultat():
    rapports, _ = _lancer()
    assert len(rapports) == 4
    vides = [r for r in rapports if r.demand_matrix == "non_mesurable"]
    assert len(vides) == 2 and all(not r.books for r in vides)


def test_fiction_le_rayon_vide_dit_que_ce_n_est_pas_une_niche_morte():
    rapports, _ = _lancer()
    vide = next(r for r in rapports if not r.books)
    assert "NON MESURÉE" in vide.verdict and "surtout pas une niche morte" in vide.verdict


def test_fiction_la_progression_dit_la_raison_sans_jargon():
    from progression_publique import message_public
    _, messages = _lancer()
    dits = [m for m in messages if "aucun livre" in m]
    assert len(dits) == 2
    for m in dits:
        assert m.lstrip().startswith("⚠") and "requête" in m
        assert message_public(m) == m, "le message est déjà public : rien à réécrire ni masquer"


def test_fiction_aucune_niche_ne_disparait_sans_un_mot():
    """Avant : « échec SERP … file saturée — niche écartée » puis, au bilan, « 2 niche(s) en
    échec sur 5 ». Un rayon vide n'est pas un échec : il n'est PAS compté comme tel."""
    _, messages = _lancer()
    assert not any("en échec sur" in m for m in messages)
    assert not any("saturée" in m for m in messages)


def test_fiction_tous_les_rayons_vides_ne_paient_aucune_fiche():
    appels = []

    def enrich(asins, **kw):
        appels.append(list(asins))
        return {}

    rapports = run_fiction_scout("feel_good", n_niches=3, rayon="papier", ideate=_ideate,
                                 serp_fn=lambda n, **kw: ("i=stripbooks", []),
                                 enrich_fn=enrich, classify=_classify, probe=_probe,
                                 progress=lambda m: None, use_cache=False)
    assert len(rapports) == 3 and all(r.demand_matrix == "non_mesurable" for r in rapports)
    assert appels == [], "rien à enrichir : aucun appel, aucune ligne « Enrichissement de 0 »"
