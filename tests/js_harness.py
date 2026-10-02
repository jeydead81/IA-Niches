"""Exécute une fonction JS de `web/index.html` et rend son résultat.

Pourquoi ce détour plutôt qu'un `assert "..." in html` : les deux tests d'interface
existants (`test_ux_glossaire.py`, `test_ux_kdp_historique.py`) vérifient que des chaînes
sont PRÉSENTES dans le fichier. Ils passaient au vert pendant que les boutons « Télécharger
le PDF » et « Mots-clés KDP » étaient inatteignables — générés à l'intérieur d'un bloc qui
sortait par `if(!v) return ''`, sur des niches dont le verdict valait toujours `None`
(CLAUDE.md §5.26). Une chaîne présente dans un fichier ne prouve rien sur ce que
l'utilisateur peut cliquer.

On extrait donc les fonctions PURES de rendu (celles qui ne touchent pas au DOM) et on les
appelle vraiment, avec node. Node absent → skip explicite plutôt qu'un faux vert.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"


def _source_js() -> str:
    html = _INDEX.read_text(encoding="utf-8")
    return "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", html, re.S))


def _declaration(nom: str, src: str) -> str | None:
    """Une déclaration `const x = …;`, y compris quand elle court sur plusieurs lignes.

    Première version : une regex mono-ligne. Elle tronquait `fmtDec`, dont la flèche tient
    sur deux lignes — node recevait une expression coupée et levait une SyntaxError qui
    n'avait rien à voir avec le code testé. On accumule donc les lignes jusqu'à ce que les
    parenthèses, crochets et accolades soient équilibrés."""
    m = re.search(r"^\s*(?:const|let|var)\s+" + re.escape(nom) + r"\s*=", src, re.M)
    if not m:
        return None
    lignes = src[m.start():].splitlines()
    acc, prof = [], 0
    for ligne in lignes:
        acc.append(ligne)
        for c in ligne:
            if c in "([{":
                prof += 1
            elif c in ")]}":
                prof -= 1
        if prof <= 0 and ligne.rstrip().endswith(";"):
            return chr(10).join(acc).strip()
    return None


def extraire_fonction(nom: str, src: str | None = None) -> str:
    """Rend le texte complet de `function <nom>(…){…}` par comptage d'accolades.

    Comptage naïf assumé : il suffit pour les fonctions de rendu du fichier, qui ne
    contiennent ni accolade en chaîne littérale ni regex à accolade. Si cela devient faux,
    le test cassera bruyamment — ce qu'on préfère à un extrait tronqué qui passerait."""
    src = src if src is not None else _source_js()
    # Les helpers du fichier sont ecrits en `const x = ... ;` sur UNE ligne (esc, fmt...),
    # les fonctions de rendu en `function x(){...}` multi-lignes. On accepte les deux
    # plutot que d'imposer un style au fichier de production pour le confort du test.
    une_ligne = _declaration(nom, src)
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(nom) + r"\s*\(", src)
    if not m:
        if une_ligne:
            return une_ligne
        raise AssertionError(f"fonction JS « {nom} » introuvable dans web/index.html")
    i = src.index("{", m.end() - 1)
    prof = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            prof += 1
        elif src[j] == "}":
            prof -= 1
            if prof == 0:
                return src[m.start():j + 1]
    raise AssertionError(f"accolades non refermées pour « {nom} »")


def appeler(nom: str, *args, dependances: tuple[str, ...] = ()) -> str:
    """Appelle une fonction de rendu avec `args` et rend sa sortie (chaîne)."""
    return _executer(nom, args, dependances, "String({appel})")


def appeler_json(nom: str, *args, dependances: tuple[str, ...] = ()):
    """Comme `appeler`, mais pour une fonction qui rend une STRUCTURE et non du HTML.

    `appeler` fait `String(f(...))` : sur un tableau d'objets il rendrait « [object Object] »
    et le test passerait au vert en ne vérifiant rien — exactement la famille de faux vert
    que ce harnais existe pour éviter (§5.26). On sérialise côté node, on relit côté Python."""
    return json.loads(_executer(nom, args, dependances, "JSON.stringify({appel})"))


def _executer(nom: str, args, dependances: tuple[str, ...], enveloppe: str) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node absent : le rendu JS ne peut pas être exercé ici")
    src = _source_js()
    bloc = "\n".join(extraire_fonction(d, src) for d in dependances)
    appel = f"{nom}(...{json.dumps(list(args))})"
    prog = (bloc + "\n" + extraire_fonction(nom, src) + "\n"
            + f"process.stdout.write({enveloppe.format(appel=appel)});")
    r = subprocess.run([node, "-e", prog], capture_output=True, text=True,
                       encoding="utf-8", timeout=30)
    if r.returncode != 0:
        raise AssertionError(f"node a échoué sur « {nom} » :\n{r.stderr}")
    return r.stdout
