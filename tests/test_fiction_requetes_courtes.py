"""La requête d'un trio fiction : COURTE, ancrée sur celle du rayon.

Mesuré le 2026-10-05 sur le run feel_good / papier (deux runs fiction enregistrés, 8 niches) :
- les deux requêtes que l'idéateur a écrites hors de la requête de référence (« roman reprise
  ferme famille », 4 mots ; « roman nouvelle vie île recommencer », 5 mots) n'ont rendu AUCUN
  résultat sur Amazon (statut 40102, cf. test_serp_aucun_resultat.py) ;
- les autres requêtes de 5 à 6 mots ont rendu 0, 2, 3 ou 9 livres, dont 8 hors sujet, là où un
  rayon se mesure sur une dizaine ;
- sur l'autocomplete d'Amazon (gratuit), seule la TÊTE du rayon (« roman feel good », « cosy
  mystery ») est tapée par de vrais lecteurs : ajoutez « librairie » ou « boulangerie » et il ne
  rend plus rien.

Le prompt demandait pourtant « 3 à 6 mots ». Il demande désormais 2 à 4 mots, qui COMMENCENT par
la requête de référence du sous-genre — et c'est le CODE qui le garantit (un modèle oublie une
consigne sous pression ; rendre une requête hors règle, c'est payer une recherche vide).

HYPOTHÈSE À MESURER, pas un acquis : qu'une requête ancrée rende plus de livres. Aucune recherche
n'a été payée pour le vérifier ; seules les causes ci-dessus sont observées.
"""
import json

import pytest

from fiction_ideator import SYSTEM_PROMPT, generate_trios, requete_courte
from fiction_taxonomy import load_taxonomy, valid_keys

HEAD = "roman feel good"


# ── La règle, sur des cas réels du run du 2026-10-05 ─────────────────────────────

@pytest.mark.parametrize("query,decor,attendu", [
    # 6 mots, la tête éclatée : on rétablit la tête, le décor passe en premier
    ("roman héritage maison village feel good", "village", "roman feel good village"),
    # 5 mots : le décor est « librairie_cafe », son mot concret est gardé
    ("roman feel good librairie reconstruction", "librairie_cafe", "roman feel good librairie"),
    # 4 mots mais SANS la tête : c'est elle qui manquait (résultat : aucun résultat chez Amazon).
    # Aucun mot ne recoupe le décor : on garde le premier mot concret du modèle, l'ordre d'origine.
    ("roman reprise ferme famille", "village", "roman feel good reprise"),
])
def test_cas_reels_du_run_feel_good(query, decor, attendu):
    assert requete_courte(query, HEAD, decor) == attendu


def test_une_requete_deja_conforme_n_est_pas_touchee():
    assert requete_courte("roman feel good village", HEAD, "village") == "roman feel good village"
    assert requete_courte("roman feel good", HEAD, "village") == "roman feel good"


def test_la_tete_est_reconnue_sans_casse_ni_accents():
    assert requete_courte("Roman Feel Good Village", HEAD, "village") == "Roman Feel Good Village"
    assert requete_courte("cosy mystery village", "cosy mystery", None) == "cosy mystery village"
    assert requete_courte("thriller psychologique chalet", "thriller psychologique",
                          "chalet_isole") == "thriller psychologique chalet"


def test_une_tete_courte_laisse_plus_de_place_aux_mots_concrets():
    # « cosy mystery » : 2 mots de tête, donc jusqu'à 2 mots concrets (4 au total)
    assert requete_courte("cosy mystery librairie duo enquête", "cosy mystery",
                          "village_breton") == "cosy mystery librairie duo"
    # « romantasy » : 1 mot de tête, 3 mots concrets au plus
    assert requete_courte("romantasy académie rivaux ennemis amants", "romantasy",
                          "academie") == "romantasy académie rivaux ennemis"


def test_les_mots_vides_ne_comptent_pas():
    assert requete_courte("cosy mystery dans un village de bretagne", "cosy mystery",
                          "village_breton") == "cosy mystery village bretagne"


def test_jamais_plus_de_quatre_mots_et_toujours_la_tete_en_premier():
    for q in ["un très long titre de roman qui raconte une histoire interminable de village",
              "feel good librairie roman reconstruction deuil village montagne",
              "x", "roman"]:
        r = requete_courte(q, HEAD, "village")
        assert len(r.split()) <= 4 and r.startswith(HEAD)


def test_une_requete_vide_ou_une_tete_inconnue_ne_plante_pas():
    assert requete_courte("", HEAD, "village") == HEAD
    assert requete_courte("roman reprise ferme", "", "village") == "roman reprise ferme"


def test_la_regle_est_idempotente():
    for q in ["roman héritage maison village feel good", "roman reprise ferme famille"]:
        une = requete_courte(q, HEAD, "village")
        assert requete_courte(une, HEAD, "village") == une


def test_sur_toute_la_taxonomie_une_requete_longue_devient_conforme():
    """Pour CHAQUE sous-genre et CHAQUE décor réels : quatre mots au plus, tête en premier."""
    t = load_taxonomy()
    for cle, sg in t["sous_genres"].items():
        tete = sg["query_fr"]
        _, decors = valid_keys(cle)
        for d in decors:
            r = requete_courte(f"{tete} très long mot quatre cinq six", tete, d)
            assert len(r.split()) <= 4 and r.startswith(tete), (cle, d, r)


# ── Branchée dans la génération ──────────────────────────────────────────────────

class _Bloc:
    type = "tool_use"

    def __init__(self, entree):
        self.input = entree


class _Rep:
    def __init__(self, entree):
        self.content, self.usage = [_Bloc(entree)], None


class _Client:
    def __init__(self, trios):
        self.trios, self.appels = trios, []
        self.messages = self

    def create(self, **kw):
        self.appels.append(kw)
        return _Rep({"trios": self.trios})


def _generer(trios, **kw):
    return generate_trios("feel_good", n=len(trios), client=_Client(trios), **kw)


def test_generate_trios_raccourcit_la_requete_sans_perdre_le_trio():
    tropes, decors = valid_keys("feel_good")
    out = _generer([{"tropes": [tropes[0]], "decor": "village", "rationale": "r",
                     "query": "roman héritage maison village feel good"}])
    assert len(out) == 1
    assert out[0].query == "roman feel good village"
    assert out[0].tropes == [tropes[0]] and out[0].decor == "village"


def test_generate_trios_laisse_une_requete_conforme_intacte():
    tropes, _ = valid_keys("feel_good")
    out = _generer([{"tropes": [tropes[0]], "decor": "village", "rationale": "r",
                     "query": "roman feel good village"}])
    assert out[0].query == "roman feel good village"


def test_generate_trios_sans_decor_ne_perd_pas_la_requete():
    tropes, _ = valid_keys("feel_good")
    out = _generer([{"tropes": [tropes[0]], "decor": None, "rationale": "r",
                     "query": "roman retour aux sources montagne"}])
    assert out[0].query.startswith("roman feel good") and len(out[0].query.split()) <= 4


# ── Le prompt ────────────────────────────────────────────────────────────────────

def test_le_prompt_demande_2_a_4_mots_et_plus_3_a_6():
    assert "3 à 6 mots" not in SYSTEM_PROMPT
    assert "2 à 4 mots" in SYSTEM_PROMPT


def test_le_prompt_impose_la_requete_de_reference_et_dit_pourquoi():
    assert "COMMENCE par la requête de référence" in SYSTEM_PROMPT
    assert "aucun résultat" in SYSTEM_PROMPT.lower()


def test_le_prompt_envoye_porte_la_requete_de_reference_du_sous_genre():
    c = _Client([])
    generate_trios("feel_good", n=1, client=c)
    envoye = c.appels[0]["messages"][0]["content"]
    assert "Requête de référence du rayon : « roman feel good »" in envoye


# ── La requête n'est PAS l'identité du trio ─────────────────────────────────────
#
# Revue adverse du 2026-10-05. Ancrer chaque requête sur « tête + un mot du décor » fait
# partager le MÊME rayon à tous les trios d'un même décor : c'est la nature d'une requête courte
# (feel_good : 6 décors pour 11 trios), pas un défaut à corriger. Première version : écarter le
# trio dont la requête collisionnait — 11 demandés, 7 rendus ; décor imposé, 8 demandés, 2 rendus.
# Deuxième version testée : un repli sur un autre mot du modèle — un rayon sans rapport avec le
# décor, présenté comme celui du trio. Les deux ont été écartées.
#
# Décision : les trios gardent leur identité propre (`FictionNiche.cle`, cf. test_fiction_cle_trio.py),
# la recherche payée est PARTAGÉE entre trios de même requête (cf. test_fiction_rayon_partage.py),
# et `generate_trios` ne jette aucun trio pour cause de requête identique.

from fiction_ideator import cle_requete


def _trio(tropes, decor, query):
    return {"tropes": tropes, "decor": decor, "rationale": "r", "query": query}


def test_deux_trios_au_meme_decor_gardent_chacun_leur_trio_meme_requete():
    tropes, _ = valid_keys("feel_good")
    out = _generer([
        _trio([tropes[0]], "village", "roman héritage maison village feel good"),
        _trio([tropes[1]], "village", "roman village retour sources feel good")])
    assert len(out) == 2
    assert [t.query for t in out] == ["roman feel good village", "roman feel good village"]
    assert out[0].tropes != out[1].tropes


def test_aucun_trio_n_est_ecarte_pour_une_requete_identique():
    """11 trios demandés, 6 décors (plafond du formulaire) : 11 rendus. Décor imposé, 8 trios : 8."""
    tropes, decors = valid_keys("feel_good")
    onze = [_trio([tropes[i % len(tropes)]], decors[i % len(decors)],
                  f"roman feel good {decors[i % len(decors)]}") for i in range(11)]
    assert len(_generer(onze)) == 11
    imposes = [_trio([tropes[i % len(tropes)]], "village", "roman feel good village")
               for i in range(8)]
    assert len(_generer(imposes)) == 8


def test_la_requete_est_repliee_sans_changer_le_decor_du_trio():
    """Aucun repli sur un mot de ressort : le mot concret reste celui du décor quand il y est."""
    tropes, _ = valid_keys("feel_good")
    out = _generer([_trio([tropes[0]], "village", "roman feel good village deuil reconstruction")])
    assert out[0].query == "roman feel good village"


def test_les_requetes_sont_comparees_sans_casse_ni_accents():
    assert cle_requete("Roman Feel Good Éclair") == cle_requete("roman feel good eclair")


def test_requete_courte_ne_prend_plus_d_exclusion():
    """Plus de collision à éviter : la signature ne porte pas `exclure`."""
    import inspect
    assert "exclure" not in inspect.signature(requete_courte).parameters
