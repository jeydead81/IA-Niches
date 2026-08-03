"""test_auth.py — comptes email/mot de passe et sessions.

Ces tests sont d'abord des tests de SÉCURITÉ. Ce module est le seul du dépôt dont un
défaut ne produit pas un mauvais chiffre mais une compromission : mot de passe lisible,
session volable, plafond contournable, énumération des clients. Chaque test nomme la
menace qu'il ferme.

Aucun réseau, aucune horloge réelle imposée : `now` est injectable comme dans usage.py."""
import sqlite3

import pytest

from auth import (LONGUEUR_MIN_MOT_DE_PASSE, SESSION_TTL_S, EmailInvalide, EmailDejaPris,
                  MotDePasseFaible, UserStore, normaliser_email)


def _store(tmp_path, now=None):
    return UserStore(tmp_path / "comptes.db", now=now)


# ── Mot de passe ────────────────────────────────────────────────────────────────────

def test_le_mot_de_passe_n_est_jamais_stocke_en_clair(tmp_path):
    """MENACE : une copie de la base (sauvegarde, disque revendu, acces au serveur) rendrait
    les mots de passe de tous les clients — et ces mots de passe sont reutilises ailleurs."""
    s = _store(tmp_path)
    s.creer_compte("baptiste@example.com", "un-mot-de-passe-solide")
    brut = (tmp_path / "comptes.db").read_bytes()
    assert b"un-mot-de-passe-solide" not in brut


def test_deux_comptes_au_meme_mot_de_passe_ont_des_empreintes_differentes(tmp_path):
    """MENACE : sans sel PAR COMPTE, une seule table pre-calculee casse tous les comptes
    partageant un mot de passe courant, et l'egalite des empreintes revele qui l'utilise."""
    s = _store(tmp_path)
    a = s.creer_compte("a@example.com", "le-meme-mot-de-passe")
    b = s.creer_compte("b@example.com", "le-meme-mot-de-passe")
    with sqlite3.connect(tmp_path / "comptes.db") as cx:
        emp = cx.execute("SELECT empreinte FROM comptes WHERE user_id IN (?,?)",
                         (a.user_id, b.user_id)).fetchall()
    assert len(emp) == 2 and emp[0][0] != emp[1][0]


def test_un_mot_de_passe_trop_court_est_refuse(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(MotDePasseFaible):
        s.creer_compte("a@example.com", "a" * (LONGUEUR_MIN_MOT_DE_PASSE - 1))


def test_le_bon_mot_de_passe_ouvre_le_compte_et_le_mauvais_non(tmp_path):
    s = _store(tmp_path)
    s.creer_compte("baptiste@example.com", "un-mot-de-passe-solide")
    assert s.verifier("baptiste@example.com", "un-mot-de-passe-solide") is not None
    assert s.verifier("baptiste@example.com", "un-mot-de-passe-SOLIDE") is None


# ── Énumération des comptes ─────────────────────────────────────────────────────────

def test_un_email_inconnu_et_un_mot_de_passe_faux_echouent_pareil(tmp_path):
    """MENACE : si « email inconnu » se distingue de « mot de passe faux », n'importe qui
    teste une liste d'adresses et apprend QUI est client. `verifier` doit rendre None dans
    les deux cas, sans jamais dire lequel."""
    s = _store(tmp_path)
    s.creer_compte("connu@example.com", "un-mot-de-passe-solide")
    assert s.verifier("inconnu@example.com", "un-mot-de-passe-solide") is None
    assert s.verifier("connu@example.com", "mauvais-mot-de-passe") is None


def test_un_email_inconnu_coute_le_meme_travail_qu_un_compte_existant(tmp_path):
    """MENACE : meme si le message est identique, repondre INSTANTANEMENT sur un email
    inconnu (parce qu'on n'a rien a hacher) et lentement sur un email connu revele la meme
    information par le temps de reponse. `verifier` doit hacher un leurre quand le compte
    n'existe pas."""
    s = _store(tmp_path)
    s.creer_compte("connu@example.com", "un-mot-de-passe-solide")
    appels = []
    s._deriver = _compter(s._deriver, appels)
    s.verifier("inconnu@example.com", "peu importe")
    assert appels, "aucun hachage sur email inconnu — le temps de reponse trahit le compte"


def _compter(fn, journal):
    def enveloppe(*a, **kw):
        journal.append(1)
        return fn(*a, **kw)
    return enveloppe


# ── Email ───────────────────────────────────────────────────────────────────────────

def test_l_email_est_normalise(tmp_path):
    """« Baptiste@Example.com » et « baptiste@example.com » sont le MEME compte : sinon un
    client se cree un doublon sans comprendre pourquoi son historique a disparu."""
    assert normaliser_email("  Baptiste@Example.COM ") == "baptiste@example.com"
    s = _store(tmp_path)
    s.creer_compte("Baptiste@Example.COM", "un-mot-de-passe-solide")
    assert s.verifier("baptiste@example.com", "un-mot-de-passe-solide") is not None


def test_un_email_deja_pris_est_refuse(tmp_path):
    s = _store(tmp_path)
    s.creer_compte("baptiste@example.com", "un-mot-de-passe-solide")
    with pytest.raises(EmailDejaPris):
        s.creer_compte("BAPTISTE@example.com", "un-autre-mot-de-passe")


@pytest.mark.parametrize("mauvais", ["", "   ", "sansarobase", "@example.com", "a@", "a@b"])
def test_un_email_malforme_est_refuse(tmp_path, mauvais):
    s = _store(tmp_path)
    with pytest.raises(EmailInvalide):
        s.creer_compte(mauvais, "un-mot-de-passe-solide")


# ── Sessions ────────────────────────────────────────────────────────────────────────

def test_le_jeton_de_session_n_est_pas_stocke_en_clair(tmp_path):
    """MENACE : un jeton stocke en clair transforme une lecture de la base en vol de
    session — l'attaquant se connecte SANS le mot de passe. On stocke une empreinte."""
    s = _store(tmp_path)
    u = s.creer_compte("baptiste@example.com", "un-mot-de-passe-solide")
    jeton = s.creer_session(u.user_id)
    assert jeton and len(jeton) >= 32
    assert jeton.encode() not in (tmp_path / "comptes.db").read_bytes()


def test_une_session_valide_rend_son_utilisateur(tmp_path):
    s = _store(tmp_path)
    u = s.creer_compte("baptiste@example.com", "un-mot-de-passe-solide")
    assert s.session_valide(s.creer_session(u.user_id)) == u.user_id


@pytest.mark.parametrize("jeton", ["", "  ", "jeton-invente", "x" * 64])
def test_un_jeton_inconnu_ou_vide_ne_vaut_rien(tmp_path, jeton):
    s = _store(tmp_path)
    s.creer_compte("baptiste@example.com", "un-mot-de-passe-solide")
    assert s.session_valide(jeton) is None


def test_une_session_expire(tmp_path):
    """MENACE : une session eternelle survit au vol d'un poste ou d'un cookie. Horloge
    injectee, comme partout dans le depot — aucun test ne dort."""
    horloge = {"t": 1_000_000.0}
    s = _store(tmp_path, now=lambda: horloge["t"])
    u = s.creer_compte("baptiste@example.com", "un-mot-de-passe-solide")
    jeton = s.creer_session(u.user_id)
    horloge["t"] += SESSION_TTL_S - 10
    assert s.session_valide(jeton) == u.user_id
    horloge["t"] += 20
    assert s.session_valide(jeton) is None


def test_la_deconnexion_invalide_le_jeton(tmp_path):
    s = _store(tmp_path)
    u = s.creer_compte("baptiste@example.com", "un-mot-de-passe-solide")
    jeton = s.creer_session(u.user_id)
    s.fermer_session(jeton)
    assert s.session_valide(jeton) is None


def test_deux_sessions_du_meme_compte_sont_independantes(tmp_path):
    """Se deconnecter du telephone ne doit pas deconnecter l'ordinateur."""
    s = _store(tmp_path)
    u = s.creer_compte("baptiste@example.com", "un-mot-de-passe-solide")
    j1, j2 = s.creer_session(u.user_id), s.creer_session(u.user_id)
    assert j1 != j2
    s.fermer_session(j1)
    assert s.session_valide(j1) is None
    assert s.session_valide(j2) == u.user_id


# ── Identité des comptes ────────────────────────────────────────────────────────────

def test_le_user_id_n_est_pas_l_email(tmp_path):
    """L'email peut changer ; l'identifiant qui indexe l'historique, l'usage et les jobs ne
    doit jamais bouger. Un email en cle etrangere obligerait a reecrire trois bases pour un
    changement d'adresse — et ferait fuiter l'adresse dans chaque ligne de journal."""
    s = _store(tmp_path)
    u = s.creer_compte("baptiste@example.com", "un-mot-de-passe-solide")
    assert u.user_id and "@" not in u.user_id and u.user_id != u.email


def test_durcir_la_politique_ne_verrouille_pas_les_comptes_existants(tmp_path, monkeypatch):
    """MENACE : la politique de mot de passe a été durcie APRÈS que Baptiste ait créé son
    compte (minimum passé de 10 à 12 caractères, liste de mots courants ajoutée). Si
    `verifier` réappliquait la politique, il se retrouverait enfermé dehors de son propre
    outil, sans aucune procédure de réinitialisation. La politique s'applique à la CRÉATION,
    jamais à la vérification."""
    import auth
    monkeypatch.setattr(auth, "LONGUEUR_MIN_MOT_DE_PASSE", 10)
    s = _store(tmp_path)
    s.creer_compte("ancien@example.com", "dix-caract")     # 10 caractères, valide à l'époque
    monkeypatch.setattr(auth, "LONGUEUR_MIN_MOT_DE_PASSE", 12)   # durcissement ultérieur

    assert s.verifier("ancien@example.com", "dix-caract") is not None, (
        "un compte existant doit continuer à s'ouvrir après un durcissement de la politique")
    # …mais la création, elle, applique bien la nouvelle règle.
    with pytest.raises(MotDePasseFaible):
        s.creer_compte("nouveau@example.com", "dix-caract")
