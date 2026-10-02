"""Le script de la page doit être syntaxiquement VALIDE — cliquet ajouté le 2026-10-02.

Une apostrophe non échappée dans une chaîne JS (« Aucune analyse pour l'instant ») a suffi à
casser le script ENTIER : plus un bouton, plus un onglet, plus un lien ne répondait. Et rien
ne le disait — ni les 1 369 tests, qui exercent des fonctions extraites une par une, ni le
serveur, qui sert le fichier tel quel.

C'est la limite du harnais node (§2.10) : il extrait la fonction qu'il teste, donc il ne voit
jamais une erreur de syntaxe située ailleurs dans le fichier. Ce test-ci lit le script en
entier, comme le navigateur.

`web/index.html` porte 125 ko de JS inline écrits à la main : ce garde coûte une seconde et
rattrape la seule panne qui met l'interface entière par terre.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"


def test_le_script_de_la_page_est_syntaxiquement_valide(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent : la syntaxe JS ne peut pas être vérifiée ici")
    blocs = re.findall(r"<script[^>]*>(.*?)</script>", _INDEX.read_text(encoding="utf-8"), re.S)
    assert blocs, "aucun script dans la page"
    for i, bloc in enumerate(blocs):
        fichier = tmp_path / f"bloc{i}.mjs"
        fichier.write_text(bloc, encoding="utf-8")
        r = subprocess.run([node, "--check", str(fichier)], capture_output=True, text=True,
                           encoding="utf-8", timeout=30)
        assert r.returncode == 0, (
            f"le bloc <script> n°{i} ne compile pas — toute l'interface est morte :\n"
            + "\n".join((r.stderr or "").splitlines()[:8]))
