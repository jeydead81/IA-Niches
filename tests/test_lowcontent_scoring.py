"""Scoring low-content — quatre axes, tout pur, tout testé.

Deux axes n'existent pas en non-fiction :

- RENTABILITÉ. Sous 9,99 € de prix catalogue, KDP verse 50 % au lieu de 60 %, et le coût
  d'impression se déduit ENSUITE. Un rayon très demandé à 6,99 € peut ne rien rapporter.
  C'est la question qui distingue le low-content : en non-fiction, un livre de texte à
  14,99 € ne pose pas ce problème.
- FAISABILITÉ. Un carnet quadrillé et un cahier d'activités illustré ne se produisent pas
  dans le même monde. En non-fiction tout est du texte, la question ne se pose pas.

Et deux signaux de pénétration propres au rayon :
- PART INDIE. Douze références peuvent toutes venir de papetiers (Exacompta, Quo Vadis).
  Un comptage de résultats ne le voit pas ; c'est pourtant ce qui décide si le rayon est
  attaquable par un auteur seul.
- VARIANTES QUASI IDENTIQUES. Un rayon de dix couvertures pour un seul intérieur n'est pas
  un rayon concurrentiel, c'est une ferme de variantes. Publier la onzième n'y gagne rien.

Les seuils vivent dans `data/lowcontent_criteres.json` et sont des HYPOTHÈSES tant que G1
ne les a pas calibrés. Les tests s'appuient sur des valeurs qu'ils passent explicitement,
pour ne pas devenir faux à la première recalibration.
"""
import pytest

from lowcontent_scoring import (charger_criteres, part_editeurs_traditionnels,
                                part_indie, part_recents, redevance_estimee,
                                score_lowcontent, variantes_quasi_identiques)
from models import (EnrichedBook, LowContentNiche, NicheValidation, SearchItem,
                    SearchResult)


def _livre(asin="A", publisher=None, date=None, titre="T", prix=None, pages=None):
    return EnrichedBook(asin=asin, title=titre, publisher=publisher,
                        publication_date=date, price=prix, pages=pages)


def _niche(**kw) -> LowContentNiche:
    base = dict(niche="carnet suivi glycémie", requete_amazon="carnet suivi glycemie",
                rationale="r", categorie="santé", format_cle="journal_suivi",
                theme="glycémie", public="adulte", source="autocomplete")
    base.update(kw)
    return LowContentNiche(**base)


# ── Part indie ─────────────────────────────────────────────────────────────────

def test_part_indie_exclut_les_inconnus_du_denominateur():
    """3 indie + 1 Larousse + 1 inconnu = 3/4, pas 3/5. Compter l'inconnu au
    dénominateur le traiterait comme « pas indie », donc comme un éditeur installé —
    une conclusion que rien ne soutient (§5.10)."""
    livres = [_livre("A1", "Independently published"),
              _livre("A2", "Independently published"),
              _livre("A3", "independently published"),
              _livre("A4", "Larousse"),
              _livre("A5", "Presses du Marais")]
    part, n_inconnu = part_indie(livres)
    assert part == 0.75 and n_inconnu == 1


def test_part_indie_rend_None_si_aucun_editeur_n_est_lisible():
    """Zéro serait « aucun indie dans ce rayon », donc une mauvaise nouvelle mesurée.
    None dit qu'on n'a rien pu lire."""
    part, n_inconnu = part_indie([_livre("A1"), _livre("A2", "Presses du Marais")])
    assert part is None and n_inconnu == 2


def test_part_indie_sur_liste_vide_rend_None():
    assert part_indie([]) == (None, 0)


def test_part_editeurs_traditionnels_est_le_symetrique():
    livres = [_livre("A1", "Hachette"), _livre("A2", "Independently published")]
    assert part_editeurs_traditionnels(livres)[0] == 0.5


# ── Fraîcheur du rayon ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("date", ["12 mars 2026", "2026-03-12", "12/03/2026"])
def test_les_formats_de_date_reels_sont_lus(date):
    """Amazon.fr rend « 12 mars 2025 » ; le cache et d'autres sources rendent l'ISO.
    Une date non lue doit être EXCLUE, jamais comptée comme ancienne."""
    part, n_inconnu = part_recents([_livre("A1", date=date)], mois=12,
                                   aujourdhui="2026-08-18")
    assert part == 1.0 and n_inconnu == 0


def test_une_date_illisible_est_exclue_pas_comptee_ancienne():
    part, n_inconnu = part_recents(
        [_livre("A1", date="2026-03-12"), _livre("A2", date="bientôt")],
        mois=12, aujourdhui="2026-08-18")
    assert part == 1.0 and n_inconnu == 1


def test_un_livre_ancien_ne_compte_pas_comme_recent():
    part, _ = part_recents([_livre("A1", date="2020-01-01"),
                            _livre("A2", date="2026-06-01")],
                           mois=12, aujourdhui="2026-08-18")
    assert part == 0.5


# ── Variantes quasi identiques ─────────────────────────────────────────────────

def test_des_variantes_du_meme_carnet_forment_un_seul_cluster():
    """Le signal qui distingue un rayon concurrentiel d'une ferme de variantes : même
    intérieur, dix couvertures. Publier la onzième n'y gagne rien."""
    titres = [
        "Carnet de suivi glycémie | 120 pages | A5",
        "Carnet de suivi glycémie - 120 pages - format A5",
        "CARNET DE SUIVI GLYCEMIE 120 pages (A5)",
        "Carnet de suivi glycemie : 100 pages, format A5",
        "Carnet suivi glycémie 150 pages A5 broché",
    ]
    assert variantes_quasi_identiques(titres) == 5


def test_des_titres_distincts_ne_forment_pas_de_cluster():
    titres = ["Carnet de suivi glycémie", "Mon journal de méditation",
              "Registre du personnel", "Cahier de recettes de famille"]
    assert variantes_quasi_identiques(titres) == 1


def test_le_bruit_de_format_est_neutralise():
    """« 120 pages », « A5 », « broché » décrivent le contenant, pas le sujet : les
    garder ferait de deux carnets distincts des variantes l'un de l'autre."""
    titres = ["Carnet de recettes 120 pages A5 broché",
              "Journal de bord 120 pages A5 broché"]
    assert variantes_quasi_identiques(titres) == 1


def test_une_liste_vide_ne_conclut_rien():
    """Zéro titre n'est pas « aucune variante » : c'est une absence de mesure."""
    assert variantes_quasi_identiques([]) == 0


# ── Redevance ──────────────────────────────────────────────────────────────────

def test_le_taux_bascule_au_seuil_officiel():
    """Barème RELEVÉ chez Amazon (topic G201834330) : 50 % jusqu'à 9,98 €, 60 % à partir
    de 9,99 €. À 100 pages en encre noire, l'impression est le forfait de la bande COURTE
    (2,05 €), sans coût par page."""
    assert redevance_estimee(9.98, 100) == pytest.approx(0.50 * 9.98 - 2.05, abs=0.01)
    assert redevance_estimee(9.99, 100) == pytest.approx(0.60 * 9.99 - 2.05, abs=0.01)


def test_les_deux_bandes_ont_chacune_leur_forfait():
    """CE test est né d'un bug réel, trouvé par audit après coup.

    La grille KDP a DEUX bandes par encre, et chacune a SON forfait : 2,05 € pour 24-110
    pages (sans coût par page), 0,75 € + 0,012 €/page au-delà. Le premier relevé n'avait
    retenu qu'un forfait unique de 0,75 € appliqué aux deux — ce qui sous-estimait le coût
    d'impression de 1,30 € sur toute pagination courte, donc SURESTIMAIT la redevance
    d'autant. Or 35 des 36 formats de la taxonomie ont une borne basse ≤ 110 pages : c'était
    le cas NORMAL du rayon, pas un cas limite.

    Et ce n'était pas cosmétique : à 7,99 € sur 100 pages, la redevance affichée passait de
    1,95 € (sous `redevance_min_bonne`) à 3,25 € (au-dessus), ce qui accordait +2 sur l'axe
    rentabilité et faisait basculer le verdict."""
    courte = redevance_estimee(7.99, 100)
    assert courte == pytest.approx(0.50 * 7.99 - 2.05, abs=0.01)
    assert courte < 2.0                       # sous le seuil de bonus : c'est le point

    longue = redevance_estimee(7.99, 200)
    assert longue == pytest.approx(0.50 * 7.99 - (0.75 + 200 * 0.012), abs=0.01)


def test_le_saut_au_point_de_bascule_reste_petit():
    """Le symptôme qui a trahi le bug : avec un forfait unique, passer de 110 à 111 pages
    coûtait 1,33 € de plus — aucune grille d'impression à la demande ne fait ça. Avec les
    deux forfaits relevés, l'écart au point de bascule est de quelques centimes."""
    c110 = redevance_estimee(14.99, 110)
    c111 = redevance_estimee(14.99, 111)
    assert abs(c110 - c111) < 0.10


def test_au_dela_du_seuil_de_pages_le_cout_par_page_s_applique():
    """0,75 € + 0,012 €/page en encre noire au-delà de 110 pages."""
    attendu = 0.60 * 14.99 - (0.75 + 200 * 0.012)
    assert redevance_estimee(14.99, 200) == pytest.approx(attendu, abs=0.01)


def test_la_couleur_standard_coute_deux_fois_plus_par_page():
    noir = redevance_estimee(14.99, 120, encre="bw")
    couleur = redevance_estimee(14.99, 120, encre="couleur_standard")
    assert couleur < noir


def test_une_redevance_negative_est_rendue_telle_quelle():
    """Un carnet de 400 pages à 6,99 € PERD de l'argent à chaque vente. Ramener le
    résultat à zéro cacherait exactement ce qu'on veut montrer."""
    r = redevance_estimee(6.99, 400)
    assert r is not None and r < 0


def test_sans_prix_ou_sans_pages_la_redevance_est_None():
    """None, jamais 0 : une redevance inconnue n'est pas une redevance nulle. Le scoring
    n'applique aucun bonus ni malus dessus."""
    assert redevance_estimee(None, 120) is None
    assert redevance_estimee(9.99, None) is None


def test_une_encre_inconnue_leve():
    """Deviner une grille de coût fabriquerait un chiffre présenté comme relevé."""
    with pytest.raises(ValueError):
        redevance_estimee(9.99, 120, encre="paillettes")


# ── Score complet ──────────────────────────────────────────────────────────────

def _validation(demand=6, validated=True):
    return NicheValidation(niche="carnet suivi glycémie",
                           requete_amazon="carnet suivi glycemie", categorie="santé",
                           demand_score=demand, validated=validated)


def _serp(n=4):
    return SearchResult(keyword="q", sponsored=[], organic=[
        SearchItem(title=f"Carnet {i}", asin=f"A{i}", price=11.99, reviews_count=10)
        for i in range(n)])


def _livres_indie(n=4):
    return [_livre(f"A{i}", "Independently published", "2026-06-01",
                   f"Carnet {i}", 11.99, 120) for i in range(n)]


def test_le_score_rend_les_quatre_axes_et_un_global():
    s = score_lowcontent(_niche(), _validation(), _serp(), _livres_indie(), [3000])
    assert 0 < s.global_score <= 10
    for axe in (s.demande, s.penetration, s.rentabilite, s.faisabilite):
        assert 0 <= axe <= 10


def test_une_serp_absente_n_accorde_aucun_bonus_de_penetration():
    """Même garde qu'en non-fiction (§4.1) : sans mesure, `n_concurrents_cibles == 0`
    déclencherait le bonus « rayon vide » sur une niche dont rien n'a été mesuré."""
    s = score_lowcontent(_niche(), _validation(), None, [], [])
    assert s.concurrence_mesuree is False
    assert "non mesur" in s.priorite.lower()


def test_un_rayon_tenu_par_des_editeurs_traditionnels_est_penalise():
    trad = [_livre(f"A{i}", "Hachette", "2026-06-01", f"Agenda {i}", 12.99, 120)
            for i in range(4)]
    s_trad = score_lowcontent(_niche(), _validation(), _serp(), trad, [3000])
    s_indie = score_lowcontent(_niche(), _validation(), _serp(), _livres_indie(), [3000])
    assert s_trad.demande < s_indie.demande


_COULEURS = ["bleue", "rose", "verte", "noire", "jaune", "grise", "beige", "violette"]


def _titre_de_ferme(couleur: str) -> str:
    """Ce a quoi ressemble VRAIMENT une ferme de variantes : le meme titre long, un seul
    mot de couverture qui change. Un suffixe artificiel « v0 / v1 » sur un titre court ne
    l'imite pas -- apres retrait du bruit de format il ne reste que deux mots utiles, et
    un seul mot different suffit alors a faire tomber Jaccard sous le seuil."""
    return (f"Carnet de Suivi Glycémie : journal de bord pour diabétique "
            f"| 120 pages | format A5 | couverture {couleur}")


def test_une_ferme_de_variantes_est_penalisee():
    serp = SearchResult(keyword="q", sponsored=[], organic=[
        SearchItem(title=_titre_de_ferme(c), asin=f"A{i}", price=11.99)
        for i, c in enumerate(_COULEURS)])
    s = score_lowcontent(_niche(), _validation(), serp, _livres_indie(8), [3000])
    assert s.n_variantes_quasi_identiques >= 6


def test_un_rayon_sous_le_seuil_est_signale_sans_etre_condamne():
    """Le drapeau informe ; il ne remplace pas le score. Un rayon à 7 € peut rester
    intéressant si le volume est là — c'est à l'auteur de trancher, pas au barème."""
    pas_cher = [_livre(f"A{i}", "Independently published", "2026-06-01", f"C{i}", 6.99, 100)
                for i in range(4)]
    serp = SearchResult(keyword="q", sponsored=[], organic=[
        SearchItem(title=f"C{i}", asin=f"A{i}", price=6.99) for i in range(4)])
    s = score_lowcontent(_niche(), _validation(), serp, pas_cher, [3000])
    assert s.prix_sous_seuil_60pct is True
    assert s.global_score > 0


def test_un_format_hors_taxonomie_ne_vaut_pas_zero_en_faisabilite():
    """« non évalué » n'est pas « mauvais » — c'est la faute que règle 3 interdit. Le
    format inconnu prend une valeur neutre, et le dit."""
    s = score_lowcontent(_niche(format_cle="other", other_libelle="carnet lunaire"),
                         _validation(), _serp(), _livres_indie(), [3000])
    assert s.faisabilite == 5.0


def test_un_format_illustre_est_plus_couteux_a_produire():
    facile = score_lowcontent(_niche(format_cle="journal_suivi"), _validation(),
                              _serp(), _livres_indie(), [3000])
    dur = score_lowcontent(_niche(format_cle="coloriage_enfant"), _validation(),
                           _serp(), _livres_indie(), [3000])
    assert dur.faisabilite < facile.faisabilite


def test_un_format_norme_porte_son_risque_sans_perdre_en_faisabilite():
    """« Normé » ne veut pas dire « difficile » : le contenu est IMPOSÉ, donc simple à
    produire. C'est la conformité qui est exigeante, et elle sort en risque."""
    s = score_lowcontent(_niche(format_cle="registres_reglementaires"), _validation(),
                         _serp(), _livres_indie(), [3000])
    assert "norme_a_verifier" in s.risques
    assert s.faisabilite >= 8


def test_un_risque_de_marque_pese_lourd_sur_le_global():
    propre = score_lowcontent(_niche(), _validation(), _serp(), _livres_indie(), [3000])
    risquee = score_lowcontent(_niche(risques=["ip_marque"]), _validation(), _serp(),
                               _livres_indie(), [3000])
    assert risquee.global_score < propre.global_score - 1


def test_la_profondeur_dans_l_arbre_nourrit_la_demande():
    """Le signal propre au low-content : une requête que les acheteurs affinent encore
    porte une intention plus forte qu'une requête terminale."""
    plate = score_lowcontent(_niche(profondeur_autocomplete=0, n_enfants_autocomplete=0),
                             _validation(), _serp(), _livres_indie(), [3000])
    profonde = score_lowcontent(_niche(profondeur_autocomplete=2, n_enfants_autocomplete=5),
                                _validation(), _serp(), _livres_indie(), [3000])
    assert profonde.demande > plate.demande


def test_les_seuils_viennent_du_fichier_de_criteres():
    """G1 recalibre le FICHIER, jamais le code. Un seuil qui migre dans le .py redevient
    invisible et non discutable.

    `variantes_max` valait 6 ; il est NEUTRALISÉ à 1000 depuis le 2026-09-30 (décision de
    Baptiste, rejeu hors ligne des runs 5 et 6) : 1000 est au-delà de tout maximum observé
    (29 variantes sur 95 niches), donc le terme ne se déclenche jamais. Le test garde une
    valeur en dur pour la même raison qu'avant — c'est le FICHIER qui doit porter le
    réglage — mais il ne peut plus prétendre que 6 est un seuil calibré."""
    c = charger_criteres()
    assert c["variantes_max"] == 1000 and c["cibles_max"] == 1000, \
        "termes neutralisés : les remettre en service est une décision, pas un ajustement"
    assert c["seuil_prix_60pct"] == 9.99


def test_les_criteres_peuvent_etre_surcharges_par_l_appelant():
    """C'est ce qui rend la calibration possible sans toucher au dépôt."""
    c = charger_criteres()
    c["variantes_max"] = 1
    serp = SearchResult(keyword="q", sponsored=[], organic=[
        SearchItem(title=_titre_de_ferme(coul), asin=f"A{i}")
        for i, coul in enumerate(_COULEURS[:4])])
    s = score_lowcontent(_niche(), _validation(), serp, _livres_indie(), [3000],
                         criteres=c)
    assert s.n_variantes_quasi_identiques > 1


def test_la_limite_du_clustering_est_nommee_pas_masquee():
    """Le calcul porte sur les mots UTILES : apres retrait du bruit de format (« 120
    pages », « A5 », « broche »), un titre tres court ne laisse que deux ou trois mots, et
    un seul mot different fait alors tomber Jaccard sous le seuil.

    C'est une limite reelle, pas un bug : deux carnets titres « Carnet glycemie bleu » et
    « Carnet glycemie rose » ne seront PAS groupes. Les vraies fermes de variantes ont des
    titres longs et bourres de mots-cles, ou l'overlap est ecrasant. Le seuil est
    calibrable dans G1 si la mesure en live dit le contraire."""
    courts = ["Carnet glycémie bleu", "Carnet glycémie rose"]
    assert variantes_quasi_identiques(courts) == 1
    longs = [_titre_de_ferme("bleue"), _titre_de_ferme("rose")]
    assert variantes_quasi_identiques(longs) == 2
