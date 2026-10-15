"""Vérification d'adresse e-mail et mot de passe oublié : le magasin de comptes (2026-10-06).

Les deux se traitent ENSEMBLE ou pas du tout (ROADMAP §2.1) : une réinitialisation par e-mail
suppose une adresse dont on sait qu'elle appartient à son titulaire, et c'est précisément ce
qu'établit un lien envoyé à cette adresse. Un lien de réinitialisation consommé PROUVE l'accès à
la boîte : il vérifie donc l'adresse du même coup — c'est aussi ce qui permet à un titulaire de
récupérer une adresse « squattée » par quelqu'un qui s'y est inscrit avant lui.

Règles tenues par ces tests, dans l'ordre de ce qu'elles coûteraient si on les cassait :

1. Le jeton n'est JAMAIS stocké en clair (SHA-256 seulement), comme le jeton de session : lire la
   base ne doit pas permettre de réinitialiser le mot de passe d'un client.
2. Un jeton sert UNE fois, et expire. Un lien traîne dans une boîte, un historique, un relais.
3. Une réinitialisation ferme TOUTES les sessions : on oublie son mot de passe aussi quand on
   craint qu'un tiers ait la main sur le compte.
4. Un mot de passe refusé par la politique ne CONSOMME PAS le jeton : sinon une faute de frappe
   obligerait à tout redemander.
5. Les comptes qui existaient avant la colonne sont considérés vérifiés : ils sont locaux, et les
   verrouiller dehors serait la seule conséquence de la migration.
"""
import sqlite3

import pytest

from auth import (MotDePasseFaible, UserStore, _empreinte_jeton)

MDP = "un-mot-de-passe-solide"
NOUVEAU = "un-autre-mot-de-passe-solide"


def _store(tmp_path, now=None) -> UserStore:
    return UserStore(tmp_path / "comptes.db", now=now)


# ── La colonne ──────────────────────────────────────────────────────────────────────

def test_un_compte_neuf_n_est_pas_verifie(tmp_path):
    s = _store(tmp_path)
    c = s.creer_compte("a@example.com", MDP)
    assert c.email_verifie is False
    assert s.compte(c.user_id).email_verifie is False
    assert s.verifier("a@example.com", MDP).email_verifie is False


def test_les_comptes_anterieurs_a_la_colonne_sont_consideres_verifies(tmp_path):
    chemin = tmp_path / "comptes.db"
    cx = sqlite3.connect(chemin)
    cx.execute("CREATE TABLE comptes (user_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, "
               "sel BLOB NOT NULL, empreinte BLOB NOT NULL, params TEXT NOT NULL, "
               "cree_le REAL NOT NULL)")
    cx.execute("INSERT INTO comptes VALUES ('u1', 'ancien@example.com', x'00', x'00', "
               "'scrypt:16384:8:1', 1.0)")
    cx.commit()
    cx.close()
    s = UserStore(chemin)
    assert s.compte("u1").email_verifie is True
    assert s.creer_compte("neuf@example.com", MDP).email_verifie is False


# ── Les jetons ──────────────────────────────────────────────────────────────────────

def test_un_jeton_de_verification_verifie_l_adresse_une_seule_fois(tmp_path):
    s = _store(tmp_path)
    c = s.creer_compte("a@example.com", MDP)
    jeton = s.creer_jeton_courriel(c.user_id, "verification")
    ok = s.verifier_email_par_jeton(jeton)
    assert ok is not None and ok.user_id == c.user_id and ok.email_verifie is True
    assert s.compte(c.user_id).email_verifie is True
    assert s.verifier_email_par_jeton(jeton) is None, "un lien ne sert qu'une fois"


def test_le_jeton_n_est_jamais_stocke_en_clair(tmp_path):
    s = _store(tmp_path)
    c = s.creer_compte("a@example.com", MDP)
    jeton = s.creer_jeton_courriel(c.user_id, "verification")
    with sqlite3.connect(s.path) as cx:
        lignes = cx.execute("SELECT empreinte FROM jetons_courriel").fetchall()
    assert lignes == [(_empreinte_jeton(jeton),)]
    assert jeton not in repr(lignes) and len(jeton) >= 40


def test_un_jeton_expire_ne_sert_plus(tmp_path):
    horloge = [1000.0]
    s = _store(tmp_path, now=lambda: horloge[0])
    c = s.creer_compte("a@example.com", MDP)
    jeton = s.creer_jeton_courriel(c.user_id, "verification", ttl_s=60)
    horloge[0] += 61
    assert s.verifier_email_par_jeton(jeton) is None
    assert s.compte(c.user_id).email_verifie is False


def test_un_jeton_d_un_usage_ne_sert_pas_pour_l_autre(tmp_path):
    """Un lien de vérification (48 h, traîne dans les boîtes) ne doit pas pouvoir réinitialiser
    un mot de passe."""
    s = _store(tmp_path)
    c = s.creer_compte("a@example.com", MDP)
    jeton = s.creer_jeton_courriel(c.user_id, "verification")
    assert s.reinitialiser_mot_de_passe_par_jeton(jeton, NOUVEAU) is None
    assert s.verifier("a@example.com", MDP) is not None, "le mot de passe n'a pas bougé"


def test_un_nouveau_jeton_remplace_les_precedents_non_utilises(tmp_path):
    s = _store(tmp_path)
    c = s.creer_compte("a@example.com", MDP)
    ancien = s.creer_jeton_courriel(c.user_id, "reinitialisation")
    recent = s.creer_jeton_courriel(c.user_id, "reinitialisation")
    assert s.reinitialiser_mot_de_passe_par_jeton(ancien, NOUVEAU) is None
    assert s.reinitialiser_mot_de_passe_par_jeton(recent, NOUVEAU) is not None


def test_un_jeton_inconnu_ou_vide_ne_fait_rien(tmp_path):
    s = _store(tmp_path)
    s.creer_compte("a@example.com", MDP)
    for j in ("", "   ", "pas-un-jeton", None):
        assert s.verifier_email_par_jeton(j) is None
        assert s.reinitialiser_mot_de_passe_par_jeton(j, NOUVEAU) is None


# ── La réinitialisation ─────────────────────────────────────────────────────────────

def test_la_reinitialisation_change_le_mot_de_passe_et_ferme_toutes_les_sessions(tmp_path):
    s = _store(tmp_path)
    c = s.creer_compte("a@example.com", MDP)
    sessions = [s.creer_session(c.user_id) for _ in range(3)]
    jeton = s.creer_jeton_courriel(c.user_id, "reinitialisation")
    r = s.reinitialiser_mot_de_passe_par_jeton(jeton, NOUVEAU)
    assert r is not None and r.user_id == c.user_id
    assert s.verifier("a@example.com", NOUVEAU) is not None
    assert s.verifier("a@example.com", MDP) is None
    assert all(s.session_valide(j) is None for j in sessions), "toutes les sessions sont fermées"


def test_un_lien_de_reinitialisation_consomme_verifie_aussi_l_adresse(tmp_path):
    """Il prouve l'accès à la boîte : c'est la définition d'une adresse vérifiée, et c'est ce
    qui rend à son titulaire une adresse squattée."""
    s = _store(tmp_path)
    c = s.creer_compte("a@example.com", MDP)
    s.reinitialiser_mot_de_passe_par_jeton(s.creer_jeton_courriel(c.user_id, "reinitialisation"),
                                           NOUVEAU)
    assert s.compte(c.user_id).email_verifie is True


def test_un_mot_de_passe_refuse_ne_consomme_pas_le_jeton(tmp_path):
    s = _store(tmp_path)
    c = s.creer_compte("a@example.com", MDP)
    jeton = s.creer_jeton_courriel(c.user_id, "reinitialisation")
    with pytest.raises(MotDePasseFaible):
        s.reinitialiser_mot_de_passe_par_jeton(jeton, "court")
    assert s.reinitialiser_mot_de_passe_par_jeton(jeton, NOUVEAU) is not None


def test_la_reinitialisation_remet_les_tentatives_a_zero(tmp_path):
    """Quelqu'un qui a oublié son mot de passe l'a souvent essayé huit fois : le verrouiller
    APRÈS qu'il l'a réinitialisé serait absurde."""
    s = _store(tmp_path)
    c = s.creer_compte("a@example.com", MDP)
    for _ in range(8):
        s.verifier("a@example.com", "faux-faux-faux-faux")
    jeton = s.creer_jeton_courriel(c.user_id, "reinitialisation")
    s.reinitialiser_mot_de_passe_par_jeton(jeton, NOUVEAU)
    assert s.verifier("a@example.com", NOUVEAU) is not None


def test_cloturer_le_compte_efface_ses_jetons(tmp_path):
    s = _store(tmp_path)
    c = s.creer_compte("a@example.com", MDP)
    s.creer_jeton_courriel(c.user_id, "verification")
    s.supprimer_compte("a@example.com", MDP)
    with sqlite3.connect(s.path) as cx:
        assert cx.execute("SELECT COUNT(*) FROM jetons_courriel").fetchone()[0] == 0


def test_compte_par_email_retrouve_un_compte_sans_distinguer_la_casse(tmp_path):
    s = _store(tmp_path)
    c = s.creer_compte("a@example.com", MDP)
    assert s.compte_par_email("  A@Example.COM ").user_id == c.user_id
    assert s.compte_par_email("inconnu@example.com") is None
    assert s.compte_par_email(None) is None


# ── Revue adversariale du 2026-10-06 ─────────────────────────────────────────────────

def test_les_echecs_de_connexion_ne_remplissent_pas_les_compteurs_des_autres_usages(tmp_path):
    """Un « e-mail » libre posé à la connexion était noté tel quel dans la table des tentatives :
    envoyer `reinit:victime@x.com` trois fois suffisait à bloquer la demande de réinitialisation
    de la victime. La connexion note désormais sous SON préfixe."""
    s = _store(tmp_path)
    for _ in range(5):
        s.verifier("reinit:victime@example.com", "faux-faux-faux-faux")
        s.verifier("ip:1.2.3.4", "faux-faux-faux-faux")
    assert s.tentatives_recentes("reinit:victime@example.com") == 0
    assert s.tentatives_recentes("ip:1.2.3.4") == 0


def test_le_verrou_de_connexion_par_adresse_fonctionne_toujours(tmp_path):
    from auth import MAX_TENTATIVES, TropDeTentatives
    s = _store(tmp_path)
    s.creer_compte("a@example.com", MDP)
    for _ in range(MAX_TENTATIVES):
        s.verifier("a@example.com", "faux-faux-faux-faux")
    with pytest.raises(TropDeTentatives):
        s.verifier("a@example.com", MDP)


@pytest.mark.parametrize("adresse", ["a,b@example.com", "a;b@example.com", "<a>@example.com",
                                     'a"b@example.com', "a(b)@example.com", "a[b]@example.com",
                                     "a\\b@example.com", "a@exa,mple.com"])
def test_une_adresse_qui_ajouterait_un_destinataire_est_refusee(tmp_path, adresse):
    """`msg["To"] = "a,b@example.com"` s'analyse en DEUX destinataires : une inscription pourrait
    faire envoyer le lien de vérification à un tiers."""
    from auth import EmailInvalide
    with pytest.raises(EmailInvalide):
        _store(tmp_path).creer_compte(adresse, MDP)


def test_une_adresse_ordinaire_reste_acceptee(tmp_path):
    s = _store(tmp_path)
    for a in ("prenom.nom+kdp@example.co.uk", "o'brien@example.com", "a_b-c@sous.domaine.fr"):
        assert s.creer_compte(a, MDP).email == a


def test_changer_son_mot_de_passe_invalide_un_lien_de_reinitialisation_en_attente(tmp_path):
    """Un lien demandé avant le changement ne doit pas pouvoir REPRENDRE la main après."""
    s = _store(tmp_path)
    c = s.creer_compte("a@example.com", MDP)
    jeton = s.creer_jeton_courriel(c.user_id, "reinitialisation")
    s.changer_mot_de_passe("a@example.com", MDP, NOUVEAU)
    assert s.reinitialiser_mot_de_passe_par_jeton(jeton, "encore-un-autre-solide") is None


def test_un_lien_invalide_ne_declenche_aucune_derivation_scrypt(tmp_path):
    """scrypt coûte ~45 ms et 16 Mo : exécutée AVANT de savoir si le lien est valide, elle faisait
    de cette route (sans session) un amplificateur de coût pour n'importe qui."""
    s = _store(tmp_path)
    c = s.creer_compte("a@example.com", MDP)
    appels = []
    original = s._deriver
    s._deriver = lambda *a, **k: appels.append(1) or original(*a, **k)
    assert s.reinitialiser_mot_de_passe_par_jeton("faux", NOUVEAU) is None
    assert s.reinitialiser_mot_de_passe_par_jeton(
        s.creer_jeton_courriel(c.user_id, "verification"), NOUVEAU) is None
    assert appels == [], "aucune dérivation pour un lien inconnu ou d'un autre usage"
    assert s.reinitialiser_mot_de_passe_par_jeton(
        s.creer_jeton_courriel(c.user_id, "reinitialisation"), NOUVEAU) is not None
    assert appels == [1]
