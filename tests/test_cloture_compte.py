"""Clôturer un compte efface AUSSI ses données personnelles — décision de Baptiste, 2026-10-02.

Les comptes vivent dans `comptes.db`, mais l'historique, la consommation et les travaux sont
dans trois autres bases, cloisonnées par `user_id` (§1). Supprimer le compte seul laisserait
derrière lui ce qu'il a produit : des niches analysées, des dates, une consommation — et
l'adresse e-mail disparaîtrait justement, rendant ces lignes orphelines et impossibles à
réclamer. « Clôturer » doit vouloir dire ce qu'il dit.

Ce qui N'EST PAS effacé, et c'est délibéré : le cache des rayons Amazon (`df-cache.db`). Il
est MUTUALISÉ, ne porte aucun `user_id` et ne contient aucune donnée personnelle — ce sont
des pages publiques d'Amazon. L'effacer ferait repayer tous les autres comptes (§1).
"""
import pytest

from history import NicheHistory
from jobs import JobStore
from usage import UsageMeter


def test_les_trois_magasins_effacent_un_utilisateur(tmp_path):
    jobs, usage, hist = (JobStore(tmp_path / "j.db"), UsageMeter(tmp_path / "u.db"),
                         NicheHistory(tmp_path / "h.db"))
    jobs.create("scout", {"seed": "x"}, user_id="moi")
    jobs.create("scout", {"seed": "y"}, user_id="autre")
    usage.enregistrer("moi", type="scout", cout_usd=0.03, n_analyses=1)
    usage.enregistrer("autre", type="scout", cout_usd=0.03, n_analyses=1)
    hist.enregistrer("moi", "scout", "sommeil", {"global_score": 7.0})
    hist.enregistrer("autre", "scout", "sommeil", {"global_score": 7.0})

    assert jobs.supprimer_utilisateur("moi") == 1
    assert usage.supprimer_utilisateur("moi") == 1
    assert hist.supprimer_utilisateur("moi") == 1

    assert jobs.list_jobs(user_id="moi") == []
    assert usage.resume("moi").n_analyses == 0
    assert hist.historique("moi", "sommeil") == []

    # Le voisin n'est pas touché : c'est tout l'intérêt du cloisonnement par user_id.
    assert len(jobs.list_jobs(user_id="autre")) == 1
    assert usage.resume("autre").n_analyses == 1
    assert hist.historique("autre", "sommeil") != []


def test_effacer_un_utilisateur_inconnu_ne_leve_pas(tmp_path):
    """Une clôture ne doit pas échouer parce qu'un compte n'avait jamais rien produit."""
    assert JobStore(tmp_path / "j.db").supprimer_utilisateur("fantome") == 0
    assert UsageMeter(tmp_path / "u.db").supprimer_utilisateur("fantome") == 0
    assert NicheHistory(tmp_path / "h.db").supprimer_utilisateur("fantome") == 0
