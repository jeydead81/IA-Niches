"""Le PITCH de l'angle fiction : 3 à 4 phrases de ce que pourrait raconter le livre.

Demande de Baptiste (2026-10-05) : sous la couverture, dans l'analyse du trio, un pitch de 3 à 4
phrases MAXIMUM. Le modèle le produit (champ `pitch` de l'angle, requis par le schéma strict) ; le
CODE le borne — on demande, puis on contrôle : un modèle déborde, et un pitch de quinze lignes
casserait la carte. Le nombre de phrases est un format, pas un fait : la coupe se fait à la fin
d'une phrase, jamais au milieu d'un mot.

Un pitch absent ou illisible vaut « » : jamais deviné, jamais « non disponible » écrit à sa place.

FIXTURES INVENTÉES : aucune réponse réelle de cette version du modèle n'a été capturée.
"""
import pytest

from fiction_verdict import (SYSTEM_PROMPT, VERDICT_FIC_SCHEMA, generate_fiction_verdict,
                             limiter_pitch)
from models import AngleAttaque
from tests.test_fiction_verdict import _Client, _payload, _rapport

TROIS = ("Léa reprend la librairie de sa grand-mère dans un port breton. Elle y trouve un "
         "carnet de commandes jamais livrées. Un libraire rival veut racheter les murs avant "
         "l'hiver.")


# ── Le modèle et le schéma ──────────────────────────────────────────────────────

def test_l_angle_porte_un_pitch_vide_par_defaut():
    a = AngleAttaque(angle="a", pourquoi="p", risque="r", titre="t", sous_titre="s")
    assert a.pitch == ""


def test_le_schema_demande_un_pitch_obligatoire():
    angle = VERDICT_FIC_SCHEMA["properties"]["angles"]["items"]
    assert angle["properties"]["pitch"]["type"] == "string"
    assert "pitch" in angle["required"]
    assert angle["additionalProperties"] is False


def test_le_prompt_cadre_le_pitch():
    assert "pitch" in SYSTEM_PROMPT.lower()
    assert "3 à 4 phrases" in SYSTEM_PROMPT
    assert "ne révèle pas la fin" in SYSTEM_PROMPT.lower()
    assert "personnage existant" in SYSTEM_PROMPT


# ── Ce que rend le verdict ──────────────────────────────────────────────────────

def _verdict(pitch):
    p = _payload()
    p["angles"][0]["pitch"] = pitch
    return generate_fiction_verdict(_rapport(), client=_Client(p))


def test_un_pitch_de_trois_phrases_est_garde_tel_quel():
    assert _verdict(TROIS).angles[0].pitch == TROIS


def test_au_dela_de_quatre_phrases_on_coupe_a_la_fin_de_la_quatrieme():
    long = " ".join(f"Phrase numéro {i} du pitch." for i in range(1, 8))
    p = _verdict(long).angles[0].pitch
    assert p == " ".join(f"Phrase numéro {i} du pitch." for i in range(1, 5))


def test_un_pitch_absent_ou_illisible_vaut_vide_jamais_devine():
    p = _payload()
    del p["angles"][0]["pitch"]
    assert generate_fiction_verdict(_rapport(), client=_Client(p)).angles[0].pitch == ""
    for illisible in (None, 12, ["a", "b"], {"x": 1}):
        assert _verdict(illisible).angles[0].pitch == ""


def test_le_pitch_survit_a_la_serialisation():
    d = _verdict(TROIS).model_dump()
    assert d["angles"][0]["pitch"] == TROIS


# ── limiter_pitch ───────────────────────────────────────────────────────────────

def test_les_retours_a_la_ligne_et_espaces_multiples_sont_normalises():
    assert limiter_pitch("Une phrase.\n\nEt   une   autre.") == "Une phrase. Et une autre."


def test_les_abreviations_ne_comptent_pas_pour_une_fin_de_phrase():
    t = "M. Dupont arrive au village. Mme Roux le guette. Dr. Pelletier hésite. Il est tard."
    assert limiter_pitch(t, max_phrases=2) == "M. Dupont arrive au village. Mme Roux le guette."


def test_les_points_de_suspension_et_les_guillemets_terminent_une_phrase():
    t = "Elle part… Il reste. « Reviens ! » crie-t-elle. Rien. Plus tard, tout change."
    assert limiter_pitch(t, max_phrases=3) == "Elle part… Il reste. « Reviens ! » crie-t-elle."


def test_une_seule_phrase_demesuree_est_coupee_sur_un_mot_avec_une_ellipse():
    t = "mot " * 600
    r = limiter_pitch(t)
    assert len(r) <= 701 and r.endswith("…") and not r.endswith(" …")
    assert " mo…" not in r, "jamais au milieu d'un mot"


@pytest.mark.parametrize("entree", ["", "   ", None, 7, [], {}])
def test_une_entree_vide_ou_non_textuelle_rend_vide(entree):
    assert limiter_pitch(entree) == ""


def test_le_comptage_est_borne_par_le_parametre():
    assert limiter_pitch("A b. C d. E f.", max_phrases=1) == "A b."
    assert limiter_pitch("A b. C d. E f.", max_phrases=9) == "A b. C d. E f."
