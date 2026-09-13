"""Le CLI qui enchaîne xlsx corrigé -> sonde gratuite -> run payant -> rapport JSON.

Deux exigences le distinguent d'un simple script d'appel :

1. **Il ne laisse PAS l'ideator choisir les requêtes.** Ce sont celles de Baptiste, et
   c'est tout l'intérêt : si le modèle proposait les requêtes qu'on va ensuite corréler à
   son propre scoring, on mesurerait la cohérence du produit avec lui-même. Le LLM garde
   son rôle de classement (format, thème, public) — il ne choisit pas le sujet.

2. **Une requête perdue en route doit se voir.** Le gate gratuit, le filtre IP et le
   filtre saisonnier peuvent écarter une requête AVANT toute dépense. Une « morte »
   écartée là est une bonne nouvelle (le produit l'a rejetée pour zéro centime) ; une
   « bonne » écartée là est un faux négatif coûteux, invisible par construction puisque
   l'utilisateur ne verra jamais la niche. Les compter ensemble effacerait la différence.

Aucun réseau, aucun LLM : `sonde` et `run` sont injectés.
"""
import json
from pathlib import Path

import pytest

from build_lowcontent_validation_set import construire_rapport, sonder
from lowcontent_validation import RequeteEtiquetee, rapport_calibration
from models import LowContentNiche, LowContentScored


def _etq(requete, etiquette, famille="carnets"):
    return RequeteEtiquetee(requete=requete, famille=famille, etiquette=etiquette)


def _scored(requete, score, **kw):
    n = LowContentNiche(niche=requete, requete_amazon=requete, rationale="r",
                        categorie="c", format_cle="journal_suivi", theme="t",
                        public="adulte")
    base = dict(niche=n, global_score=score, concurrence_mesuree=True,
                priorite="🟢 À analyser en priorité" if score >= 7.5 else "🔴 Faible")
    base.update(kw)
    return LowContentScored(**base)


# ── L'extension du rapport : ce qui n'a jamais été analysé ─────────────────────

def test_une_morte_ecartee_avant_toute_depense_est_un_SUCCES():
    """Le produit l'a rejetée pour zéro centime. C'est le gate gratuit qui fait son
    travail, pas une donnée manquante."""
    r = rapport_calibration([("bonne", _scored("a", 8.0))],
                            ecartees=[("carnet noel a completer", "morte")])
    assert r.ecartees_correctement == ["carnet noel a completer"]
    assert r.bonnes_perdues_avant_analyse == []


def test_une_bonne_ecartee_avant_analyse_est_un_FAUX_NEGATIF_annonce():
    """Le pire défaut possible et le plus invisible : la niche n'apparaît nulle part, donc
    rien à l'écran ne signale qu'elle a existé. Le rapport est le seul endroit où ça peut
    se voir."""
    r = rapport_calibration([("bonne", _scored("a", 8.0))],
                            ecartees=[("carnet suivi glycemie", "bonne")])
    assert r.bonnes_perdues_avant_analyse == ["carnet suivi glycemie"]
    assert any("perdue" in a.lower() or "faux négatif" in a.lower()
               for a in r.avertissements)


def test_les_ecartees_ne_ferment_PAS_la_porte():
    """Le critère du plan est « Spearman ≥ 0,5 ET aucune morte en vert ». Ajouter un
    troisième critère de mon propre chef ferait passer une intention pour une règle
    (§4.2). Le faux négatif est annoncé fort, il ne bloque pas."""
    lu = dict(part_indie=0.7, redevance_estimee=3.1)   # run nominal : le rayon a été lu
    paires = [("bonne", _scored(f"b{i}", 8.0 + i * 0.1, **lu)) for i in range(3)]
    paires += [("mauvaise", _scored(f"m{i}", 6.0 + i * 0.1, **lu)) for i in range(3)]
    paires += [("morte", _scored(f"d{i}", 2.0 + i * 0.1, **lu)) for i in range(3)]
    r = rapport_calibration(paires, ecartees=[("perdue", "bonne")])
    assert r.porte_franchie is True
    assert r.bonnes_perdues_avant_analyse == ["perdue"]


# ── La sonde gratuite ──────────────────────────────────────────────────────────

def test_la_sonde_mesure_les_enfants_de_CHAQUE_requete():
    """`demand_score` en sort. Sans sonde, la branche « tautologie » du master retomberait
    sur `max(1, 0)` pour toutes les requêtes : l'axe demande serait plat et le Spearman
    ne mesurerait plus que les trois autres axes."""
    appels = []

    def faux_expand(seed, **kw):
        appels.append(seed)
        from autocomplete_expand import Suggestion
        n = {"carnet a": 4, "carnet b": 0}[seed]
        return [Suggestion(requete=f"{seed} {i}", parent=seed, profondeur=1)
                for i in range(n)]

    out = sonder(["carnet a", "carnet b"], expand_fn=faux_expand)
    assert appels == ["carnet a", "carnet b"]
    assert {s.requete: s.n_enfants for s in out} == {"carnet a": 4, "carnet b": 0}


def test_la_sonde_reprend_la_requete_telle_quelle():
    """C'est la requête de Baptiste. La normaliser en ferait une autre mesure que celle
    qu'il a jugée."""
    from autocomplete_expand import Suggestion
    out = sonder(["Carnet de Suivi Glycémie"], expand_fn=lambda seed, **kw: [])
    assert out[0].requete == "Carnet de Suivi Glycémie"


def test_une_sonde_en_PANNE_ne_se_lit_pas_zero_enfant():
    """Invariant du dépôt (§5.10). Zéro enfant est une mesure — « personne n'affine cette
    requête » — et vaudrait un malus sur l'axe demande. Une panne réseau doit rendre
    `None`, qui ne donne ni bonus ni malus."""
    def tombe(seed, **kw):
        raise RuntimeError("réseau")

    out = sonder(["carnet a"], expand_fn=tombe)
    assert out[0].n_enfants is None


# ── Le rapport de bout en bout ─────────────────────────────────────────────────

def _run_factice(scores):
    """Simule `run_lowcontent_scout` : rend les niches scorées pour les requêtes qu'on
    lui a passées, dans l'ordre de son choix (le vrai trie par score)."""
    vus = {}

    def run(**kw):
        vus.update(kw)
        return [_scored(r, s) for r, s in scores.items()]

    run.vus = vus
    return run


def test_le_rapport_apparie_etiquette_et_score_par_requete():
    etq = [_etq("carnet a", "bonne"), _etq("mots meles seniors", "morte", "jeux_esprit")]
    run = _run_factice({"mots meles seniors": 2.0, "carnet a": 8.4})
    r = construire_rapport(etq, run=run, sonde=lambda rs, **kw: [])
    assert r.n_calibrees == 2
    assert r.signaux["bonne"]["score"] == pytest.approx(8.4)
    assert r.signaux["morte"]["score"] == pytest.approx(2.0)


def test_le_run_recoit_TOUTES_les_requetes_sans_troncature():
    """`n_search` borne la shortlist payante. Le laisser à son défaut de 6 n'analyserait
    que 6 des 30 requêtes de Baptiste, et le rapport annoncerait pourtant 30."""
    etq = [_etq(f"carnet {i}", "bonne") for i in range(9)]
    run = _run_factice({f"carnet {i}": 7.0 for i in range(9)})
    construire_rapport(etq, run=run, sonde=lambda rs, **kw: [])
    assert run.vus["n_search"] >= 9 and run.vus["n_ideas"] >= 9


def test_l_ideator_ne_choisit_PAS_les_requetes():
    """LE test du module. Les requêtes sont injectées par `expand_fn` ; si le CLI laissait
    le master partir d'une graine, le modèle proposerait ses propres niches et on
    corrélerait le produit avec lui-même."""
    etq = [_etq("carnet suivi glycemie", "bonne")]
    run = _run_factice({"carnet suivi glycemie": 8.0})
    construire_rapport(etq, run=run, sonde=lambda rs, **kw: [])
    fournies = run.vus["expand_fn"]("peu importe la graine")
    assert [s.requete for s in fournies] == ["carnet suivi glycemie"]


def test_une_requete_absente_du_resultat_est_comptee_ECARTEE():
    """Filtre IP, filtre saisonnier, gate gratuit : trois façons de perdre une requête
    avant la moindre dépense. Silencieuses, elles feraient annoncer 30 requêtes calibrées
    pour 27 réellement mesurées."""
    etq = [_etq("carnet a", "bonne"), _etq("coloriage pat patrouille", "bonne")]
    run = _run_factice({"carnet a": 8.0})
    r = construire_rapport(etq, run=run, sonde=lambda rs, **kw: [])
    assert r.bonnes_perdues_avant_analyse == ["coloriage pat patrouille"]
    assert r.n_calibrees == 1


def test_l_appariement_ignore_la_casse_et_les_espaces():
    """La dédup de l'ideator normalise. Une requête rendue en casse différente est la même
    requête — la déclarer écartée serait un faux signalement."""
    etq = [_etq("Carnet Suivi Glycémie ", "bonne")]
    run = _run_factice({"carnet suivi glycémie": 8.0})
    r = construire_rapport(etq, run=run, sonde=lambda rs, **kw: [])
    assert r.n_calibrees == 1 and r.bonnes_perdues_avant_analyse == []


def test_les_familles_du_xlsx_remontent_dans_le_rapport():
    etq = [_etq("carnet a", "bonne", "carnets"), _etq("registre b", "morte", "pro")]
    run = _run_factice({"carnet a": 8.0, "registre b": 2.0})
    r = construire_rapport(etq, run=run, sonde=lambda rs, **kw: [])
    assert r.familles["carnets"] == 1 and r.familles["pro"] == 1
    assert any("sous-représentée" in a for a in r.avertissements)


def test_le_rapport_final_s_ecrit_en_json(tmp_path):
    etq = [_etq("carnet a", "bonne")]
    run = _run_factice({"carnet a": 8.0})
    r = construire_rapport(etq, run=run, sonde=lambda rs, **kw: [])
    p = tmp_path / "rapport.json"
    p.write_text(r.model_dump_json(indent=2), encoding="utf-8")
    assert "porte_franchie" in json.loads(p.read_text(encoding="utf-8"))


def test_le_cout_est_borne_par_un_plafond_explicite():
    """Un jeu de 30 requêtes est le plus gros run que ce dépôt lance jamais. Sans plafond
    passé au tracker, une erreur de saisie sur le xlsx dépenserait sans borne."""
    etq = [_etq("carnet a", "bonne")]
    run = _run_factice({"carnet a": 8.0})
    construire_rapport(etq, run=run, sonde=lambda rs, **kw: [], plafond_usd=1.5)
    assert run.vus["cost"].plafond_usd == pytest.approx(1.5)
