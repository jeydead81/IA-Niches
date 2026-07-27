"""test_kdp_keywords.py — les 7 mots-clés backend KDP.

Les contraintes de KDP sont DURES (7 emplacements, 50 caractères, termes proscrits) et un
modèle les oublie sous pression : elles sont donc vérifiées côté code, comme la taxonomie
l'est dans fiction_ideator."""
from kdp_keywords import LIMITE_CARACTERES, TERMES_INTERDITS, nettoyer_candidats


def test_un_emplacement_ne_depasse_jamais_50_caracteres():
    """Contrainte dure de KDP : au-delà, Amazon tronque en SILENCE et l'auteur perd la fin
    de son expression sans jamais le savoir."""
    gardes, rejets = nettoyer_candidats(["a" * 60, "roman policier village breton"], titre="")
    assert all(len(k) <= LIMITE_CARACTERES for k in gardes)
    assert "roman policier village breton" in gardes
    assert any("50" in motif for _, motif in rejets)


def test_les_termes_interdits_par_kdp_sont_ecartes():
    """« livre », « kindle », « gratuit », « meilleur »… sont proscrits par les conditions
    KDP ou déjà indexés par Amazon. Les demander au prompt ne suffit pas."""
    gardes, rejets = nettoyer_candidats(
        ["meilleur livre policier", "kindle gratuit", "enquête village breton"], titre="")
    assert gardes == ["enquête village breton"]
    assert len(rejets) == 2


def test_les_mots_du_titre_ne_sont_pas_regaspilles():
    """Amazon indexe déjà titre et sous-titre : redonner ces mots gâche un emplacement sur
    les sept, qui sont la ressource rare."""
    gardes, _ = nettoyer_candidats(
        ["cosy mystery bretagne", "enquête pâtissière village"],
        titre="Cosy Mystery en Bretagne")
    assert gardes == ["enquête pâtissière village"]


def test_les_doublons_la_casse_et_les_espaces_sont_normalises():
    gardes, _ = nettoyer_candidats(
        ["Enquête Village", "enquête village", "  enquête   village  "], titre="")
    assert len(gardes) == 1


def test_chaque_rejet_porte_son_motif():
    """Un mot-clé écarté sans explication est une décision invisible (CLAUDE.md §10)."""
    _, rejets = nettoyer_candidats(["meilleur livre"], titre="")
    assert rejets and all(isinstance(m, str) and m for _, m in rejets)


def test_les_termes_interdits_sont_documentes_et_non_vides():
    assert "livre" in TERMES_INTERDITS and "kindle" in TERMES_INTERDITS


# ── Génération + confirmation gratuite par l'autocomplete (K2) ──────────────────────

from kdp_keywords import N_EMPLACEMENTS, generer_mots_cles          # noqa: E402
from models import ScoredNiche                                       # noqa: E402


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


def _niche(titre=""):
    return ScoredNiche(niche="cosy mystery breton", requete_amazon="cosy mystery breton",
                       categorie="policier", satellite_keywords=["enquête village"],
                       global_score=7.5)


def test_les_mots_confirmes_par_amazon_passent_devant():
    """LE point du module : un mot-clé qu'Amazon ne complète pas est un mot-clé que
    personne ne tape. La sonde est gratuite — on ne devine pas, on vérifie. C'est ce
    qu'aucun outil concurrent ne fait."""
    def fausse_sonde(prefixe):
        return ["enquête village breton", "enquête village breton tome 2"] \
            if "village breton" in prefixe else []

    # 9 candidats pour dépasser les 7 emplacements : c'est là que l'ordre se voit.
    candidats = [f"expression sans echo {i}" for i in range(8)] + ["enquête village breton"]
    r = generer_mots_cles(_niche(), client=_Client({"candidats": candidats}),
                          sonde=fausse_sonde)
    assert r.emplacements[0] == "enquête village breton"   # le confirmé passe devant
    assert r.confirmes_par_amazon == ["enquête village breton"]
    assert len(r.emplacements) == N_EMPLACEMENTS
    # Les non confirmés ne sont pas jetés : ils remplissent les emplacements restants
    # (un emplacement vide est une perte sèche), le surplus part à vérifier à la main.
    assert r.a_verifier and all(a.startswith("expression") for a in r.a_verifier)


def test_sept_emplacements_maximum():
    """KDP n'en offre que sept : en rendre plus donnerait à l'auteur l'illusion d'un
    choix qu'il n'a pas."""
    r = generer_mots_cles(_niche(),
                          client=_Client({"candidats": [f"expression numero {i}" for i in range(30)]}),
                          sonde=lambda p: [p])
    assert len(r.emplacements) == N_EMPLACEMENTS


def test_les_rejets_sont_expliques_pas_silencieux():
    r = generer_mots_cles(_niche(), client=_Client({"candidats": ["meilleur livre kindle"]}),
                          sonde=lambda p: [])
    assert r.rejetes and r.rejetes[0]["motif"]


def test_une_sonde_en_echec_ne_coule_pas_la_generation():
    """L'autocomplete peut tomber. On rend alors des candidats NON confirmés plutôt que
    rien — mais en le disant, sinon une panne se lirait comme « aucun mot ne marche »."""
    def sonde_ko(prefixe):
        raise RuntimeError("réseau")

    r = generer_mots_cles(_niche(), client=_Client({"candidats": ["enquête village breton"]}),
                          sonde=sonde_ko)
    assert r.emplacements == ["enquête village breton"]
    assert r.confirmes_par_amazon == []
    assert r.sonde_indisponible is True


def test_tool_use_force_et_cout_remonte():
    vus = []
    c = _Client({"candidats": ["enquête village breton"]},
                usage=type("U", (), {"input_tokens": 900, "output_tokens": 300})())
    generer_mots_cles(_niche(), client=c, sonde=lambda p: [p],
                      on_usage=lambda i, o, m: vus.append((i, o, m)))
    assert c.vu["tool_choice"] == {"type": "tool", "name": "proposer_mots_cles"}
    assert vus == [(900, 300, c.vu["model"])]


def test_la_sonde_porte_sur_l_AMORCE_pas_sur_l_expression_entiere():
    """L'autocomplete Amazon est PRÉFIXE-based : mesuré en M3, une expression longue et
    précise ne remonte jamais rien. Sonder « gérer ses émotions négatives » en entier
    garantit un zéro, alors que « gérer ses émotions » est une vraie voie de recherche.
    Vérifié en live : sonder l'expression complète donnait 0 confirmation sur 7."""
    sondes = []

    def espionne(prefixe):
        sondes.append(prefixe)
        return ["gérer ses émotions au travail"] if prefixe == "gérer ses émotions" else []

    r = generer_mots_cles(_niche(),
                          client=_Client({"candidats": ["gérer ses émotions négatives"]}),
                          sonde=espionne)
    assert sondes == ["gérer ses émotions"]          # 3 premiers mots, pas les 4
    assert r.confirmes_par_amazon == ["gérer ses émotions négatives"]


def test_une_expression_courte_est_sondee_telle_quelle():
    sondes = []
    generer_mots_cles(_niche(), client=_Client({"candidats": ["philosophie stoïcienne"]}),
                      sonde=lambda p: sondes.append(p) or [])
    assert sondes == ["philosophie stoïcienne"]
