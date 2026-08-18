"""Modèles low-content.

`LowContentNiche` hérite de `NicheCandidate` pour une raison précise : `validate_niches`
(la phase 2 gratuite du scout non-fiction) consomme des `NicheCandidate` et n'a pas besoin
d'être touchée. Hériter plutôt que dupliquer, c'est réutiliser le gate gratuit tel quel.

`LowContentScored` porte quatre axes au lieu de trois, et surtout trois champs à `None`
possible — `part_indie`, `part_editeurs_traditionnels`, `part_moins_12_mois`. Ce ne sont
pas des commodités : `0.0` voudrait dire « aucun livre indie dans ce rayon », une mesure ;
`None` dit « aucun éditeur n'a pu être lu », une absence. Le scoring ne les traite pas
pareil, et l'écran non plus.
"""
import pytest
from pydantic import ValidationError

from models import LowContentNiche, LowContentScored, NicheCandidate, TopBook


def _niche(**kw) -> LowContentNiche:
    base = dict(niche="carnet de suivi glycémie", requete_amazon="carnet suivi glycemie",
                rationale="traîne réelle", categorie="santé", format_cle="journal_suivi",
                theme="glycémie", public="adulte")
    base.update(kw)
    return LowContentNiche(**base)


# ── LowContentNiche ────────────────────────────────────────────────────────────

def test_une_niche_lc_est_une_NicheCandidate():
    """C'est ce qui permet de réutiliser `validate_niches` sans y toucher."""
    assert isinstance(_niche(), NicheCandidate)


def test_les_champs_specifiques_au_lc_sont_portes():
    n = _niche(source="autocomplete", profondeur_autocomplete=2, n_enfants_autocomplete=4)
    assert n.format_cle == "journal_suivi" and n.theme == "glycémie"
    assert n.public == "adulte" and n.source == "autocomplete"
    assert n.profondeur_autocomplete == 2 and n.n_enfants_autocomplete == 4


def test_other_libelle_conserve_ce_que_le_modele_a_propose():
    """Même rôle que `TropeClassification.other` : une requête inclassable n'est pas un
    déchet, c'est le signal qui fera évoluer la taxonomie en v2. La jeter perdrait
    l'information la plus utile du run."""
    n = _niche(format_cle="other", other_libelle="carnet de rituels lunaires")
    assert n.format_cle == "other" and n.other_libelle == "carnet de rituels lunaires"


def test_les_champs_d_arbre_valent_zero_par_defaut():
    """Une niche issue de l'idéation pure n'a pas de position dans l'arbre. Zéro est ici
    une valeur JUSTE — elle n'a pas été trouvée dans une traîne — et non une mesure
    manquante déguisée : `source` dit laquelle des deux on regarde."""
    n = _niche(source="ideation")
    assert n.profondeur_autocomplete == 0 and n.n_enfants_autocomplete == 0


def test_la_source_est_contrainte():
    """« autocomplete » et « ideation » ne se lisent pas pareil : la première porte une
    demande observée, la seconde une hypothèse. Les confondre effacerait la distinction
    qui justifie tout le chunk."""
    with pytest.raises(ValidationError):
        _niche(source="inventee")


# ── LowContentScored ───────────────────────────────────────────────────────────

def test_les_quatre_axes_existent():
    s = LowContentScored(niche=_niche())
    for axe in ("demande", "penetration", "rentabilite", "faisabilite"):
        assert hasattr(s, axe)


@pytest.mark.parametrize("champ", ["part_indie", "part_editeurs_traditionnels",
                                   "part_moins_12_mois", "redevance_estimee",
                                   "prix_median", "pages_median"])
def test_les_mesures_absentes_valent_None_et_jamais_zero(champ):
    """LE point du modèle. `0.0` sur `part_indie` voudrait dire « aucun livre indie dans
    ce rayon » — une mesure, et une mauvaise nouvelle. `None` dit « aucun éditeur n'a pu
    être lu » — une absence. Le scoring n'applique aucun bonus ni malus sur `None`
    (§5.10), et l'écran doit le dire au lieu d'afficher un zéro."""
    s = LowContentScored(niche=_niche())
    assert getattr(s, champ) is None


def test_n_editeur_inconnu_compte_ce_qu_on_n_a_pas_pu_lire():
    """Sans lui, `part_indie=0.6` ne dit pas si elle porte sur cinq livres ou sur deux.
    Même logique que `n_prix_connus` côté non-fiction."""
    s = LowContentScored(niche=_niche(), part_indie=0.6, n_editeur_inconnu=3)
    assert s.n_editeur_inconnu == 3


def test_le_seuil_de_redevance_est_un_drapeau_pas_un_score():
    """En dessous de 9,99 €, KDP verse 50 % au lieu de 60 %. C'est un fait de barème, pas
    un jugement sur la niche : le drapeau informe, il n'entre dans aucun axe."""
    s = LowContentScored(niche=_niche(), prix_median=7.99, prix_sous_seuil_60pct=True)
    assert s.prix_sous_seuil_60pct is True


def test_les_concurrents_du_top_voyagent_avec_la_niche():
    """Même `TopBook` qu'en non-fiction : un seul modèle, donc un seul rendu côté UI et
    un seul tableau dans le Dossier PDF."""
    s = LowContentScored(niche=_niche(),
                         top_books=[TopBook(asin="A1", title="T", url="u")])
    assert s.top_books[0].asin == "A1"


def test_le_verdict_est_absent_par_defaut():
    """Gate de coût : le verdict se demande à la pièce, comme en non-fiction."""
    assert LowContentScored(niche=_niche()).verdict is None


def test_les_risques_remontent_jusqu_au_score():
    """`NicheCandidate.risques` est un champ MORT en non-fiction : rempli par le LLM et
    propagé nulle part (§4.2). En low-content il porte `ip_marque`, `tos` et
    `norme_a_verifier`, qui pèsent sur le global — donc il doit voyager."""
    s = LowContentScored(niche=_niche(), risques=["norme_a_verifier"])
    assert s.risques == ["norme_a_verifier"]
