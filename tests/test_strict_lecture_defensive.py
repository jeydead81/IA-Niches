"""R15 — mode STRICT et lecture défensive des quatre outils LLM qui lisaient `block.input`
sans garantie de forme : lowcontent_verdict, fiction_ideator, kdp_keywords, fiction_classifier.

Le 2026-09-13, `lowcontent_ideator` a reçu des niches en TEXTE là où son schéma attend des
objets, et a levé APRÈS l'appel payé (§2.14). Ces quatre modules portaient le même défaut
latent. Deux moitiés, testées séparément :
- l'outil ENVOYÉ porte `strict: true` et `additionalProperties: false` sur chaque objet
  (§5.32 : la valeur passée à l'API, jamais la présence d'une constante) ;
- une réponse hors schéma ne lève plus, et ne fabrique rien — le strict ne protège pas
  d'une troncature.

FIXTURES INVENTÉES : aucune réponse malformée de ces quatre outils n'a été capturée. Leur
forme transpose à chaque schéma celle, RÉELLE, du plantage du 2026-09-13 (des chaînes à la
place d'objets).
"""
import json

import pytest

from fiction_classifier import classify_books
from fiction_ideator import generate_trios
from kdp_keywords import generer_mots_cles
from lowcontent_verdict import generate_lowcontent_verdict
from models import EnrichedBook, ScoredNiche
from tests.test_lowcontent_verdict import _payload, _scored


class _Bloc:
    type = "tool_use"

    def __init__(self, entree):
        self.input = entree


class _Reponse:
    def __init__(self, entree):
        self.content = [_Bloc(entree)]
        self.usage = None
        self.stop_reason = "tool_use"


class _Client:
    """Client Anthropic factice : capture ce qui est ENVOYÉ, rend une entrée figée."""

    def __init__(self, entree):
        self.entree, self.appels = entree, []
        self.messages = self

    def create(self, **kw):
        self.appels.append(kw)
        return _Reponse(self.entree)


def _objets(schema):
    """Tous les sous-schémas de type objet, à n'importe quelle profondeur."""
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for v in schema.values():
            yield from _objets(v)
    elif isinstance(schema, list):
        for v in schema:
            yield from _objets(v)


def _verifier_strict(client, n_objets_min: int) -> None:
    outil = client.appels[0]["tools"][0]
    assert outil.get("strict") is True
    objets = list(_objets(outil["input_schema"]))
    assert len(objets) >= n_objets_min
    assert all(o.get("additionalProperties") is False for o in objets)


_TRIO = {"tropes": ["animal_compagnon", "petite_communaute"], "decor": "village_breton",
         "query": "cosy mystery chat village breton", "rationale": "r"}


def _niche_kdp() -> ScoredNiche:
    return ScoredNiche(niche="cosy mystery breton", requete_amazon="cosy mystery breton",
                       categorie="policier")


def _livres():
    return [EnrichedBook(asin="A1", title="T1", blurb="Une pâtissière enquête au village."),
            EnrichedBook(asin="A2", title="T2", blurb="Un chat, une libraire, un meurtre.")]


# ══ 1. L'outil part en mode STRICT — sur ce qui est réellement ENVOYÉ ═══════════

def test_verdict_lc_part_en_mode_strict():
    c = _Client(_payload())
    generate_lowcontent_verdict(_scored(), client=c)
    _verifier_strict(c, n_objets_min=2)            # la racine ET chaque angle


def test_ideator_fiction_part_en_mode_strict():
    c = _Client({"trios": []})
    generate_trios("cosy_mystery", n=2, client=c)
    _verifier_strict(c, n_objets_min=2)


def test_mots_cles_kdp_partent_en_mode_strict():
    c = _Client({"candidats": []})
    generer_mots_cles(_niche_kdp(), client=c, sonde=lambda p: [])
    _verifier_strict(c, n_objets_min=1)


def test_classifieur_part_en_mode_strict():
    c = _Client({"livres": []})
    classify_books(_livres(), "cosy_mystery", client=c)
    _verifier_strict(c, n_objets_min=2)


# ══ 2. lowcontent_verdict ════════════════════════════════════════════════════════

def test_verdict_lc_angles_en_texte_ne_leve_pas():
    """La forme exacte du plantage : des chaînes là où le schéma attend des objets. Aucun
    angle n'est deviné, et l'écran dit qu'il en manque (règle 2)."""
    v = generate_lowcontent_verdict(_scored(), client=_Client(_payload(angles=["a", "b"])))
    assert v.angles == []
    assert "illisible" in v.facteur_decisif.lower()


def test_verdict_lc_angles_en_chaine_json_sont_relus():
    """Décoder n'est pas deviner : c'est le contenu structuré du modèle, seulement
    sérialisé."""
    angles = _payload()["angles"]
    v = generate_lowcontent_verdict(
        _scored(), client=_Client(_payload(angles=json.dumps(angles))))
    assert len(v.angles) == 1 and "120 pages" in v.angles[0].spec_interieur


def test_verdict_lc_un_angle_mal_forme_n_emporte_pas_les_autres():
    bon = _payload()["angles"][0]
    v = generate_lowcontent_verdict(
        _scored(), client=_Client(_payload(angles=[{"angle": "incomplet"}, bon])))
    assert [a.titre for a in v.angles] == ["t"]


def test_verdict_lc_confiance_illisible_n_est_jamais_zero():
    """« 0/10 » se lirait comme un jugement du modèle. Une confiance qu'on ne sait pas lire
    est une réponse illisible, pas une mesure à zéro (règle 3)."""
    with pytest.raises(ValueError, match="illisible"):
        generate_lowcontent_verdict(_scored(), client=_Client(_payload(confiance="haute")))


def test_verdict_lc_entree_en_texte_libre_leve_proprement():
    with pytest.raises(ValueError, match="illisible"):
        generate_lowcontent_verdict(_scored(), client=_Client("texte libre"))


def test_la_garde_des_formats_normes_tient_sur_des_angles_illisibles():
    """Des angles perdus ne portent pas de source réglementaire : le « Go » d'un registre
    doit rester dégradé, jamais passer parce que la lecture a échoué."""
    v = generate_lowcontent_verdict(
        _scored(format_cle="registres_reglementaires"),
        client=_Client(_payload(verdict="Go", angles=["a"])))
    assert v.verdict == "Go prudent"


# ══ 3. fiction_ideator ═══════════════════════════════════════════════════════════

def test_trios_en_texte_ne_levent_pas():
    assert generate_trios("cosy_mystery", n=3,
                          client=_Client({"trios": ["cosy mystery chat", "autre"]})) == []


def test_trios_en_chaine_json_sont_relus():
    trios = generate_trios("cosy_mystery", n=3,
                           client=_Client({"trios": json.dumps([_TRIO])}))
    assert len(trios) == 1 and trios[0].decor == "village_breton"


def test_une_requete_non_textuelle_ecarte_le_trio_sans_lever():
    trios = generate_trios("cosy_mystery", n=3,
                           client=_Client({"trios": [{**_TRIO, "query": ["x"]}, _TRIO]}))
    assert len(trios) == 1


# ══ 4. kdp_keywords ══════════════════════════════════════════════════════════════

def test_kdp_candidats_en_chaine_ne_produit_pas_de_lettres():
    """Le rejeu a produit emplacements=['c','a','r','n','e','t','d'] sans erreur : `extend`
    d'une chaîne la découpe en lettres, et la sonde factice les « confirmait »."""
    r = generer_mots_cles(_niche_kdp(), client=_Client({"candidats": "carnet de voyage"}),
                          sonde=lambda p: [p])
    assert not any(len(k) <= 1 for k in r.emplacements + r.a_verifier)
    assert r.emplacements == []
    assert any("illisible" in x["motif"] for x in r.rejetes)


def test_kdp_candidats_en_chaine_json_sont_relus():
    r = generer_mots_cles(
        _niche_kdp(), client=_Client({"candidats": json.dumps(["enquête village pâtissière"])}),
        sonde=lambda p: [])
    assert r.emplacements == ["enquête village pâtissière"]


def test_kdp_entree_en_texte_libre_ne_leve_pas():
    r = generer_mots_cles(_niche_kdp(), client=_Client("texte libre"), sonde=lambda p: [])
    assert r.emplacements == []
    assert any("illisible" in x["motif"] for x in r.rejetes)


# ══ 5. fiction_classifier ════════════════════════════════════════════════════════

def test_classifieur_champ_mal_type_ne_perd_pas_le_lot():
    """Un seul livre au champ mal typé levait une ValidationError et emportait les 19
    autres classifications du lot — déjà payées."""
    etapes = []
    cl = classify_books(_livres(), "cosy_mystery", progress=etapes.append,
                        client=_Client({"livres": [
                            {"asin": "A1", "tropes": ["metier_gourmand"], "confidence": "haute"},
                            {"asin": "A2", "tropes": ["metier_gourmand"], "est_roman": True}]}))
    assert [c.asin for c in cl] == ["A2"]
    assert any("A1" in e and "illisible" in e for e in etapes)


def test_classifieur_livres_en_chaine_json_sont_relus():
    livres = [{"asin": "A1", "tropes": ["metier_gourmand"], "est_roman": True},
              {"asin": "A2", "tropes": [], "est_roman": True}]
    cl = classify_books(_livres(), "cosy_mystery",
                        client=_Client({"livres": json.dumps(livres)}))
    assert sorted(c.asin for c in cl) == ["A1", "A2"]
