"""L'essai gratuit — le magasin de comptes (2026-10-15).

Ce que ces tests tiennent, dans l'ordre où un fraudeur le rencontrerait :

1. Un compte a un PLAN (`essai`, `abonne`, `illimite`). Les comptes d'avant la colonne sont locaux : ils passent
   `illimite`. Tout compte créé ensuite est `essai` SAUF demande explicite — défaut pessimiste.
2. Un essai = 2 recherches. Il DÉMARRE à la première, et c'est à ce moment seulement qu'on juge l'identité
   (alias de la même boîte, adresse jetable, réseau, domaine propre) et le plafond GLOBAL de nouveaux essais par
   jour. Créer un compte ne brûle le quota de personne : seul un essai réellement démarré compte.
3. Ce qui a servi ne se rend jamais en supprimant le compte : la table `essais` survit, et elle ne contient que
   des empreintes (jamais l'adresse, le domaine ni le réseau en clair).
4. Tout est ATOMIQUE : vingt comptes qui démarrent en même temps ne dépassent pas le plafond du jour.
"""
import sqlite3
import threading

import pytest

import essai
from auth import UserStore

MDP = "un-mot-de-passe-solide"
JOUR = 24 * 3600


def magasin(tmp_path, t0=1_700_000_000.0):
    horloge = [t0]
    return UserStore(tmp_path / "comptes.db", now=lambda: horloge[0]), horloge


def ouvrir(s, email, plan=essai.PLAN_ESSAI):
    return s.creer_compte(email, MDP, plan=plan)


# ── Le plan ─────────────────────────────────────────────────────────────────────────────

def test_un_compte_est_en_essai_par_defaut(tmp_path):
    s, _ = magasin(tmp_path)
    c = s.creer_compte("a@gmail.com", MDP)
    assert c.plan == essai.PLAN_ESSAI == "essai"
    assert s.plan_de(c.user_id) == "essai"
    assert s.compte(c.user_id).plan == "essai"


def test_le_plan_peut_etre_demande_et_il_est_valide(tmp_path):
    s, _ = magasin(tmp_path)
    assert ouvrir(s, "a@gmail.com", plan=essai.PLAN_ILLIMITE).plan == "illimite"
    assert ouvrir(s, "b@gmail.com", plan=essai.PLAN_ABONNE).plan == "abonne"
    with pytest.raises(ValueError):
        ouvrir(s, "c@gmail.com", plan="gratuit-a-vie")


def test_plan_d_un_compte_inconnu_est_none(tmp_path):
    s, _ = magasin(tmp_path)
    assert s.plan_de("inconnu") is None


def test_les_comptes_d_avant_la_colonne_passent_illimite_les_suivants_essai(tmp_path):
    """Une base créée avant `plan` ne contient que des comptes LOCAUX : les passer en essai verrouillerait
    leur propriétaire dehors de son propre outil."""
    chemin = tmp_path / "comptes.db"
    with sqlite3.connect(chemin) as cx:
        cx.execute("CREATE TABLE comptes (user_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, "
                   "sel BLOB NOT NULL, empreinte BLOB NOT NULL, params TEXT NOT NULL, "
                   "cree_le REAL NOT NULL, email_verifie INTEGER NOT NULL DEFAULT 0)")
        cx.execute("INSERT INTO comptes VALUES ('u1', 'vieux@x.fr', x'00', x'00', 'scrypt:16384:8:1', "
                   "1.0, 1)")
    s = UserStore(chemin)
    assert s.plan_de("u1") == "illimite"
    assert ouvrir(s, "neuf@gmail.com").plan == "essai"
    assert UserStore(chemin).plan_de("u1") == "illimite"          # la migration ne rejoue pas


def test_une_ligne_inseree_sans_plan_est_un_essai_pas_un_illimite(tmp_path):
    """Le DEFAULT de la colonne est le côté sûr : un chemin d'insertion qui oublierait le plan ne fabrique
    pas un compte illimité."""
    s, _ = magasin(tmp_path)
    with sqlite3.connect(s.path) as cx:
        cx.execute("INSERT INTO comptes (user_id, email, sel, empreinte, params, cree_le, email_verifie) "
                   "VALUES ('u9', 'oubli@x.fr', x'00', x'00', 'p', 1.0, 0)")
    assert s.plan_de("u9") == "essai"


# ── Un compte qui n'est pas en essai ────────────────────────────────────────────────────

@pytest.mark.parametrize("plan", [essai.PLAN_ILLIMITE, essai.PLAN_ABONNE])
def test_hors_essai_rien_n_est_compte_ni_refuse(tmp_path, plan):
    s, _ = magasin(tmp_path)
    c = ouvrir(s, "a@gmail.com", plan=plan)
    for _ in range(5):
        assert s.reserver_recherche_essai(c.user_id, client="1.1.1.1", par_jour_max=0) is None
    assert s.situation_essai(c.user_id) is None
    s.rendre_recherche_essai(c.user_id)                         # sans effet, sans erreur


# ── Deux recherches ─────────────────────────────────────────────────────────────────────

def test_deux_recherches_puis_l_essai_est_epuise(tmp_path):
    s, _ = magasin(tmp_path)
    c = ouvrir(s, "a@gmail.com")
    r1 = s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=20)
    r2 = s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=20)
    assert r1.demarre_ici is True and r2.demarre_ici is False
    assert s.situation_essai(c.user_id)["recherches_restantes"] == 0
    with pytest.raises(essai.EssaiEpuise):
        s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=20)


def test_la_situation_dit_ce_qui_reste(tmp_path):
    s, _ = magasin(tmp_path)
    c = ouvrir(s, "a@gmail.com")
    assert s.situation_essai(c.user_id) == {
        "recherches_restantes": 2, "recherches_max": 2, "niches_par_recherche": 5,
        "analyses_detaillees_max": 5, "demarre": False}
    s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=20)
    sit = s.situation_essai(c.user_id)
    assert sit["recherches_restantes"] == 1 and sit["demarre"] is True


def test_rendre_une_recherche_qui_n_a_rien_livre_la_redonne(tmp_path):
    """Une analyse qui échoue à 0 $ ne coûte pas une recherche d'essai — même règle que les niches."""
    s, _ = magasin(tmp_path)
    c = ouvrir(s, "a@gmail.com")
    s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=20)
    s.rendre_recherche_essai(c.user_id)
    assert s.situation_essai(c.user_id)["recherches_restantes"] == 2
    s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=20)
    s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=20)
    with pytest.raises(essai.EssaiEpuise):
        s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=20)


def test_rendre_ne_descend_jamais_sous_zero(tmp_path):
    s, _ = magasin(tmp_path)
    c = ouvrir(s, "a@gmail.com")
    s.rendre_recherche_essai(c.user_id)
    s.rendre_recherche_essai(c.user_id)
    assert s.situation_essai(c.user_id)["recherches_restantes"] == 2


def test_un_lancement_refuse_apres_coup_annule_aussi_le_demarrage(tmp_path):
    """Si la réservation de niches échoue APRÈS le démarrage de l'essai (plafond atteint…), rien n'a tourné :
    l'essai ne doit pas rester « démarré », ni peser sur le plafond du jour."""
    s, _ = magasin(tmp_path)
    c = ouvrir(s, "a@gmail.com")
    r = s.reserver_recherche_essai(c.user_id, client="9.9.9.9", par_jour_max=1)
    s.rendre_recherche_essai(c.user_id, annuler_demarrage=r.demarre_ici)
    assert s.situation_essai(c.user_id)["demarre"] is False
    autre = ouvrir(s, "b@gmail.com")
    assert s.reserver_recherche_essai(autre.user_id, client="1.0.0.1", par_jour_max=1).demarre_ici


def test_une_recherche_rendue_apres_livraison_ne_defait_pas_le_demarrage(tmp_path):
    s, _ = magasin(tmp_path)
    c = ouvrir(s, "a@gmail.com")
    s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=1)
    s.rendre_recherche_essai(c.user_id)                          # règlement d'un échec à 0 $
    assert s.situation_essai(c.user_id)["demarre"] is True       # l'identité reste consommée
    autre = ouvrir(s, "b@gmail.com")
    with pytest.raises(essai.QuotaJournalier):
        s.reserver_recherche_essai(autre.user_id, client=None, par_jour_max=1)


# ── Une identité = un essai ─────────────────────────────────────────────────────────────

def test_les_alias_d_une_meme_boite_ne_donnent_pas_un_second_essai(tmp_path):
    s, _ = magasin(tmp_path)
    a = ouvrir(s, "jean.martin@gmail.com")
    s.reserver_recherche_essai(a.user_id, client=None, par_jour_max=20)
    for alias in ("jeanmartin@gmail.com", "jean.martin+kdp@gmail.com", "j.e.a.n.martin@googlemail.com"):
        b = ouvrir(s, alias)                                     # le compte se crée…
        with pytest.raises(essai.EssaiRefuse):                   # …l'essai, non
            s.reserver_recherche_essai(b.user_id, client=None, par_jour_max=20)
        assert s.situation_essai(b.user_id)["demarre"] is False


def test_un_refus_ne_consomme_rien(tmp_path):
    s, _ = magasin(tmp_path)
    a = ouvrir(s, "jean@gmail.com")
    s.reserver_recherche_essai(a.user_id, client=None, par_jour_max=20)
    b = ouvrir(s, "jean+2@gmail.com")
    with pytest.raises(essai.EssaiRefuse):
        s.reserver_recherche_essai(b.user_id, client=None, par_jour_max=20)
    assert s.situation_essai(b.user_id)["recherches_restantes"] == 2


def test_supprimer_son_compte_ne_rend_pas_l_essai(tmp_path):
    """Fermer le compte efface sa consommation (décision antérieure) : sans mémoire à part, « fermer puis
    rouvrir avec la même adresse » donnerait un essai neuf à l'infini."""
    s, _ = magasin(tmp_path)
    a = ouvrir(s, "jean@gmail.com")
    s.reserver_recherche_essai(a.user_id, client=None, par_jour_max=20)
    s.supprimer_compte("jean@gmail.com", MDP)
    b = ouvrir(s, "jean@gmail.com")
    with pytest.raises(essai.EssaiRefuse):
        s.reserver_recherche_essai(b.user_id, client=None, par_jour_max=20)


def test_l_identite_est_oubliee_apres_un_an(tmp_path):
    s, h = magasin(tmp_path)
    a = ouvrir(s, "jean@gmail.com")
    s.reserver_recherche_essai(a.user_id, client=None, par_jour_max=20)
    h[0] += 364 * JOUR
    b = ouvrir(s, "jean+bis@gmail.com")
    with pytest.raises(essai.EssaiRefuse):
        s.reserver_recherche_essai(b.user_id, client=None, par_jour_max=20)
    h[0] += 2 * JOUR
    assert s.reserver_recherche_essai(b.user_id, client=None, par_jour_max=20).demarre_ici


def test_l_essai_ne_garde_que_des_empreintes(tmp_path):
    s, _ = magasin(tmp_path)
    a = ouvrir(s, "Jean.Martin@Mon-Site.fr")
    s.reserver_recherche_essai(a.user_id, client="151.101.1.77", par_jour_max=20)
    with sqlite3.connect(s.path) as cx:
        lignes = cx.execute("SELECT * FROM essais").fetchall()
        tout = " ".join(str(v) for ligne in lignes for v in ligne).lower()
    assert len(lignes) == 1
    for clair in ("jean", "martin", "mon-site", "151.101.1.77", "@"):
        assert clair not in tout, clair


def test_deux_essais_de_meme_identite_ont_la_meme_empreinte(tmp_path):
    """L'empreinte est stable (même clé, même entrée) : c'est ce qui permet de comparer sans stocker le clair."""
    s, _ = magasin(tmp_path)
    a = ouvrir(s, "jean@gmail.com")
    s.reserver_recherche_essai(a.user_id, client=None, par_jour_max=20)
    with sqlite3.connect(s.path) as cx:
        (avant,) = cx.execute("SELECT identite FROM essais").fetchone()
    assert avant == UserStore(s.path)._empreinte("identite", essai.identite_courriel("jean@gmail.com"))


# ── Adresses jetables, domaines, réseaux ────────────────────────────────────────────────

def test_une_adresse_jetable_n_ouvre_pas_d_essai(tmp_path):
    s, _ = magasin(tmp_path)
    for adresse in ("x@mailinator.com", "y@sous.yopmail.com"):
        c = ouvrir(s, adresse)
        with pytest.raises(essai.EssaiRefuse):
            s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=20)


def test_un_domaine_propre_est_plafonne_a_trois_essais_par_mois(tmp_path):
    """Le moyen le moins cher de fabriquer des adresses sans limite : acheter un domaine et tout y recevoir."""
    s, h = magasin(tmp_path)
    for i in range(essai.ESSAI_PAR_DOMAINE):
        c = ouvrir(s, f"a{i}@mon-site.fr")
        assert s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=50).demarre_ici
    quatrieme = ouvrir(s, "a9@mon-site.fr")
    with pytest.raises(essai.EssaiRefuse):
        s.reserver_recherche_essai(quatrieme.user_id, client=None, par_jour_max=50)
    h[0] += 31 * JOUR
    assert s.reserver_recherche_essai(quatrieme.user_id, client=None, par_jour_max=50).demarre_ici


def test_un_fournisseur_grand_public_n_est_pas_plafonne_par_domaine(tmp_path):
    s, _ = magasin(tmp_path)
    for i in range(essai.ESSAI_PAR_DOMAINE + 4):
        c = ouvrir(s, f"personne{i}@gmail.com")
        assert s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=50).demarre_ici


def test_un_meme_reseau_est_plafonne_par_mois(tmp_path):
    s, h = magasin(tmp_path)
    for i in range(essai.ESSAI_PAR_RESEAU):
        c = ouvrir(s, f"p{i}@gmail.com")
        assert s.reserver_recherche_essai(c.user_id, client="8.8.8.8", par_jour_max=50).demarre_ici
    quatrieme = ouvrir(s, "p9@gmail.com")
    with pytest.raises(essai.EssaiRefuse):
        s.reserver_recherche_essai(quatrieme.user_id, client="8.8.8.8", par_jour_max=50)
    # un autre réseau passe ; le même, un mois plus tard, aussi
    assert s.reserver_recherche_essai(quatrieme.user_id, client="208.67.222.222", par_jour_max=50).demarre_ici
    h[0] += 31 * JOUR
    cinquieme = ouvrir(s, "p10@gmail.com")
    assert s.reserver_recherche_essai(cinquieme.user_id, client="8.8.8.8", par_jour_max=50).demarre_ici


def test_un_reseau_prive_ou_illisible_ne_bloque_personne(tmp_path):
    """Derrière un proxy mal réglé tout le monde arrive de la même adresse privée : la compter refuserait
    tous les visiteurs au quatrième. Sans signal, pas de refus."""
    s, _ = magasin(tmp_path)
    for i, client in enumerate(["10.0.0.5", "127.0.0.1", "testclient", None, "100.64.0.3", "10.0.0.5"]):
        c = ouvrir(s, f"q{i}@gmail.com")
        assert s.reserver_recherche_essai(c.user_id, client=client, par_jour_max=50).demarre_ici


# ── Le plafond du jour ──────────────────────────────────────────────────────────────────

def test_le_plafond_du_jour_borne_les_nouveaux_essais(tmp_path):
    s, h = magasin(tmp_path)
    a, b, c = (ouvrir(s, f"u{i}@gmail.com") for i in range(3))
    s.reserver_recherche_essai(a.user_id, client=None, par_jour_max=2)
    s.reserver_recherche_essai(b.user_id, client=None, par_jour_max=2)
    with pytest.raises(essai.QuotaJournalier):
        s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=2)
    assert s.situation_essai(c.user_id)["demarre"] is False
    h[0] += JOUR + 1                                             # fenêtre glissante de 24 h
    assert s.reserver_recherche_essai(c.user_id, client=None, par_jour_max=2).demarre_ici


def test_le_plafond_du_jour_ne_coupe_pas_un_essai_deja_demarre(tmp_path):
    """Il borne les NOUVEAUX essais : celui qui a commencé finit ses deux recherches même un jour de
    saturation, sinon on lui retire ce qu'on lui a promis."""
    s, _ = magasin(tmp_path)
    a = ouvrir(s, "u@gmail.com")
    s.reserver_recherche_essai(a.user_id, client=None, par_jour_max=1)
    assert s.reserver_recherche_essai(a.user_id, client=None, par_jour_max=0).demarre_ici is False


def test_un_plafond_du_jour_nul_ferme_le_robinet(tmp_path):
    s, _ = magasin(tmp_path)
    a = ouvrir(s, "u@gmail.com")
    with pytest.raises(essai.QuotaJournalier):
        s.reserver_recherche_essai(a.user_id, client=None, par_jour_max=0)


def test_un_refus_d_identite_passe_avant_le_message_du_plafond_du_jour(tmp_path):
    """« Revenez demain » à quelqu'un qui n'y aura jamais droit serait un mensonge qui le fait revenir."""
    s, _ = magasin(tmp_path)
    a = ouvrir(s, "jean@gmail.com")
    s.reserver_recherche_essai(a.user_id, client=None, par_jour_max=1)
    b = ouvrir(s, "jean+2@gmail.com")
    with pytest.raises(essai.EssaiRefuse):
        s.reserver_recherche_essai(b.user_id, client=None, par_jour_max=1)


def test_vingt_departs_simultanes_ne_depassent_pas_le_plafond_du_jour(tmp_path):
    """Le plafond protège l'argent : une course ne doit pas le laisser passer. Même idiome que
    `reserver_analyse` (verrou d'écriture pris AVANT de compter)."""
    s, _ = magasin(tmp_path)
    comptes = [ouvrir(s, f"c{i}@gmail.com") for i in range(20)]
    ok, refuses, erreurs = [], [], []
    verrou = threading.Lock()

    def tenter(compte):
        try:
            s.reserver_recherche_essai(compte.user_id, client=None, par_jour_max=3)
            res = ok
        except essai.QuotaJournalier:
            res = refuses
        except Exception as e:  # noqa: BLE001
            with verrou:
                erreurs.append(repr(e))
            return
        with verrou:
            res.append(compte.user_id)

    fils = [threading.Thread(target=tenter, args=(c,)) for c in comptes]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    assert not erreurs, erreurs
    assert len(ok) == 3 and len(refuses) == 17
