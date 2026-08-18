"""Taxonomie low-content — le contrat que l'ideator et le scoring lisent tous les deux.

Même rôle que `fiction_taxonomy` : borner ce que le LLM a le droit de proposer, et servir
de source unique aux libellés. Un format inventé par le modèle serait invérifiable, et un
libellé recopié en dur côté JS se périmerait à la première v2.

Le test itère sur TOUS les formats plutôt que d'en vérifier trois : un format incomplet
doit faire échouer la suite, pas un run en production — c'est-à-dire pas après que
l'utilisateur a payé.

Deux notions portées par la taxo et pas par le code :
- `norme: true` — le contenu est fixé par une règle externe (Code du travail, HACCP, ERP).
  La faisabilité est haute, mais le verdict DOIT citer la source (E7) : un registre
  incomplet prend des avis à une étoile.
- `effort` — 1 à 3. Un carnet quadrillé et un cahier d'activités illustré ne se produisent
  pas dans le même monde, et le scoring doit pouvoir le dire.
"""
import pytest

from lowcontent_taxonomy import (est_editeur_traditionnel, est_indie, est_norme,
                                 est_saisonnier, format_, load_taxonomy, valid_formats)


@pytest.fixture(scope="module")
def taxo() -> dict:
    return load_taxonomy("fr_v1")


# ── Contrat de structure ───────────────────────────────────────────────────────

def test_chaque_format_porte_tous_ses_champs(taxo):
    """Un format à qui il manque `pages` fait planter `redevance_estimee` en plein run
    payant. On préfère que ça casse ici."""
    requis = ("label", "famille", "patterns", "effort", "illustration", "norme",
              "pages", "prix_typique")
    for cle, f in taxo["formats"].items():
        for champ in requis:
            assert champ in f, f"format « {cle} » : champ « {champ} » manquant"


def test_l_effort_est_un_des_trois_niveaux(taxo):
    for cle, f in taxo["formats"].items():
        assert f["effort"] in (1, 2, 3), f"{cle} : effort={f['effort']}"


@pytest.mark.parametrize("champ", ["pages", "prix_typique"])
def test_les_fourchettes_sont_ordonnees(taxo, champ):
    """Une fourchette inversée passerait tous les tests de type et rendrait des malus
    absurdes au scoring."""
    for cle, f in taxo["formats"].items():
        bas, haut = f[champ]
        assert bas <= haut, f"{cle} : {champ} = [{bas}, {haut}]"


def test_chaque_format_propose_au_moins_un_patron_de_requete(taxo):
    """Les `patterns` servent de graine en mode « à partir de rien » : sans eux, le
    format ne peut pas amorcer d'arbre d'autocomplete."""
    for cle, f in taxo["formats"].items():
        assert f["patterns"], f"{cle} : aucun pattern"
        assert any("{theme}" in p for p in f["patterns"]), \
            f"{cle} : aucun pattern paramétré par {{theme}}"


def test_les_familles_annoncees_couvrent_tous_les_formats(taxo):
    """L'UI groupe le sélecteur par famille : un format dont la famille n'existe nulle
    part ailleurs tomberait dans un groupe fantôme."""
    familles = {f["famille"] for f in taxo["formats"].values()}
    assert familles >= {"carnets", "pro", "coloriage", "grilles", "jeux_esprit",
                        "enfant", "specialises"}


def test_les_sept_familles_sont_toutes_peuplees(taxo):
    """Le jeu de validation (G1) exige au moins 3 requêtes par famille : une famille
    vide rendrait ce critère intenable."""
    from collections import Counter
    c = Counter(f["famille"] for f in taxo["formats"].values())
    for famille in ("carnets", "pro", "coloriage", "grilles", "enfant"):
        assert c[famille] >= 2, f"famille « {famille} » : {c[famille]} format(s)"


def test_les_publics_sont_declares(taxo):
    assert "adulte" in taxo["publics"] and "professionnel" in taxo["publics"]


# ── Formats normés ─────────────────────────────────────────────────────────────

def test_les_registres_reglementaires_sont_marques_normes(taxo):
    """`norme: true` déclenche le risque `norme_a_verifier` (E4) et l'obligation de
    citer une source réglementaire dans le verdict (E7)."""
    assert est_norme("registres_reglementaires") is True
    assert est_norme("coloriage_adulte") is False


def test_un_format_norme_reste_facile_a_produire(taxo):
    """Piège de lecture : « normé » ne veut pas dire « difficile ». Le contenu est
    IMPOSÉ, donc simple à produire — c'est la conformité qui est exigeante, pas la mise
    en page. Confondre les deux ferait fuir l'auteur du rayon le plus accessible."""
    assert format_("registres_reglementaires")["effort"] == 1


def test_format_inconnu_leve(taxo):
    """Silencieux, ça ferait croire à l'auteur que sa contrainte est appliquée — même
    règle que la taxonomie fiction."""
    with pytest.raises((KeyError, ValueError)):
        format_("format_qui_n_existe_pas")


def test_valid_formats_rend_les_cles_de_la_taxo(taxo):
    cles = valid_formats()
    assert "registres_reglementaires" in cles and "mots_meles" in cles
    assert len(cles) == len(taxo["formats"])


# ── Éditeurs ───────────────────────────────────────────────────────────────────

def test_un_editeur_traditionnel_est_reconnu_malgre_la_casse():
    assert est_editeur_traditionnel("HACHETTE") is True
    assert est_editeur_traditionnel("Éditions Larousse") is True


def test_independently_published_est_le_marqueur_indie():
    assert est_indie("Independently published") is True
    assert est_indie("Hachette") is False


def test_un_editeur_inconnu_rend_None_et_jamais_False():
    """LE point du module. `False` voudrait dire « ce n'est pas de l'indie », donc
    « c'est un éditeur installé » — une conclusion. `None` dit qu'on ne sait pas, et le
    scoring l'exclut du dénominateur au lieu de le compter contre la niche (§5.10)."""
    assert est_indie("Presses du Marais") is None
    assert est_indie("") is None
    assert est_indie(None) is None


# ── Saisonnalité ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texte", ["carnet de noël", "agenda 2027",
                                   "coloriage halloween", "cahier de vacances d'été"])
def test_la_saisonnalite_est_detectee_sans_accent_ni_casse(texte):
    """Amazon rend « noel » et « noël » : comparer sans dépouiller manquerait la moitié
    des cas."""
    assert est_saisonnier(texte) is True


def test_un_carnet_ordinaire_n_est_pas_saisonnier():
    assert est_saisonnier("carnet de suivi glycémie") is False


def test_la_saisonnalite_ne_se_declenche_pas_sur_un_fragment_de_mot():
    """« paques » ne doit pas sortir de « paquet ». Un faux positif écarte une niche
    valable AVANT tout appel payant, donc sans que rien ne le rattrape."""
    assert est_saisonnier("carnet de suivi des paquets") is False
