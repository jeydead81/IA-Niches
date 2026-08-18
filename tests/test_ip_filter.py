"""Filtre IP/marques — le seul filtre du dépôt dont l'enjeu est juridique.

Les autres garde-fous protègent un chiffre. Celui-ci protège le compte KDP : un cahier de
coloriage « pat patrouille » n'est pas une niche moyenne, c'est un retrait de publication
et, répété, une fermeture de compte. Or l'autocomplete en est PLEIN — c'est précisément ce
que les gens tapent, donc c'est ce que l'arbre remonte en premier.

Il tourne CÔTÉ CODE et AVANT l'appel LLM, pour deux raisons distinctes :
- le prompt système demande déjà au modèle de ne pas proposer de marques, mais §4.2 est
  formel : ce qui n'est pas doublé en code n'est pas une règle, c'est une intention ;
- filtrer avant l'appel évite de payer des tokens pour classer « coloriage pat patrouille »
  et de le voir revenir dans le rapport.

Chaque rejet sort avec son MOTIF. Un rejet muet ferait croire à un rayon vide.
"""
import pytest

from ip_filter import charger_termes, filtrer_ip, terme_ip


class _Niche:
    """Sosie minimal de LowContentNiche : le filtre ne doit dépendre que de trois champs,
    pas du modèle complet — il tourne aussi sur des suggestions brutes."""

    def __init__(self, niche="", requete_amazon="", satellite_keywords=None):
        self.niche = niche
        self.requete_amazon = requete_amazon
        self.satellite_keywords = satellite_keywords or []


# ── Détection ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texte", [
    "coloriage pat patrouille",
    "cahier d'activités Pokémon",
    "coloriage LICORNE harry potter",
    "carnet de notes Marvel",
    "coloriage mario kart",
])
def test_une_marque_est_detectee_quelle_que_soit_la_casse(texte):
    assert terme_ip(texte) is not None


def test_le_motif_rendu_est_le_terme_qui_a_declenche():
    """« rejeté » ne dit rien à l'auteur ; « pokemon » lui dit quoi changer."""
    assert terme_ip("coloriage pokemon 6 ans") == "pokemon"


def test_les_accents_ne_font_pas_passer_une_marque():
    """« Pokémon » et « pokemon » sont la même marque. Comparer sans dépouiller laisserait
    passer l'orthographe la plus courante."""
    assert terme_ip("coloriage Pokémon") == "pokemon"


def test_une_niche_ordinaire_passe():
    assert terme_ip("carnet de suivi glycémie") is None
    assert terme_ip("registre du personnel obligatoire") is None


def test_le_filtre_ne_mord_pas_sur_un_fragment_de_mot():
    """LE piège de ce module. Une comparaison par sous-chaîne fait sortir « om » (club de
    foot) de « coloriage bonhomme », et « psg » ne doit pas sortir d'un mot plus long.
    Un faux positif écarte une niche valable en silence, avant toute mesure."""
    assert terme_ip("coloriage bonhomme de neige") is None
    assert terme_ip("carnet de bord pompier") is None
    assert terme_ip("cahier de vacances CM2") is None


def test_une_marque_en_plusieurs_mots_est_reconnue():
    assert terme_ip("coloriage pat patrouille") == "pat patrouille"


# ── Filtrage d'une liste ───────────────────────────────────────────────────────

def test_filtrer_rend_les_gardees_et_les_rejets_motives():
    niches = [
        _Niche(niche="coloriage licorne", requete_amazon="coloriage licorne 3 ans"),
        _Niche(niche="coloriage pokemon", requete_amazon="coloriage pokemon"),
    ]
    gardees, rejets = filtrer_ip(niches)
    assert [n.niche for n in gardees] == ["coloriage licorne"]
    assert len(rejets) == 1
    objet, motif = rejets[0]
    assert objet.niche == "coloriage pokemon" and motif == "pokemon"


def test_une_marque_cachee_dans_un_satellite_fait_rejeter_la_niche():
    """La requête principale peut être propre pendant qu'un satellite porte la marque —
    et les satellites finissent dans les mots-clés KDP, donc sur la fiche produit."""
    n = _Niche(niche="coloriage voiture", requete_amazon="coloriage voiture",
               satellite_keywords=["coloriage cars disney"])
    gardees, rejets = filtrer_ip([n])
    assert gardees == [] and rejets[0][1] == "disney"


def test_filtrer_accepte_des_chaines_nues():
    """Le filtre tourne AUSSI sur les suggestions brutes de l'arbre, avant qu'aucun
    modèle n'existe — c'est même là qu'il coûte le moins cher."""
    gardees, rejets = filtrer_ip(["coloriage licorne", "coloriage barbie"])
    assert gardees == ["coloriage licorne"]
    assert rejets == [("coloriage barbie", "barbie")]


def test_une_liste_vide_ne_leve_pas():
    assert filtrer_ip([]) == ([], [])


# ── La liste elle-même ─────────────────────────────────────────────────────────

def test_la_liste_est_lue_depuis_un_fichier_versionne():
    """Une liste en dur dans le .py obligerait à un commit de code pour ajouter une
    franchise. Elle vivra, et c'est Baptiste qui la fera vivre."""
    termes = charger_termes()
    assert len(termes) >= 30
    for attendu in ("disney", "pokemon", "harry potter", "lego", "pat patrouille"):
        assert attendu in termes


def test_les_commentaires_et_lignes_vides_sont_ignores():
    """Le fichier est édité à la main : il doit tolérer des commentaires, sinon personne
    ne saura pourquoi une entrée y est."""
    termes = charger_termes()
    assert not any(t.startswith("#") for t in termes)
    assert all(t.strip() == t and t for t in termes)


def test_les_termes_sont_normalises_a_la_lecture():
    """Comparer un terme accentué à un texte dépouillé ne matcherait jamais."""
    assert all(t == t.lower() for t in charger_termes())


# ── Sigles : la ligne de crête du module ───────────────────────────────────────

def test_les_sigles_de_clubs_courants_sont_couverts():
    """Manqué à la première passe : la liste portait « paris saint-germain » mais pas
    « psg », alors que c'est la forme que les gens tapent."""
    assert terme_ip("coloriage psg") == "psg"


def test_om_n_est_deliberement_PAS_dans_la_liste():
    """« om » est aussi le mantra. « carnet de méditation om » est une niche parfaitement
    valable et serait rejetée en silence. Le club est couvert par sa forme longue.

    Ce test existe pour empêcher qu'on l'ajoute « par cohérence » avec « psg » — la
    décision est asymétrique, et elle est motivée dans data/exclusions_ip.md."""
    assert "om" not in charger_termes()
    assert terme_ip("carnet de méditation om") is None
    assert terme_ip("olympique de marseille coloriage") == "olympique de marseille"
