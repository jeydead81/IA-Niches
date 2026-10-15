"""L'écran de connexion sait récupérer un mot de passe et confirmer une adresse (2026-10-06).

Fonctions pures appelées avec node (§2.10) ; le câblage — ce qui est branché sur quoi — se lit
dans le source, parce qu'une fonction juste branchée nulle part est le défaut central de ce
dépôt (§5.26).
"""
import re
from pathlib import Path

import pytest

from tests.js_harness import appeler_json

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text(encoding="utf-8")


# ── Les quatre états de l'écran ─────────────────────────────────────────────────────

@pytest.mark.parametrize("mode,email,mdp,oubli", [
    ("connexion", True, True, True),
    ("inscription", True, True, False),
    ("oubli", True, False, False),
    ("reinit", False, True, False),
])
def test_chaque_etat_montre_les_bons_champs(mode, email, mdp, oubli):
    l = appeler_json("libellesAuth", mode)
    assert (l["email"], l["mdp"], l["oubli"]) == (email, mdp, oubli)
    assert l["titre"] and l["bouton"]


def test_un_etat_inconnu_retombe_sur_la_connexion():
    assert appeler_json("libellesAuth", "n-importe-quoi")["titre"] == "Connexion"


def test_la_politique_de_mot_de_passe_est_montree_a_l_inscription_et_a_la_reinitialisation():
    assert appeler_json("libellesAuth", "inscription")["aide"] is True
    assert appeler_json("libellesAuth", "reinit")["aide"] is True
    assert appeler_json("libellesAuth", "connexion")["aide"] is False


def test_la_reprise_des_donnees_locales_reste_propre_a_l_inscription():
    assert [m for m in ("connexion", "inscription", "oubli", "reinit")
            if appeler_json("libellesAuth", m)["reprise"]] == ["inscription"]


# ── Le bandeau « confirmez votre adresse » ──────────────────────────────────────────

def test_hors_production_aucun_bandeau():
    """La vérification n'est pas exigée : un bandeau se lirait comme une panne."""
    assert appeler_json("libelleVerif", {"email_verifie": False, "verification_requise": False},
                        None) is None


def test_en_production_une_adresse_non_verifiee_propose_de_renvoyer_le_lien():
    l = appeler_json("libelleVerif", {"email_verifie": False, "verification_requise": True}, None)
    assert l["renvoyer"] is True and "e-mail" in l["texte"]


def test_une_adresse_verifiee_n_affiche_rien():
    assert appeler_json("libelleVerif", {"email_verifie": True, "verification_requise": True},
                        None) is None


def test_un_lien_valide_remercie_sans_proposer_de_renvoi():
    l = appeler_json("libelleVerif", {"email_verifie": True}, True)
    assert l["renvoyer"] is False and "confirmée" in l["texte"]


def test_un_remerciement_ne_s_affiche_jamais_pour_un_compte_qui_n_est_pas_verifie():
    """Le lien suivi peut être celui d'un AUTRE compte (ou d'une autre adresse) : dire « confirmée »
    à un compte encore non vérifié le laisserait croire qu'il peut lancer, puis le 403."""
    l = appeler_json("libelleVerif", {"email_verifie": False, "verification_requise": True}, True)
    assert "confirmée" not in l["texte"] and l["renvoyer"] is True


def test_un_lien_invalide_propose_un_nouveau_a_qui_n_est_pas_verifie_seulement():
    non = appeler_json("libelleVerif", {"email_verifie": False}, False)
    assert non["renvoyer"] is True and "invalide ou expiré" in non["texte"]
    # Un compte DÉJÀ vérifié qui suit un vieux lien n'a rien à faire : pas de bandeau d'alarme.
    assert appeler_json("libelleVerif", {"email_verifie": True}, False) is None


def test_un_compte_illisible_ne_leve_pas():
    assert appeler_json("libelleVerif", None, None) is None
    assert appeler_json("libelleVerif", None, False)["renvoyer"] is True


# ── Le câblage ──────────────────────────────────────────────────────────────────────

def test_le_lien_mot_de_passe_oublie_est_atteignable_depuis_la_connexion():
    assert 'id="auth-oubli"' in HTML and 'id="auth-oubli-bloc"' in HTML
    assert "$('#auth-oubli').addEventListener('click'" in HTML


def test_les_trois_routes_sont_appelees_par_la_page():
    for route in ("/api/auth/mot-de-passe-oublie", "/api/auth/mot-de-passe-reinitialiser",
                  "/api/auth/verification", "/api/auth/verification/renvoyer"):
        assert f"'{route}'" in HTML, route


def test_le_jeton_est_retire_de_l_url_des_qu_il_est_lu():
    """Il ne doit rester ni dans la barre d'adresse ni dans l'historique du navigateur."""
    m = re.search(r"jetonVerif \|\| jetonReinit\)\{[^}]*history\.replaceState", HTML)
    assert m, "le jeton doit être retiré de l'URL au chargement"


def test_le_jeton_se_lit_dans_le_fragment():
    """Le lien porte `#verif=...` : un fragment n'est jamais envoyé au serveur ni journalisé."""
    assert "new URLSearchParams(location.hash.replace(/^#/, ''))" in HTML
    assert "location.pathname + location.search" in HTML, \
        "retirer le fragment SANS toucher aux paramètres de requête éventuels"


def test_un_seul_appel_a_moi_au_demarrage_et_le_compteur_se_rafraichit():
    """Trois appels à /api/auth/moi se disputaient le bandeau ; le compteur de niches restait celui
    de l'ouverture de la page, donc faux dès le premier run."""
    i = HTML.index("async function demarrer()")
    fin = HTML.index("  demarrer();", i)
    assert HTML[i:fin].count("fetch('/api/auth/moi')") == 1
    assert HTML.count("chargerUsage()") >= 3, "définition + ouverture + fin d'analyse / lancement"


def test_les_mots_cles_montrent_le_motif_du_serveur():
    i = HTML.index("async function loadKdp")
    assert "d.detail" in HTML[i:i + 3000], "un 429 mensuel ou un 403 de vérification doit se lire"


def test_le_champ_masque_n_est_jamais_obligatoire():
    """Un champ invisible et `required` bloquerait l'envoi du formulaire sans rien dire : c'est
    exactement ce que ferait l'e-mail en mode « nouveau mot de passe »."""
    assert "email.required = l.email" in HTML and "mdp.required = l.mdp" in HTML


def test_la_reinitialisation_n_attend_pas_de_session():
    """Les sessions sont toutes fermées par la réinitialisation : exiger d'être connecté pour
    afficher le formulaire le rendrait inatteignable."""
    i = HTML.index("async function demarrer()")
    assert "if(jetonReinit)" in HTML[i:i + 400]
    assert HTML[i:].index("if(jetonReinit)") < HTML[i:].index("/api/auth/moi")
