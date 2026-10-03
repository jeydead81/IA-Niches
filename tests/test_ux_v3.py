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


# ── Page d'analyse éditoriale : ce que le modèle produit et que l'écran taisait ───────────
#
# `AngleAttaque` porte le prix conseillé, la direction de couverture, le RISQUE, et en
# low-content la spec d'intérieur, la redevance et la source réglementaire. L'écran n'en
# montrait que le titre, le sous-titre, le pourquoi et les requêtes : le reste n'existait
# que dans le PDF. Ce qui justifie l'analyse (le prix, l'intérieur) doit se lire à l'écran.

def _verdict(**angle):
    a = {"angle": "a", "titre": "Dormir enfin : le protocole en 21 jours", "sous_titre": "pas à pas",
         "pourquoi": "parce que le rayon généraliste est saturé", "risque": "Allégations santé",
         "direction_couverture": "Bleu nuit", "prix_suggere": "14,90 – 19,90 €",
         "requete_principale": "insomnie chronique", "requetes_secondaires": ["dormir sans somnifère"]}
    a.update(angle)
    return {"verdict": "Go prudent", "confiance": 7, "facteur_decisif": "raisonnement long",
            "saturation": "Rayon dense", "faux_concurrent": "aucun", "differenciation": "Angle",
            "angles": [a, {"angle": "b", "titre": "Autre angle", "sous_titre": "s", "pourquoi": "p",
                           "risque": "r"}]}


_VB = ("esc", "verdictGrade")


def test_le_prix_conseille_et_le_risque_sont_VISIBLES_sans_deplier():
    html = appeler("verdictBlock", {"niche": "n", "verdict": _verdict()}, dependances=_VB)
    visible = html[:html.index('<details class="va-pli"')]
    assert "14,90 – 19,90 €" in visible and "Allégations santé" in visible


def test_le_pourquoi_et_l_analyse_strategique_sont_repliables_mais_PRESENTS():
    html = appeler("verdictBlock", {"niche": "n", "verdict": _verdict()}, dependances=_VB)
    assert html.count('<details class="va-pli"') == 3     # pourquoi, stratégie, autres angles
    for texte in ("parce que le rayon généraliste est saturé", "Rayon dense", "Autre angle"):
        assert texte in html, f"contenu disparu : {texte}"


def test_les_mots_cles_ne_sont_offerts_qu_en_non_fiction():
    """`/api/kdp-keywords` ne valide que la forme non-fiction : en low-content le bouton
    rendait une 400, donc un bouton mort (§5.26)."""
    nf = appeler("verdictBlock", {"niche": "n", "verdict": _verdict()}, dependances=_VB)
    lc = appeler("verdictBlock", {"niche": {"niche": "registre"}, "verdict": _verdict()},
                 dependances=_VB)
    assert "btn-kdp" in nf and "btn-pdf" in nf
    assert "btn-kdp" not in lc and "btn-pdf" in lc


def test_un_format_norme_SANS_source_le_dit_en_toutes_lettres():
    """Le serveur dégrade un « Go » sans source citée (lowcontent_verdict) ; l'écran doit dire
    pourquoi, et ne jamais le replier : un registre incomplet expose l'acheteur."""
    lc = {"niche": {"niche": "registre"}, "risques": ["norme_a_verifier"],
          "verdict": _verdict(spec_interieur="21 x 29,7 cm")}
    html = appeler("verdictBlock", lc, dependances=_VB)
    assert "Format normé sans source citée" in html
    visible = html[:html.index('<details class="va-pli"')]
    assert "Format normé sans source citée" in visible


def test_une_source_reglementaire_citee_est_affichee():
    lc = {"niche": {"niche": "registre"}, "risques": ["norme_a_verifier"],
          "verdict": _verdict(source_reglementaire="Code du travail, art. L1221-13")}
    html = appeler("verdictBlock", lc, dependances=_VB)
    assert "Code du travail, art. L1221-13" in html and "sans source citée" not in html


def test_la_specification_d_interieur_low_content_est_lisible_d_emblee():
    lc = {"niche": {"niche": "carnet"}, "risques": [],
          "verdict": _verdict(spec_interieur="21 x 29,7 cm, 200 pages", redevance_estimee="≈ 2,80 € par vente")}
    html = appeler("verdictBlock", lc, dependances=_VB)
    visible = html[:html.index('<details class="va-pli"')]
    assert "21 x 29,7 cm, 200 pages" in visible and "2,80 €" in visible


def test_la_jauge_de_confiance_porte_le_bon_nombre_de_segments():
    html = appeler("verdictBlock", {"niche": "n", "verdict": _verdict()}, dependances=_VB)
    assert html.count('<i class="on"></i>') == 7 and "Confiance 7/10" in html


def test_un_angle_sans_champ_facultatif_ne_laisse_ni_trou_ni_undefined():
    v = {"verdict": "Go", "confiance": 8, "facteur_decisif": "f",
         "angles": [{"titre": "T", "sous_titre": "S", "pourquoi": "P",
                     "requete_principale": "q", "requetes_secondaires": []}]}
    html = appeler("verdictBlock", {"niche": "n", "verdict": v}, dependances=_VB)
    assert "undefined" not in html and "null" not in html
    assert "va-risque" not in html and "va-pastilles" not in html


# ── Mots-clés KDP et concurrents du top ────────────────────────────────────────

def _kdp(**kw):
    base = {"emplacements": ["insomnie chronique", "dormir sans somnifère", "troubles du sommeil"],
            "confirmes_par_amazon": ["insomnie chronique"], "a_verifier": [], "rejetes": [],
            "sonde_indisponible": False}
    base.update(kw)
    return base


def test_chaque_emplacement_porte_sa_longueur_et_son_statut_et_tout_se_copie_d_un_clic():
    html = appeler("kdpBlock", _kdp(), dependances=("esc",))
    assert "18/50" in html and "confirmé par Amazon" in html and "à vérifier" in html
    assert html.count('class="btn-copy"') == 3
    assert "btn-copy-tout" in html and "Tout copier" in html


def test_un_seul_emplacement_n_offre_pas_de_Tout_copier():
    html = appeler("kdpBlock", _kdp(emplacements=["insomnie chronique"]), dependances=("esc",))
    assert "btn-copy-tout" not in html


def test_une_sonde_en_panne_est_une_alerte_VISIBLE_pas_un_zero_confirme():
    """« 0 confirmé » se lirait « aucun de vos mots-clés n'est cherché » : contresens."""
    html = appeler("kdpBlock", _kdp(confirmes_par_amazon=[], sonde_indisponible=True),
                   dependances=("esc",))
    visible = html[:html.index("<details") if "<details" in html else len(html)]
    assert "n'a pas répondu" in visible and "n'ont pas pu être vérifiées" in visible


def test_les_expressions_ecartees_gardent_leur_motif():
    html = appeler("kdpBlock", _kdp(rejetes=[{"mot": "meilleur livre", "motif": "terme interdit"}]),
                   dependances=("esc",))
    assert "meilleur livre" in html and "terme interdit" in html


def test_les_concurrents_sont_classes_et_le_sens_du_BSR_est_dit():
    livres = [{"asin": "A", "title": "Premier", "price": 9.99, "rating": 4.4, "reviews_count": 37,
               "bsr": 964, "url": "u1"},
              {"asin": "B", "title": "Second", "bsr": 142622, "url": "u2"},
              {"asin": "C", "title": "Troisième", "bsr": None, "url": "u3"}]
    html = appeler("blocConcurrents", {"top_books": livres}, dependances=("esc", "fmt", "fmtEur"))
    assert "plus il est <strong>bas</strong>" in html
    assert html.count('<td class="rang">') == 3
    assert html.count('class="fort"') == 1, "seul le BSR sous 10 000 est signalé fort"
    assert ">0<" not in html


# ── Mon compte ────────────────────────────────────────────────────────────────

def test_la_cloture_est_repliee_mais_l_avertissement_precede_le_bouton():
    """Clôturer est la seule action irréversible du produit : on n'y tombe pas par hasard
    (volet fermé), et ce qui part se lit AVANT le bouton, une fois le volet ouvert."""
    html = appeler("menuCompteHtml", dependances=())
    assert '<details class="cpt-danger">' in html, "volet fermé par défaut (aucun attribut open)"
    assert html.index("Irréversible") < html.index("Clôturer définitivement")
    assert 'id="form-mdp"' in html and 'id="form-cloture"' in html
    assert html.index('id="form-mdp"') < html.index('id="form-cloture"'), \
        "le changement de mot de passe, courant, passe avant la clôture"


# ── BSR « hors top 3 » : une mesure jamais demandée n'est pas une mesure ratée ──────────

def _livres(n):
    return [{"asin": f"A{i}", "title": f"Livre {i}", "bsr": None, "url": f"u{i}"} for i in range(n)]


def test_au_dela_du_top_releve_le_BSR_vide_se_dit_HORS_TOP_et_non_non_mesure():
    """scout_master ne résout le BSR que des 3 premiers organiques de chaque niche : pour les
    livres 4 à 8, « non mesuré » ferait croire à une panne alors que rien n'a été demandé."""
    html = appeler("blocConcurrents", {"top_books": _livres(5)}, dependances=("esc", "fmt", "fmtEur"))
    assert html.count("non mesure") == 3, "les trois premiers : lecture tentée, absente"
    assert html.count("hors top 3") == 2
    assert ">0<" not in html


def test_un_BSR_lu_au_dela_du_top_s_affiche_normalement():
    livres = _livres(5)
    livres[4]["bsr"] = 5230
    html = appeler("blocConcurrents", {"top_books": livres}, dependances=("esc", "fmt", "fmtEur"))
    assert "5" in html and html.count("hors top 3") == 1


def test_le_nombre_de_BSR_releves_affiche_est_celui_du_moteur():
    """Deux sources pour la même valeur dériveraient en silence (§5.32) : la constante de
    l'interface est tenue égale au défaut de `run_scout`."""
    import inspect
    import re
    from pathlib import Path

    from scout_master import run_scout
    defaut = inspect.signature(run_scout).parameters["n_bsr_per_niche"].default
    src = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text(encoding="utf-8")
    assert re.search(r"const BSR_RELEVES = (\d+);", src).group(1) == str(defaut)


# ── Aide contextuelle : trois gestes d'abord, le mode d'emploi à la demande ────────────────

_AIDE_DEPS = ("emojiAide", "aideSections")


def test_aideSections_decoupe_en_rubriques_repliables_la_premiere_ouverte():
    corps = "<h3>À quoi sert cet onglet</h3><p>a</p><h3>Lire une carte</h3><ul><li>b</li></ul>"
    html = appeler("aideSections", corps, dependances=("emojiAide",))
    assert html.count('<details class="aide-sec"') == 2
    assert html.count("<details class=\"aide-sec\" open>") == 1
    assert "À quoi sert cet onglet" in html and "<li>b</li>" in html


def test_les_pieges_de_lecture_restent_VISIBLES_hors_des_volets():
    """Une mise en garde repliée ne prévient personne : seule l'explication se replie."""
    a = {"corps": "<h3>Rubrique</h3><p>x</p>", "pieges": ["piège un", "piège deux"]}
    html = appeler("aideHtml", a, [["🚀", "Lancez", "t"]], dependances=_AIDE_DEPS)
    pieges = html[html.index('<div class="aide-pieges">'):]
    assert "<details" not in pieges and pieges.count("<li>") == 2
    assert html.count('class="aide-geste"') == 1


def test_aucune_rubrique_de_l_aide_ne_se_perd_dans_la_mise_en_volets():
    """Le mode d'emploi n'est pas supprimé, il est rangé : autant de volets que de <h3>,
    pour les trois onglets, sur le contenu RÉEL."""
    import json
    import subprocess
    import shutil
    import pytest
    from tests.js_harness import _declaration, _source_js, extraire_fonction
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent")
    src = _source_js()
    prog = (_declaration("AIDE", src) + "\n" + extraire_fonction("emojiAide", src) + "\n"
            + extraire_fonction("aideSections", src) + "\n"
            + "const r = {}; for (const k of Object.keys(AIDE)) r[k] = "
              "[(AIDE[k].corps.match(/<h3>/g)||[]).length, "
              "(aideSections(AIDE[k].corps).match(/<details class=\"aide-sec\"/g)||[]).length];"
            + "process.stdout.write(JSON.stringify(r));")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    for onglet, (h3, volets) in json.loads(out.stdout).items():
        assert h3 > 0 and h3 == volets, f"rubriques perdues pour « {onglet} »"


def test_l_aide_ne_promet_plus_de_laisser_l_onglet_ouvert():
    """Faux depuis les travaux asynchrones : le run survit à la fermeture de la page."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text(encoding="utf-8")
    assert "Laissez l'onglet ouvert" not in src
    assert "Mes analyses" in src


# ── Compositeur : trois tropes au plus ─────────────────────────────────────────────────────

def test_le_nombre_de_tropes_imposables_est_celui_d_un_trio():
    """Un trio porte 1 à 3 tropes (prompt et `tr[:3]` de fiction_ideator) : en imposer un
    quatrième rendrait la contrainte irréalisable, sans que rien le dise."""
    import re
    from pathlib import Path
    racine = Path(__file__).resolve().parent.parent
    ui = (racine / "web" / "index.html").read_text(encoding="utf-8")
    ideateur = (racine / "01-scripts" / "fiction_ideator.py").read_text(encoding="utf-8")
    assert re.search(r"const MAX_TROPES_IMPOSES = 3;", ui)
    assert "tr[:3]" in ideateur and "1 à 3 tropes" in ideateur


# ── Écran de connexion : une marque, un formulaire, rien d'autre ──────────────────────────
#
# Signalé par Baptiste (capture du 2026-10-03) : « trop de texte, ça ressemble à rien ». Et un
# défaut derrière : la case « reprendre mes analyses » portait l'attribut `hidden`, mais
# `.auth-reprise{display:flex}` le battait — elle s'affichait aussi en CONNEXION, alors que la
# reprise ne se propose qu'à l'inscription (CLAUDE.md §2.1).

def _html():
    from pathlib import Path
    return (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text(encoding="utf-8")


def test_l_attribut_hidden_n_est_plus_battu_par_un_display_d_auteur():
    assert "[hidden]{display:none!important}" in _html()


def test_la_connexion_ne_porte_plus_de_phrase_de_presentation():
    html = _html()
    assert 'id="auth-sous"' not in html
    assert "rattachés à votre compte" not in html


def test_les_champs_gardent_un_label_accessible_meme_sans_label_visible():
    """Icônes + placeholders : les <label for> restent (masqués visuellement) pour les
    lecteurs d'écran."""
    html = _html()
    for champ, libelle in (("auth-email", "Adresse e-mail"), ("auth-mdp", "Mot de passe")):
        assert f'<label for="{champ}" class="vh">{libelle}</label>' in html


def test_le_mot_de_passe_peut_etre_affiche_et_la_regle_des_12_caracteres_est_dite():
    from auth import LONGUEUR_MIN_MOT_DE_PASSE
    html = _html()
    assert 'id="auth-voir"' in html and 'aria-pressed="false"' in html
    assert f"{LONGUEUR_MIN_MOT_DE_PASSE} caractères minimum" in html


def test_la_reprise_garde_son_avertissement_de_consentement():
    """Le texte est raccourci, jamais l'avertissement : on ne coche cela que sur sa propre
    installation (le premier inscrit venu raflait sinon l'historique)."""
    html = _html()
    bloc = html[html.index('id="auth-reprise-bloc"'):html.index('id="auth-btn"')]
    assert "propre installation" in bloc and 'type="checkbox"' in bloc and "hidden" in html[
        html.index('id="auth-reprise-bloc"') - 40:html.index('id="auth-reprise-bloc"') + 40]
