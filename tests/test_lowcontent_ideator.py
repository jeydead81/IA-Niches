"""Ideator low-content : le LLM CLASSE des requêtes réelles, il n'en invente pas.

C'est le renversement du chunk, et il tient dans une phrase : en mode classement, le
modèle reçoit des requêtes qu'Amazon complète déjà, et son travail est de leur attribuer
un format, un thème et un public. Il ne peut pas inventer une demande qui n'existe pas —
la demande est acquise avant qu'il ne parle.

Le mode idéation reste, pour la graine vide (« à partir de rien »). Là, le modèle propose,
et l'orchestrateur ira vérifier auprès d'Amazon (E6) : la demande y est une HYPOTHÈSE,
et `source="ideation"` le dit jusque dans le rapport.

Deux garde-fous côté CODE, parce que §4.2 est formel — ce qui n'est pas doublé en code est
une intention, pas une règle :
- une clé de format hallucinée est REMAPPÉE en `other`, jamais devinée ni levée ;
- le filtre IP est rejoué APRÈS le modèle, et surtout appliqué AVANT l'appel.
"""
import pytest

from lowcontent_ideator import generate_lowcontent_niches
from autocomplete_expand import Suggestion


class _FauxBloc:
    type = "tool_use"

    def __init__(self, payload):
        self.input = payload


class _FauxUsage:
    input_tokens = 1200
    output_tokens = 800


class _FauxReponse:
    def __init__(self, payload):
        self.content = [_FauxBloc(payload)]
        self.usage = _FauxUsage()


class _FauxClient:
    """Capture ce qui est ENVOYÉ au modèle : c'est ce qui permet de vérifier qu'une niche
    filtrée n'a jamais coûté un token."""

    def __init__(self, payload):
        self.payload = payload
        self.appels = []
        self.messages = self

    def create(self, **kw):
        self.appels.append(kw)
        return _FauxReponse(self.payload)

    @property
    def prompt_envoye(self) -> str:
        return " ".join(m["content"] for a in self.appels for m in a["messages"])


def _sugg(requete, profondeur=2, n_enfants=3):
    return Suggestion(requete=requete, parent="carnet", profondeur=profondeur,
                      n_enfants=n_enfants)


def _payload(*niches):
    return {"niches": list(niches)}


# ── Mode classement ────────────────────────────────────────────────────────────

def test_la_requete_reelle_est_reprise_telle_quelle():
    """Le modèle classe, il ne réécrit pas. Reformuler la requête perdrait la seule chose
    qu'on sait avec certitude : que celle-ci est réellement tapée."""
    client = _FauxClient(_payload({
        "requete_amazon": "carnet de suivi glycemie diabete type 2",
        "format_cle": "journal_suivi", "theme": "glycémie", "public": "adulte",
        "niche": "carnet de suivi glycémie", "rationale": "traîne réelle",
        "categorie": "santé", "risques": []}))
    out = generate_lowcontent_niches(
        seed="carnet", suggestions=[_sugg("carnet de suivi glycemie diabete type 2")],
        client=client)
    assert len(out) == 1
    assert out[0].requete_amazon == "carnet de suivi glycemie diabete type 2"
    assert out[0].source == "autocomplete"


def test_la_position_dans_l_arbre_est_recopiee_pas_recalculee():
    """`profondeur` et `n_enfants` sont des MESURES faites par l'arbre. Laisser le modèle
    les produire reviendrait à lui demander d'inventer un signal."""
    client = _FauxClient(_payload({
        "requete_amazon": "carnet de suivi glycemie diabete type 2",
        "format_cle": "journal_suivi", "theme": "glycémie", "public": "adulte",
        "niche": "n", "rationale": "r", "categorie": "santé",
        "profondeur_autocomplete": 99, "n_enfants_autocomplete": 99}))
    out = generate_lowcontent_niches(
        seed="carnet",
        suggestions=[_sugg("carnet de suivi glycemie diabete type 2", 2, 4)],
        client=client)
    assert out[0].profondeur_autocomplete == 2 and out[0].n_enfants_autocomplete == 4


def test_une_cle_de_format_hallucinee_est_remappee_en_other():
    """Ni exception, ni format deviné. Deviner ferait porter à la niche une faisabilité
    calculée sur un format qui n'est pas le sien ; lever perdrait toute la requête."""
    client = _FauxClient(_payload({
        "requete_amazon": "carnet de rituels lunaires",
        "format_cle": "grimoire_astral", "theme": "ésotérisme", "public": "adulte",
        "niche": "n", "rationale": "r", "categorie": "ésotérisme"}))
    out = generate_lowcontent_niches(seed="carnet",
                                     suggestions=[_sugg("carnet de rituels lunaires")],
                                     client=client)
    assert out[0].format_cle == "other"
    assert out[0].other_libelle == "grimoire_astral"


def test_un_public_hors_liste_est_neutralise_pas_rejete():
    """Le public est une facette de confort. Rejeter la niche entière pour un public mal
    orthographié jetterait une requête réelle pour une étiquette."""
    client = _FauxClient(_payload({
        "requete_amazon": "carnet de suivi glycemie senior",
        "format_cle": "journal_suivi", "theme": "glycémie", "public": "les vieux",
        "niche": "n", "rationale": "r", "categorie": "santé"}))
    out = generate_lowcontent_niches(seed="carnet",
                                     suggestions=[_sugg("carnet de suivi glycemie senior")],
                                     client=client)
    assert len(out) == 1 and out[0].public == ""


def test_les_doublons_de_requete_sont_ecartes():
    client = _FauxClient(_payload(
        {"requete_amazon": "carnet suivi glycemie", "format_cle": "journal_suivi",
         "theme": "t", "public": "adulte", "niche": "n", "rationale": "r",
         "categorie": "c"},
        {"requete_amazon": "Carnet Suivi Glycémie", "format_cle": "journal_suivi",
         "theme": "t", "public": "adulte", "niche": "n", "rationale": "r",
         "categorie": "c"}))
    out = generate_lowcontent_niches(seed="carnet",
                                     suggestions=[_sugg("carnet suivi glycemie")],
                                     client=client)
    assert len(out) == 1


def test_n_est_un_plafond_reel():
    """Les dix requêtes rendues sont des requêtes DONNÉES au modèle. L'ancienne fixture n'en
    donnait qu'une (« carnet ») et en recevait dix autres : elle ne testait le plafond qu'en
    violant le contrat du module, et elle a cessé de passer le jour où ce contrat a été
    imposé en code plutôt que seulement demandé au prompt (§4.2)."""
    sugg = [_sugg(f"carnet suivi {i}") for i in range(10)]
    client = _FauxClient(_payload(*[
        {"requete_amazon": f"carnet suivi {i}", "format_cle": "journal_suivi",
         "theme": "t", "public": "adulte", "niche": f"n{i}", "rationale": "r",
         "categorie": "c"} for i in range(10)]))
    out = generate_lowcontent_niches(seed="carnet", suggestions=sugg, n=3, client=client)
    assert len(out) == 3


# ── Le filtre IP tourne AVANT l'appel ──────────────────────────────────────────

def test_une_suggestion_sous_marque_ne_coute_aucun_token():
    """LE test du module. Le filtre IP est rejoué après le modèle, mais surtout appliqué
    AVANT : sans ça on paierait des tokens pour classer « coloriage pat patrouille » et
    on le verrait revenir dans le rapport."""
    client = _FauxClient(_payload())
    generate_lowcontent_niches(
        seed="coloriage",
        suggestions=[_sugg("coloriage pat patrouille"), _sugg("coloriage licorne 3 ans")],
        client=client)
    envoye = client.prompt_envoye.lower()
    assert "pat patrouille" not in envoye
    assert "licorne" in envoye


def test_une_marque_qui_repasse_dans_la_reponse_est_rejouee():
    """Le modèle peut réintroduire une marque de lui-même. Le filtre tourne donc des DEUX
    côtés de l'appel.

    Testé en mode IDÉATION, le seul où ce rejeu est la dernière barrière. En mode
    classement, une requête réécrite en « coloriage disney princesses » n'est plus une des
    requêtes données : elle est écartée plus tôt, comme inventée, et ce test passerait au
    vert sans jamais atteindre le filtre qu'il prétend vérifier. D'où l'assertion sur le
    MOTIF, et pas seulement sur la liste vide."""
    etapes = []
    client = _FauxClient(_payload({
        "requete_amazon": "coloriage disney princesses", "format_cle": "coloriage_enfant",
        "theme": "princesses", "public": "enfant_3_6", "niche": "n", "rationale": "r",
        "categorie": "c"}))
    out = generate_lowcontent_niches(seed=None, client=client, progress=etapes.append)
    assert out == []
    assert any("marque" in e for e in etapes), "écartée, mais pas par le filtre IP"


def test_le_saisonnier_est_ecarte_sauf_opt_in():
    """Un carnet de Noël se vend six semaines par an. L'auteur doit le demander
    explicitement, pas le découvrir après publication."""
    sugg = [_sugg("carnet de noel a completer")]
    client = _FauxClient(_payload())
    generate_lowcontent_niches(seed="carnet", suggestions=sugg, client=client)
    assert "noel" not in client.prompt_envoye.lower()

    client2 = _FauxClient(_payload())
    generate_lowcontent_niches(seed="carnet", suggestions=sugg, client=client2,
                               inclure_saisonnier=True)
    assert "noel" in client2.prompt_envoye.lower()


def test_les_rejets_sont_annonces_avec_leur_motif():
    """Un rejet muet ferait passer un filtrage pour un rayon vide (règle 3)."""
    etapes = []
    client = _FauxClient(_payload())
    generate_lowcontent_niches(seed="coloriage",
                               suggestions=[_sugg("coloriage pat patrouille")],
                               client=client, progress=etapes.append)
    msg = " ".join(etapes).lower()
    assert "pat patrouille" in msg or "marque" in msg


def test_sans_aucune_suggestion_survivante_aucun_appel_n_est_paye():
    """Toutes les suggestions filtrées = rien à classer. Appeler le modèle sur une liste
    vide serait payer pour rien."""
    client = _FauxClient(_payload())
    out = generate_lowcontent_niches(seed="coloriage",
                                     suggestions=[_sugg("coloriage pokemon")],
                                     client=client)
    assert out == [] and client.appels == []


# ── Mode idéation ──────────────────────────────────────────────────────────────

def test_sans_suggestions_le_mode_ideation_marque_la_source():
    """« ideation » dit que la demande est une HYPOTHÈSE, pas une observation. C'est ce
    qui empêche de lire un trio inventé comme une requête mesurée."""
    client = _FauxClient(_payload({
        "requete_amazon": "carnet de suivi migraine", "format_cle": "journal_suivi",
        "theme": "migraine", "public": "adulte", "niche": "n", "rationale": "r",
        "categorie": "santé"}))
    out = generate_lowcontent_niches(seed=None, client=client)
    assert out[0].source == "ideation"
    assert out[0].profondeur_autocomplete == 0


def test_le_format_impose_est_verifie_apres_le_modele():
    """Comme pour les contraintes de trio fiction : on demande au prompt, puis on
    contrôle. Rendre une niche hors format, c'est répondre à côté de la question."""
    client = _FauxClient(_payload(
        {"requete_amazon": "carnet suivi tension", "format_cle": "journal_suivi",
         "theme": "tension", "public": "adulte", "niche": "n", "rationale": "r",
         "categorie": "c"},
        {"requete_amazon": "mots meles seniors", "format_cle": "mots_meles",
         "theme": "seniors", "public": "senior", "niche": "n", "rationale": "r",
         "categorie": "c"}))
    out = generate_lowcontent_niches(seed=None, format_cle="journal_suivi", client=client)
    assert [n.format_cle for n in out] == ["journal_suivi"]


def test_un_format_impose_inconnu_leve():
    """La liste des formats est peuplée depuis la taxo : une clé inconnue ne peut venir
    que d'une requête forgée. L'ignorer ferait croire à l'auteur que sa contrainte est
    appliquée."""
    with pytest.raises(ValueError):
        generate_lowcontent_niches(seed=None, format_cle="grimoire",
                                   client=_FauxClient(_payload()))


def test_le_cout_est_impute_a_l_appelant():
    vues = []
    client = _FauxClient(_payload())
    generate_lowcontent_niches(seed=None, client=client,
                               on_usage=lambda i, o, m: vues.append((i, o, m)))
    assert vues and vues[0][0] == 1200 and vues[0][1] == 800


def test_le_prompt_declare_les_requetes_comme_des_donnees():
    """Les requêtes viennent d'Amazon, donc de tiers. Même garde qu'au verdict et au
    classifieur fiction."""
    from lowcontent_ideator import SYSTEM_PROMPT
    p = SYSTEM_PROMPT.lower()
    assert "données" in p and "jamais des instructions" in p
