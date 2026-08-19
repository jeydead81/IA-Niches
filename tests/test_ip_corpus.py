"""Le filtre IP mesuré sur un corpus adversarial, pas sur une poignée d'exemples choisis.

Le filtre existant attrapait « pokemon » et laissait passer « pokemons ». Il attrapait
« spider-man » et laissait passer « spider man ». Il portait « les minions » et laissait
passer « minions ». Mesuré sur 198 requêtes low-content françaises portant une marque sous
une forme mutée : **198 échappaient**, soit la totalité.

Le corpus a été construit pour ça — il ne contient QUE des formes que le filtre d'alors
manquait — donc 100 % n'est pas une surprise, c'est la définition. Ce qui compte est
l'autre bout : combien on en rattrape après correction, et surtout combien de niches
LÉGITIMES on écarte au passage.

L'ASYMÉTRIE EST LE CŒUR DU SUJET. Un faux négatif coûte un compte KDP fermé. Un faux
positif coûte une niche perdue, en silence, avant toute mesure. Les deux sont graves, mais
pas également : c'est pourquoi le seuil de rattrapage tolère des trous, et celui de faux
positifs est à ZÉRO.

La mesure a d'ailleurs révélé cinq faux positifs qui existaient DÉJÀ : « bts » attrapait
« cahier de révision BTS MCO », « puma » attrapait « coloriage puma animal sauvage ».
Personne ne les avait vus, parce qu'un rejet muet ne se remarque pas.
"""
import json
from pathlib import Path

import pytest

from ip_filter import terme_ip

_CORPUS = Path(__file__).parent / "fixtures" / "corpus_ip.json"

# Deux faux positifs ASSUMÉS, chacun avec sa raison. Les nommer ici plutôt que de relâcher
# l'assertion : un seuil « 2 faux positifs tolérés » laisserait passer les deux SUIVANTS
# sans que personne s'en aperçoive.
#
# La règle qui les a tranchés : on RETIRE de la liste un terme dont l'usage légitime est
# une CATÉGORIE COURANTE du low-content (« bts » = cahiers de révision, « puma » = coloriage
# animalier, tous deux retirés) ; on le GARDE quand l'usage légitime est INCIDENT. Ces deux-là
# sont incidents — et les carnets sous marque de sport ou de voiture sont un risque réel.
ARBITRES = {
    "livre d'or famille ferrari",              # patronyme italien courant
    "coloriage mythologie grecque nike deesse",  # la déesse grecque
}


@pytest.fixture(scope="module")
def corpus() -> dict:
    return json.loads(_CORPUS.read_text(encoding="utf-8"))


def test_le_corpus_est_consequent(corpus):
    """Un corpus de dix exemples ne mesure rien : il se règle à la main sans rien prouver."""
    assert len(corpus["doivent_etre_bloquees"]) >= 150
    assert len(corpus["doivent_passer"]) >= 100


def test_AUCUNE_niche_legitime_n_est_ecartee(corpus):
    """Seuil à ZÉRO, et pas par perfectionnisme : un faux positif écarte une niche valable
    EN SILENCE et avant toute mesure. Rien en aval ne peut le rattraper, puisque la niche
    n'atteint jamais la phase payante — l'auteur ne saura même pas qu'elle a existé."""
    fautifs = [(x["requete"], terme_ip(x["requete"]))
               for x in corpus["doivent_passer"]
               if terme_ip(x["requete"]) and x["requete"] not in ARBITRES]
    assert fautifs == [], f"niches légitimes rejetées : {fautifs}"


def test_les_arbitrages_restent_des_arbitrages_pas_des_oublis(corpus):
    """Les exceptions ci-dessus sont NOMMÉES, pas tolérées en silence. Si l'une cessait
    d'être rejetée, ce test le dirait — parce qu'une exception qui ne sert plus doit
    disparaître, pas rester en travers du chemin comme une dette."""
    for requete in ARBITRES:
        assert terme_ip(requete) is not None, (
            f"« {requete} » n'est plus rejetée : l'exception peut être retirée")


def test_au_moins_neuf_marques_sur_dix_sont_attrapees(corpus):
    """Pas 100 % : une marque peut toujours s'écrire d'une façon qu'aucune liste ne prévoit
    (« sonik le hérisson », « jurassic parc »). Le filtre est une PREMIÈRE LIGNE, jamais
    une garantie juridique — c'est écrit dans `data/exclusions_ip.md` et ça doit le rester.
    Mais laisser passer une forme sur deux n'est pas une première ligne, c'est une passoire."""
    rates = [x for x in corpus["doivent_etre_bloquees"] if terme_ip(x["requete"]) is None]
    taux = 1 - len(rates) / len(corpus["doivent_etre_bloquees"])
    assert taux >= 0.90, (
        f"seulement {taux:.0%} des marques attrapées ; "
        f"exemples manqués : {[x['requete'] for x in rates[:8]]}")


@pytest.mark.parametrize("mutation", ["apostrophe", "trait-union", "espace", "pluriel",
                                      "determinant", "agglutine"])
def test_chaque_famille_de_mutation_est_couverte(corpus, mutation):
    """Mesuré PAR FAMILLE : un taux global peut cacher une classe entière manquée. Les six
    familles ci-dessous relèvent du MATCHER — elles doivent être couvertes sans ajouter la
    moindre entrée à la liste, sinon on ne fait que jouer au chat et à la souris."""
    cas = [x for x in corpus["doivent_etre_bloquees"] if x["mutation"] == mutation]
    assert cas, f"aucun cas de mutation « {mutation} » dans le corpus"
    rates = [x["requete"] for x in cas if terme_ip(x["requete"]) is None]
    taux = 1 - len(rates) / len(cas)
    assert taux >= 0.85, f"« {mutation} » : {taux:.0%} attrapés, manqués : {rates[:5]}"


# ── Les mutations, cas par cas et lisibles ─────────────────────────────────────

@pytest.mark.parametrize("requete,attendu", [
    ("coloriage pat’patrouille gratuit", "apostrophe typographique U+2019"),
    ("cahier de coloriage pat-patrouille", "trait d'union à la place de l'apostrophe"),
    ("coloriage patpatrouille à imprimer", "agglutiné"),
    ("coloriage pokemons à imprimer", "pluriel"),
    ("coloriage minions à imprimer", "entrée « les minions » sans son déterminant"),
    ("coloriage reine des neiges à imprimer", "déterminant retiré"),
    ("cahier de coloriage star-wars", "trait d'union ajouté"),
    ("carnet starwars a personnaliser", "agglutiné"),
    ("coloriage stars wars enfant 5 ans", "pluriel sur le PREMIER mot"),
])
def test_les_mutations_emblematiques(requete, attendu):
    assert terme_ip(requete) is not None, f"non attrapé ({attendu}) : {requete}"


# ── Les faux positifs trouvés par la mesure ────────────────────────────────────

@pytest.mark.parametrize("requete,pourquoi", [
    ("cahier de revision bts mco", "BTS est un diplôme français avant d'être un groupe"),
    ("carnet de bord bts communication", "idem"),
    ("coloriage puma animal sauvage", "le puma est un animal, et le coloriage animalier "
                                      "est une catégorie entière du low-content"),
    ("carnet de meditation om", "« om » est le mantra"),
    ("coloriage bonhomme de neige", "« om » ne doit pas sortir de « bonhomme »"),
    ("cahier de vacances CM2", "« cm2 » n'est pas une marque"),
])
def test_les_termes_ambigus_ne_bloquent_pas_une_niche_valable(requete, pourquoi):
    """Ces requêtes étaient rejetées EN SILENCE. La règle appliquée : on retire de la liste
    un terme dont l'usage légitime est une CATÉGORIE COURANTE du low-content (cahiers de
    révision, coloriage animalier) ; on le garde quand l'usage légitime est incident (un
    patronyme dans un livre d'or, une déesse grecque dans un cahier de mythologie).

    L'asymétrie joue dans les deux sens et il faut la peser à chaque fois, pas appliquer
    une règle unique."""
    assert terme_ip(requete) is None, f"rejeté à tort ({pourquoi})"


def test_les_marques_restent_attrapees_sous_leur_forme_longue():
    """Retirer un sigle ambigu ne doit pas ouvrir la porte à la marque elle-même."""
    assert terme_ip("carnet de fan bangtan boys kpop") is not None
    assert terme_ip("coloriage olympique de marseille") is not None
    assert terme_ip("coloriage chaussures puma sport marque") is None  # assumé : voir liste
