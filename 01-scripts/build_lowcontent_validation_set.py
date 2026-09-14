"""build_lowcontent_validation_set.py — CLI de calibration du scoring low-content (G1).

Deux modes, à lancer dans cet ordre :

    python 01-scripts/build_lowcontent_validation_set.py --gabarit 99-logs/validation-lc.xlsx
    # ... Baptiste remplit la colonne « requete » et la colonne « etiquette » ...
    python 01-scripts/build_lowcontent_validation_set.py --xlsx 99-logs/validation-lc.xlsx

Le second **dépense** : une SERP et un lot d'enrichissement ASIN par requête. Un jeu de
31 requêtes coûte au pire ~0,80 $ sur un poste résidentiel et ~1,35 $ avec
BSR_SOURCE=dataforseo (calculé, jamais mesuré : une SERP et six fiches ASIN par requête, la
réponse du modèle qui grandit avec n, et en production la relance des fiches non enrichies)
— moins si le cache a déjà vu ces rayons. Les SERP partent une par
une : compter 20 min à 2 h selon la file DataForSEO. Le plafond
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
import traceback
from pathlib import Path

from autocomplete_expand import Suggestion, expand as _expand
from cost_tracker import CostTracker
from ip_filter import filtrer_ip
from lowcontent_ideator import _norm
from lowcontent_taxonomy import est_saisonnier
from lowcontent_validation import (RapportCalibration, RequeteEtiquetee,
                                    charger_etiquettes, exporter_gabarit,
                                    rapport_calibration)

# Généreux mais fini. Pire cas CALCULÉ (jamais mesuré) pour 31 requêtes, cache froid :
# ~0,80 $ sur un poste résidentiel (BSR scrapé gratuit), ~1,35 $ avec BSR_SOURCE=dataforseo
# (les fiches non enrichies sont relancées au tarif ASIN). 2 $ couvre les deux sans jamais
# devenir illimité. Une ancienne version annonçait « ~0,25 $ mesuré » : ni l'un ni l'autre.
PLAFOND_USD_DEFAUT = 2.0

_RACINE = Path(__file__).resolve().parent.parent


def _noop(_msg: str) -> None:
    pass


def _cle(requete: str) -> str:
    """Clé d'appariement. La dédup de l'ideator normalise casse et espaces : comparer
    brut déclarerait « écartée » une requête simplement rendue en minuscules — un faux
    signalement qui ferait chercher un bug de filtre inexistant.

    Delegue a `lowcontent_ideator._norm` (casse, espaces, accents, apostrophes) : c'est la
    MEME regle qui recale la requete dans l'ideator. Deux copies d'une regle divergent, et
    ici la divergence produisait des faux negatifs attribues au gate gratuit."""
    return _norm(requete)


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
    # `classer_toutes=True` n'est PAS une option : sans lui, la règle de sélection du
    # prompt fait trier au modèle le jeu qu'on veut mesurer, et le Spearman porte sur ce
    # qu'il a gardé.
    journal: list[dict] = []
    scorees = run(seed="validation", n_ideas=max(len(requetes), 1),
                  n_search=max(len(requetes), 1), version=version, cost=cost,
                  progress=progress, expand_fn=lambda *a, **k: list(suggestions),
                  classer_toutes=True, journal_rejets=journal, **kw)

    # Les SEULS rejets imputables à un filtre sont recalculés ici, avec les MÊMES fonctions
    # que le moteur. Tout le reste de ce qui manque en sortie n'a été écarté par personne.
    _, rejets_ip = filtrer_ip(suggestions)
    filtrees = {_cle(s.requete) for s, _terme in rejets_ip}
    if not kw.get("inclure_saisonnier"):
        filtrees |= {_cle(r) for r in requetes if est_saisonnier(r, version)}
    # Les rejets APRÈS le modèle (marque glissée dans une annotation) ne se devinent pas en
    # rejouant le filtre sur la seule requête : le moteur les remonte lui-même.
    filtrees |= {_cle(d["requete"]) for d in journal}

    par_cle = {_cle(s.niche.requete_amazon): s for s in scorees}
    paires, familles, ecartees, non_rendues = [], [], [], []
    for e in etiquetees:
        s = par_cle.get(_cle(e.requete))
        if s is not None:
            paires.append((e.etiquette, s))
            familles.append(e.famille)
        elif _cle(e.requete) in filtrees:
            ecartees.append((e.requete, e.etiquette))
        else:
            non_rendues.append((e.requete, e.etiquette))

    return rapport_calibration(paires, familles=familles, ecartees=ecartees,
                               non_rendues=non_rendues, version=version)


# ── CLI ────────────────────────────────────────────────────────────────────────

def _imprimer(r: RapportCalibration) -> None:
    print()
    print(f"  requêtes du jeu ......... {r.n_requetes}")
    print(f"  calibrées ............... {r.n_calibrees}")
    if r.n_non_mesurees:
        print(f"  SERP tombée ............. {r.n_non_mesurees}")
    if r.ecartees_correctement or r.bonnes_perdues_avant_analyse:
        print(f"  écartées par un filtre .. "
              f"{len(r.ecartees_correctement) + len(r.bonnes_perdues_avant_analyse)}")
    if r.non_rendues:
        print(f"  NON rendues ............. {len(r.non_rendues)}  (omises, tronquées ou "
              f"plafond — ni filtre ni gate)")
    if r.n_demande_non_mesuree:
        print(f"  demande non mesurée ..... {r.n_demande_non_mesuree}")
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
    if r.porte_franchie:
        print("  ✅ PORTE FRANCHIE")
    elif r.porte_indecidable:
        # Une porte fermée faute de mesure ne dit RIEN des seuils. Le premier run réel
        # (2026-09-13) conseillait ici de les corriger avec 0 niche calibrée.
        print("  ⚪ porte INDÉCIDABLE — mesure incomplète (voir les avertissements) : "
              "relancer, sans toucher à data/lowcontent_criteres.json")
    else:
        print("  ❌ porte NON franchie — corriger data/lowcontent_criteres.json, jamais le code")


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
    ap.add_argument("--forcer", action="store_true",
                    help="avec --gabarit : écrase un classeur DÉJÀ étiqueté (destructif)")
    ap.add_argument("--inclure-saisonnier", action="store_true",
                    help="score aussi les requêtes saisonnières (sinon écartées, comme "
                         "dans le produit)")
    ap.add_argument("--version", default="fr_v1")
    a = ap.parse_args(argv)

    # La console Windows redirigee encode en cp1252, ou ni « 🟢 », ni « ⚠ », ni « ✅ »
    # n'existent : le premier avertissement du run levait UnicodeEncodeError. On remplace
    # l'illisible au lieu de planter — un caractere de moins vaut mieux qu'un run perdu.
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    if a.gabarit:
        try:
            out = exporter_gabarit(a.gabarit, version=a.version, ecraser=a.forcer)
        except FileExistsError as e:
            # Message net et code de sortie distinct : un script appelant doit pouvoir
            # distinguer « rien à faire, le travail est déjà là » d'une vraie panne.
            print(str(e), file=sys.stderr)
            return 3
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
    code_echec = None
    try:
        r = construire_rapport(etiquetees, cost=cost, progress=lambda m: print(f"  {m}"),
                               version=a.version, inclure_saisonnier=a.inclure_saisonnier)
    except (Exception, KeyboardInterrupt) as exc:          # noqa: BLE001 — voir ci-dessous
        # Le run a pu PAYER avant de lever : le 2026-09-13, le classement Anthropic était
        # revenu, puis `AttributeError` sur sa réponse — trace Python brute, ni rapport ni
        # coût. Ctrl-C compris : couper la console pendant le batch ASIN brûle 0,558 $ sans
        # rien mettre en cache, c'est le cas où la trace compte le plus.
        interrompu = isinstance(exc, KeyboardInterrupt)
        code_echec = 130 if interrompu else 4
        if not interrompu:
            traceback.print_exc()
        r = RapportCalibration(
            n_requetes=len(etiquetees), porte_franchie=False, porte_indecidable=True,
            avertissements=[
                f"run interrompu ({type(exc).__name__}: {exc}) APRÈS "
                f"{cost.total_usd():.4f} $ déjà engagés — aucune mesure exploitable. Ne "
                f"touchez pas à data/lowcontent_criteres.json : relancer une fois la cause "
                f"réglée. Les SERP et fiches déjà rendues sont en cache ; l'appel Anthropic, "
                f"lui, sera repayé."])

    # ECRIT AVANT tout affichage. Le run vient de couter de l'argent reel : le JSON est la
    # seule trace qui compte, et il ne doit dependre d'aucune ligne decorative. L'ordre
    # inverse a existe — et `total_usd` formate comme un attribut alors que c'est une
    # methode garantissait un TypeError entre la depense et l'ecriture.
    dest = Path(a.out) if a.out else _RACINE / "99-logs" / "rapport-calibration-lc.json"
    dest.write_text(r.model_dump_json(indent=2), encoding="utf-8")

    _imprimer(r)
    # La CLI est l'outil du développeur : le coût s'y affiche, contrairement à l'écran
    # client (§5.27).
    print(f"\n  coût réel du run : {cost.total_usd():.4f} $")
    print(f"  rapport écrit : {dest}")
    if code_echec is not None:
        return code_echec
    return 0 if r.porte_franchie else 2


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
