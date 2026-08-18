"""Le verdict, le PDF et les mots-clés KDP doivent être ATTEIGNABLES — pas seulement
présents dans le fichier.

C'est le piège §5.26 de CLAUDE.md, et son ironie : `test_ux_kdp_historique.py` vérifiait
que les chaînes « Télécharger le PDF » et « Mots-clés KDP » étaient bien dans le HTML, et
passait au vert — alors que ces deux boutons étaient générés à l'intérieur de
`verdictBlock(r)`, qui sort par `if(!v) return ''`. Or `_run_scout_job` appelle `run_scout`
sans `n_verdict`, donc `ScoredNiche.verdict` vaut TOUJOURS `None`, donc le bloc n'était
jamais rendu. Trois endpoints — `/api/verdict`, `/api/pdf`, `/api/kdp-keywords` — étaient
développés, testés, payés, et sans aucun chemin d'accès.

Ces tests-ci APPELLENT la fonction de rendu et regardent ce qu'elle produit. Un test qui
cherche une chaîne dans un fichier ne peut pas distinguer « affiché » de « mort ».
"""
import pytest

from tests.js_harness import appeler

_DEPS = ("esc", "verdictGrade", "verdictBlock")

_VERDICT = {
    "verdict": "Go", "confiance": 8, "facteur_decisif": "l'exécution",
    "angles": [{"titre": "Le carnet du diabétique", "sous_titre": "120 jours de suivi",
                "pourquoi": "rayon indie", "requete_principale": "carnet glycémie",
                "requetes_secondaires": ["suivi diabète"]}],
}


def test_une_niche_sans_verdict_propose_de_l_analyser():
    """LE test qui manquait. Sans verdict, l'utilisateur doit voir un bouton — pas le vide."""
    html = appeler("verdictSlot", {"niche": "carnet glycémie", "verdict": None},
                   dependances=_DEPS)
    assert "btn-verdict" in html
    assert "Analyser" in html


def test_une_niche_sans_verdict_ne_montre_pas_de_bouton_pdf():
    """Le PDF de positionnement se construit SUR le verdict : l'offrir avant de l'avoir
    produirait un document vide, et ferait passer une absence d'analyse pour une analyse."""
    html = appeler("verdictSlot", {"niche": "n", "verdict": None}, dependances=_DEPS)
    assert "btn-pdf" not in html


def test_une_niche_avec_verdict_expose_le_pdf_et_les_mots_cles():
    html = appeler("verdictSlot", {"niche": "n", "verdict": _VERDICT}, dependances=_DEPS)
    assert "btn-pdf" in html and "btn-kdp" in html
    assert "btn-verdict" not in html          # déjà analysée : ne pas re-proposer, ni re-payer


def test_le_verdict_rendu_porte_bien_son_contenu():
    html = appeler("verdictSlot", {"niche": "n", "verdict": _VERDICT}, dependances=_DEPS)
    assert "Go" in html and "8/10" in html
    assert "Le carnet du diab" in html


def test_le_cout_n_est_jamais_affiche_sur_le_bouton():
    """Décision du commit 4165efb : plus aucun montant à l'écran. Le TEMPS se dit, le
    montant non — un compteur visible freine l'exploration."""
    html = appeler("verdictSlot", {"niche": "n", "verdict": None}, dependances=_DEPS)
    assert "$" not in html and "€" not in html and "0,02" not in html


# ── Les concurrents du top : titres et chiffres, pas des ASIN nus ────────────────

def test_le_tableau_des_concurrents_montre_titre_prix_avis_et_bsr():
    """`top_asins` n'affichait que des identifiants : « B0C3K9 » ne dit rien à un auteur
    sur ce qu'il devrait battre."""
    livres = [{"asin": "A1", "title": "Carnet de suivi glycémie", "price": 9.99,
               "rating": 4.4, "reviews_count": 37, "bsr": 8214,
               "url": "https://www.amazon.fr/dp/A1"}]
    html = appeler("blocConcurrents", {"top_books": livres}, dependances=("esc", "fmt", "fmtEur"))
    assert "Carnet de suivi glyc" in html
    assert "8" in html and "37" in html
    assert "https://www.amazon.fr/dp/A1" in html


def test_un_bsr_inconnu_s_affiche_comme_non_mesure_pas_comme_zero():
    """Zéro serait le MEILLEUR classement possible : afficher 0 pour un BSR absent
    inverserait complètement la lecture (§5.10)."""
    livres = [{"asin": "A1", "title": "T", "bsr": None, "url": "u"}]
    html = appeler("blocConcurrents", {"top_books": livres}, dependances=("esc", "fmt", "fmtEur"))
    assert ">0<" not in html


def test_sans_concurrents_connus_le_bloc_le_dit():
    """Liste vide = rayon non mesuré, jamais « aucun concurrent » (règle 3)."""
    html = appeler("blocConcurrents", {"top_books": []}, dependances=("esc", "fmt", "fmtEur"))
    assert html.strip() == "" or "—" in html


# ── Le câblage : le bouton doit appeler l'endpoint ──────────────────────────────

def test_l_interface_appelle_reellement_l_endpoint_verdict():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text(
        encoding="utf-8")
    assert "'/api/verdict'" in src or '"/api/verdict"' in src
