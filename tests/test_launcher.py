"""`launcher.py` n'expose QUE des canaux gratuits.

Le lanceur du raccourci bureau est antérieur à l'interface web : il ne connaît ni compte,
ni session, ni plafond. Son option 3 appelait pourtant `generate_niches` — un appel
Anthropic réel, sans `_verifier_plafond`, sans `UsageMeter`, et sans même un `CostTracker`.
Le montant était faible (~0,02 € annoncés dans le menu) ; le problème n'était pas là. Ce
chemin était le seul du dépôt à dépenser sans laisser de trace dans `usage.db`, or c'est
`usage.db` qui porte tout le raisonnement de marge : ce qu'il ne voit pas, personne ne le
voit.

Décision de Baptiste (2026-08-18) : retirer l'option, garder le lanceur. Les deux sondes
gratuites (autocomplete, BSR scrapé) sont utiles et ne coûtent rien ; c'est le chemin
payant qui n'avait pas sa place hors de l'interface.

Ces tests sont un CLIQUET : ils échouent si un chemin payant revient par cette porte.
"""
import pytest

import launcher


@pytest.fixture(autouse=True)
def jamais_de_depense(monkeypatch):
    """Coupe le SDK Anthropic et le HTTP sortant AVANT chaque test de ce fichier.

    Ecrit apres une erreur reelle : la premiere version de
    `test_un_choix_3_ne_fait_plus_rien_de_particulier` envoyait ["3", "q"] a `input`,
    donc "3" au menu puis "q" comme GRAINE -- et `_do_niches` a lance un vrai appel
    Anthropic, qui a rendu dix niches commencant toutes par Q. Le test a depense de
    l'argent et touche le reseau, dans une suite dont l'invariant est justement d'etre
    hors-ligne.

    La lecon n'est pas "mieux choisir ses reponses d'entree" : c'est qu'un test ne doit
    pas dependre de la proprete du code qu'il teste pour rester inoffensif. Si un chemin
    payant revient dans launcher.py, ce filet le fait ECHOUER au lieu de le faire PAYER."""
    def refuser(*a, **k):
        raise AssertionError(
            "un test de launcher a tente un appel sortant : un chemin payant est "
            "revenu dans le lanceur (voir le docstring du module)")

    monkeypatch.setattr("amazon_autocomplete.fetch_suggestions", refuser)
    monkeypatch.setattr("amazon_product.fetch_bsr", refuser)
    monkeypatch.setattr("util.http_get", refuser, raising=False)
    monkeypatch.setattr("launcher.fetch_suggestions", refuser, raising=False)
    monkeypatch.setattr("launcher.fetch_bsr", refuser, raising=False)




def test_le_menu_n_offre_aucun_canal_payant(capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "q")
    launcher._menu()
    texte = capsys.readouterr().out.lower()
    assert "gratuit" in texte
    assert "anthropic" not in texte and "ia" not in texte.replace("ia-niches", "")


def test_le_lanceur_n_importe_aucun_module_payant():
    """`niche_ideator` importe le SDK Anthropic et facture au token. Le lanceur ne doit y
    toucher ni à l'import, ni en import tardif dans une fonction."""
    from pathlib import Path
    src = Path(launcher.__file__).read_text(encoding="utf-8")
    for interdit in ("niche_ideator", "generate_niches", "scout_master", "run_scout",
                     "fiction_master", "search_providers", "dataforseo"):
        assert interdit not in src, f"chemin payant réintroduit : {interdit}"


def test_la_fonction_de_niches_ia_n_existe_plus():
    assert not hasattr(launcher, "_do_niches")


def test_les_deux_sondes_gratuites_restent_la():
    """Retirer le chemin payant ne doit pas emporter l'outil : c'est un lanceur utile."""
    assert hasattr(launcher, "_do_suggest") and hasattr(launcher, "_do_bsr")


def test_un_choix_3_ne_fait_plus_rien_de_particulier(capsys, monkeypatch):
    """L'utilisateur qui tapait « 3 » par habitude doit voir un refus lisible, pas un
    appel silencieux ni un plantage."""
    # Seconde reponse VIDE et non "q" : si un `_do_niches` revenait un jour, il
    # demanderait une graine et sortirait immediatement sur une saisie vide, sans rien
    # appeler. Le filet `jamais_de_depense` couvre le reste.
    reponses = iter(["3", "", "q"])
    monkeypatch.setattr("builtins.input", lambda *a: next(reponses))
    launcher.main()
    assert "non reconnu" in capsys.readouterr().out.lower()
