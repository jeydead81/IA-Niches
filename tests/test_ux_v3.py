"""Refonte « Vif » (2026-10-03) : moins de texte, plus de signaux, le détail à la demande.

Ce que Baptiste a demandé devant l'écran : « simplifier ou alors mettre en évidence » — le prix
médian en tuile, c'est bien ; le pavé de texte dessous, il doit être repliable ou en puces.

Ce fichier tient ce qui ne doit PAS se perdre dans la simplification :
- une mise en garde n'est jamais repliée (une alerte cachée ne prévient personne) ;
- un chiffre déplacé dans un volet n'est pas supprimé ;
- une mesure absente se dit « non mesuré » et jamais 0 (règle 3).

Les fonctions sont PURES et appelées pour de vrai (harnais node, §2.10).
"""
import re

from tests.js_harness import appeler, appeler_json

_FICHE = ("esc", "fmt", "fmtEur", "fmtDec", "grade", "verdict", "nonMesuree", "pourquoiNiche")
_LC = ("esc", "fmt", "fmtEur", "fmtPct", "fmtDec", "grade", "mesure",
       "verdictGrade", "verdictBlock", "verdictSlot")


def _niche(**kw):
    base = {"niche": "Sommeil et insomnie", "categorie": "Santé / Bien-être",
            "global_score": 7.4, "demande": 10.0, "penetration": 4.5,
            "bsr_best": 964, "bsr_top5_avg": 48248, "n_concurrents_cibles": 98,
            "n_sponsored": 1, "concurrence_mesuree": True, "criteres_bsr_ok": True,
            "prix_median": 12.93, "n_prix_connus": 56}
    base.update(kw)
    return base


def _lc(**kw):
    base = {
        "niche": {"niche": "carnet de suivi glycémie", "requete_amazon": "carnet suivi glycemie",
                  "format_cle": "journal_suivi", "source": "autocomplete"},
        "global_score": 7.4, "priorite": "🟢 Rayon vivant — à examiner",
        "part_indie": 0.8, "part_editeurs_traditionnels": 0.2, "n_editeur_inconnu": 0,
        "n_variantes_quasi_identiques": 3, "prix_median": 11.99, "prix_sous_seuil_60pct": False,
        "redevance_estimee": 3.15, "prix_catalogue_ht": 9.99, "taux_tva_suppose": 0.2,
        "format_coupe": "standard", "n_format_lus": 6, "bsr_best": 8214, "bsr_top_avg": 41000,
        "concurrence_mesuree": True, "risques": [], "verdict": None,
    }
    base.update(kw)
    return base


# ── Carte non-fiction : le prix remonte ───────────────────────────────────────

def test_la_carte_non_fiction_montre_le_PRIX_median():
    html = appeler("carteNicheTete", _niche(),
                   dependances=("esc", "fmt", "fmtEur", "fmtDec", "grade", "verdict", "nonMesuree"))
    assert "12,93" in html and "Prix médian" in html


def test_un_prix_absent_sur_la_carte_n_est_jamais_zero():
    html = appeler("carteNicheTete", _niche(prix_median=None, n_prix_connus=0),
                   dependances=("esc", "fmt", "fmtEur", "fmtDec", "grade", "verdict", "nonMesuree"))
    assert "0,00" not in html


# ── Fiche non-fiction : des lignes, pas des pavés ─────────────────────────────

def test_les_raisons_sont_des_LIGNES_repliables_avec_un_libelle_court():
    cartes = appeler_json("pourquoiNiche", _niche(), dependances=("fmt", "nonMesuree"))
    assert all(c.get("court") for c in cartes), "chaque raison porte sa demi-phrase"
    # Le texte long reste : rien n'est supprimé, il se déplie.
    assert all(c["texte"] for c in cartes)


def test_la_fiche_rend_les_raisons_en_details_et_garde_le_texte_complet():
    html = appeler("ficheNiche", _niche(), dependances=_FICHE)
    assert html.count('<details class="pq') == 3
    assert "Sous 10 000, la preuve est solide" in html


def test_le_prix_passe_avant_l_accessibilite_dans_la_fiche():
    """Deuxième question de l'auteur, après « est-ce que ça vend »."""
    html = appeler("ficheNiche", _niche(), dependances=_FICHE)
    assert html.index("Prix médian") < html.index("Accessibilité")


def test_une_niche_non_mesuree_ne_declare_ni_bon_ni_mauvais():
    cartes = appeler_json("pourquoiNiche", _niche(concurrence_mesuree=False),
                          dependances=("fmt", "nonMesuree"))
    assert [c["ton"] for c in cartes] == ["alerte"] and cartes[0]["court"]


# ── Alertes : toujours visibles ───────────────────────────────────────────────

def test_l_alerte_terme_dominant_garde_son_titre_VISIBLE():
    """Seule l'explication se déplie : le titre de l'alerte est dans <summary>."""
    html = appeler("blocSuggestions", _niche(terme_dominant="sommeil", part_dominante=0.5),
                   dependances=("esc",))
    resume = html[html.index("<summary>"):html.index("</summary>")]
    assert "sommeil" in resume and "50 %" in resume


def test_l_alerte_informationnelle_nomme_ses_marqueurs_dans_le_resume():
    html = appeler("blocSuggestions",
                   _niche(intention_informationnelle=True, marqueurs_informationnels=["avis", "résumé"]),
                   dependances=("esc",))
    resume = html[html.index("<summary>"):html.index("</summary>")]
    assert "avis" in resume


def test_sans_drapeau_aucune_alerte_n_est_rendue():
    assert appeler("blocSuggestions", _niche(), dependances=("esc",)).strip() == ""


# ── Carte low-content : trois chiffres, le reste replié ───────────────────────

def _avant_detail(html):
    return html[:html.index('<details class="lc-detail"')]


def test_les_trois_chiffres_decisifs_sont_AVANT_le_volet_de_detail():
    visible = _avant_detail(appeler("carteLowContent", _lc(), dependances=_LC))
    for chiffre in ("11,99", "3,15", "80"):
        assert chiffre in visible, f"chiffre décisif replié : {chiffre}"


def test_le_detail_garde_toutes_les_mesures():
    """Rien n'est supprimé : les six mesures complètes sont dans le volet."""
    html = appeler("carteLowContent", _lc(), dependances=_LC)
    detail = html[html.index('<details class="lc-detail"'):]
    for cle in ("Part indie", "Variantes", "Prix médian", "Redevance estimée",
                "Éditeurs installés", "BSR meilleur"):
        assert cle in detail, f"mesure disparue : {cle}"


def test_une_part_indie_non_mesuree_se_dit_dans_la_zone_visible():
    visible = _avant_detail(appeler("carteLowContent", _lc(part_indie=None, n_editeur_inconnu=6),
                                    dependances=_LC))
    assert "non mesuré" in visible
    assert not re.search(r"(?<!\d)0\s?%", visible)


def test_le_seuil_de_redevance_est_un_drapeau_VISIBLE_pas_replie():
    """Sous 9,99 € HT, KDP verse 50 % : l'auteur doit le voir sans rien déplier."""
    visible = _avant_detail(appeler(
        "carteLowContent", _lc(prix_median=7.99, prix_sous_seuil_60pct=True, redevance_estimee=1.2),
        dependances=_LC))
    assert "9,99" in visible and "50 %" in visible


def test_les_variantes_n_alarment_PAS_sur_la_carte_mais_restent_lisibles_a_l_envers():
    """Décision de Baptiste (2026-10-03) : le score ignore les variantes depuis le 2026-09-30
    (variantes_max=1000 — le terme dégradait la détection des rayons morts). Les signaler
    en alerte visible contredisait cette décision. Le chiffre reste affiché, dans le volet,
    avec son sens inversé (piège 5.30)."""
    html = appeler("carteLowContent", _lc(n_variantes_quasi_identiques=9), dependances=_LC)
    assert "9 variantes" not in _avant_detail(html)
    detail = html[html.index('<details class="lc-detail"'):]
    assert "élevé = mauvais" in detail and "v-bad" in detail


def test_un_seuil_d_HYPOTHESE_informe_sans_alarmer_un_FAIT_de_bareme_alerte():
    """Redevance sous 2 € et éditeurs > 50 % sont des seuils non calibrés : ℹ️, fond neutre.
    Le seuil de 9,99 € HT est un fait de barème KDP : ⚠️."""
    hypo = _avant_detail(appeler("carteLowContent",
                                 _lc(redevance_estimee=1.2, part_editeurs_traditionnels=0.7),
                                 dependances=_LC))
    assert hypo.count("lc-info") == 2 and "lc-fait" not in hypo
    assert "v-bad" not in hypo, "une hypothèse ne rougit pas la tuile"
    fait = _avant_detail(appeler("carteLowContent",
                                 _lc(prix_median=7.99, prix_sous_seuil_60pct=True),
                                 dependances=_LC))
    assert "lc-fait" in fait and "⚠️" in fait


def test_un_rayon_sain_n_affiche_aucun_drapeau():
    html = appeler("carteLowContent", _lc(), dependances=_LC)
    assert "lc-flags" not in html and "v-bad" not in html


def test_les_groupes_portent_un_emoji_et_un_sous_titre_court():
    groupes = appeler_json("grouperLc", [_lc()], dependances=())
    assert groupes[0]["emo"] and groupes[0]["court"]


def test_le_groupe_MORT_dit_dans_son_sous_titre_VISIBLE_que_ce_n_est_pas_un_rejet():
    """Le rouge enterrait 7 bonnes sur 39 au lot 1 : cette mise en garde ne se replie pas."""
    groupes = appeler_json("grouperLc", [_lc(priorite="🔴 Signaux de rayon mort — à vérifier")],
                           dependances=())
    assert "rejet" in groupes[0]["court"].lower()


# ── Fiction : libellés français ───────────────────────────────────────────────

def test_les_cles_de_taxonomie_perdent_leur_tiret_bas():
    assert appeler("libCle", "cosy_mystery", dependances=()) == "cosy mystery"
    assert appeler("libCle", None, dependances=()) == ""


# ── Revue adversariale du 2026-10-03 : ce que la simplification avait replié à tort ──

def test_le_groupe_VIVANT_dit_dans_son_sous_titre_VISIBLE_que_l_ordre_n_est_pas_un_classement():
    """Le titre « classées » et la pastille chiffrée promettent un rang que la mesure ne
    donne pas (AUC 0,43 sur le lot neuf). La phrase ne se replie pas."""
    groupes = appeler_json("grouperLc", [_lc()], dependances=())
    assert "classement" in groupes[0]["court"].lower()


def test_une_part_indie_PARTIELLE_garde_sa_reserve_dans_la_zone_visible():
    """« 100 % d'indie » sur trois livres lus ne se lit pas comme sur douze : le nombre
    d'éditeurs illisibles reste à côté du chiffre (lowcontent_scoring._part)."""
    visible = _avant_detail(appeler("carteLowContent", _lc(part_indie=1.0, n_editeur_inconnu=9),
                                    dependances=_LC))
    assert "9 éditeur(s) illisible(s)" in visible


def test_une_redevance_faible_est_dite_en_TEXTE_pas_seulement_en_couleur():
    visible = _avant_detail(appeler("carteLowContent", _lc(redevance_estimee=1.2), dependances=_LC))
    assert "sous 2 €" in visible
    perte = _avant_detail(appeler("carteLowContent", _lc(redevance_estimee=-0.4), dependances=_LC))
    assert "négative" in perte


def test_un_echec_long_ne_ronge_pas_la_ligne_de_l_analyse():
    """L'erreur d'un run interrompu fait ~130 caractères : sur sa propre ligne, sinon la
    colonne du sujet tombe à 0 px."""
    job = {"id": "x", "type": "scout", "statut": "echec", "params": {"seed": "sommeil"},
           "resultat": None, "cree_le": 1790000000.0, "erreur": "Analyse interrompue " * 6}
    html = appeler("ligneAnalyse", job, dependances=("esc", "TYPE_LABEL", "TYPE_EMO", "fmtDate"))
    assert "etat-long" in html and "sommeil" in html


def test_les_pastilles_de_couleur_ont_un_equivalent_texte():
    html = appeler("carteNicheTete", _niche(),
                   dependances=("esc", "fmt", "fmtEur", "fmtDec", "grade", "verdict", "nonMesuree"))
    assert 'aria-label="favorable"' in html and 'aria-label="défavorable"' in html
