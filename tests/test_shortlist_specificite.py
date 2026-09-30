"""Le gate qui décide de CE QU'ON PAIE trie désormais par SPÉCIFICITÉ de la requête —
décision de Baptiste, 2026-09-30, après chiffrage hors ligne des deux lots étiquetés.

Ce que le tri par `n_enfants` faisait, mesuré sur les 95 requêtes (rejeu des entrées
capturées, 0 $) :

- il ne triait que sur `n_enfants` : `profondeur_autocomplete` vaut **0 sur les 95**, et
  `demand_score` vaut `max(1, n_enfants)` en mode classement — deux termes morts sur trois ;
- `n_enfants` mesure la GÉNÉRICITÉ : Amazon complète d'autant plus qu'une requête est
  courte. Le top 6 payé du lot 1 était « Carnet de Voyage », « registre du personnel »,
  « carnet a5 pointillés »… c'est-à-dire la tête de traîne que §2.11 décrit comme morte ou
  tenue par des éditeurs, et que ce moteur existe POUR ÉVITER ;
- résultat : 0,00 bonne dans le top 6 du lot 1 (1,41 attendue par tirage au sort) et 0,86
  au lot 2 (2,18 attendue). Le gate écartait les bonnes PLUS FORT que le hasard ;
- deux tiers du vivier sont à `n_enfants = 0` — un bloc muet qui porte 92 % des bonnes du
  lot 1 et 69 % de celles du lot 2, où l'ordre réellement appliqué était celui de sortie du
  LLM (`sorted` est stable), donc ni un signal ni quoi que ce soit de testé ;
- `n_enfants` sature à 9 (Amazon rend une dizaine de complétions) : au lot 2, SEPT niches
  ex aequo à 9 se disputaient 6 places payées — un tirage au sort à 0,126 $.

Le nombre de mots est le signal le mieux mesuré à ce jour pour séparer une bonne d'une
mauvaise : AUC 0,711 [0,54 ; 0,88] sur le lot 2, seul intervalle qui exclue le hasard. Il
est GRATUIT, disponible avant toute dépense, et il décroît avec la généricité — l'inverse
exact du défaut mesuré.

Ce qui est CONSERVÉ : `n_enfants` reste dans la clé, en second rang. Il n'est pas disqualifié
comme mesure de demande, il l'est comme critère de DÉPENSE. À nombre de mots égal, une
requête qu'Amazon complète encore reste préférable.
"""
from lowcontent_master import _rang_shortlist


def test_la_requete_la_plus_SPECIFIQUE_passe_en_premier():
    """Le cas mesuré au lot 1 : « Carnet de Voyage » (3 mots, 9 complétions) raflait une
    place payée devant « carnet de suivi bebe journal de bord » (7 mots, 0 complétion)."""
    generique = _rang_shortlist("carnet de voyage", 9, 0, 9)
    specifique = _rang_shortlist("carnet de suivi bebe journal de bord", 0, 0, 1)
    assert specifique > generique


def test_a_specificite_EGALE_l_autocomplete_departage_encore():
    """`n_enfants` n'est pas disqualifié comme demande, seulement comme critère de dépense."""
    sonde = _rang_shortlist("cahier de jeux adultes de poche", 5, 0, 5)
    muette = _rang_shortlist("cahier de jeux enfants de poche", 0, 0, 1)
    assert sonde > muette


def test_une_requete_JAMAIS_SONDEE_ne_tombe_pas_derriere_une_feuille_sterile():
    """Piège 5.34 intact : `None` n'est pas zéro. On ne sait rien d'elle, ce n'est pas la
    même chose que savoir qu'elle est stérile."""
    inconnue = _rang_shortlist("cahier de jeux adultes de poche", None, 0, 1)
    sterile = _rang_shortlist("cahier de jeux adultes de poche", 0, 0, 1)
    assert inconnue > sterile


def test_les_mots_se_comptent_sur_la_requete_DEPOUILLEE():
    """Ponctuation, tirets et espaces multiples ne créent pas de spécificité : « mots
    mêlés 7-12 ans » ne doit pas battre une vraie requête de six mots par un artifice de
    typographie."""
    assert _rang_shortlist("mots meles 7-12 ans", 0, 0, 1)[0] == 4
    assert _rang_shortlist("  cahier   de  vacances  ", 0, 0, 1)[0] == 3
    assert _rang_shortlist("", 0, 0, 1)[0] == 0


def test_les_EX_AEQUO_sont_departages_par_la_requete_et_pas_par_l_ordre_du_LLM():
    """`sorted` est stable : à clé égale, l'ordre appliqué était celui de sortie du modèle —
    un comportement qui décide de la DÉPENSE et que rien ne surveillait (famille §5.32).
    Mesuré : avec l'ancienne clé, deux tiers du vivier tombaient dans un seul paquet d'ex
    aequo. Le départage est désormais une empreinte de la requête : arbitraire mais STABLE
    et reproductible, donc rejouable — et surtout indépendant de l'ordre d'arrivée."""
    a = _rang_shortlist("cahier de jeux adultes", 0, 0, 1)
    b = _rang_shortlist("cahier de jeux enfants", 0, 0, 1)
    assert a != b, "deux requêtes de même clé doivent être départagées"
    assert _rang_shortlist("cahier de jeux adultes", 0, 0, 1) == a, "et de façon STABLE"
    assert a[:4] == b[:4], "le départage vient APRÈS les vrais critères, jamais avant"
