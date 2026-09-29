"""La porte ne se prononce plus sur une mesure AMPUTÉE — décision de Baptiste, 2026-09-29.

Deux conditions s'ajoutent à `porte_franchie`, toutes deux de la forme « au moins une » /
« toutes », jamais une proportion inventée :

1. TOUTES les requêtes étiquetées doivent être calibrées (`n_calibrees == n_requetes`).
   Mesuré au pré-mortem du run 6, sur les entrées RÉELLES du run 5 rescorées avec les
   critères courants : un jeu amputé à 10 niches sur 46 (les 9 mortes plus une autre)
   sortait `porte_franchie=True` avec un Spearman de **+0,522**, contre **+0,462** pour le
   run 5 COMPLET. Ce n'est pas un hasard : ce sont les « mortes » qui portent le signal
   (run 5 sans elles : +0,219), donc l'échec partiel est précisément le scénario qui
   fabrique un faux vert. Un run dont 40 SERP tombent aurait réglé les seuils sur 4 niches.

2. Au moins une « morte » doit avoir été SCORÉE. « Aucune morte en vert » se vérifiait
   jusqu'ici sur l'ensemble vide : neuf mortes toutes écartées en amont (filtre IP appliqué
   APRÈS le modèle) satisfaisaient le critère le plus important du plan sans qu'aucune
   n'ait vu un rayon. Même forme que les deux conditions de décidabilité déjà en place
   (`n_part_indie_mesuree`, `n_redevance_mesuree`).

Dans les deux cas la porte est INDÉCIDABLE, pas échouée : le conseil « corriger
data/lowcontent_criteres.json » ne doit pas s'afficher sur une mesure trouée (§2.14).
"""
from lowcontent_validation import rapport_calibration
from tests.test_calibration_premortem import _paires_alignees, _scored


def _completes():
    """Un run nominal : rayon lu (part_indie, redevance), sonde et SERP mesurées."""
    return [(e, _scored(s.global_score, f"{e}{i}", part_indie=0.7,
                        redevance_estimee=3.1))
            for i, (e, s) in enumerate(_paires_alignees())]


def test_temoin_un_jeu_COMPLET_franchit_toujours_la_porte():
    r = rapport_calibration(_completes())
    assert r.n_calibrees == r.n_requetes == 9
    assert r.porte_franchie is True and r.porte_indecidable is False


def test_une_SERP_tombee_rend_la_porte_INDECIDABLE_meme_avec_un_bon_spearman():
    """La niche non mesurée est une « mauvaise » : ni morte indécidable, ni bonne perdue.
    Aucune des conditions existantes ne la voit — c'est exactement le trou du run 6."""
    paires = _completes()
    tombee = _scored(5.9, "serp tombee", concurrence_mesuree=False)
    r = rapport_calibration(paires + [("mauvaise", tombee)])
    assert r.spearman is not None and r.spearman >= 0.5
    assert r.n_calibrees == 9 and r.n_requetes == 10
    assert r.porte_franchie is False
    assert r.porte_indecidable is True
    assert any("calibr" in a.lower() for a in r.avertissements)


def test_une_bonne_NON_RENDUE_par_le_classement_rend_la_porte_INDECIDABLE():
    """Renversement ASSUMÉ : jusqu'au 2026-09-29 une « bonne » non rendue se disait sans
    fermer la porte (le dépôt refusait d'ajouter un critère de son propre chef). Baptiste a
    tranché l'inverse : une requête qu'on n'a pas mesurée manque au jeu, quelle que soit son
    étiquette."""
    r = rapport_calibration(_completes(),
                            non_rendues=[("livre quizz culture générale", "bonne")])
    assert r.n_calibrees == 9 and r.n_requetes == 10
    assert r.porte_franchie is False and r.porte_indecidable is True


def test_sans_aucune_morte_SCOREE_la_porte_est_INDECIDABLE():
    """Aucune morte dans le jeu analysé : « aucune morte en vert » porterait sur l'ensemble
    vide. La mesure est COMPLÈTE ici (6 sur 6) — c'est bien la seconde condition, et elle
    seule, qui ferme. L'assertion porte sur le motif, pas seulement sur le booléen."""
    vivantes = [(e, s) for e, s in _completes() if e != "morte"]
    r = rapport_calibration(vivantes)
    assert r.n_calibrees == r.n_requetes == 6
    assert r.morts_en_vert == []
    assert r.porte_franchie is False
    assert r.porte_indecidable is True
    assert any("morte" in a.lower() and "scor" in a.lower() for a in r.avertissements)


def test_une_seule_morte_scoree_suffit():
    """« Au moins une », jamais une proportion : exiger « la moitié des mortes » serait un
    seuil inventé (§4.2). C'est Baptiste qui juge si la mesure suffit, sur les compteurs."""
    paires = [(e, s) for e, s in _completes() if e != "morte"]
    paires.append(("morte", _scored(2.4, "morte scoree", part_indie=0.7,
                                    redevance_estimee=3.1)))
    r = rapport_calibration(paires)
    assert r.porte_franchie is True and r.porte_indecidable is False


def test_le_conseil_nomme_la_MESURE_INCOMPLETE_et_ne_renvoie_pas_aux_criteres():
    """Le conseil suit la cause (§2.14). Une mesure trouée n'est ni « toutes les SERP sont
    tombées » (il en reste), ni un problème de lecture : le dire « relancer une fois la
    cause réglée » laisserait chercher ailleurs."""
    from build_lowcontent_validation_set import _conseil_indecidable
    paires = _completes()
    r = rapport_calibration(paires + [("mauvaise", _scored(5.9, "tombee",
                                                           concurrence_mesuree=False))])
    assert r.porte_indecidable is True
    conseil = _conseil_indecidable(r)
    assert "incomplète" in conseil.lower() or "incomplete" in conseil.lower()
    assert "critères" not in conseil


def test_le_conseil_nomme_l_absence_de_morte_scoree():
    from build_lowcontent_validation_set import _conseil_indecidable
    r = rapport_calibration([(e, s) for e, s in _completes() if e != "morte"])
    assert r.porte_indecidable is True
    assert "morte" in _conseil_indecidable(r).lower()
