"""build_lowcontent_validation_set.py — CLI de calibration du scoring low-content (G1).

Deux modes, à lancer dans cet ordre :

    python 01-scripts/build_lowcontent_validation_set.py --gabarit 99-logs/validation-lc.xlsx
    # ... Baptiste remplit la colonne « requete » et la colonne « etiquette » ...
    python 01-scripts/build_lowcontent_validation_set.py --xlsx 99-logs/validation-lc.xlsx

Le second **dépense** : une SERP et un lot d'enrichissement ASIN par requête. Un jeu de
30 requêtes coûte de l'ordre de 0,15 à 0,25 $ selon ce que le cache a déjà vu. Le plafond
est passé explicitement au `CostTracker` (`--plafond`), parce qu'une erreur de saisie dans
le classeur ne doit pas pouvoir se traduire en dépense non bornée.

**Ce que le CLI ne fait PAS, et c'est son point** : il ne laisse pas l'ideator choisir les
requêtes. Elles viennent du classeur, injectées par `expand_fn` là où le master lit
d'ordinaire l'arbre d'autocomplete. Le LLM garde son rôle — classer chaque requête en
format / thème / public — mais il ne choisit pas le sujet. S'il proposait les requêtes
qu'on corrèle ensuite à son propre scoring, on mesurerait la cohérence du produit avec
lui-même et le résultat serait garanti sans rien prouver.

**Ce que le CLI mesure en plus de la corrélation** : les requêtes perdues avant la moindre
dépense. Le filtre IP, le filtre saisonnier et le gate gratuit peuvent en écarter, et
c'est normal — mais une requête que Baptiste juge « bonne » et que le produit jette avant
toute analyse est un faux négatif que l'utilisateur ne peut PAS voir : la niche
n'apparaît nulle part à l'écran. Le rapport est le seul endroit où ça peut se lire.

En cas d'échec de la porte, on corrige `data/lowcontent_criteres.json` — jamais le code.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from autocomplete_expand import Suggestion, expand as _expand
from cost_tracker import CostTracker
from lowcontent_validation import (RapportCalibration, RequeteEtiquetee,
                                    charger_etiquettes, exporter_gabarit,
                                    rapport_calibration)

# Généreux mais fini. Un jeu de 30 requêtes mesuré à vide coûte ~0,25 $ ; 2 $ laisse la
# place à un cache froid et à un jeu plus large sans jamais devenir illimité.
PLAFOND_USD_DEFAUT = 2.0

_RACINE = Path(__file__).resolve().parent.parent


def _noop(_msg: str) -> None:
    pass


def _cle(requete: str) -> str:
    """Clé d'appariement. La dédup de l'ideator normalise casse et espaces : comparer
    brut déclarerait « écartée » une requête simplement rendue en minuscules — un faux
    signalement qui ferait chercher un bug de filtre inexistant."""
    return " ".join(requete.lower().split())


def sonder(requetes: list[str], expand_fn=None, pause: float = 0.4, cache=None,
           progress=None) -> list[Suggestion]:
    """Compte les complétions de CHAQUE requête du classeur. Gratuit.

    Sans cette sonde, la branche « tautologie » du master retomberait sur
    `demand_score = max(1, 0)` pour toutes les requêtes : l'axe demande serait plat et le
    Spearman ne mesurerait plus que les trois autres axes.

    `profondeur` vaut 0 pour toutes : ces requêtes n'ont pas été trouvées dans un arbre,
    elles ont été choisies. C'est une constante sur tout le jeu, donc sans effet sur le
    CLASSEMENT que Spearman mesure — mais le bonus « profondeur ≥ 2 » du scoring ne sera
    calibré par personne, et il faut le savoir.

    Une sonde en panne rend `n_enfants=None`, jamais 0 : zéro complétion est une MESURE
    (« personne n'affine cette requête ») et vaudrait un signal défavorable (§5.10)."""
    expand_fn = expand_fn or _expand
    progress = progress or _noop
    out: list[Suggestion] = []
    for r in requetes:
        try:
            enfants = expand_fn(r, depth=1, alphabet=False, max_probes=6, pause=pause,
                                cache=cache, progress=_noop)
            n = len(enfants)
        except Exception as exc:                      # noqa: BLE001 — voir docstring
            progress(f"  ⚠ sonde indisponible sur « {r} » ({exc}) — demande non mesurée")
            n = None
        out.append(Suggestion(requete=r, parent="", profondeur=0, n_enfants=n))
    return out


def construire_rapport(etiquetees: list[RequeteEtiquetee], run=None, sonde=None,
                       plafond_usd: float = PLAFOND_USD_DEFAUT, cost=None,
                       progress=None, version: str = "fr_v1",
                       **kw) -> RapportCalibration:
    """Sonde gratuite -> run payant sur les requêtes du classeur -> rapport."""
    progress = progress or _noop
    sonde = sonde or sonder
    if run is None:
        from lowcontent_master import run_lowcontent_scout as run
    cost = cost if cost is not None else CostTracker(plafond_usd=plafond_usd)

    requetes = [e.requete for e in etiquetees]
    progress(f"Sonde autocomplete sur {len(requetes)} requête(s) (gratuit)…")
    # La liste envoyée au master est construite ICI, depuis le classeur, et la sonde n'y
    # apporte QUE la mesure `n_enfants`. Repartir de ce que la sonde a rendu ferait
    # dépendre l'invariant « les requêtes viennent du fichier » du succès d'un appel
    # réseau : une sonde muette rendrait une liste vide, le master basculerait en mode
    # idéation, et le LLM choisirait lui-même les requêtes qu'on corrèle ensuite à son
    # propre scoring. Le jeu de calibration serait invalide sans que rien ne le signale.
    mesures = {_cle(s.requete): s.n_enfants for s in sonde(requetes, progress=progress)}
    suggestions = [Suggestion(requete=r, parent="", profondeur=0,
                              n_enfants=mesures.get(_cle(r)))
                   for r in requetes]

    # `n_ideas` et `n_search` sont bornés à la taille du jeu : laisser `n_search` à son
    # défaut de 6 n'analyserait que 6 des 30 requêtes, et le rapport annoncerait pourtant
    # 30 requêtes calibrées.
    scorees = run(seed="validation", n_ideas=max(len(requetes), 1),
                  n_search=max(len(requetes), 1), version=version, cost=cost,
                  progress=progress, expand_fn=lambda *a, **k: list(suggestions), **kw)

    par_cle = {_cle(s.niche.requete_amazon): s for s in scorees}
    paires, familles, ecartees = [], [], []
    for e in etiquetees:
        s = par_cle.get(_cle(e.requete))
        if s is None:
            ecartees.append((e.requete, e.etiquette))
        else:
            paires.append((e.etiquette, s))
            familles.append(e.famille)

    return rapport_calibration(paires, familles=familles, ecartees=ecartees,
                               version=version)


# ── CLI ────────────────────────────────────────────────────────────────────────

def _imprimer(r: RapportCalibration) -> None:
    print()
    print(f"  requêtes du jeu ......... {r.n_requetes}")
    print(f"  calibrées ............... {r.n_calibrees}")
    if r.n_non_mesurees:
        print(f"  SERP tombée ............. {r.n_non_mesurees}")
    if r.ecartees_correctement or r.bonnes_perdues_avant_analyse:
        print(f"  écartées avant analyse .. "
              f"{len(r.ecartees_correctement) + len(r.bonnes_perdues_avant_analyse)}")
    sp = "indéfini" if r.spearman is None else f"{r.spearman:+.3f}"
    print(f"  Spearman ................ {sp}  (porte : ≥ {r.seuil_spearman})")
    print(f"  mortes en 🟢 ............ {len(r.morts_en_vert)}  (porte : 0)")
    print()
    if r.signaux:
        cles = ["n", "score", "part_indie", "n_variantes", "prix_median", "redevance"]
        print("  " + "étiquette".ljust(11) + "".join(c.rjust(13) for c in cles))
        for e, d in r.signaux.items():
            vals = []
            for c in cles:
                v = d.get(c)
                vals.append(("—" if v is None else
                             f"{v:g}" if isinstance(v, int) or float(v).is_integer()
                             else f"{v:.2f}").rjust(13))
            print("  " + e.ljust(11) + "".join(vals))
        print()
    for a in r.avertissements:
        print(f"  ⚠ {a}")
    if r.hors_taxonomie:
        print(f"\n  Hors taxonomie ({len(r.hors_taxonomie)}) — matière de la v2 :")
        for h in r.hors_taxonomie:
            print(f"    · « {h['requete']} » → {h['libelle_observe'] or '(sans libellé)'}")
    print()
    print("  ✅ PORTE FRANCHIE" if r.porte_franchie else
          "  ❌ porte NON franchie — corriger data/lowcontent_criteres.json, jamais le code")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gabarit", metavar="XLSX",
                    help="écrit un classeur vide, pré-découpé par famille, puis sort")
    ap.add_argument("--xlsx", metavar="XLSX",
                    help="classeur corrigé par Baptiste — LANCE LE RUN PAYANT")
    ap.add_argument("--out", metavar="JSON", default=None,
                    help="où écrire le rapport (défaut : 99-logs/rapport-calibration-lc.json)")
    ap.add_argument("--plafond", type=float, default=PLAFOND_USD_DEFAUT,
                    help=f"plafond de dépense du run, en $ (défaut {PLAFOND_USD_DEFAUT})")
    ap.add_argument("--version", default="fr_v1")
    a = ap.parse_args(argv)

    if a.gabarit:
        out = exporter_gabarit(a.gabarit, version=a.version)
        print(f"Gabarit écrit : {out}")
        print("Remplissez les colonnes « requete » et « etiquette », puis relancez "
              f"avec --xlsx {out}")
        return 0

    if not a.xlsx:
        ap.error("il faut --gabarit ou --xlsx")

    etiquetees = charger_etiquettes(a.xlsx)
    if not etiquetees:
        print(f"Aucune ligne étiquetée dans {a.xlsx} — rien à calibrer.", file=sys.stderr)
        return 1

    cost = CostTracker(plafond_usd=a.plafond)
    print(f"{len(etiquetees)} requête(s) étiquetée(s). Plafond du run : {a.plafond:.2f} $")
    r = construire_rapport(etiquetees, cost=cost, progress=lambda m: print(f"  {m}"),
                           version=a.version)
    _imprimer(r)
    # La CLI est l'outil du développeur : le coût s'y affiche, contrairement à l'écran
    # client (§5.27).
    print(f"\n  coût réel du run : {cost.total_usd:.4f} $")

    dest = Path(a.out) if a.out else _RACINE / "99-logs" / "rapport-calibration-lc.json"
    dest.write_text(r.model_dump_json(indent=2), encoding="utf-8")
    print(f"  rapport écrit : {dest}")
    return 0 if r.porte_franchie else 2


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
