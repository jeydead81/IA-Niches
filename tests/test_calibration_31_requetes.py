"""Ce que 31 requêtes déclenchent et que 12 ne déclenchaient jamais.

Le moteur low-content a été construit et testé pour 6 à 12 niches par run. Le jeu de
calibration de Baptiste en envoie 31 d'un coup, écrites comme on les tape — sans accent
(« vehicule », « tresor », « enquete »), avec des apostrophes. Relu AVANT le run payant, il a
fait apparaître cinq défauts, tous silencieux :

1. **La requête n'était pas forcée verbatim.** Le prompt demande au modèle de la recopier
   « EXACTEMENT », mais le code gardait le texte qu'il rendait. Un modèle qui corrige
   « tresor » en « trésor » faisait sortir la requête de l'appariement : elle remontait comme
   « écartée avant analyse », donc un faux négatif attribué au gate gratuit qui n'y était
   pour rien. §4.2 : ce qui n'est pas doublé en code est une intention, pas une règle.
2. **Une requête inventée en mode classement était gardée**, avec `source="autocomplete"` —
   une demande inventée présentée comme observée. C'est la chose que ce mode existe pour
   empêcher.
3. **`max_tokens=4000` fixe et `stop_reason` jamais lu.** À ~130 jetons par niche, 31 niches
   touchent le plafond : la réponse est tronquée, les dernières niches disparaissent, et rien
   ne le dit.
4. **`n_ideas` (12) plafonnait la shortlist en silence.** Un client qui demande 20 recherches
   en obtient 12 — le contraire exact de `_borner`, qui refuse plutôt que de rogner.
5. **La CLI plantait APRÈS la dépense et AVANT d'écrire le rapport** : `total_usd` formaté
   comme un attribut alors que c'est une méthode, et un « 🟢 » ou un « ⚠ » imprimé sur une
   sortie cp1252 lève `UnicodeEncodeError`. Le run payé ne laissait aucune trace.

Aucun réseau : client LLM et orchestrateur injectés.
"""
import io
import json
import sys

import pytest

from autocomplete_expand import Suggestion
from lowcontent_ideator import generate_lowcontent_niches
from lowcontent_validation import RapportCalibration, exporter_gabarit


class _Bloc:
    type = "tool_use"

    def __init__(self, payload):
        self.input = payload


class _Usage:
    input_tokens = 1000
    output_tokens = 900


class _Reponse:
    def __init__(self, payload, stop_reason):
        self.content = [_Bloc(payload)]
        self.usage = _Usage()
        self.stop_reason = stop_reason


class _Client:
    def __init__(self, payload, stop_reason="tool_use"):
        self.payload, self.stop_reason = payload, stop_reason
        self.appels = []
        self.messages = self

    def create(self, **kw):
        self.appels.append(kw)
        return _Reponse(self.payload, self.stop_reason)


def _sugg(requete, n_enfants=3):
    return Suggestion(requete=requete, parent="", profondeur=0, n_enfants=n_enfants)


def _niche(requete, format_cle="journal_suivi"):
    return {"requete_amazon": requete, "format_cle": format_cle, "theme": "t",
            "public": "adulte", "niche": requete, "rationale": "r", "categorie": "c"}


# ── 1. La requête est la VRAIE, pas celle que le modèle a réécrite ────────────

def test_une_requete_rendue_AVEC_accents_reprend_le_texte_reel():
    """Baptiste tape « tresor », le modèle rend « trésor ». La requête mesurée doit rester
    la sienne : c'est elle que des gens tapent, et c'est elle qu'il a étiquetée."""
    client = _Client({"niches": [_niche("livre chasse au trésor enfant")]})
    out = generate_lowcontent_niches(
        seed="x", suggestions=[_sugg("livre chasse au tresor enfant")], client=client)
    assert [n.requete_amazon for n in out] == ["livre chasse au tresor enfant"]


def test_une_apostrophe_typographique_ne_change_pas_de_requete():
    """Le modèle rend volontiers « ’ » là où la requête porte « ' ». Même requête."""
    client = _Client({"niches": [_niche("cahier d’écriture dinosaure")]})
    out = generate_lowcontent_niches(
        seed="x", suggestions=[_sugg("cahier d'écriture dinosaure")], client=client)
    assert [n.requete_amazon for n in out] == ["cahier d'écriture dinosaure"]


def test_la_mesure_de_l_arbre_suit_la_requete_recalee():
    """`n_enfants` est une MESURE faite par l'arbre. Une requête retrouvée malgré ses accents
    doit la garder — la perdre la ferait retomber à 0, qui se lit « personne n'affine »."""
    client = _Client({"niches": [_niche("livre enquête enfant 9 ans")]})
    out = generate_lowcontent_niches(
        seed="x", suggestions=[_sugg("livre enquete enfant 9 ans", n_enfants=5)],
        client=client)
    assert out[0].n_enfants_autocomplete == 5


# ── 2. En mode classement, le modèle n'invente rien ────────────────────────────

def test_une_requete_INVENTEE_en_mode_classement_est_ecartee_et_annoncee():
    """LE test du lot. Le mode classement n'a qu'une promesse : la demande est acquise
    AVANT que le modèle parle. Une requête qu'on ne lui a pas donnée est une demande
    inventée ; la garder avec `source="autocomplete"` la présenterait comme observée."""
    etapes = []
    client = _Client({"niches": [_niche("carnet de suivi migraine"),
                                 _niche("carnet de suivi tension artérielle")]})
    out = generate_lowcontent_niches(
        seed="x", suggestions=[_sugg("carnet de suivi migraine")], client=client,
        progress=etapes.append)
    assert [n.requete_amazon for n in out] == ["carnet de suivi migraine"]
    assert any("tension" in e for e in etapes), "l'écart doit être annoncé"


def test_en_mode_IDEATION_les_requetes_du_modele_restent_les_siennes():
    """Sans graine, il n'y a pas de liste de référence : le modèle propose, et
    `source="ideation"` dit que la demande est une hypothèse. Rien à recaler."""
    client = _Client({"niches": [_niche("carnet de suivi migraine")]})
    out = generate_lowcontent_niches(seed=None, client=client)
    assert out[0].requete_amazon == "carnet de suivi migraine"
    assert out[0].source == "ideation"


# ── 3. Le budget de réponse suit le volume, et une troncature se dit ───────────

def test_le_budget_de_reponse_suit_le_nombre_de_niches_demandees():
    sugg = [_sugg(f"carnet de suivi numero {i}") for i in range(31)]
    grand, petit = _Client({"niches": []}), _Client({"niches": []})
    generate_lowcontent_niches(seed="x", suggestions=sugg, n=31, client=grand)
    generate_lowcontent_niches(seed="x", suggestions=sugg[:6], n=6, client=petit)
    assert petit.appels[0]["max_tokens"] >= 4000, "le défaut des petits runs ne baisse pas"
    assert grand.appels[0]["max_tokens"] >= 31 * 200


def test_une_reponse_TRONQUEE_est_annoncee_pas_avalee():
    """Même règle que le classifieur fiction : les niches coupées ne reviennent pas, et ne
    pas le dire ferait lire une troncature comme un rayon qui n'a rien donné."""
    etapes = []
    client = _Client({"niches": [_niche("carnet de suivi migraine")]}, stop_reason="max_tokens")
    generate_lowcontent_niches(
        seed="x", suggestions=[_sugg("carnet de suivi migraine"),
                               _sugg("carnet de suivi tension")],
        client=client, progress=etapes.append)
    assert any("tronqu" in e.lower() for e in etapes)


# ── 4. Le nombre de niches classées ne plafonne jamais la shortlist ───────────

def test_n_ideas_ne_plafonne_jamais_la_shortlist():
    """La shortlist est prise PARMI les niches classées : si le modèle n'en garde que 12,
    `n_search=20` ne peut pas en rendre 20. Le client qui demande 20 recherches en
    obtenait 12, sans message — le contraire exact de `_borner`, qui refuse plutôt que de
    rogner en silence."""
    from lowcontent_master import run_lowcontent_scout
    vus = {}

    def ideate(**kw):
        vus.update(kw)
        return []

    sugg = [_sugg(f"carnet de suivi numero {i}") for i in range(25)]
    run_lowcontent_scout(seed="carnet", n_search=20, use_cache=False,
                         expand_fn=lambda *a, **k: list(sugg), ideate=ideate)
    assert vus["n"] >= 20


# ── 5. La CLI laisse TOUJOURS un rapport derrière la dépense ──────────────────

def _classeur(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    chemin = exporter_gabarit(tmp_path / "v.xlsx")
    wb = openpyxl.load_workbook(chemin)
    wb.active["A7"], wb.active["C7"] = "carnet de suivi migraine", "morte"
    wb.save(chemin)
    return chemin


def _rapport_parlant():
    """Un rapport qui imprime tout ce qui ne passe pas en cp1252 : 🟢 et ⚠."""
    return RapportCalibration(n_requetes=1, n_calibrees=1, spearman=0.61,
                              morts_en_vert=["carnet de suivi migraine"],
                              avertissements=["⚠ famille sous-représentée"])


def test_le_rapport_est_ECRIT_meme_si_l_affichage_plante(tmp_path, monkeypatch):
    """L'ordre compte. Le run a coûté de l'argent réel : le JSON doit exister avant la
    moindre ligne décorative, sinon une panne d'affichage efface la seule trace du run."""
    import build_lowcontent_validation_set as cli
    # Isole le VRAI df-cache.db : la CLI chiffre desormais un devis en lisant le cache, et ce
    # test ne doit pas dependre de ce que le poste a deja achete.
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "donnees"))
    monkeypatch.setattr(cli, "construire_rapport", lambda *a, **k: _rapport_parlant())

    def plante(_r):
        raise RuntimeError("affichage en panne")

    monkeypatch.setattr(cli, "_imprimer", plante)
    sortie = tmp_path / "r.json"
    try:
        cli.main(["--xlsx", str(_classeur(tmp_path)), "--out", str(sortie)])
    except RuntimeError:
        pass
    assert json.loads(sortie.read_text(encoding="utf-8"))["n_requetes"] == 1


def test_la_CLI_passe_sur_une_sortie_cp1252_avec_un_vrai_CostTracker(tmp_path, monkeypatch):
    """Les deux pannes réelles, ensemble : `total_usd` est une MÉTHODE, et la console
    Windows redirigée encode en cp1252, où ni « 🟢 » ni « ⚠ » n'existent. Les deux levaient
    après la dépense. On passe le vrai `CostTracker` : c'est lui que le run utilisera."""
    import build_lowcontent_validation_set as cli
    # Isole le VRAI df-cache.db : la CLI chiffre desormais un devis en lisant le cache, et ce
    # test ne doit pas dependre de ce que le poste a deja achete.
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "donnees"))
    monkeypatch.setattr(cli, "construire_rapport", lambda *a, **k: _rapport_parlant())
    tampon = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", tampon)
    sortie = tmp_path / "r.json"
    code = cli.main(["--xlsx", str(_classeur(tmp_path)), "--out", str(sortie)])
    assert code in (0, 2)
    assert sortie.exists()


def test_le_filtre_saisonnier_se_leve_EXPLICITEMENT_pour_la_calibration(tmp_path, monkeypatch):
    """Le filtre saisonnier est un réglage du produit (opt-in), pas un seuil qu'on calibre.
    Une requête saisonnière étiquetée n'a de valeur pour la calibration que si elle est
    SCORÉE. Le défaut reste celui du produit ; le lever est une décision visible."""
    import build_lowcontent_validation_set as cli
    # Isole le VRAI df-cache.db : la CLI chiffre desormais un devis en lisant le cache, et ce
    # test ne doit pas dependre de ce que le poste a deja achete.
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "donnees"))
    vus = []
    monkeypatch.setattr(cli, "construire_rapport",
                        lambda *a, **k: vus.append(k) or RapportCalibration())
    classeur = _classeur(tmp_path)
    cli.main(["--xlsx", str(classeur), "--out", str(tmp_path / "a.json")])
    cli.main(["--xlsx", str(classeur), "--out", str(tmp_path / "b.json"),
              "--inclure-saisonnier"])
    assert not vus[0].get("inclure_saisonnier")
    assert vus[1].get("inclure_saisonnier") is True


def test_l_appariement_de_la_CLI_ignore_accents_casse_et_apostrophes():
    """Défense en profondeur : même si une requête revenait réécrite, l'appariement ne
    doit pas en faire une « écartée avant analyse »."""
    from build_lowcontent_validation_set import _cle
    assert _cle("livre chasse au trésor enfant") == _cle("Livre chasse au tresor enfant ")
    assert _cle("cahier d’écriture") == _cle("cahier d'ecriture")
