"""L'essai gratuit — les règles PURES (2026-10-15).

Un essai sans carte bancaire n'a qu'une identité à offrir : une adresse e-mail. Ce module ne cherche
pas à l'empêcher d'être multipliée — c'est impossible sans carte ni téléphone — il élève le coût de
chaque identité de plus et BORNE ce que toutes ensemble peuvent coûter (cf. `tests/test_auth_essai.py`
pour le quota global par jour).

Les règles testées ici ne touchent aucune base :
- `identite_courriel` : les alias d'une même boîte (`a.b@gmail.com`, `ab+x@gmail.com`) sont UNE identité ;
- `domaine` / `est_jetable` / `est_courant` : adresses à usage unique et fournisseurs grand public ;
- `empreinte_reseau` : l'adresse du client, ou RIEN quand elle ne prouve rien (réseau privé d'un
  hébergeur, adresse illisible). Un contrôle qui n'a pas pu se faire n'est pas un refus (règle 3).
"""
import ipaddress
from pathlib import Path

import pytest

import essai

RACINE = Path(__file__).resolve().parent.parent


# ── Identité d'une adresse ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("brut, attendu", [
    ("Marie@Example.COM", "marie@example.com"),
    ("  marie@example.com ", "marie@example.com"),
    ("marie+essai2@example.com", "marie@example.com"),        # +suffixe : le même courrier
    ("marie+a+b@example.com", "marie@example.com"),
    ("marie.dupont@gmail.com", "mariedupont@gmail.com"),      # Gmail ignore les points
    ("m.a.r.i.e@gmail.com", "marie@gmail.com"),
    ("marie.dupont+x@googlemail.com", "mariedupont@gmail.com"),   # googlemail.com == gmail.com
    ("marie.dupont@outlook.fr", "marie.dupont@outlook.fr"),   # ailleurs, les points comptent
    ("marie.dupont@entreprise.fr", "marie.dupont@entreprise.fr"),
])
def test_identite_courriel_ramene_les_alias_a_une_seule_boite(brut, attendu):
    assert essai.identite_courriel(brut) == attendu


@pytest.mark.parametrize("brut", ["", "pas-une-adresse", "@x.fr", None, 42])
def test_identite_courriel_illisible_rend_une_chaine_vide(brut):
    """Jamais une exception, jamais une identité inventée : un appelant qui reçoit « » sait qu'il n'a pas
    d'identité à comparer."""
    assert essai.identite_courriel(brut) == ""


def test_deux_alias_de_la_meme_boite_ont_la_meme_identite():
    assert (essai.identite_courriel("jean.martin@gmail.com")
            == essai.identite_courriel("jeanmartin+kdp@gmail.com")
            == essai.identite_courriel("J.E.A.N.martin@googlemail.com"))


def test_deux_boites_differentes_n_ont_pas_la_meme_identite():
    assert essai.identite_courriel("jean@gmail.com") != essai.identite_courriel("jeanne@gmail.com")
    assert essai.identite_courriel("a@x.fr") != essai.identite_courriel("a@y.fr")


# ── Domaines ────────────────────────────────────────────────────────────────────────────

def test_domaine_de_l_adresse():
    assert essai.domaine("Marie@Mon-Site.FR") == "mon-site.fr"
    assert essai.domaine("pas-une-adresse") == ""
    assert essai.domaine(None) == ""


def test_les_domaines_jetables_connus_sont_refuses_sous_domaines_compris():
    assert essai.est_jetable("mailinator.com")
    assert essai.est_jetable("YOPMAIL.com")                       # casse ignorée
    assert essai.est_jetable("sous.mailinator.com")               # sous-domaine d'un service jetable
    assert not essai.est_jetable("gmail.com")
    assert not essai.est_jetable("monmailinator.com")             # un mot qui CONTIENT n'est pas un sous-domaine
    assert not essai.est_jetable("")


def test_les_fournisseurs_grand_public_ne_sont_pas_plafonnes_par_domaine():
    for d in ("gmail.com", "outlook.fr", "hotmail.fr", "orange.fr", "free.fr", "laposte.net",
              "sfr.fr", "icloud.com", "proton.me", "yahoo.fr", "wanadoo.fr"):
        assert essai.est_courant(d), d
    assert not essai.est_courant("mon-site.fr")                   # domaine propre : plafonné
    assert not essai.est_courant("")


def test_les_listes_sont_des_fichiers_de_donnees_versionnes_et_coherents():
    """Deux fichiers texte, un domaine par ligne, que Baptiste étend sans toucher au code. Un domaine ne peut
    pas être à la fois jetable et grand public (il serait refusé ET exempté)."""
    jetables = essai.charger_liste(RACINE / "data" / "domaines_jetables.txt")
    courants = essai.charger_liste(RACINE / "data" / "domaines_courants.txt")
    assert len(jetables) >= 30 and len(courants) >= 30
    assert not (jetables & courants)
    for d in jetables | courants:
        assert d == d.lower() and "@" not in d and "." in d and " " not in d, d


def test_charger_liste_ignore_commentaires_lignes_vides_et_casse(tmp_path):
    f = tmp_path / "liste.txt"
    f.write_text("# commentaire\n\nExemple.COM\n  autre.fr  # note en fin de ligne\n", encoding="utf-8")
    assert essai.charger_liste(f) == {"exemple.com", "autre.fr"}


def test_une_liste_absente_leve_au_lieu_de_ne_rien_filtrer(tmp_path):
    """Un fichier manquant ne doit JAMAIS se lire « aucun domaine jetable » : le filtre se désactiverait
    sans un mot."""
    with pytest.raises(FileNotFoundError):
        essai.charger_liste(tmp_path / "absente.txt")


# ── Adresse du client ───────────────────────────────────────────────────────────────────

def test_une_adresse_publique_ipv4_est_un_signal():
    assert essai.empreinte_reseau("8.8.8.8") == "8.8.8.8"
    assert essai.empreinte_reseau("  8.8.8.8 ") == "8.8.8.8"


def test_ipv6_est_ramenee_a_son_prefixe_64():
    """Un abonné IPv6 reçoit un /64 entier : compter l'adresse exacte laisserait 2^64 identités gratuites."""
    a = essai.empreinte_reseau("2a01:e0a:1:2:aaaa:bbbb:cccc:dddd")
    b = essai.empreinte_reseau("2a01:e0a:1:2:1111:2222:3333:4444")
    c = essai.empreinte_reseau("2a01:e0a:1:3:1111:2222:3333:4444")
    assert a == b and a != c
    assert ipaddress.ip_network(a, strict=True).prefixlen == 64


def test_une_adresse_ipv4_enveloppee_dans_ipv6_est_lue_comme_ipv4():
    assert essai.empreinte_reseau("::ffff:8.8.8.8") == "8.8.8.8"


@pytest.mark.parametrize("brut", [
    "127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.1.20",     # réseau local / privé
    "100.64.0.7",                                             # partage d'adresse d'un opérateur
    "169.254.1.1", "::1", "fd00::1",                          # lien local, loopback, ULA
    "testclient", "inconnu", "", None, "999.1.1.1", 12,       # illisible : aucune preuve
])
def test_une_adresse_qui_ne_prouve_rien_ne_donne_aucun_signal(brut):
    """Derrière un proxy mal réglé, tous les visiteurs arrivent avec LA MÊME adresse privée : la compter
    bloquerait tout le monde au quatrième essai. Pas de signal vaut pas de refus."""
    assert essai.empreinte_reseau(brut) is None


# ── Réglages ────────────────────────────────────────────────────────────────────────────

def test_les_constantes_de_l_offre():
    """Décision de Baptiste du 2026-10-15 : 2 recherches différentes, 5 niches au plus chacune, puis 5 analyses
    détaillées (une par niche d'une recherche) — il avait d'abord envisagé 1 recherche, écartée : un seul run
    peut sortir « non mesuré » et gâcher tout l'essai."""
    assert essai.ESSAI_RECHERCHES == 2
    assert essai.ESSAI_NICHES_PAR_RECHERCHE == 5
    assert essai.ESSAI_APPELS_A_LA_PIECE == 5
    assert essai.ESSAI_RECHERCHES * essai.ESSAI_NICHES_PAR_RECHERCHE == 10


def test_essais_par_jour_max_defaut_et_lecture_de_l_environnement(monkeypatch):
    monkeypatch.delenv("ESSAIS_PAR_JOUR_MAX", raising=False)
    assert essai.essais_par_jour_max() == 10          # prudent au démarrage ; à monter les jours de promotion
    monkeypatch.setenv("ESSAIS_PAR_JOUR_MAX", "5")
    assert essai.essais_par_jour_max() == 5
    monkeypatch.setenv("ESSAIS_PAR_JOUR_MAX", "100")
    assert essai.essais_par_jour_max() == 100
    monkeypatch.setenv("ESSAIS_PAR_JOUR_MAX", "0")           # 0 = robinet fermé, pas « illimité »
    assert essai.essais_par_jour_max() == 0


@pytest.mark.parametrize("valeur", ["beaucoup", "-3", "2.5", " "])
def test_une_valeur_illisible_retombe_sur_le_defaut_jamais_sur_illimite(monkeypatch, valeur):
    monkeypatch.setenv("ESSAIS_PAR_JOUR_MAX", valeur)
    assert essai.essais_par_jour_max() == 10
