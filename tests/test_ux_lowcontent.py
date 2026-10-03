"""Onglet Low-content — rendu exercé, pas seulement cherché dans le fichier.

Même discipline que `test_ux_verdict_atteignable` : les fonctions de rendu sont PURES et
appelées pour de vrai (harnais node). Un test qui cherche une chaîne dans `index.html`
prouve qu'elle est écrite, jamais qu'elle est affichée — c'est ce qui a laissé trois
endpoints inatteignables pendant des semaines (§5.26).

Ce que les cartes doivent dire, et qui n'existe dans aucun autre onglet :
- PART INDIE, avec « non mesurée » quand aucun éditeur n'a pu être lu ;
- VARIANTES, dont l'échelle est INVERSÉE — élevé = mauvais, comme la saturation fiction ;
- le SEUIL DE 9,99 €, qui décide de 50 % ou 60 % de redevance.
"""
import re
from pathlib import Path

import pytest

from tests.js_harness import appeler, appeler_json

_INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"
# Dépendances de `carteLowContent`, dans l'ordre où node en a besoin.
_DEPS = ("esc", "fmt", "fmtEur", "fmtPct", "fmtDec", "grade", "mesure",
         "verdictGrade", "verdictBlock", "verdictSlot")


def _lc(**kw) -> dict:
    base = {
        "niche": {"niche": "carnet de suivi glycémie",
                  "requete_amazon": "carnet suivi glycemie diabete",
                  "format_cle": "journal_suivi", "theme": "glycémie",
                  "public": "adulte", "source": "autocomplete",
                  "profondeur_autocomplete": 2, "n_enfants_autocomplete": 4},
        "global_score": 7.4, "priorite": "🟡 Intéressant",
        "demande": 7.5, "penetration": 7.0, "rentabilite": 7.0, "faisabilite": 9.0,
        "part_indie": 0.8, "part_editeurs_traditionnels": 0.2, "n_editeur_inconnu": 0,
        "n_variantes_quasi_identiques": 3, "prix_median": 11.99,
        "prix_sous_seuil_60pct": False, "redevance_estimee": 3.15, "pages_median": 120,
        # Champs du calcul hors TVA (2026-09-15) : 11,99 € TTC = 9,99 € HT à 20 %.
        "prix_catalogue_ht": 9.99, "taux_tva_suppose": 0.2,
        "format_coupe": "standard", "n_format_lus": 6, "n_grand_format": 0,
        "bsr_best": 8214, "bsr_top_avg": 41000, "concurrence_mesuree": True,
        "n_organic": 12, "n_sponsored": 3, "n_concurrents_cibles": 6,
        "risques": [], "top_books": [], "verdict": None,
    }
    base.update(kw)
    return base


def _carte(**kw) -> str:
    return appeler("carteLowContent", _lc(**kw), dependances=_DEPS)


# ── Part indie ─────────────────────────────────────────────────────────────────

def test_la_part_indie_est_affichee_en_pourcentage():
    """C'est LE signal qui décide si un auteur seul peut attaquer le rayon."""
    assert "80" in _carte(part_indie=0.8)


def test_une_part_indie_non_mesuree_le_dit_au_lieu_d_afficher_zero():
    """« 0 % d'indie » se lirait « rayon tenu par des éditeurs », donc « n'y va pas ».
    C'est une conclusion, là où il n'y a qu'une absence de lecture (§5.10)."""
    html = _carte(part_indie=None, n_editeur_inconnu=6)
    assert "non mesur" in html.lower()
    assert not re.search(r"(?<!\d)0\s?%", html)


def test_le_nombre_d_editeurs_illisibles_est_dit():
    """« 60 % d'indie » sur deux livres ne se lit pas comme sur vingt."""
    assert "6" in _carte(part_indie=0.6, n_editeur_inconnu=6)


# ── Variantes : l'échelle inversée ─────────────────────────────────────────────

def test_beaucoup_de_variantes_est_signale_comme_MAUVAIS():
    """Piège n°1 du dépôt, transposé au low-content : sur `variantes`, élevé = mauvais.
    Une jauge colorée uniformément ferait recommander les pires rayons."""
    peu = _carte(n_variantes_quasi_identiques=1)
    beaucoup = _carte(n_variantes_quasi_identiques=9)
    assert 'class="v-bad"' in beaucoup or "v-bad" in beaucoup
    assert "v-bad" not in peu


def test_l_echelle_inversee_est_dite_a_l_ecran():
    """Le lecteur doit savoir que le chiffre se lit à l'envers, sans avoir à le déduire."""
    html = _carte(n_variantes_quasi_identiques=9)
    assert "élevé" in html.lower() or "eleve" in html.lower()


# ── Le seuil de 9,99 € ─────────────────────────────────────────────────────────

def test_un_prix_sous_le_seuil_est_signale_avec_son_taux():
    """Un auteur qui ne connaît pas le barème verrait « 7,99 € » comme un bon prix."""
    html = _carte(prix_median=7.99, prix_sous_seuil_60pct=True)
    assert "50" in html and "9,99" in html


def test_un_prix_au_dessus_du_seuil_ne_declenche_pas_l_alerte():
    html = _carte(prix_median=12.99, prix_sous_seuil_60pct=False)
    assert "v-bad" not in html or "50 %" not in html


def test_un_prix_non_mesure_n_affiche_ni_prix_ni_taux():
    """`prix_sous_seuil_60pct` vaut False faute de mesure, pas parce que le rayon est
    cher — même défaut que celui trouvé dans le brief du verdict."""
    html = _carte(prix_median=None, prix_sous_seuil_60pct=False, redevance_estimee=None)
    assert "non mesur" in html.lower()
    assert "60 %" not in html


# ── Redevance ──────────────────────────────────────────────────────────────────

def test_une_redevance_negative_est_montree_comme_une_perte():
    """Le seul cas où la réponse est « ne publie pas ça ». La masquer serait pire que de
    ne rien afficher."""
    html = _carte(redevance_estimee=-0.42)
    assert "v-bad" in html


# ── Non mesuré ─────────────────────────────────────────────────────────────────

def test_une_niche_sans_concurrence_mesuree_est_encadree():
    html = _carte(concurrence_mesuree=False, priorite="⚪ Concurrence non mesurée — à relancer")
    assert "non mesur" in html.lower()


def test_un_format_hors_taxonomie_est_nomme():
    """Les « other » sont le matériau de la taxonomie v2 : les afficher comme les autres
    perdrait le seul retour terrain du run."""
    html = _carte(niche={**_lc()["niche"], "format_cle": "other",
                         "other_libelle": "carnet de rituels lunaires"})
    assert "rituels lunaires" in html


def test_un_format_norme_porte_son_badge():
    html = _carte(risques=["norme_a_verifier"])
    assert "norm" in html.lower()


# ── Câblage ────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def src() -> str:
    return _INDEX.read_text(encoding="utf-8")


def test_l_onglet_existe_et_a_sa_vue(src):
    assert 'id="tab-lc"' in src and 'id="view-lc"' in src


def test_le_selecteur_de_format_vient_de_l_api(src):
    """Jamais une liste dupliquée en dur : elle se périmerait à la première taxo v2."""
    assert "/api/lowcontent/formats" in src


def test_le_lancement_passe_par_les_jobs(src):
    """Un seul chemin de lancement pour les trois scouts (§2.6)."""
    assert "lancerTravail('lowcontent'" in src or 'lancerTravail("lowcontent"' in src


def test_le_verdict_low_content_envoie_son_type(src):
    """`POST /api/verdict` dispatche sur `type` : sans lui, une niche low-content serait
    validée comme une `ScoredNiche` et rendrait une 400."""
    assert "type: 'lowcontent'" in src or '"type": "lowcontent"' in src


def test_le_glossaire_couvre_les_termes_low_content(src):
    for terme in ("Part indie", "Variantes", "Seuil 9,99"):
        assert terme in src, f"terme de glossaire manquant : {terme}"


def test_le_bouton_pdf_appelle_le_dossier_et_non_l_ancien_one_pager(src):
    """Le one-pager s'arrêtait au verdict. Laisser le bouton dessus rendrait le Dossier
    inatteignable — développé, testé, et sans chemin d'accès. C'est le piège §5.26, et il
    a déjà coûté trois endpoints."""
    assert "'/api/dossier'" in src
    assert "'/api/pdf'" not in src


def test_le_bouton_distingue_les_deux_formes_de_niche(src):
    """`type` est obligatoire : sans lui, une niche low-content serait validée comme une
    ScoredNiche non-fiction et rendrait une 400."""
    assert "typeof niche.niche === 'object'" in src


# ── Hors TVA et format de coupe (2026-09-15) ───────────────────────────────────

def test_le_seuil_est_dit_hors_tva_a_l_ecran():
    """Le prix du rayon est celui que voit le client (TTC) ; le seuil de 9,99 € porte sur
    le prix catalogue saisi dans KDP, HORS TVA. Sans le dire, « 10,49 € » se lit
    « au-dessus du seuil » alors que KDP verse 50 %."""
    html = _carte(prix_median=10.49, prix_catalogue_ht=8.74, taux_tva_suppose=0.2,
                  prix_sous_seuil_60pct=True)
    assert "HT" in html and "8,74" in html and "9,99" in html


def test_le_format_de_coupe_retenu_est_dit_avec_la_redevance():
    """Grand format : 0,43 € d'impression de plus par vente sous 110 pages. La redevance
    n'a de sens qu'avec le format sur lequel elle a été calculée."""
    html = _carte(format_coupe="grand", n_format_lus=6, n_grand_format=5)
    assert "grand format" in html.lower()


def test_un_format_de_coupe_non_determine_le_dit():
    html = _carte(format_coupe=None, n_format_lus=0)
    assert "non déterminé" in html.lower()


def test_le_glossaire_dit_que_le_seuil_est_hors_tva(src):
    entree = next(l for l in src.splitlines() if "'Seuil 9,99 €':" in l)
    assert "hors TVA" in entree


# ── Résultat antérieur au calcul hors TVA (revue du correctif, 2026-09-15) ─────

def _ancien(**kw) -> dict:
    """Un résultat low-content produit AVANT le calcul hors TVA : les cinq champs n'existent
    pas, et le drapeau de seuil comme la redevance ont été calculés sur le prix AFFICHÉ."""
    r = _lc(**kw)
    for cle in ("prix_catalogue_ht", "taux_tva_suppose", "format_coupe",
                "n_format_lus", "n_grand_format"):
        r.pop(cle, None)
    return r


def test_un_resultat_anterieur_ne_presente_pas_sa_redevance_ttc_comme_etablie():
    """10,49 € affichés : l'ancien calcul donnait 0,60 x 10,49 − 2,05 = 4,24 €. Hors TVA,
    KDP verse 0,50 x 8,74 − 2,05 = 2,32 €. Afficher 4,24 € sous « barème standard supposé »
    ferait croire que seul le format est une hypothèse."""
    html = appeler("carteLowContent", _ancien(prix_median=10.49, prix_sous_seuil_60pct=False,
                                               redevance_estimee=4.244), dependances=_DEPS)
    assert "4,24" not in html
    assert "recalcul" in html.lower()


def test_un_resultat_anterieur_affiche_sous_9_99_reste_signale_a_50_pct():
    """Le prix hors TVA est toujours plus bas que le prix affiché : un ancien drapeau
    « sous 9,99 € » reste vrai quel que soit le taux de TVA. Seul un ancien « au-dessus »
    est douteux."""
    html = appeler("carteLowContent", _ancien(prix_median=7.99, prix_sous_seuil_60pct=True,
                                               redevance_estimee=1.95), dependances=_DEPS)
    assert "v-bad" in html and "50 %" in html


# ── La pastille suit le verdict du serveur (2026-09-18) ────────────────────────

def test_la_pastille_suit_le_verdict_du_serveur_et_non_des_seuils_recopies():
    """Les seuils des pastilles vivent dans `lowcontent_criteres.json` (6,0 / 5,0 depuis le
    2026-09-18). La carte les recopiait en dur (7,5 / 6,0, via `grade`) : une niche à 5,5
    que le serveur classe 🟡 s'affichait ROUGE — deux sources pour le même seuil (§5.32)."""
    assert 'class="pill a"' in _carte(global_score=5.5, priorite="🟡 Intéressant")
    assert 'class="pill r"' in _carte(global_score=5.5, priorite="🔴 Faible")
    assert 'class="pill g"' in _carte(global_score=6.2, priorite="🟢 À analyser en priorité")


def test_sans_verdict_serveur_la_pastille_retombe_sur_le_score():
    """Un résultat sans `priorite` (ancien job) garde l'ancienne couleur : jamais vide."""
    assert 'class="pill g"' in _carte(global_score=8.0, priorite="")


# ── Ce que l'écran a le droit de promettre (2026-10-02) ────────────────────────
#
# Mesuré sur 95 rayons étiquetés à l'aveugle par Baptiste, validé sur un lot neuf : le score
# sépare un rayon MORT d'un rayon vivant (AUC 0,82 puis 0,91) et ne départage PAS une bonne
# niche d'une mauvaise (0,64 puis 0,43, les deux intervalles à cheval sur le hasard). Une
# liste triée par score, avec une note sur 10 en tête de carte, promet donc un classement
# qui n'existe pas. On regroupe par ce qui est mesuré, et on écrit ce qu'on ne sait pas.

def _rows_melanges():
    return [_lc(global_score=7.0, priorite="🟢 Rayon vivant — à examiner"),
            _lc(global_score=3.1, priorite="🔴 Signaux de rayon mort — à vérifier"),
            _lc(global_score=5.4, priorite="⚪ Concurrence non mesurée — à relancer",
                concurrence_mesuree=False),
            _lc(global_score=6.2, priorite="🟢 Rayon vivant — à examiner")]


def test_les_niches_sont_groupees_par_ce_qui_est_MESURE():
    groupes = appeler_json("grouperLc", _rows_melanges())
    assert [g["cle"] for g in groupes] == ["vivant", "mort", "nonmesure"]
    assert [len(g["rows"]) for g in groupes] == [2, 1, 1]
    assert sum(len(g["rows"]) for g in groupes) == 4, "aucune niche ne disparaît du regroupement"


def test_un_groupe_vide_ne_s_affiche_pas():
    rows = [_lc(priorite="🟢 Rayon vivant — à examiner")]
    assert [g["cle"] for g in appeler_json("grouperLc", rows)] == ["vivant"]


def test_le_groupe_VIVANT_dit_que_l_ordre_n_est_pas_un_classement():
    g = appeler_json("grouperLc", _rows_melanges())[0]
    assert "classement" in g["note"].lower()


def test_le_groupe_MORT_dit_que_ce_n_est_pas_un_rejet():
    """« rouge ⇒ mort » est FAUX : le rouge enterrait 7 bonnes sur 39 au lot 1 et 12 sur 32
    au lot 2. L'écran doit le dire, sinon il fait renoncer à une bonne niche — la faute la
    plus grave que ce produit puisse commettre (règle 3)."""
    g = appeler_json("grouperLc", _rows_melanges())[1]
    assert "rejet" in g["note"].lower()


def test_la_pastille_annonce_une_VITALITE_pas_une_note_de_qualite():
    html = appeler("carteLowContent", _lc(priorite="🟢 Rayon vivant — à examiner"),
                   dependances=_DEPS)
    assert "vitalité" in html.lower()
    assert "priorité" not in html.lower(), "le moteur ne sait pas classer par priorité"


def test_le_selecteur_de_FORMATS_se_charge_APRES_la_connexion():
    """« (formats indisponibles) » vu à l'écran le 2026-10-02, sur un compte connecté.

    L'appel `fetch('/api/lowcontent/formats')` était au niveau module : il partait au
    chargement de la page, donc AVANT que `GET /api/auth/moi` ait confirmé la session, se
    prenait un 401 et retombait sur le message d'indisponibilité — définitivement, car rien
    ne le rejouait après la connexion. Exactement le piège §2.9, qui avait déjà coûté la
    reprise des travaux low-content, dans le même fichier.

    Le test porte sur la PLACE de l'appel, pas sur sa présence : c'est la place qui était
    fausse, et une chaîne présente ne prouve rien (§5.26)."""
    src = _INDEX.read_text(encoding="utf-8")
    assert src.count("'/api/lowcontent/formats'") == 1, "un seul site d'appel"
    debut = src.index("function chargerFormatsLc")
    fin = src.index("\n}", debut)
    assert "'/api/lowcontent/formats'" in src[debut:fin], \
        "l'appel vit dans la fonction, pas au niveau module"
    entrer = src.index("function entrer(")
    assert "chargerFormatsLc()" in src[entrer:src.index("\n  }", entrer)], \
        "et `entrer()` l'appelle, une fois la session confirmée"


# ── Historique des analyses (2026-10-02) ──────────────────────────────────────
#
# « aucun moyen de récupérer ses analyses ? » — question de Baptiste devant le bandeau
# « Ce mois-ci : 3 analyse(s) ». Les runs sont TOUS en base, avec leur résultat complet, et
# `GET /api/jobs` les rend déjà. Il manquait l'écran : l'interface ne savait reprendre que
# le DERNIER run de chaque onglet, via localStorage. Un run payé 15 minutes plus tôt était
# donc inatteignable — la même famille que §5.26, une donnée produite et jamais affichée.

def _job(**kw):
    base = {"id": "a1b2", "type": "lowcontent", "statut": "termine",
            "params": {"seed": "registre", "n_search": 6},
            "resultat": [{"niche": {}}, {"niche": {}}, {"niche": {}}],
            "cree_le": 1790000000.0, "erreur": None}
    base.update(kw)
    return base


def test_une_analyse_terminee_est_REOUVRABLE_avec_son_contenu():
    html = appeler("ligneAnalyse", _job(), dependances=("esc", "TYPE_LABEL", "TYPE_EMO", "fmtDate"))
    assert "registre" in html and "3 niche" in html
    assert "Low-content" in html
    assert 'data-id="a1b2"' in html, "le bouton doit porter l'identifiant du run"


def test_une_analyse_en_cours_n_est_pas_proposee_a_la_reouverture():
    """Rouvrir un run sans résultat afficherait un écran vide en faisant croire qu'il n'a
    rien trouvé — une absence de mesure présentée comme un verdict (règle 3)."""
    html = appeler("ligneAnalyse", _job(statut="en_cours", resultat=None),
                   dependances=("esc", "TYPE_LABEL", "TYPE_EMO", "fmtDate"))
    assert "data-id" not in html
    assert "cours" in html.lower()


def test_une_analyse_en_ECHEC_dit_pourquoi_et_ne_se_rouvre_pas():
    html = appeler("ligneAnalyse",
                   _job(statut="echec", resultat=None, erreur="compte DataForSEO refusé"),
                   dependances=("esc", "TYPE_LABEL", "TYPE_EMO", "fmtDate"))
    assert "data-id" not in html
    assert "dataforseo" in html.lower()
