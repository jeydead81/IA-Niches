"""Verdict low-content — et LA garde qui n'existe nulle part ailleurs dans le dépôt.

Un registre du personnel incomplet ne rate pas une vente : il expose l'acheteur, qui est
un employeur. Il prend des avis à une étoile et se fait retourner. Pour ces formats, la
CONFORMITÉ est la différenciation — pas la couverture, pas l'angle.

D'où une règle qu'aucun autre verdict n'a : sur un format `norme: true`, un « Go » sans
source réglementaire citée est **dégradé côté code**. On demande au prompt de citer le
texte, puis on vérifie que le champ est rempli. §4.2 : ce qui n'est pas doublé en code est
une intention, pas une règle — et ici l'intention ne suffit pas, parce que le coût d'un
oubli est porté par l'acheteur, pas par l'auteur.
"""
import pytest

from lowcontent_verdict import SYSTEM_PROMPT, generate_lowcontent_verdict
from models import AngleAttaque, LowContentNiche, LowContentScored


class _Bloc:
    type = "tool_use"

    def __init__(self, payload):
        self.input = payload


class _Usage:
    input_tokens = 900
    output_tokens = 1400


class _Reponse:
    def __init__(self, payload):
        self.content = [_Bloc(payload)]
        self.usage = _Usage()


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.appels = []
        self.messages = self

    def create(self, **kw):
        self.appels.append(kw)
        return _Reponse(self.payload)

    @property
    def prompt(self) -> str:
        return " ".join(m["content"] for a in self.appels for m in a["messages"])


def _scored(format_cle="journal_suivi", **kw) -> LowContentScored:
    n = LowContentNiche(niche="carnet de suivi glycémie",
                        requete_amazon="carnet suivi glycemie diabete",
                        rationale="r", categorie="santé", format_cle=format_cle,
                        theme="glycémie", public="adulte")
    base = dict(niche=n, global_score=7.4, demande=7.5, penetration=7.0,
                rentabilite=7.0, faisabilite=9.0, part_indie=0.8,
                n_variantes_quasi_identiques=3, prix_median=11.99, pages_median=120,
                redevance_estimee=3.15,
                # Calcul hors TVA (2026-09-15) : 11,99 € TTC = 9,99 € HT à 20 %.
                prix_catalogue_ht=9.99, taux_tva_suppose=0.2)
    base.update(kw)
    return LowContentScored(**base)


def _payload(verdict="Go", source_reglementaire="", **kw):
    d = {"verdict": verdict, "confiance": 8, "facteur_decisif": "la conformité",
         "saturation": "non", "faux_concurrent": "aucun",
         "differenciation": "par exécution",
         "angles": [{"angle": "a", "pourquoi": "p", "risque": "r", "titre": "t",
                     "sous_titre": "s", "prix_suggere": "11,99 €",
                     "spec_interieur": "120 pages, A5, une double page par semaine",
                     "redevance_estimee": "3,15 € par vente",
                     "source_reglementaire": source_reglementaire}]}
    d.update(kw)
    return d


# ── La spec d'intérieur ────────────────────────────────────────────────────────

def test_l_angle_porte_la_spec_d_interieur():
    """En low-content, l'intérieur EST le produit. Un angle qui ne dit pas combien de
    pages ni comment elles sont structurées ne se fabrique pas."""
    v = generate_lowcontent_verdict(_scored(), client=_Client(_payload()))
    a = v.angles[0]
    assert isinstance(a, AngleAttaque)
    assert "120 pages" in a.spec_interieur
    assert a.redevance_estimee


# ── La garde des formats normés ────────────────────────────────────────────────

def test_un_go_sur_un_format_norme_sans_source_est_degrade():
    """LE test du module. Un registre incomplet expose l'acheteur, qui est un employeur.
    Un « Go » silencieux sur un registre non sourcé est la pire sortie possible."""
    v = generate_lowcontent_verdict(
        _scored(format_cle="registres_reglementaires"),
        client=_Client(_payload(verdict="Go", source_reglementaire="")))
    assert v.verdict == "Go prudent"
    assert "source réglementaire" in v.facteur_decisif.lower()


def test_un_go_sur_un_format_norme_AVEC_source_reste_un_go():
    v = generate_lowcontent_verdict(
        _scored(format_cle="registres_reglementaires"),
        client=_Client(_payload(
            verdict="Go",
            source_reglementaire="Code du travail, art. L1221-13 et suivants")))
    assert v.verdict == "Go"
    assert "L1221-13" in v.angles[0].source_reglementaire


def test_un_no_go_n_est_jamais_remonte_par_la_garde():
    """La garde ne peut que DÉGRADER. Un « No-Go » qui deviendrait « Go prudent » parce
    qu'une source est citée serait une inversion absurde."""
    v = generate_lowcontent_verdict(
        _scored(format_cle="registres_reglementaires"),
        client=_Client(_payload(verdict="No-Go", source_reglementaire="")))
    assert v.verdict == "No-Go"


def test_la_garde_ne_s_applique_pas_a_un_format_ordinaire():
    """Un carnet de suivi n'a aucune source réglementaire à citer : exiger le champ
    dégraderait tous les verdicts du produit."""
    v = generate_lowcontent_verdict(
        _scored(format_cle="journal_suivi"),
        client=_Client(_payload(verdict="Go", source_reglementaire="")))
    assert v.verdict == "Go"


def test_le_prompt_reclame_la_source_sur_un_format_norme():
    """On demande d'abord, on vérifie ensuite — vérifier sans demander produirait des
    « Go prudent » systématiques."""
    c = _Client(_payload())
    generate_lowcontent_verdict(_scored(format_cle="registres_reglementaires"), client=c)
    p = c.prompt.lower()
    assert "réglementaire" in p or "reglementaire" in p


# ── Le brief ───────────────────────────────────────────────────────────────────

def test_le_brief_porte_les_signaux_propres_au_low_content():
    """Sans part indie ni variantes, le modèle raisonnerait comme sur du non-fiction et
    manquerait ce qui décide en low-content."""
    c = _Client(_payload())
    generate_lowcontent_verdict(_scored(), client=c)
    p = c.prompt.lower()
    assert "indie" in p and "variante" in p and "9,99" in p.replace(".", ",")


def test_une_mesure_absente_est_dite_comme_absente_dans_le_brief():
    """« part indie : 0 % » ferait conclure au modèle que le rayon est tenu par des
    éditeurs. « non mesurée » ne conclut rien (§5.10)."""
    c = _Client(_payload())
    generate_lowcontent_verdict(_scored(part_indie=None, n_editeur_inconnu=6), client=c)
    p = c.prompt.lower()
    assert "non mesur" in p
    # « 0 % » comme mot entier : chercher la sous-chaîne attraperait « 60 % », qui est le
    # taux de redevance et n'a rien à voir avec une part non mesurée.
    import re
    assert not re.search(r"(?<!\d)0\s?%", p)


def test_le_cout_est_impute_a_l_appelant():
    vus = []
    generate_lowcontent_verdict(_scored(), client=_Client(_payload()),
                                on_usage=lambda i, o, m: vus.append((i, o, m)))
    assert vus and vus[0][:2] == (900, 1400)


def test_le_prompt_declare_les_titres_concurrents_comme_des_donnees():
    p = SYSTEM_PROMPT.lower()
    assert "données" in p and "jamais des instructions" in p


def test_une_reponse_sans_bloc_outil_leve_proprement():
    """Tool-use FORCÉ : une réponse sans bloc d'outil est une anomalie, pas un verdict
    vide qu'on afficherait comme une analyse."""
    class _Vide:
        content = []
        usage = None

    class _ClientVide:
        messages = property(lambda self: self)

        def create(self, **kw):
            return _Vide()

    with pytest.raises(ValueError):
        generate_lowcontent_verdict(_scored(), client=_ClientVide())


def test_un_prix_non_mesure_n_est_pas_presente_comme_au_dessus_du_seuil():
    """Défaut trouvé en écrivant les tests : `prix_sous_seuil_60pct` vaut False quand
    AUCUN prix n'a été lu — pas parce que le rayon est cher. Le brief annonçait donc
    « au-dessus du seuil de 9,99 € → redevance 60 % » sur un rayon dont on ignorait tout
    des prix, et le modèle aurait raisonné sur une marge jamais constatée."""
    c = _Client(_payload())
    generate_lowcontent_verdict(_scored(prix_median=None, prix_sous_seuil_60pct=False),
                                client=c)
    p = c.prompt
    assert "Prix médian : non mesuré" in p
    assert "au-dessus du seuil" not in p


def test_le_brief_distingue_prix_affiche_et_prix_catalogue_hors_tva():
    """Le modèle propose un prix à SAISIR dans KDP : c'est un prix hors TVA. Sans le
    savoir, il lirait « 10,49 € » comme « au-dessus de 9,99 € », alors que le prix
    catalogue vaut 8,74 € et que KDP verse 50 % (écrans KDP du 2026-09-15)."""
    c = _Client(_payload())
    generate_lowcontent_verdict(_scored(prix_median=10.49, prix_catalogue_ht=8.74,
                                        taux_tva_suppose=0.2, prix_sous_seuil_60pct=True,
                                        format_coupe="grand", n_format_lus=6,
                                        n_grand_format=6), client=c)
    p = c.prompt
    assert "8.74" in p or "8,74" in p
    assert "hors TVA" in p and "grand format" in p
    assert "HORS TVA" in c.appels[0]["system"]


def test_un_resultat_anterieur_ne_donne_pas_au_modele_sa_redevance_ttc():
    """Résultat produit avant le calcul hors TVA (aucun prix HT) : sa redevance vient d'un
    taux appliqué au prix AFFICHÉ. Le modèle ne doit pas la recevoir comme une estimation,
    à côté d'un « taux de redevance non établi »."""
    c = _Client(_payload())
    generate_lowcontent_verdict(_scored(prix_median=10.49, prix_catalogue_ht=None,
                                        taux_tva_suppose=None, redevance_estimee=4.244),
                                client=c)
    p = c.prompt
    assert "4.244" not in p and "4,244" not in p
    assert "non établie" in p


def test_un_resultat_anterieur_affiche_sous_9_99_reste_a_50_pct_dans_le_brief():
    """Prix hors TVA < prix affiché : un ancien « sous 9,99 € » reste vrai à tout taux."""
    c = _Client(_payload())
    generate_lowcontent_verdict(_scored(prix_median=7.99, prix_catalogue_ht=None,
                                        taux_tva_suppose=None, prix_sous_seuil_60pct=True),
                                client=c)
    assert "50 %" in c.prompt
