"""Cliquet du pré-enregistrement du lot 3 (`docs/preenregistrement-lot3.md`).

Un pré-enregistrement ne vaut que si ce qu'il gèle est vraiment gelé. Les seuils touchés
entre le gel et le run rendraient la validation nulle — et rien ne le signalerait, puisque le
rapport ne porte ni les critères ni le commit (§2.14). Ce test est la seule chose qui le dise.

Le levier est réel : au lot 1, régler `cibles_max` et `variantes_max` en maximisant sur le lot
donnait +0,534, porte franchie, et +0,190 en validation. Le fichier de critères a assez de
degrés de liberté pour ajuster le bruit de 51 niches.

Si Baptiste décide de changer un de ces seuils, ce test doit échouer : c'est alors le
pré-enregistrement qu'on met à jour, en actant que le lot 3 ne valide plus rien.
"""
from pathlib import Path

import pytest

from lowcontent_scoring import charger_criteres

_DOC = Path(__file__).resolve().parents[1] / "docs" / "preenregistrement-lot3.md"


@pytest.mark.parametrize("cle,valeur", [
    ("demande_plafond", 5),
    ("seuil_verdict_vivant", 5.0),
    ("cibles_max", 1000),
    ("variantes_max", 1000),
])
def test_les_seuils_geles_n_ont_pas_bouge(cle, valeur):
    assert charger_criteres()[cle] == valeur, (
        f"{cle} a changé depuis le gel du lot 3 : mettre à jour "
        f"docs/preenregistrement-lot3.md et acter que ce lot ne valide plus les hypothèses "
        f"qui en dépendent.")


def test_le_document_existe_et_porte_ses_sept_hypotheses():
    texte = _DOC.read_text(encoding="utf-8")
    for h in ("H1", "H2", "H3", "H4", "H5", "H6", "H7"):
        assert f"**{h}**" in texte
    assert "[[" not in texte, "un pré-enregistrement à trous ne gèle rien"


def test_la_cle_du_gate_est_bien_celle_qui_a_ete_gelee():
    """Le premier terme est le nombre de mots, le dernier une empreinte stable."""
    from lowcontent_master import _rang_shortlist
    cle = _rang_shortlist("cahier de vacances cm2", 3, 1, 3)
    assert len(cle) == 5 and cle[0] == 4 and cle[1] == 3
    assert _rang_shortlist("cahier de vacances cm2", 3, 1, 3) == cle
