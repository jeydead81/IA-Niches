"""Arbre d'autocomplete — l'autocomplete devient la SOURCE des niches, pas leur validation.

C'est le renversement du chunk. En non-fiction, le LLM propose et Amazon valide. En
low-content ça ne marche pas : la tête de requête (« livre coloriage », « registre ») est
morte ou tenue par des éditeurs, et l'argent est trois crans plus bas dans la traîne
(« coloriage licorne 3 ans fille », « registre du personnel obligatoire »). Un LLM qui
invente des requêtes long-tail invente aussi la demande qui va avec. Amazon, lui, ne
complète que ce que des gens tapent réellement — et il le donne gratuitement.

D'où : on descend l'arbre des complétions, puis le LLM CLASSE ce qu'on a trouvé (E4). Il
ne peut plus inventer une demande qui n'existe pas.

`n_enfants` est le signal qui n'existait pas avant : une requête que les acheteurs
affinent encore est une intention plus forte qu'une requête terminale. Il ne se déduit
d'aucun comptage de suggestions — il faut avoir descendu l'arbre pour le connaître.
"""
import json
from pathlib import Path

import pytest

from autocomplete_expand import Suggestion, expand

_FIX = Path(__file__).parent / "fixtures" / "autocomplete_tree_coloriage.json"


def _arbre() -> dict:
    return json.loads(_FIX.read_text(encoding="utf-8"))


def _fetch_fige(arbre: dict):
    """Sonde hors-ligne : rend ce que la fixture connaît, et une liste VIDE sinon.

    Vide et non exception : c'est le comportement d'Amazon sur un préfixe qu'il ne
    complète pas, et c'est précisément ce que l'algorithme doit savoir distinguer d'une
    panne. Le compteur d'appels sert aux tests de budget."""
    appels = []

    def fetch(prefixe: str) -> list[str]:
        appels.append(prefixe)
        return list(arbre.get(prefixe, []))

    fetch.appels = appels
    return fetch


def test_la_graine_est_sondee_et_ses_completions_rendues():
    f = _fetch_fige(_arbre())
    out = expand("livre coloriage", fetch=f, depth=1, alphabet=False, pause=0)
    requetes = [s.requete for s in out]
    assert "livre coloriage princesse" in requetes
    assert "livre coloriage adulte anti stress" in requetes


def test_la_profondeur_2_descend_dans_la_traine():
    """Le niveau 1 rend « livre coloriage princesse » ; c'est le niveau 2 qui rend
    « livre coloriage princesse licorne 3 ans » — la requête qui vaut de l'argent."""
    f = _fetch_fige(_arbre())
    out = expand("livre coloriage", fetch=f, depth=2, alphabet=False, pause=0)
    requetes = [s.requete for s in out]
    assert "livre coloriage princesse licorne 3 ans" in requetes
    profonde = next(s for s in out if s.requete == "livre coloriage princesse licorne 3 ans")
    assert profonde.profondeur == 2
    assert profonde.parent == "livre coloriage princesse"


def test_n_enfants_compte_ce_que_la_requete_a_elle_meme_produit():
    """LE signal apporté par l'arbre. Une requête que les acheteurs affinent encore est
    une intention forte ; ça ne se déduit d'aucun comptage de suggestions."""
    f = _fetch_fige(_arbre())
    out = expand("livre coloriage", fetch=f, depth=2, alphabet=False, pause=0)
    par_requete = {s.requete: s for s in out}
    assert par_requete["livre coloriage princesse"].n_enfants == 2
    # Au DERNIER niveau, la requete n'est jamais sondee : son compteur vaut None, et pas
    # zero. La version precedente de ce test affirmait « 0 mesure, pas 0 par defaut » --
    # c'etait faux, et ca encodait le malentendu que ce compteur devait justement eviter.
    assert par_requete["livre coloriage princesse licorne 3 ans"].n_enfants is None


def test_le_mode_alphabet_fait_ressortir_ce_que_le_prefixe_seul_cache():
    """Amazon ne rend qu'une dizaine de complétions par préfixe : « livre coloriage » seul
    ne montre jamais « livre coloriage zen ». Sonder « livre coloriage z » le fait sortir."""
    f = _fetch_fige(_arbre())
    sans = {s.requete for s in expand("livre coloriage", fetch=f, depth=1,
                                      alphabet=False, pause=0)}
    f2 = _fetch_fige(_arbre())
    avec = {s.requete for s in expand("livre coloriage", fetch=f2, depth=1,
                                      alphabet=True, pause=0)}
    assert "livre coloriage zen" in avec
    assert "livre coloriage zen" not in sans


def test_le_budget_de_sondes_est_un_arret_NET():
    """L'endpoint n'est pas officiel : on ne boucle jamais dessus. `max_probes` est un
    plafond dur, pas une indication."""
    f = _fetch_fige(_arbre())
    expand("livre coloriage", fetch=f, depth=3, alphabet=True, max_probes=5, pause=0)
    assert len(f.appels) <= 5


def test_un_doublon_normalise_n_est_jamais_re_sonde():
    """Amazon rend « Livre Coloriage Adulte » et « livre coloriage adulte ». Les sonder
    deux fois double le budget pour zéro information."""
    arbre = _arbre()
    arbre["livre coloriage"] = ["livre coloriage adulte", "Livre Coloriage Adulte",
                               "livre coloriage adulté"]
    f = _fetch_fige(arbre)
    out = expand("livre coloriage", fetch=f, depth=2, alphabet=False, pause=0)
    # exactement les trois variantes de casse/accent, PAS leurs enfants legitimes
    # (« livre coloriage adulte mandala » est un noeud plus profond, pas un doublon)
    from autocomplete_expand import _plat
    variantes = [s for s in out if _plat(s.requete) == "livre coloriage adulte"]
    assert len(variantes) == 1
    assert f.appels.count("livre coloriage adulte") <= 1
    assert "Livre Coloriage Adulte" not in f.appels


def test_la_graine_elle_meme_n_est_pas_rendue_comme_une_suggestion():
    """La graine est le point de départ, pas une trouvaille. La rendre ferait compter
    une requête que personne n'a suggérée."""
    f = _fetch_fige(_arbre())
    out = expand("livre coloriage", fetch=f, depth=2, alphabet=False, pause=0)
    assert all(s.requete != "livre coloriage" for s in out)


def test_une_graine_vide_ne_sonde_rien():
    f = _fetch_fige(_arbre())
    assert expand("", fetch=f, pause=0) == []
    assert f.appels == []


def test_une_graine_sans_completion_rend_une_liste_vide_sans_lever():
    """Zéro suggestion ne conclut RIEN (§5.10) : c'est à l'appelant de le dire. Ici on
    rend simplement une liste vide, on ne déclare pas la niche morte."""
    f = _fetch_fige({})
    assert expand("requete inexistante", fetch=f, depth=2, pause=0) == []


def test_les_suggestions_sont_triees_du_plus_proche_au_plus_loin():
    """Profondeur croissante : l'appelant veut pouvoir couper la traîne au bon niveau."""
    f = _fetch_fige(_arbre())
    out = expand("livre coloriage", fetch=f, depth=2, alphabet=False, pause=0)
    profondeurs = [s.profondeur for s in out]
    assert profondeurs == sorted(profondeurs)


def test_une_panne_de_sonde_ne_se_lit_pas_comme_une_absence_de_demande():
    """Invariant le plus répété du dépôt. Si la sonde LÈVE, on ne rend pas « zéro
    suggestion » : on laisse remonter, pour que l'appelant sache qu'il n'a pas mesuré."""
    def fetch_en_panne(prefixe):
        raise RuntimeError("réseau coupé")

    with pytest.raises(RuntimeError):
        expand("livre coloriage", fetch=fetch_en_panne, pause=0)


def test_le_cache_evite_de_re_sonder_entre_deux_runs(tmp_path):
    """Deux clients qui explorent le même rayon ne resondent pas Amazon. Le cache est
    mutualisé, comme tout `cache.py` (§5.15)."""
    from cache import Cache
    c = Cache(tmp_path / "t.db")
    f1 = _fetch_fige(_arbre())
    expand("livre coloriage", fetch=f1, depth=1, alphabet=False, pause=0, cache=c)
    n1 = len(f1.appels)
    assert n1 > 0

    f2 = _fetch_fige(_arbre())
    out = expand("livre coloriage", fetch=f2, depth=1, alphabet=False, pause=0, cache=c)
    assert f2.appels == []                 # tout est servi par le cache
    assert out                             # ...et le résultat est le même


def test_la_progression_est_annoncee():
    """Un arbre à 80 sondes prend ~30 s à 0,4 s de pause : sans progression, l'interface
    est muette pendant tout ce temps."""
    etapes = []
    f = _fetch_fige(_arbre())
    expand("livre coloriage", fetch=f, depth=1, alphabet=False, pause=0,
           progress=etapes.append)
    assert etapes and any("coloriage" in e for e in etapes)


def test_Suggestion_expose_les_quatre_champs_attendus():
    s = Suggestion(requete="q", parent="p", profondeur=1, n_enfants=3)
    assert (s.requete, s.parent, s.profondeur, s.n_enfants) == ("q", "p", 1, 3)
