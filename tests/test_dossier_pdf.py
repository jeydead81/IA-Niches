"""Dossier PDF v2 — le document qu'on emporte, commun non-fiction et low-content.

Le one-pager existant s'arrête au verdict. Ce qui manque à un auteur qui va publier tient
en trois choses, et elles étaient déjà toutes payées :

- CONTRE QUI il publie. `top_books` porte titres, prix, avis et BSR depuis le chunk B ;
  jusqu'ici le PDF n'en montrait rien.
- QUOI écrire dans les 7 champs de mots-clés KDP.
- DANS QUELLES CATÉGORIES ranger le livre — déduit des BSR déjà collectés, coût 0 $.

Un invariant traverse tout le module : une donnée ABSENTE s'écrit « non mesuré » et jamais
zéro. Sur un document imprimé que l'auteur relira dans trois semaines, un zéro muet est
pire qu'ailleurs — il n'y a plus d'écran pour poser la question.
"""
from pathlib import Path

import pytest

from dossier_pdf import build_dossier_pdf
from models import (AngleAttaque, LowContentNiche, LowContentScored, MotsClesKDP,
                    NicheVerdict, ScoredNiche, TopBook)


def _verdict(**kw) -> NicheVerdict:
    base = dict(verdict="Go", confiance=8, facteur_decisif="l'exécution",
                saturation="non", faux_concurrent="aucun",
                differenciation="par exécution",
                angles=[AngleAttaque(
                    angle="le carnet du diabétique", pourquoi="rayon indie",
                    risque="saisonnalité faible", titre="Mon carnet de glycémie",
                    sous_titre="120 jours de suivi", prix_suggere="11,99 €",
                    requete_principale="carnet glycémie",
                    spec_interieur="A5, 120 pages, une double page par semaine",
                    # Texte de l'IA, volontairement DIFFÉRENT de tout float calculé : le
                    # dossier ne doit jamais laisser croire que les deux sont la même chose.
                    redevance_estimee="environ 3,20 € par vente",
                    source_reglementaire="")])
    base.update(kw)
    return NicheVerdict(**base)


def _nf(**kw) -> ScoredNiche:
    base = dict(niche="carnet de suivi glycémie", requete_amazon="carnet suivi glycemie",
                categorie="santé", global_score=7.8, demande=8.0, penetration=7.4,
                bsr_best=8214, bsr_top5_avg=41000, n_concurrents_cibles=6,
                n_sponsored=3, concurrence_mesuree=True, verdict=_verdict(),
                top_books=[
                    TopBook(asin="A1", title="Carnet de suivi glycémie 120 pages",
                            url="https://www.amazon.fr/dp/A1", price=9.99, rating=4.4,
                            reviews_count=37, bsr=8214),
                    TopBook(asin="A2", title="Journal du diabétique",
                            url="https://www.amazon.fr/dp/A2")])
    base.update(kw)
    return ScoredNiche(**base)


def _lc(**kw) -> LowContentScored:
    n = LowContentNiche(niche="registre du personnel",
                        requete_amazon="registre du personnel obligatoire", rationale="r",
                        categorie="pro", format_cle="registres_reglementaires",
                        theme="personnel", public="professionnel")
    base = dict(niche=n, global_score=7.1, demande=7.0, penetration=7.5,
                rentabilite=8.0, faisabilite=9.0, part_indie=0.7,
                n_variantes_quasi_identiques=2, prix_median=14.99, pages_median=120,
                redevance_estimee=4.24, concurrence_mesuree=True,
                # Calcul hors TVA (2026-09-15) : 14,99 € TTC = 12,49 € HT à 20 %.
                prix_catalogue_ht=12.49, taux_tva_suppose=0.2,
                verdict=_verdict(angles=[AngleAttaque(
                    angle="registre conforme", pourquoi="conformité", risque="texte",
                    titre="Registre unique du personnel", sous_titre="conforme 2026",
                    spec_interieur="A4, 100 pages, une ligne par salarié",
                    redevance_estimee="environ 4,50 € par vente",   # ≠ 4.24 calculé
                    source_reglementaire="Code du travail, art. L1221-13")]))
    base.update(kw)
    return LowContentScored(**base)


def _texte(chemin: Path) -> str:
    """Texte brut du PDF. On ne vérifie pas la mise en page — on vérifie que l'INFORMATION
    y est. Un PDF qui compile mais qui a perdu le tableau des concurrents est un PDF qui
    ment par omission."""
    pypdf = pytest.importorskip("pypdf")
    lecteur = pypdf.PdfReader(str(chemin))
    return "\n".join(p.extract_text() or "" for p in lecteur.pages)


# ── Structure ──────────────────────────────────────────────────────────────────

def test_le_dossier_est_ecrit_et_non_vide(tmp_path):
    out = build_dossier_pdf(_nf(), tmp_path / "d.pdf")
    assert out.exists() and out.stat().st_size > 2000


def test_le_dossier_tient_en_trois_pages(tmp_path):
    """Trois pages : ce qu'on affronte, ce qu'on écrit, comment on le range. Au-delà,
    l'auteur ne le lit plus."""
    pypdf = pytest.importorskip("pypdf")
    out = build_dossier_pdf(_nf(), tmp_path / "d.pdf",
                            mots_cles=MotsClesKDP(emplacements=["carnet glycémie"]),
                            categories=[{"category": "Diabète", "n_livres": 3,
                                         "meilleur_rang": 8}])
    assert len(pypdf.PdfReader(str(out)).pages) == 3


# ── Page 1 : les concurrents ───────────────────────────────────────────────────

def test_les_concurrents_du_top_sont_dans_le_dossier(tmp_path):
    """`top_books` est payé depuis le chunk B et n'apparaissait nulle part. C'est pourtant
    la seule chose que l'auteur veut vraiment voir : contre qui il publie."""
    t = _texte(build_dossier_pdf(_nf(), tmp_path / "d.pdf"))
    assert "Carnet de suivi glyc" in t
    assert "8214" in t.replace(" ", "") or "8 214" in t


def test_un_bsr_inconnu_s_ecrit_non_mesure_et_jamais_zero(tmp_path):
    """Zéro est le MEILLEUR classement possible : sur un document imprimé, un BSR manquant
    affiché « 0 » se lirait comme un best-seller, et rien ne viendra le corriger."""
    t = _texte(build_dossier_pdf(_nf(), tmp_path / "d.pdf"))
    assert "Journal du diab" in t          # le livre sans BSR est bien present
    assert "non mesure" in t.lower() or "non mesuré" in t.lower()


def test_sans_concurrents_connus_le_dossier_le_dit(tmp_path):
    """Liste vide = rayon non mesuré, jamais « aucun concurrent » (règle 3)."""
    t = _texte(build_dossier_pdf(_nf(top_books=[]), tmp_path / "d.pdf"))
    assert "non mesur" in t.lower() or "aucun concurrent connu" in t.lower()


def test_une_niche_sans_concurrence_mesuree_porte_son_avertissement(tmp_path):
    t = _texte(build_dossier_pdf(_nf(concurrence_mesuree=False), tmp_path / "d.pdf"))
    assert "non mesur" in t.lower()


# ── Page 2 : l'angle ───────────────────────────────────────────────────────────

def test_l_angle_recommande_est_complet(tmp_path):
    t = _texte(build_dossier_pdf(_nf(), tmp_path / "d.pdf"))
    assert "Mon carnet de glyc" in t and "120 jours" in t


def test_la_spec_d_interieur_apparait_en_low_content(tmp_path):
    """En low-content, l'intérieur EST le produit : un dossier sans spec ne se fabrique
    pas. En non-fiction le champ est vide et ne doit pas laisser de section fantôme."""
    t = _texte(build_dossier_pdf(_lc(), tmp_path / "d.pdf"))
    assert "100 pages" in t and "une ligne par salari" in t


def test_la_source_reglementaire_apparait_sur_un_format_norme(tmp_path):
    """C'est LA différenciation d'un registre. L'omettre du document emporté viderait la
    garde du verdict de son effet."""
    t = _texte(build_dossier_pdf(_lc(), tmp_path / "d.pdf"))
    assert "L1221-13" in t


def test_un_dossier_sans_verdict_reste_utile(tmp_path):
    """Le verdict est payé à la pièce et peut ne pas avoir été demandé. Le PDF doit alors
    livrer les mesures et le dire, pas échouer ni faire semblant."""
    t = _texte(build_dossier_pdf(_nf(verdict=None), tmp_path / "d.pdf"))
    assert "8214" in t.replace(" ", "") or "8 214" in t
    assert "verdict" in t.lower()


# ── Page 3 : mots-clés et catégories ───────────────────────────────────────────

def test_les_mots_cles_kdp_sont_repris_avec_leur_longueur(tmp_path):
    """KDP impose 50 caractères par champ : la longueur consommée est une donnée de
    saisie, pas une décoration."""
    mc = MotsClesKDP(emplacements=["carnet suivi glycemie",
                               "journal diabete type 2"])
    t = _texte(build_dossier_pdf(_nf(), tmp_path / "d.pdf", mots_cles=mc))
    assert "carnet suivi glycemie" in t
    assert "50" in t


def test_les_rejets_de_mots_cles_sortent_avec_leur_motif(tmp_path):
    """« rejeté » n'apprend rien ; « contient une marque » évite de le reproposer."""
    mc = MotsClesKDP(emplacements=["carnet glycemie"],
                     rejetes=[{"mot": "livre glycemie",
                               "motif": "terme interdit : livre"}])
    t = _texte(build_dossier_pdf(_nf(), tmp_path / "d.pdf", mots_cles=mc))
    assert "terme interdit" in t


def test_la_sonde_indisponible_est_signalee(tmp_path):
    """Sans ça, des mots-clés NON confirmés se liraient comme confirmés (§5.10)."""
    mc = MotsClesKDP(emplacements=["carnet glycemie"], sonde_indisponible=True)
    t = _texte(build_dossier_pdf(_nf(), tmp_path / "d.pdf", mots_cles=mc))
    assert "sonde" in t.lower() or "non confirm" in t.lower()


def test_les_categories_suggerees_disent_sur_quoi_elles_reposent(tmp_path):
    """« Diabète » seul serait un conseil. « 3 livres du top y sont rangés » est une
    observation — et c'est tout ce que la donnée soutient."""
    t = _texte(build_dossier_pdf(
        _nf(), tmp_path / "d.pdf",
        categories=[{"category": "Diabète", "n_livres": 3, "meilleur_rang": 8}]))
    assert "Diab" in t and "3" in t


def test_sans_categories_le_dossier_ne_fabrique_rien(tmp_path):
    """Aucune sous-catégorie lisible n'est pas « aucune catégorie pertinente »."""
    t = _texte(build_dossier_pdf(_nf(), tmp_path / "d.pdf", categories=[]))
    assert "non mesur" in t.lower() or "aucune cat" in t.lower()


# ── Robustesse ─────────────────────────────────────────────────────────────────

def test_un_titre_accentue_ne_fait_pas_echouer_le_pdf(tmp_path):
    """fpdf2 en police core Helvetica exige du latin-1 : un caractère hors jeu ferait
    planter la génération, pas juste s'afficher de travers."""
    n = _nf(top_books=[TopBook(asin="A1", title="Cœur — « résumé » … 100 %",
                               url="u", bsr=100)])
    assert build_dossier_pdf(n, tmp_path / "d.pdf").exists()


def test_un_titre_tres_long_ne_deborde_pas(tmp_path):
    n = _nf(top_books=[TopBook(asin="A1", title="T" * 400, url="u", bsr=1)])
    assert build_dossier_pdf(n, tmp_path / "d.pdf").exists()


def test_le_dossier_low_content_porte_ses_signaux_propres(tmp_path):
    t = _texte(build_dossier_pdf(_lc(), tmp_path / "d.pdf"))
    assert "indie" in t.lower()
    assert "14,99" in t or "14.99" in t


# ── R31 : la redevance de l'IA n'est pas un calcul ─────────────────────────────

def _pages(chemin: Path) -> list[str]:
    pypdf = pytest.importorskip("pypdf")
    return [p.extract_text() or "" for p in pypdf.PdfReader(str(chemin)).pages]


def test_la_redevance_de_l_angle_est_dite_estimee_par_l_ia(tmp_path):
    """La « Redevance » de la page 2 est une phrase du modèle : aucun prix, aucune pagination
    ni aucun barème d'impression n'y entre côté code. Imprimée sans qualificatif, elle se
    lisait comme le montant calculé — sur un document qu'on relit sans écran pour demander."""
    import re
    angle = AngleAttaque(angle="a", pourquoi="p", risque="r", titre="Registre",
                         sous_titre="s", spec_interieur="A4, 100 pages",
                         redevance_estimee="environ 3,20 € par vente")
    p = _pages(build_dossier_pdf(
        _lc(pages_median=None, redevance_estimee=None, prix_median=None,
            verdict=_verdict(angles=[angle])), tmp_path / "d.pdf"))
    assert "estimation de l" in p[1] and "non calcul" in p[1]
    assert "3,20" in p[1]
    # Page 1 : « non mesuré EUR par vente » mettait une unité sur une absence de mesure.
    assert not re.search(r"non mesur\S*\s*EUR", p[0])


def test_une_redevance_calculee_garde_son_montant_en_page_1(tmp_path):
    p = _pages(build_dossier_pdf(_lc(), tmp_path / "d.pdf"))
    assert "4,24 EUR par vente" in p[0] and "14,99 EUR" in p[0]


def test_le_prompt_demande_le_cout_d_impression_suppose():
    """Le texte reste celui de l'IA ; on lui demande au moins de dire sur quel coût
    d'impression il repose, ou qu'il ne peut pas le chiffrer. Vérifié sur le prompt ENVOYÉ."""
    from lowcontent_verdict import generate_lowcontent_verdict
    from tests.test_lowcontent_verdict import _Client, _payload, _scored
    c = _Client(_payload())
    generate_lowcontent_verdict(_scored(), client=c)
    assert "ne peux pas le chiffrer" in c.appels[0]["system"]


def test_la_page_1_dit_le_prix_hors_tva_et_le_format_de_coupe(tmp_path):
    """Le prix médian est celui que voit le client ; la redevance se calcule sur le prix
    catalogue HORS TVA, au format de coupe du rayon. Imprimer l'un sans l'autre fait lire
    un montant calculé sur des hypothèses qu'on ne voit pas."""
    p = _pages(build_dossier_pdf(_lc(prix_median=14.99, prix_catalogue_ht=12.49,
                                     taux_tva_suppose=0.2, format_coupe="grand"),
                                 tmp_path / "d.pdf"))
    assert "12,49 EUR HT" in p[0]
    assert "grand format" in p[0]


def test_un_resultat_anterieur_n_imprime_pas_sa_redevance_ttc(tmp_path):
    """Résultat produit avant le calcul hors TVA : sa redevance a été calculée à 60 % sur le
    prix AFFICHÉ (0,60 x 10,49 − 2,05 = 4,24 €), là où KDP verserait 2,32 €. L'imprimer
    sous « prix catalogue KDP : non calcule » la ferait lire comme un montant établi."""
    p = _pages(build_dossier_pdf(_lc(prix_median=10.49, prix_catalogue_ht=None,
                                     taux_tva_suppose=None, redevance_estimee=4.24),
                                 tmp_path / "d.pdf"))
    assert "4,24" not in p[0]
    assert "recalcul" in p[0]
