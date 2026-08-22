"""Les quatre pages publiques sont des BROUILLONS. Ce test empêche de les servir telles quelles.

Mentions légales, politique de confidentialité, CGV et landing sont rédigées à partir de ce
que le code fait réellement, mais tout ce que le code ne peut pas savoir — identité légale
de l'éditeur, hébergeur, prix, délai de rétractation — est laissé en `[[A COMPLETER : …]]`.

Le risque n'est pas qu'elles soient incomplètes : c'est qu'on les branche sur une route en
oubliant de les remplir. Des mentions légales publiées avec « [[A COMPLETER : SIREN]] »
sont pires que pas de mentions légales du tout — elles affichent au visiteur que
l'obligation a été vue et pas honorée, et elles ne remplissent aucune des conditions de
l'article 6-III de la LCEN.

C'est la famille de défaut de §5.26, dans l'autre sens : là-bas des boutons existaient
sans chemin d'accès ; ici on veut empêcher un chemin d'accès vers un contenu qui n'existe
qu'à moitié. Le test lie donc les deux : **dès qu'une route sert un de ces fichiers, il ne
doit plus rester un seul marqueur dedans.**
"""
import re
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parent.parent
_DOSSIER = _RACINE / "docs" / "pages-publiques"
_FICHIERS = ("mentions-legales.md", "politique-de-confidentialite.md", "cgv.md",
             "landing-page.md")
_MARQUEUR = "[[A COMPLETER"


@pytest.fixture(scope="module")
def serveur() -> str:
    return (_RACINE / "web" / "server.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("nom", _FICHIERS)
def test_la_page_existe(nom):
    assert (_DOSSIER / nom).is_file(), f"{nom} manquant dans docs/pages-publiques/"


@pytest.mark.parametrize("nom", _FICHIERS)
def test_une_page_servie_n_a_plus_aucun_marqueur(nom, serveur):
    """LE test. Tant que personne ne la sert, une page à trous est un brouillon utile.
    Dès qu'une route la sert, chaque `[[A COMPLETER]]` devient une mention légale
    manquante affichée en public."""
    servie = nom in serveur or nom.removesuffix(".md") in serveur
    contenu = (_DOSSIER / nom).read_text(encoding="utf-8")
    trous = contenu.count(_MARQUEUR)
    if servie:
        assert trous == 0, (
            f"{nom} est référencée par web/server.py mais contient encore {trous} "
            f"marqueur(s) {_MARQUEUR} — ne pas la publier avant de les remplir")


@pytest.mark.parametrize("nom", _FICHIERS)
def test_chaque_marqueur_dit_CE_qu_il_attend(nom):
    """`[[A COMPLETER]]` tout court obligerait Baptiste à deviner ce qu'on lui demande, et
    la première réponse plausible venue serait écrite dans un document juridique. Chaque
    marqueur porte donc sa consigne."""
    contenu = (_DOSSIER / nom).read_text(encoding="utf-8")
    for m in re.finditer(r"\[\[A COMPLETER([^\]]*)\]\]", contenu):
        consigne = m.group(1).lstrip(" :").strip()
        assert len(consigne) >= 10, f"{nom} : marqueur sans consigne — « {m.group(0)} »"


def test_la_landing_n_annonce_aucun_prix_en_dur():
    """Le prix n'est pas décidé, et « 19 EUR/mois » est un chiffre de cadrage de session de
    travail, pas une décision (CLAUDE.md §1). L'écrire sur une landing en ferait une offre."""
    contenu = (_DOSSIER / "landing-page.md").read_text(encoding="utf-8")
    section = contenu[contenu.find("## "):]
    montants = re.findall(r"\b\d+(?:[,.]\d+)?\s*(?:€|EUR)\s*(?:/|par\s+)\s*(?:mois|an)",
                          section, re.I)
    assert not montants, f"prix annoncé sur la landing : {montants}"


def test_la_landing_dit_qu_aucun_paiement_n_est_branche():
    """Rien n'encaisse (CLAUDE.md §7). Une landing qui laisse croire le contraire promet un
    service qui n'existe pas."""
    contenu = (_DOSSIER / "landing-page.md").read_text(encoding="utf-8").lower()
    assert "aucun système de paiement" in contenu or "aucun systeme de paiement" in contenu


def test_aucune_page_ne_publie_de_marge_ni_de_cout_interne():
    """Marge, coût par analyse, tarif DataForSEO : ce sont des chiffres d'exploitation.
    Les publier donnerait au premier concurrent venu la structure de coût du produit, et
    au client le sentiment d'être au-dessus du prix de revient."""
    interdits = ("88 %", "94 %", "0,084", "0.084", "0,030 $", "0.030 $", "marge")
    for nom in _FICHIERS:
        contenu = (_DOSSIER / nom).read_text(encoding="utf-8").lower()
        # L'annexe de sources d'une page cite le code : on ne la lit pas, elle ne sera
        # jamais publiée telle quelle.
        corps = contenu.split("sources dans le code")[0]
        for mot in interdits:
            assert mot.lower() not in corps, f"{nom} publie « {mot} »"
