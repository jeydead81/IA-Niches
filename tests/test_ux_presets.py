"""Presets Rapide / Standard / Approfondi.

Un champ « Niches à analyser » à 4 par défaut demande à l'utilisateur un arbitrage qu'il
n'a pas les moyens de faire : il ne sait pas ce que « 4 » coûte en temps, et le montant ne
lui est plus montré (commit `4165efb`). Trois presets nommés remplacent le chiffre par la
seule chose qu'il peut arbitrer — combien de temps il accepte d'attendre.

Le test qui compte est le DERNIER : un preset dont la valeur dépasse la borne serveur
produirait une 400 au clic, sur un choix que l'interface a elle-même proposé. Les deux
bornes vivent dans deux fichiers différents (`web/server.py` et `web/index.html`) ; rien
ne les tient ensemble à part ce test.
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

_INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"


def _presets() -> dict:
    """Lit la table PRESETS du fichier : source unique, jamais recopiée dans le test."""
    src = _INDEX.read_text(encoding="utf-8")
    m = re.search(r"const PRESETS\s*=\s*(\{.*?\});", src, re.S)
    assert m, "table PRESETS introuvable dans web/index.html"
    return json.loads(m.group(1))


def test_les_trois_presets_existent_pour_les_deux_scouts():
    p = _presets()
    assert set(p["scout"]) == {"rapide", "standard", "approfondi"}
    assert set(p["fiction"]) == {"rapide", "standard", "approfondi"}


def test_chaque_preset_annonce_une_duree():
    """C'est LA raison d'être des presets : rendre arbitrable ce qui ne l'était pas."""
    p = _presets()
    for scout in ("scout", "fiction"):
        for cle, v in p[scout].items():
            assert v.get("duree"), f"{scout}/{cle} sans durée annoncée"


def test_aucun_preset_n_affiche_de_montant():
    """Décision du commit 4165efb : le temps se dit, le montant non."""
    p = _presets()
    textes = " ".join(v["duree"] for s in p.values() for v in s.values())
    assert "$" not in textes and "€" not in textes


def test_les_presets_vont_du_plus_leger_au_plus_lourd():
    """Un « approfondi » plus léger qu'un « rapide » serait un piège de nommage."""
    p = _presets()
    s = p["scout"]
    assert s["rapide"]["n"] < s["standard"]["n"] < s["approfondi"]["n"]
    f = p["fiction"]
    assert f["rapide"]["n"] < f["standard"]["n"] < f["approfondi"]["n"]


def test_aucun_preset_ne_depasse_la_borne_serveur():
    """LE test de ce lot. Un preset au-dessus de la borne rendrait une 400 au clic, sur un
    choix que l'interface a elle-même proposé. Les deux bornes vivent dans deux fichiers
    différents : rien ne les tient ensemble à part ce test."""
    import server
    p = _presets()
    for cle, v in p["scout"].items():
        assert 1 <= v["n"] <= server.MAX_RECHERCHES, f"scout/{cle} = {v['n']}"
    for cle, v in p["fiction"].items():
        assert 1 <= v["n"] <= server.MAX_NICHES_FICTION, f"fiction/{cle} = {v['n']}"


def test_le_reglage_fin_reste_accessible():
    """Les presets simplifient le cas courant ; ils ne doivent pas retirer la main à
    Baptiste, qui teste des volumes precis."""
    src = _INDEX.read_text(encoding="utf-8")
    assert 'id="search"' in src and 'id="fic-n"' in src
    assert "avance" in src.lower()
