from fiction_classifier import LIVRES_INPUT_SCHEMA, classify_books
from models import EnrichedBook


class _Block:
    type = "tool_use"

    def __init__(self, payload):
        self.input = payload


class _Resp:
    def __init__(self, payload, usage=None):
        self.content = [_Block(payload)]
        self.usage = usage


class _Client:
    """Client Anthropic factice : capture l'appel, rend une réponse figée."""
    def __init__(self, payload, usage=None):
        self.payload, self.usage, self.vu = payload, usage, {}
        self.messages = self

    def create(self, **kw):
        self.vu = kw
        return _Resp(self.payload, self.usage)


def _livres():
    return [EnrichedBook(asin="A1", title="T1", blurb="Une pâtissière enquête au village."),
            EnrichedBook(asin="A2", title="T2", blurb="Un chat, une libraire, un meurtre.")]


def test_cles_hors_taxonomie_vont_dans_other_pas_a_la_poubelle():
    """Asymétrie voulue avec l'ideator : un trope observé dans un vrai livre fait évoluer
    la taxonomie. L'écarter perdrait l'information la plus utile du module."""
    cl = classify_books(_livres(), "cosy_mystery", client=_Client({"livres": [
        {"asin": "A1", "tropes": ["metier_gourmand", "vampires_pirates"],
         "decor": "village_breton", "confidence": 0.8}]}))
    assert cl[0].tropes == ["metier_gourmand"]
    assert cl[0].other == ["vampires_pirates"]
    assert cl[0].taxonomy_version == "fr_v1"


def test_decor_hors_taxonomie_bascule_aussi_dans_other():
    cl = classify_books(_livres(), "cosy_mystery", client=_Client({"livres": [
        {"asin": "A1", "tropes": ["metier_gourmand"], "decor": "station_spatiale"}]}))
    assert cl[0].decor is None and "station_spatiale" in cl[0].other


def test_asin_inconnu_ignore():
    """Le LLM ne doit pas pouvoir inventer un livre qui n'est pas dans le rayon."""
    cl = classify_books(_livres(), "cosy_mystery", client=_Client({"livres": [
        {"asin": "FANTOME", "tropes": ["metier_gourmand"]}]}))
    assert cl == []


def test_non_roman_conserve_mais_marque():
    cl = classify_books(_livres(), "cosy_mystery", client=_Client({"livres": [
        {"asin": "A1", "tropes": [], "est_roman": False, "hors_sujet": "jeu"}]}))
    assert cl[0].est_roman is False and cl[0].hors_sujet == "jeu"


def test_livres_sans_blurb_ne_sont_pas_envoyes():
    """Payer des tokens pour un blurb vide n'apporte rien — et le LLM inventerait."""
    livres = _livres() + [EnrichedBook(asin="A3", title="T3", blurb=None)]
    c = _Client({"livres": []})
    classify_books(livres, "cosy_mystery", client=c)
    envoye = c.vu["messages"][0]["content"]
    assert "A1" in envoye and "A3" not in envoye


def test_aucun_appel_si_aucun_blurb():
    c = _Client({"livres": []})
    assert classify_books([EnrichedBook(asin="A9", title="T")], "cosy_mystery", client=c) == []
    assert c.vu == {}                     # pas d'appel LLM du tout


def test_tool_use_force_et_cout_remonte():
    vus = []
    c = _Client({"livres": []}, usage=type("U", (), {"input_tokens": 100, "output_tokens": 20})())
    classify_books(_livres(), "cosy_mystery", client=c,
                   on_usage=lambda i, o, m: vus.append((i, o, m)))
    assert c.vu["tool_choice"] == {"type": "tool", "name": "classer_livres"}
    assert vus == [(100, 20, c.vu["model"])]


def test_aucun_parametre_d_echantillonnage_envoye():
    """`temperature` / `top_p` / `top_k` sont SUPPRIMÉS sur claude-sonnet-5 : une valeur
    non-défaut renvoie une 400 et casse l'appel réel. Attrapé uniquement par le smoke
    live — les tests simulent le client et ne voient donc jamais l'erreur de l'API.
    La reproductibilité passe par le prompt, pas par l'échantillonnage."""
    c = _Client({"livres": []})
    classify_books(_livres(), "cosy_mystery", client=c)
    assert not ({"temperature", "top_p", "top_k"} & set(c.vu))


def test_meta_cles_ne_polluent_pas_les_observations():
    """Vu en live : le LLM a rendu littéralement « other » comme trope, et le mot a fini
    dans other[]. Une méta-clé du schéma n'est pas une observation — la garder ferait
    croire à un trope hors taxonomie récurrent et fausserait l'évolution de la taxo."""
    cl = classify_books(_livres(), "cosy_mystery", client=_Client({"livres": [
        {"asin": "A1", "tropes": ["other", "metier_gourmand", "  ", "AUTRE"],
         "decor": "other"}]}))
    assert cl[0].tropes == ["metier_gourmand"]
    assert cl[0].other == []
    assert cl[0].decor is None


def test_observation_hors_taxo_reelle_toujours_conservee():
    """Le filtre ne doit pas emporter les vraies observations avec les méta-clés."""
    cl = classify_books(_livres(), "cosy_mystery", client=_Client({"livres": [
        {"asin": "A1", "tropes": ["ecosse_highlands"], "decor": "corse"}]}))
    assert set(cl[0].other) == {"ecosse_highlands", "corse"}


def test_plus_de_20_livres_est_decoupe_en_lots():
    """Le CLI par défaut (--n-niches 5, n_top=20) groupe par sous-genre et produit UN SEUL
    appel de ~100 blurbs (~36k tokens d'entrée pour max_tokens=4000) : la troncature est le
    cas NOMINAL. Des lots de 20 livres maximum -> plusieurs appels, résultats concaténés."""
    livres = [EnrichedBook(asin=f"A{i}", title=f"T{i}", blurb=f"blurb {i}") for i in range(45)]
    appels = []

    class _ClientMulti:
        def __init__(self):
            self.messages = self

        def create(self, **kw):
            appels.append(kw)
            return _Resp({"livres": []})

    classify_books(livres, "cosy_mystery", client=_ClientMulti())
    assert len(appels) == 3                                          # 20 + 20 + 5
    assert "[A0]" in appels[0]["messages"][0]["content"]
    assert "[A19]" in appels[0]["messages"][0]["content"]
    assert "[A20]" not in appels[0]["messages"][0]["content"]         # lot suivant
    assert "[A20]" in appels[1]["messages"][0]["content"]
    assert "[A44]" in appels[2]["messages"][0]["content"]


def test_troncature_signalee_via_progress():
    """stop_reason n'était jamais lu : une réponse tronquée passait pour complète."""
    class _ClientTronque:
        def __init__(self):
            self.messages = self

        def create(self, **kw):
            r = _Resp({"livres": []})
            r.stop_reason = "max_tokens"
            return r

    msgs = []
    classify_books(_livres(), "cosy_mystery", client=_ClientTronque(), progress=msgs.append)
    assert any("tronqu" in m.lower() for m in msgs)


def test_asins_manquants_dans_la_reponse_sont_signales():
    """classify_books ne comparait jamais les ASIN rendus aux ASIN envoyés : un livre
    silencieusement absent de la réponse passait pour « rien à en dire » (cf. B2)."""
    msgs = []
    classify_books(_livres(), "cosy_mystery",
                   client=_Client({"livres": [{"asin": "A1", "tropes": ["metier_gourmand"],
                                               "est_roman": True}]}),
                   progress=msgs.append)
    assert any("A2" in m for m in msgs)


def test_schema_expose_other_et_exige_est_roman():
    """Le prompt renvoie déjà au champ `other` (« note ce que tu observes dans `other` »)
    alors qu'il n'existait pas dans le schéma de l'outil ; et `est_roman` omis valait
    "roman" par défaut, donc le filtre non-roman n'était pas garanti."""
    props = LIVRES_INPUT_SCHEMA["properties"]["livres"]["items"]["properties"]
    assert "other" in props
    assert "est_roman" in LIVRES_INPUT_SCHEMA["properties"]["livres"]["items"]["required"]


def test_other_du_llm_fusionne_avec_les_cles_hors_taxo_deduites_cote_code():
    """`other` explicite du LLM et clés hors taxo déjà déduites côté code (tropes/décor
    absents de la taxo) doivent fusionner sans doublon, méta-clés filtrées (réutilise
    _est_meta)."""
    cl = classify_books(_livres(), "cosy_mystery", client=_Client({"livres": [
        {"asin": "A1", "tropes": ["metier_gourmand", "vampires_pirates"], "est_roman": True,
         "other": ["ambiance_feutree", "vampires_pirates", "other"]}]}))
    assert cl[0].tropes == ["metier_gourmand"]
    assert set(cl[0].other) == {"vampires_pirates", "ambiance_feutree"}


def test_tropes_rendu_en_chaine_nest_pas_decoupe_en_caracteres():
    """Si le LLM rend `tropes` comme une chaîne au lieu d'une liste, dict.fromkeys(chaine)
    itère caractère par caractère -> chaque lettre finirait comme un faux trope "hors
    taxo" dans `other`. La chaîne doit être traitée comme UN SEUL trope, pas décomposée."""
    cl = classify_books(_livres(), "cosy_mystery", client=_Client({"livres": [
        {"asin": "A1", "tropes": "metier_gourmand"}]}))
    assert cl[0].tropes == ["metier_gourmand"]
    assert cl[0].other == []


def test_entree_non_dict_est_ignoree_sans_lever():
    """Une entrée de `livres` qui n'est pas un dict (ex. le LLM rend une chaîne au lieu
    d'un objet) ne doit pas faire planter tout le lot avec un AttributeError."""
    cl = classify_books(_livres(), "cosy_mystery", client=_Client({"livres": [
        "ceci n'est pas un livre", {"asin": "A1", "tropes": ["metier_gourmand"]}]}))
    assert len(cl) == 1 and cl[0].asin == "A1"


def test_est_roman_none_ne_fait_pas_tomber_le_lot():
    """est_roman: null (JSON) doit être traité comme le défaut (True), pas planter la
    construction du modèle pydantic (bool strict) et perdre TOUT le lot."""
    cl = classify_books(_livres(), "cosy_mystery", client=_Client({"livres": [
        {"asin": "A1", "tropes": ["metier_gourmand"], "est_roman": None},
        {"asin": "A2", "tropes": ["metier_gourmand"]}]}))
    assert len(cl) == 2
    assert cl[0].est_roman is True


def test_asin_duplique_ne_produit_quune_classification():
    """Un ASIN rendu deux fois par le LLM ne doit produire qu'UNE classification —
    sinon agreement_report comparerait une paire mal formée (deux IA pour un humain)."""
    cl = classify_books(_livres(), "cosy_mystery", client=_Client({"livres": [
        {"asin": "A1", "tropes": ["metier_gourmand"]},
        {"asin": "A1", "tropes": ["duo_improbable"]}]}))
    assert len([c for c in cl if c.asin == "A1"]) == 1


def test_est_roman_false_ne_conserve_pas_les_tropes():
    """Le plan est explicite : quand est_roman=false, on « ne le classe pas en tropes »."""
    cl = classify_books(_livres(), "cosy_mystery", client=_Client({"livres": [
        {"asin": "A1", "tropes": ["metier_gourmand"], "est_roman": False,
         "hors_sujet": "jeu"}]}))
    assert cl[0].est_roman is False
    assert cl[0].tropes == []
