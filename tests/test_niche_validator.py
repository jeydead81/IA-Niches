from niche_validator import validate_niche, validate_niches
from models import NicheCandidate


def _cand(niche, sats=None, requete=None):
    return NicheCandidate(niche=niche, requete_amazon=requete or niche,
                          satellite_keywords=sats or [], rationale="r", categorie="c")


def test_validate_niche_flags_and_dedupes():
    # Amazon auto-complète tout ce qui contient "tarot", rien d'autre
    def fake(q):
        return ["tarot débutant", "tarot de marseille"] if "tarot" in q.lower() else []

    v = validate_niche(_cand("tarot", ["tarot débutant"]), fake)
    assert v.validated is True
    assert v.queries_hit == 2                 # "tarot" ET "tarot débutant" prennent
    assert v.demand_score == 2                # suggestions dédupliquées
    assert "tarot de marseille" in v.amazon_suggestions


def test_validate_niche_not_validated_when_amazon_silent():
    v = validate_niche(_cand("angleinexistantxyz", ["autre angle mort"]), lambda q: [])
    assert v.validated is False
    assert v.demand_score == 0
    assert v.queries_hit == 0
    assert v.amazon_suggestions == []


def test_validate_niches_sorts_validated_and_strong_first():
    def fake(q):
        if "fort" in q:
            return ["a", "b", "c"]
        if "faible" in q:
            return ["x"]
        return []

    out = validate_niches([_cand("faible"), _cand("nul"), _cand("fort")],
                          fetch=fake, pause=0)
    assert [v.niche for v in out] == ["fort", "faible", "nul"]
    assert out[0].demand_score == 3
    assert out[-1].validated is False


def test_validate_niche_respects_max_queries():
    calls = []

    def fake(q):
        calls.append(q)
        return ["s"]

    validate_niche(_cand("n", ["a", "b", "c", "d", "e"]), fake, max_queries=3)
    assert len(calls) == 3                     # niche + 2 satellites seulement


# ── Lecture du CONTENU des suggestions (et pas seulement de leur nombre) ─────────────

from niche_validator import SEUIL_DOMINANCE, lire_suggestions          # noqa: E402


def test_un_mot_qui_revient_dans_la_moitie_des_suggestions_est_signale():
    """Le compte de suggestions sature vite et ne dit rien de ce que les gens cherchent
    VRAIMENT. Si un mot absent de la requête revient dans la moitié des complétions,
    l'intention de recherche est concentrée dessus — typiquement un auteur ou un titre qui
    tient le rayon. On le NOMME sans prétendre savoir ce que c'est."""
    s = lire_suggestions([
        "tarot de marseille jodorowsky", "tarot jodorowsky pdf", "tarot marseille",
        "tarot jodorowsky livre", "tarot debutant"], "tarot")
    assert s["terme_dominant"] == "jodorowsky"
    assert s["part_dominante"] >= SEUIL_DOMINANCE


def test_les_mots_de_la_requete_ne_sont_jamais_dominants():
    """« tarot » est dans 100 % des suggestions de « tarot » : le signaler serait absurde.
    Ce qui compte est ce que les gens AJOUTENT à la requête."""
    s = lire_suggestions(["tarot debutant", "tarot marseille", "tarot divinatoire"], "tarot")
    assert s["terme_dominant"] is None


def test_aucun_terme_dominant_quand_la_longue_traine_est_dispersee():
    """Une traîne dispersée est une bonne nouvelle : plusieurs sous-intentions, aucune
    figure imposée."""
    s = lire_suggestions(["stoicisme pratique", "stoicisme debutant", "stoicisme au travail",
                          "stoicisme moderne", "stoicisme exercices"], "stoicisme")
    assert s["terme_dominant"] is None


def test_trop_peu_de_suggestions_pour_conclure():
    """Sur deux suggestions, « la moitié » ne veut rien dire. On ne conclut pas — et on ne
    présente surtout pas cette absence comme un rayon libre."""
    s = lire_suggestions(["tarot jodorowsky", "tarot marseille"], "tarot")
    assert s["terme_dominant"] is None and s["suggestions_lues"] == 2


def test_l_intention_informationnelle_est_detectee():
    """Ces gens veulent l'information, pas le livre : « résumé de X » et « avis sur X » ne
    se convertissent pas en achat. Une niche peut avoir beaucoup de demande ET un public
    qui n'achètera rien."""
    s = lire_suggestions(["stoicisme resume", "stoicisme avis", "stoicisme pratique"],
                         "stoicisme")
    assert s["intention_informationnelle"] is True
    assert "resume" in s["marqueurs_informationnels"]
    assert "avis" in s["marqueurs_informationnels"]


def test_une_intention_d_achat_n_est_pas_signalee():
    s = lire_suggestions(["stoicisme pratique", "stoicisme livre broche",
                          "stoicisme exercices"], "stoicisme")
    assert s["intention_informationnelle"] is False
    assert s["marqueurs_informationnels"] == []


def test_les_accents_et_la_casse_ne_font_pas_rater_un_marqueur():
    """« Résumé » et « resume » sont le même mot ; l'autocomplete rend les deux."""
    s = lire_suggestions(["Stoïcisme RÉSUMÉ", "stoicisme citations"], "stoicisme")
    assert s["intention_informationnelle"] is True


def test_aucune_suggestion_ne_conclut_rien():
    """Zéro suggestion n'est pas « rayon sain » : c'est une absence de mesure."""
    s = lire_suggestions([], "stoicisme")
    assert s["terme_dominant"] is None
    assert s["intention_informationnelle"] is False
    assert s["suggestions_lues"] == 0
