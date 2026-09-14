"""Le deuxième run réel de calibration (2026-09-13) — un plantage APRÈS paiement.

Compte vérifié, 31 requêtes sondées, classement lancé… puis `AttributeError: 'str' object
has no attribute 'get'` dans `lowcontent_ideator`. L'appel Anthropic était revenu, donc payé
(~0,09 $) ; aucune SERP n'était partie. Les MÊMES 31 requêtes étaient passées sans encombre au
run précédent : même entrée, autre forme de sortie. Deux défauts :

1. **L'outil n'était pas en mode STRICT.** Sans `strict: true`, l'API ne garantit pas que
   `tool_use.input` respecte le schéma : le modèle a rendu des niches sous forme de TEXTE, et
   le code, qui itérait en supposant des objets, a levé. Le mode strict — sans beta, pris en
   charge sur claude-sonnet-5 — exige `additionalProperties: false` sur chaque objet. Il ne
   protège pas d'une troncature (`max_tokens`) : la lecture reste donc défensive.
2. **La CLI ne laissait AUCUNE trace d'un run qui lève.** Le rapport s'écrivait avant
   l'affichage, mais APRÈS `construire_rapport` : une exception dedans — donc après la
   dépense — sortait en trace Python brute, sans JSON et sans coût.

Aucun réseau : client LLM factice, orchestrateur remplacé.
"""
import json

import pytest

from autocomplete_expand import Suggestion
from lowcontent_ideator import generate_lowcontent_niches
from lowcontent_validation import exporter_gabarit


class _Bloc:
    type = "tool_use"

    def __init__(self, payload):
        self.input = payload


class _Usage:
    input_tokens = 1000
    output_tokens = 900


class _Reponse:
    def __init__(self, payload):
        self.content = [_Bloc(payload)]
        self.usage = _Usage()
        self.stop_reason = "tool_use"


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.appels = []
        self.messages = self

    def create(self, **kw):
        self.appels.append(kw)
        return _Reponse(self.payload)


_REQUETES = ["carnet de voyage", "registre du personnel"]


def _niche(requete):
    return {"requete_amazon": requete, "format_cle": "journal_suivi", "theme": "t",
            "public": "adulte", "niche": requete, "rationale": "r", "categorie": "c"}


def _classer(payload):
    client, etapes = _Client(payload), []
    out = generate_lowcontent_niches(
        seed="x", classer_toutes=True, client=client, progress=etapes.append,
        suggestions=[Suggestion(requete=r, parent="", profondeur=0, n_enfants=3)
                     for r in _REQUETES])
    return out, etapes, client


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


# ══ 1. L'outil part en mode STRICT — vérifié sur ce qui est réellement ENVOYÉ ═══

def test_l_outil_part_en_mode_STRICT():
    """§5.32 : on teste la valeur PASSÉE à l'API, jamais la présence d'une constante."""
    _, _, client = _classer({"niches": []})
    assert client.appels[0]["tools"][0].get("strict") is True


def test_chaque_objet_du_schema_ENVOYE_ferme_ses_proprietes():
    """Exigence du mode strict : `additionalProperties: false` sur TOUS les objets. Un seul
    oublié, et l'API refuse le schéma (400) — non facturé, mais le run s'arrête là."""
    _, _, client = _classer({"niches": []})
    objets = list(_objets(client.appels[0]["tools"][0]["input_schema"]))
    assert len(objets) >= 2                           # la racine ET chaque niche
    assert all(o.get("additionalProperties") is False for o in objets)


# ══ 2. Une réponse hors schéma ne fait plus planter le run ══════════════════════

def test_des_niches_rendues_en_TEXTE_ne_font_plus_planter_le_run():
    """La forme exacte du plantage : des chaînes là où le schéma attend des objets."""
    out, etapes, _ = _classer({"niches": list(_REQUETES)})
    assert out == []
    assert any("illisible" in e for e in etapes)
    # Les requêtes restent NOMMÉES comme non classées : ni un filtre ni un gate ne les a
    # écartées, et le rapport de calibration les versera dans « non rendues ».
    assert any("carnet de voyage" in e and "NON classée" in e for e in etapes)


def test_un_tableau_encode_en_CHAINE_JSON_est_relu_sans_rien_inventer():
    """Décoder la chaîne n'est pas deviner : c'est le contenu structuré du modèle lui-même,
    seulement sérialisé. On récupère ce qu'il a dit, et rien de plus."""
    out, _, _ = _classer({"niches": json.dumps([_niche("carnet de voyage")])})
    assert [n.requete_amazon for n in out] == ["carnet de voyage"]


def test_une_chaine_JSON_illisible_ne_leve_pas():
    out, etapes, _ = _classer({"niches": '[{"requete_amazon": "carnet de voy'})
    assert out == []
    assert any("illisible" in e for e in etapes)


@pytest.mark.parametrize("valeur", [{"requete_amazon": "carnet de voyage"}, 42, True])
def test_des_niches_d_un_type_inattendu_ne_levent_pas(valeur):
    out, etapes, _ = _classer({"niches": valeur})
    assert out == []
    assert any("illisible" in e for e in etapes)


def test_un_lot_MIXTE_garde_les_objets_et_compte_le_reste():
    out, etapes, _ = _classer({"niches": [_niche("carnet de voyage"),
                                          "registre du personnel"]})
    assert [n.requete_amazon for n in out] == ["carnet de voyage"]
    assert any("1 entrée" in e and "illisible" in e for e in etapes)


# ══ 3. Un run qui LÈVE après avoir payé laisse un rapport et son coût ═══════════

def _classeur(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    chemin = exporter_gabarit(tmp_path / "v.xlsx")
    wb = openpyxl.load_workbook(chemin)
    wb.active["A7"], wb.active["C7"] = "carnet de voyage", "bonne"
    wb.save(chemin)
    return chemin


def _lancer(tmp_path, monkeypatch, capsys, exception):
    import build_lowcontent_validation_set as cli
    # Isole le VRAI df-cache.db : la CLI chiffre desormais un devis en lisant le cache, et ce
    # test ne doit pas dependre de ce que le poste a deja achete.
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "donnees"))

    def construire(*a, cost=None, **k):
        cost.add_llm("claude-sonnet-5", 6000, 8750)    # l'appel Anthropic est revenu
        raise exception

    monkeypatch.setattr(cli, "construire_rapport", construire)
    sortie = tmp_path / "r.json"
    code = cli.main(["--xlsx", str(_classeur(tmp_path)), "--out", str(sortie)])
    return code, sortie, capsys.readouterr()


def test_un_run_qui_LEVE_apres_avoir_paye_laisse_un_rapport(tmp_path, monkeypatch, capsys):
    code, sortie, _ = _lancer(tmp_path, monkeypatch, capsys,
                              AttributeError("'str' object has no attribute 'get'"))
    assert sortie.exists(), "le run a payé : le rapport doit exister"
    r = json.loads(sortie.read_text(encoding="utf-8"))
    assert r["porte_franchie"] is False and r["porte_indecidable"] is True
    assert any("AttributeError" in a for a in r["avertissements"])
    assert code == 4


def test_le_cout_deja_engage_est_DIT_a_l_ecran_et_dans_le_rapport(
        tmp_path, monkeypatch, capsys):
    from cost_tracker import llm_cost_usd
    _, sortie, sorties = _lancer(tmp_path, monkeypatch, capsys, AttributeError("x"))
    attendu = f"{llm_cost_usd('claude-sonnet-5', 6000, 8750):.4f}"
    assert attendu in sorties.out
    r = json.loads(sortie.read_text(encoding="utf-8"))
    assert any(attendu in a for a in r["avertissements"])


def test_le_rapport_d_echec_ne_conseille_PAS_les_criteres(tmp_path, monkeypatch, capsys):
    _, _, sorties = _lancer(tmp_path, monkeypatch, capsys, AttributeError("x"))
    assert "corriger data/lowcontent_criteres.json" not in sorties.out
    assert "INDÉCIDABLE" in sorties.out


def test_un_CTRL_C_apres_paiement_laisse_aussi_un_rapport(tmp_path, monkeypatch, capsys):
    """Couper la console pendant le batch ASIN brûle 0,558 $ sans rien mettre en cache :
    c'est le cas où la trace compte le plus. Encadré pour qu'un Ctrl-C qui traverserait la
    CLI ne coupe pas toute la suite pytest."""
    try:
        code, sortie, _ = _lancer(tmp_path, monkeypatch, capsys, KeyboardInterrupt())
    except KeyboardInterrupt:
        pytest.fail("le Ctrl-C a traversé la CLI sans laisser de rapport")
    assert sortie.exists()
    assert code == 130
