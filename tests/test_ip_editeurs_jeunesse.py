"""Marques d'ÉDITEURS JEUNESSE et de JOUETS dans le corpus IP — trouvé le 2026-10-02.

Baptiste étiquetait le lot 3 quand « coloriage magique djeco » est sorti du tirage : Djeco
est une marque de jeux et d'éditions jeunesse, et le filtre ne la connaissait pas. Le corpus
portait Disney et les licences de dessin animé, mais AUCUN éditeur ni fabricant de jeux —
or ce sont eux qui remplissent l'autocomplete du coloriage et des cahiers de jeux.

Le risque n'est pas un chiffre faux, c'est le compte KDP : un cahier sous marque est un
retrait de publication, répété une fermeture.

ARBITRAGE, règle du §5.35 (on retire un terme dont l'usage légitime est une catégorie
COURANTE du low-content, on le garde quand cet usage est incident) :
- AJOUTÉS : djeco, ravensburger, auzou, usborne, janod, sentosphere, lito jeunesse — aucun
  n'a d'usage courant hors marque en français.
- PAS AJOUTÉ, délibérément : **nathan**. C'est d'abord un prénom, et « coloriage prénom
  Nathan », « cahier d'écriture Nathan » sont des requêtes légitimes et fréquentes. L'ajouter
  écarterait en silence une catégorie entière, exactement le défaut que §5.35 a mesuré sur
  « bts » et « puma ». La marque Nathan reste donc non couverte : arbitrage assumé, écrit ici
  pour ne pas être « corrigé » plus tard sans mesure.
"""
import pytest

from ip_filter import terme_ip


@pytest.mark.parametrize("requete,marque", [
    ("coloriage magique djeco", "djeco"),
    ("puzzle ravensburger cahier", "ravensburger"),
    ("cahier d'activités auzou", "auzou"),
    ("livre de coloriage usborne", "usborne"),
    ("jeux janod enfant", "janod"),
])
def test_une_marque_d_editeur_jeunesse_est_ecartee(requete, marque):
    assert terme_ip(requete) == marque


@pytest.mark.parametrize("requete", [
    "coloriage prenom nathan",
    "cahier d'ecriture nathan",
])
def test_le_prenom_NATHAN_reste_autorise(requete):
    """Arbitrage assumé : la marque Nathan n'est pas couverte, parce que la couvrir
    écarterait en silence les coloriages de prénom — une catégorie entière du rayon."""
    assert terme_ip(requete) is None
