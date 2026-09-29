"""build_lowcontent_validation_set.py — CLI de calibration du scoring low-content (G1).

Modes, à lancer dans cet ordre :

    python 01-scripts/build_lowcontent_validation_set.py --gabarit 99-logs/validation-lc.xlsx
    # ... Baptiste remplit la colonne « requete » et la colonne « etiquette » ...
    python 01-scripts/build_lowcontent_validation_set.py --xlsx 99-logs/validation-lc.xlsx
    # après un run : essayer d'autres seuils SANS repayer
    python 01-scripts/build_lowcontent_validation_set.py --rejouer <captures>/entrees.json
    # fiches en cache lues par un parseur fautif : aperçu, puis suppression ciblée
    python 01-scripts/build_lowcontent_validation_set.py --xlsx ... --purger-fiches-sans-pages
    python 01-scripts/build_lowcontent_validation_set.py --xlsx ... --purger-fiches-sans-pages --confirmer --ecrites-avant 2026-09-14

`--xlsx` **dépense** : une SERP et un lot d'enrichissement ASIN par requête. Un jeu de
31 requêtes coûte au pire ~0,80 $ sur un poste résidentiel et ~1,35 $ avec
BSR_SOURCE=dataforseo (calculé, jamais mesuré : une SERP et six fiches ASIN par requête, la
réponse du modèle qui grandit avec n, et en production la relance des fiches non enrichies)
— moins si le cache a déjà vu ces rayons. Les SERP partent une par
une : compter 20 min à 2 h selon la file DataForSEO. Le plafond
est passé explicitement au `CostTracker` (`--plafond`), parce qu'une erreur de saisie dans
le classeur ne doit pas pouvoir se traduire en dépense non bornée.

**Deux arrêts AVANT toute dépense** (code de sortie 5), parce que le run 4 (0,7208 $) est
parti alors que sa porte était indécidable avant le premier centime : un DEVIS qui lit le
cache (fiches à payer, fiches en cache sans pagination) et une re-sonde gratuite de
l'autocomplete. Codes de sortie : 0 porte franchie ; 2 non franchie OU indécidable ; 4
exception après le début du run ; 130 Ctrl-C ; 5 refus avant toute dépense.

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
import inspect
import json
import shutil
import sqlite3
import sys
import time
import traceback
from contextlib import closing
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from autocomplete_expand import Suggestion, expand as _expand
from cache import BOOK_TTL_S, Cache
from cost_tracker import CostTracker
from ip_filter import filtrer_ip
from lowcontent_ideator import _norm
from lowcontent_taxonomy import est_saisonnier
from lowcontent_validation import (RapportCalibration, RequeteEtiquetee, SondeIndisponible,
                                    charger_etiquettes, exporter_gabarit,
                                    rapport_calibration, rejouer_entrees,
                                    requetes_non_sondees)

# Généreux mais fini. Pire cas CALCULÉ (jamais mesuré) pour 31 requêtes, cache froid :
# ~0,80 $ sur un poste résidentiel (BSR scrapé gratuit), ~1,35 $ avec BSR_SOURCE=dataforseo
# (les fiches non enrichies sont relancées au tarif ASIN). 2 $ couvre les deux sans jamais
# devenir illimité. Une ancienne version annonçait « ~0,25 $ mesuré » : ni l'un ni l'autre.
PLAFOND_USD_DEFAUT = 2.0

# Code de sortie distinct : « rien n'a été dépensé » ne se confond ni avec une porte
# indécidable APRÈS dépense (2), ni avec une exception en cours de run (4).
CODE_REFUS_AVANT_DEPENSE = 5
OPTION_PURGE = "--purger-fiches-sans-pages"

_RACINE = Path(__file__).resolve().parent.parent

# Racine des captures brutes, FIXE : elle suivait `--out`, et un rapport écrit hors de
# 99-logs/ faisait tomber asin.jsonl, serp.jsonl et entrees.json (les étiquettes de Baptiste)
# dans un dossier versionnable — `.gitignore` n'exclut que `99-logs/captures/`. Module-level
# pour que les tests la redirigent (conftest), jamais une option de la CLI.
_RACINE_CAPTURES_DEFAUT = _RACINE / "99-logs" / "captures"
RACINE_CAPTURES = _RACINE_CAPTURES_DEFAUT


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


def _horodatage() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _chemin_libre(dest: Path) -> Path:
    """Jamais d'écrasement. Le rapport du run 4 n'est pas versionné et a coûté 0,72 $ :
    un second run lancé sans `--out` l'effaçait. Un fichier existant fait prendre un nom
    horodaté à côté, et la CLI dit lequel."""
    if not dest.exists():
        return dest
    base = dest.with_name(f"{dest.stem}-{_horodatage()}{dest.suffix}")
    cand, i = base, 2
    while cand.exists():
        cand = base.with_name(f"{base.stem}-{i}{base.suffix}")
        i += 1
    return cand


# ── Lecture du cache SANS écriture ────────────────────────────────────────────

class _CacheLecture(Cache):
    """Le cache tel que le master le lira, ouvert en LECTURE SEULE. `Cache()` crée la table,
    le répertoire et passe la base en WAL : un devis ou un aperçu de purge n'écrit aucune
    LIGNE, et surtout pas dans le cache mutualisé.

    Mesuré : sur une base WAL dont les fichiers -wal et -shm ont disparu à la fermeture,
    SQLite les RECRÉE à l'ouverture `?mode=ro` (et ne peut pas les retirer). Contenu intact,
    mais « rien sur disque » serait faux. `immutable=1` l'éviterait en ignorant un -wal non
    reporté — un devis lancé pendant qu'un serveur écrit lirait alors un cache périmé : écarté."""

    def __init__(self, path, now=None):          # noqa: D107 — pas de CREATE TABLE
        self.path = str(path)
        self.now = now or time.time

    def _conn(self):
        return sqlite3.connect(Path(self.path).resolve().as_uri() + "?mode=ro", uri=True,
                               timeout=10, check_same_thread=False)


def ouvrir_cache_lecture(chemin) -> Cache | None:
    """`None` si le fichier n'existe pas : cache vide, tout est à payer."""
    p = Path(chemin)
    return _CacheLecture(p) if p.exists() else None


def _chemin_cache_defaut() -> Path:
    import storage
    return storage.base("df-cache.db")


def _n_asin_par_requete() -> int:
    """Lu dans la signature du master, jamais recopié : deux copies divergent (§5.32)."""
    from lowcontent_master import run_lowcontent_scout
    return inspect.signature(run_lowcontent_scout).parameters["n_enrich_per_niche"].default


def _lire(fn, *args):
    """Une entrée illisible compte comme ABSENTE : le devis prend le pire cas (règle 2)."""
    try:
        return fn(*args)
    except Exception:                                # noqa: BLE001
        return None


def _jeu_en_cache(requetes, cache, n_asin, loc, lang):
    """SERP en cache, SERP à payer, et les N premiers organiques dédupliqués des SERP en
    cache — exactement ce que le master enverra au batch ASIN."""
    en_cache, a_payer, asins = 0, 0, []
    for q in requetes:
        sr = _lire(cache.get_search, q, loc, lang) if cache is not None else None
        if sr is None:
            a_payer += 1
            continue
        en_cache += 1
        asins.extend([o.asin for o in sr.organic if o.asin][:n_asin])
    return en_cache, a_payer, list(dict.fromkeys(asins))


class DevisCalibration(BaseModel):
    n_requetes: int = 0
    n_serp_cache: int = 0
    n_serp_a_payer: int = 0
    n_asin_par_requete: int = 0
    n_asin_cache_utiles: int = 0
    n_asin_cache_sans_pages: int = 0
    n_asin_a_payer: int = 0
    usd_serp: float = 0.0
    usd_asin: float = 0.0
    usd_llm: float = 0.0
    total_usd: float = 0.0
    plafond_usd: float | None = None
    refus: str | None = None


def devis_calibration(requetes: list[str], cache, plafond_usd: float | None,
                      n_asin: int | None = None, location: int | None = None,
                      language: str | None = None) -> DevisCalibration:
    """Devis AVANT la sonde et avant Anthropic, sans réseau ni écriture.

    `devis.cout_max_estime` suppose un cache VIDE (c'est un pire cas produit). Ici le cache
    est lu : une SERP ou une fiche déjà achetée ne se repaie pas. Mais une fiche en cache
    SANS pagination ne se repaie pas non plus — le master la ressert telle quelle — et ne
    rendra jamais de redevance : au run 4, 185 fiches sur 185. Un jeu où aucune fiche utile
    n'est ni en cache ni à payer a une porte INDÉCIDABLE garantie : on refuse.

    Le poste LLM est celui de `devis.py` (lu, pas recopié). Comme lui, le devis n'inclut pas
    la relance BSR payante des fiches non enrichies (`BSR_SOURCE=dataforseo`) : le plafond
    du `CostTracker` reste le filet en cours de run."""
    from devis import _TARIF, ventilation_max_estimee
    from marketplace import ACTIF
    n_asin = n_asin or _n_asin_par_requete()
    loc = location or ACTIF.location_code
    lang = language or ACTIF.language_code
    n_cache, n_payer, union = _jeu_en_cache(requetes, cache, n_asin, loc, lang)
    utiles = sans_pages = manquantes = 0
    for a in union:
        b = _lire(cache.get_book, a, loc) if cache is not None else None
        if b is None:
            manquantes += 1
        elif b.pages is None:
            sans_pages += 1
        else:
            utiles += 1
    asin_a_payer = manquantes + n_payer * n_asin
    llm = ventilation_max_estimee("lowcontent", {"n_search": max(len(requetes), 1)})["llm_usd"]
    d = DevisCalibration(
        n_requetes=len(requetes), n_serp_cache=n_cache, n_serp_a_payer=n_payer,
        n_asin_par_requete=n_asin, n_asin_cache_utiles=utiles,
        n_asin_cache_sans_pages=sans_pages, n_asin_a_payer=asin_a_payer,
        usd_serp=n_payer * _TARIF, usd_asin=asin_a_payer * _TARIF, usd_llm=llm,
        total_usd=round(n_payer * _TARIF + asin_a_payer * _TARIF + llm, 4),
        plafond_usd=plafond_usd)
    motifs = []
    if utiles == 0 and asin_a_payer == 0:
        motifs.append(
            f"aucune fiche utile ni en cache ni à payer : {sans_pages} fiche(s) en cache SANS "
            f"pagination, que le run resservirait telles quelles — redevance non mesurée "
            f"partout, porte INDÉCIDABLE garantie. Corriger la lecture si besoin, puis purger "
            f"ces fiches : {OPTION_PURGE} (aperçu), puis {OPTION_PURGE} --confirmer "
            f"--ecrites-avant <date du correctif du parseur>.")
    # `>=` : même comparaison que `CostTracker.verifier`, qui refuserait en cours de run.
    if plafond_usd is not None and d.total_usd >= plafond_usd:
        motifs.append(f"devis {d.total_usd:.4f} $ ≥ plafond {plafond_usd:.2f} $ (--plafond).")
    d.refus = " ".join(motifs) or None
    return d


def _imprimer_devis(d: DevisCalibration) -> None:
    print("  Devis AVANT dépense (calculé, cache lu sans écriture) :")
    print(f"    SERP ............ {d.n_serp_cache} en cache, {d.n_serp_a_payer} à payer "
          f"({d.usd_serp:.4f} $)")
    print(f"    fiches ASIN ..... {d.n_asin_cache_utiles} utile(s) en cache, "
          f"{d.n_asin_cache_sans_pages} en cache SANS pagination, {d.n_asin_a_payer} à payer "
          f"({d.usd_asin:.4f} $)")
    print(f"    classement LLM .. {d.usd_llm:.4f} $ (estimation de devis.py)")
    plafond = "aucun" if d.plafond_usd is None else f"{d.plafond_usd:.2f} $"
    print(f"    total ........... {d.total_usd:.4f} $  (plafond : {plafond})")
    if d.n_asin_cache_sans_pages and not d.refus:
        print(f"    ⚠ {d.n_asin_cache_sans_pages} fiche(s) en cache sans pagination seront "
              f"resservies telles quelles : redevance non mesurée pour elles ({OPTION_PURGE} "
              f"si elles datent d'avant un correctif du parseur ; un livre audio n'a vraiment "
              f"pas de pagination).")
    if d.refus:
        print(f"  REFUS avant toute dépense : {d.refus}")


# ── Purge ciblée (R2, voie A) ──────────────────────────────────────────────────

def _date_ecriture(cache, cle: str) -> float | None:
    """`expires - BOOK_TTL_S` : `set_book` n'a qu'un appelant (`enrich_asins`), qui passe
    toujours `BOOK_TTL_S`. `None` si la ligne est illisible — la fiche n'est alors pas visée."""
    try:
        with closing(cache._conn()) as cx:
            row = cx.execute("SELECT expires FROM kv WHERE key=?", (cle,)).fetchone()
    except Exception:                                # noqa: BLE001
        return None
    return None if row is None else row[0] - BOOK_TTL_S


def fiches_sans_pages(requetes: list[str], cache, n_asin: int | None = None,
                      location: int | None = None, language: str | None = None,
                      ecrites_avant: float | None = None) -> list[str]:
    """Les clés `book:` VALIDES des N premiers organiques des SERP en cache du jeu dont la
    pagination est None — et rien d'autre. Ni `search:` (les SERP ne sont pas en cause), ni
    `clf:`, ni une fiche hors du jeu, ni une fiche déjà expirée.

    `ecrites_avant` (horodatage) ne garde que les fiches écrites AVANT cette date. `pages`
    None ne distingue pas une fiche mal lue par l'ancien parseur d'une VRAIE absence lue par
    le parseur corrigé (livre audio B0FS7JQNJ6) : sans date butoir, chaque purge après un run
    correct effaçait celles-ci, rachetées au run suivant pour le même None."""
    from marketplace import ACTIF
    if cache is None:
        return []
    n_asin = n_asin or _n_asin_par_requete()
    loc = location or ACTIF.location_code
    lang = language or ACTIF.language_code
    _, _, union = _jeu_en_cache(requetes, cache, n_asin, loc, lang)
    out = []
    for a in union:
        b = _lire(cache.get_book, a, loc)
        if b is None or b.pages is not None:
            continue
        cle = Cache._book_key(a, loc)
        if ecrites_avant is not None:
            ecrite = _date_ecriture(cache, cle)
            if ecrite is None or ecrite >= ecrites_avant:
                continue
        out.append(cle)
    return out


def purger_fiches_sans_pages(requetes: list[str], chemin_cache, confirmer: bool = False,
                             horodatage: str | None = None,
                             ecrites_avant: float | None = None) -> dict:
    """Aperçu par défaut. Avec `confirmer` — qui EXIGE `ecrites_avant`, la date du correctif
    du parseur — : sauvegarde horodatée (base, -wal, -shm) PUIS suppression des seules clés
    visées, revérifiées dans la transaction.

    Décision de Baptiste (voie A, §5.14) : l'empreinte de clé ne suit pas la logique du
    parseur, donc un parseur corrigé laisse le cache mutualisé resservir 15 jours des fiches
    mal lues. Purger à la main, sur une liste EXACTE, garde la limite assumée de §5.14 au
    lieu d'invalider aussi le cache fiction à chaque retouche du parseur. À lancer serveur
    arrêté et hors run : la sauvegarde est une copie de fichiers."""
    if confirmer and ecrites_avant is None:
        raise ValueError("une suppression exige une date butoir (ecrites_avant) : sans elle, "
                         "les fiches légitimement sans pagination partiraient aussi.")
    chemin = Path(chemin_cache)
    if not chemin.exists():
        raise FileNotFoundError(f"cache introuvable : {chemin}")
    visees = fiches_sans_pages(requetes, ouvrir_cache_lecture(chemin),
                               ecrites_avant=ecrites_avant)
    res = {"cles": visees, "sauvegarde": None, "supprimees": 0}
    if not confirmer or not visees:
        return res

    sauvegarde = chemin.with_name(
        f"{chemin.stem}.sauvegarde-{horodatage or _horodatage()}{chemin.suffix}")
    if sauvegarde.exists():
        raise FileExistsError(f"sauvegarde déjà présente, rien n'est supprimé : {sauvegarde}")
    for suffixe in ("", "-wal", "-shm"):
        source = Path(str(chemin) + suffixe)
        if source.exists():
            shutil.copy2(source, Path(str(sauvegarde) + suffixe))
    # La sauvegarde doit porter les clés visées AVANT qu'on en supprime une seule.
    cx = sqlite3.connect(sauvegarde)
    try:
        trous = [k for k in visees
                 if cx.execute("SELECT 1 FROM kv WHERE key=?", (k,)).fetchone() is None]
    finally:
        cx.close()
    if trous:
        raise RuntimeError(f"sauvegarde incomplète ({len(trous)} clé(s) absente(s)) : "
                           f"rien n'est supprimé.")
    res["sauvegarde"] = str(sauvegarde)

    cx = sqlite3.connect(chemin, timeout=10)
    try:
        cx.execute("BEGIN IMMEDIATE")
        maintenant = time.time()
        for k in visees:
            ligne = cx.execute("SELECT value, expires FROM kv WHERE key=?", (k,)).fetchone()
            if (ligne is None or ligne[1] < maintenant
                    or ligne[1] - BOOK_TTL_S >= ecrites_avant
                    or json.loads(ligne[0]).get("pages") is not None):
                raise RuntimeError(f"la clé {k} a changé depuis l'aperçu : rien n'est supprimé.")
        for k in visees:
            res["supprimees"] += cx.execute("DELETE FROM kv WHERE key=?", (k,)).rowcount
        cx.commit()
    except BaseException:
        cx.rollback()
        raise
    finally:
        cx.close()
    return res


# ── Captures de run (R5, R26) ──────────────────────────────────────────────────

class JournalCapture(list):
    """Le journal brut du run, écrit dans un FICHIER au moment même où un crochet le reçoit.

    C'est une liste — les crochets du fournisseur, du batch ASIN et du classement n'attendent
    que `append` — mais chaque entrée part aussitôt dans `<type>.jsonl` : un Ctrl-C ou une
    console fermée en plein batch laisse sur disque tout le brut déjà relu. Jamais dans le
    cache partagé (décision de Baptiste). Une écriture qui échoue est comptée, jamais levée :
    le run a payé, le perdre pour un disque plein serait pire."""

    FICHIERS = {"asin": "asin.jsonl", "serp_post": "serp.jsonl", "serp_get": "serp.jsonl",
                "classement": "classement.jsonl"}

    def __init__(self, dossier):
        super().__init__()
        self.dossier = Path(dossier)
        self.echecs_ecriture = 0

    def append(self, entree) -> None:
        try:
            self.dossier.mkdir(parents=True, exist_ok=True)
            nom = self.FICHIERS.get((entree or {}).get("type"), "autres.jsonl")
            ligne = json.dumps({"ecrit_le": datetime.now().isoformat(timespec="seconds"),
                                **entree}, ensure_ascii=False, default=str)
            with open(self.dossier / nom, "a", encoding="utf-8") as f:
                f.write(ligne + "\n")
        except (OSError, TypeError, ValueError):
            self.echecs_ecriture += 1
        super().append(entree)


def _dossier_captures() -> Path:
    """Toujours sous `RACINE_CAPTURES` (ignorée par git), jamais à côté de `--out`."""
    return _chemin_libre(RACINE_CAPTURES / f"calibration-{_horodatage()}")


def _ecrire_captures(dossier: Path, journal_entrees: list, cost: CostTracker,
                     devis: DevisCalibration, version: str) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "entrees.json").write_text(json.dumps(
        {"version": version, "entrees": journal_entrees}, ensure_ascii=False, indent=1,
        default=str), encoding="utf-8")
    (dossier / "cout.json").write_text(json.dumps(
        {**cost.breakdown(), "total_usd": cost.total_usd(), "devis": devis.model_dump()},
        ensure_ascii=False, indent=1), encoding="utf-8")


# ── Sonde et run ───────────────────────────────────────────────────────────────

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


def _progress_du_run(progress, n_requetes: int):
    """Le master annonce « Lecture de ce qu'Amazon complète autour de « validation » » : ici
    aucun arbre n'est lu, la graine est un nom de mode. La ligne faisait chercher pourquoi
    Amazon avait été interrogé sur le mot « validation »."""
    def p(msg: str) -> None:
        if msg.startswith("Lecture de ce qu'Amazon complète autour de"):
            msg = (f"{n_requetes} requête(s) du classeur injectée(s) telles quelles (sondées "
                   f"ci-dessus) — aucun arbre d'autocomplete.")
        progress(msg)
    return p


def construire_rapport(etiquetees: list[RequeteEtiquetee], run=None, sonde=None,
                       plafond_usd: float = PLAFOND_USD_DEFAUT, cost=None,
                       progress=None, version: str = "fr_v1",
                       journal_entrees: list | None = None,
                       **kw) -> RapportCalibration:
    """Sonde gratuite (+ une re-sonde) -> run payant sur les requêtes du classeur -> rapport.

    `journal_entrees` reçoit les entrées du scoring par niche (annotées de l'étiquette et de
    la famille), puis les requêtes écartées et non rendues : de quoi `--rejouer` sans rien
    repayer."""
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
    muettes = requetes_non_sondees(etiquetees, mesures, cle=_cle)
    if muettes:
        # UNE re-sonde, gratuite : un 503 passager ne doit pas coûter un arrêt. Au-delà,
        # c'est une panne, et la relancer en boucle retarderait seulement le constat.
        progress(f"Re-sonde (gratuite, une seule) de {len(muettes)} requête(s) muette(s)…")
        for s in sonde([e.requete for e in muettes], progress=progress):
            if s.n_enfants is not None:
                mesures[_cle(s.requete)] = s.n_enfants
        muettes = requetes_non_sondees(etiquetees, mesures, cle=_cle)
        mortes = [e.requete for e in muettes if e.etiquette == "morte"]
        if muettes and (len(muettes) == len(etiquetees) or mortes):
            raise SondeIndisponible([e.requete for e in muettes], mortes)
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
    if journal_entrees is not None:
        kw["journal_entrees"] = journal_entrees
    scorees = run(seed="validation", n_ideas=max(len(requetes), 1),
                  n_search=max(len(requetes), 1), version=version, cost=cost,
                  progress=_progress_du_run(progress, len(requetes)),
                  expand_fn=lambda *a, **k: list(suggestions),
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

    if journal_entrees is not None:
        par_etiquette = {_cle(e.requete): e for e in etiquetees}
        for d in journal_entrees:
            e = par_etiquette.get(_cle(d.get("requete", ""))) if d.get("type") == "niche" else None
            if e is not None:
                d["etiquette"], d["famille"] = e.etiquette, e.famille
        journal_entrees.extend({"type": "ecartee", "requete": q, "etiquette": etq}
                               for q, etq in ecartees)
        journal_entrees.extend({"type": "non_rendue", "requete": q, "etiquette": etq}
                               for q, etq in non_rendues)

    return rapport_calibration(paires, familles=familles, ecartees=ecartees,
                               non_rendues=non_rendues, version=version)


# ── CLI ────────────────────────────────────────────────────────────────────────

def _conseil_indecidable(r: RapportCalibration) -> str:
    """Un conseil selon la CAUSE. « Relancer » tout court, après le run 4, rachetait le même
    rapport : les fiches mal lues étaient resservies par le cache."""
    if r.n_non_mesurees and not r.n_calibrees:
        return ("toutes les SERP sont tombées : vérifier le compte DataForSEO et le motif du "
                "refus (progression, captures serp.jsonl) avant de relancer.")
    if r.n_calibrees and r.n_part_indie_mesuree and not r.n_redevance_mesuree:
        return ("fiches lues mais redevance jamais calculée : corriger la LECTURE (pagination "
                "ou prix), vérifier en rejouant le brut capturé, puis purger les fiches en "
                f"cache ({OPTION_PURGE}) — relancer tel quel rend les mêmes fiches.")
    if r.n_demande_non_mesuree:
        return "sonde autocomplete tombée en cours de route : relancer quand elle répond."
    n_ecartees = len(r.ecartees_correctement) + len(r.bonnes_perdues_avant_analyse)
    manquantes = r.n_requetes - n_ecartees - r.n_calibrees
    if manquantes > 0:
        # Ni « toutes les SERP sont tombées » (il en reste), ni un défaut de lecture : il
        # manque des niches au jeu, et c'est l'amputation qui fabrique un faux vert.
        return (f"mesure incomplète : {manquantes} requête(s) analysable(s) non calibrée(s) "
                f"sur {r.n_requetes - n_ecartees}. Reprendre CES requêtes (progression et "
                f"captures disent laquelle est tombée) — le cache ne repaiera que ce qui "
                f"manque.")
    if not r.n_mortes_scorees:
        return ("aucune « morte » scorée : « aucune morte en vert » porterait sur "
                "l'ensemble vide. Vérifier pourquoi elles ne sont pas arrivées jusqu'au "
                "score (écartées, non rendues, SERP tombée) avant de relancer.")
    return "relancer une fois la cause réglée (voir les avertissements)."


def _imprimer(r: RapportCalibration) -> None:
    print()
    print(f"  requêtes du jeu ......... {r.n_requetes}")
    print(f"  calibrées ............... {r.n_calibrees}")
    # Le compteur qui rend décidable « aucune morte en vert » : sans une seule morte
    # scorée, ce critère porte sur l'ensemble vide.
    print(f"  dont « morte » scorées .. {r.n_mortes_scorees}")
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
    # Compteurs sans effet sur la porte : « 0 morte en vert » ne dit rien si presque rien
    # n'est vert (run 5 : une seule niche verte sur 51).
    mb = "—" if r.meilleur_score_bonne is None else f"{r.meilleur_score_bonne:.2f}"
    print(f"  niches en 🟢 ............ {r.n_verts}  (compteur, hors porte)")
    print(f"  meilleure « bonne » ..... {mb}  (score, hors porte)")
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
    if r.rejeu:
        # Jamais « PORTE FRANCHIE » sur un rejeu : seuils réglés et validés sur le même jeu.
        print("  ⚪ REJEU hors ligne — aucune porte ne se franchit sur le jeu qui a servi à "
              "régler les seuils : valider par un nouveau run")
    elif r.porte_franchie:
        print("  ✅ PORTE FRANCHIE")
    elif r.porte_indecidable:
        # Une porte fermée faute de mesure ne dit RIEN des seuils. Le premier run réel
        # (2026-09-13) conseillait ici de les corriger avec 0 niche calibrée.
        print("  ⚪ porte INDÉCIDABLE — mesure incomplète (voir les avertissements), sans "
              "toucher à data/lowcontent_criteres.json")
        print(f"  → {_conseil_indecidable(r)}")
    else:
        print("  ❌ porte NON franchie — corriger data/lowcontent_criteres.json, jamais le code")


def _ecrire_rapport(r: RapportCalibration, dest_voulu: Path) -> Path:
    dest = _chemin_libre(dest_voulu)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(r.model_dump_json(indent=2), encoding="utf-8")
    return dest


def _rejouer(a) -> int:
    chemin = Path(a.rejouer)
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    criteres = (json.loads(Path(a.criteres).read_text(encoding="utf-8"))
                if a.criteres else None)
    r = rejouer_entrees(donnees, criteres=criteres, version=a.version)
    dest = _ecrire_rapport(r, Path(a.out) if a.out
                           else chemin.with_name("rapport-rejeu.json"))
    _imprimer(r)
    print(f"\n  rejeu hors ligne : 0 $ — rapport écrit : {dest}")
    return 2


def _purger(a, etiquetees, chemin_cache: Path) -> int:
    requetes = [e.requete for e in etiquetees]
    try:
        res = purger_fiches_sans_pages(requetes, chemin_cache, confirmer=a.confirmer,
                                       ecrites_avant=a.ecrites_avant_ts)
    except (FileNotFoundError, FileExistsError, RuntimeError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    n = len(res["cles"])
    borne = (f", écrite(s) avant le {a.ecrites_avant}" if a.ecrites_avant_ts is not None
             else "")
    print(f"{n} fiche(s) en cache SANS pagination{borne} parmi les premiers organiques des "
          f"SERP en cache du jeu ({chemin_cache}).")
    if not a.confirmer:
        print(f"APERÇU — rien n'a été supprimé. Une fiche lue SANS pagination par un parseur "
              f"correct est une vraie absence (livre audio) : ne purger que celles écrites "
              f"avant le correctif. Pour supprimer après sauvegarde horodatée : "
              f"{OPTION_PURGE} --confirmer --ecrites-avant <AAAA-MM-JJ[THH:MM:SS]>")
    elif n:
        print(f"Sauvegarde : {res['sauvegarde']}")
        print(f"{res['supprimees']} clé(s) supprimée(s). SERP, classifications et autres "
              f"fiches intactes.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gabarit", metavar="XLSX",
                    help="écrit un classeur vide, pré-découpé par famille, puis sort")
    ap.add_argument("--xlsx", metavar="XLSX",
                    help="classeur corrigé par Baptiste — LANCE LE RUN PAYANT")
    ap.add_argument("--out", metavar="JSON", default=None,
                    help="où écrire le rapport (défaut : 99-logs/rapport-calibration-lc.json ; "
                         "jamais écrasé, un nom horodaté est pris à côté)")
    ap.add_argument("--plafond", type=float, default=PLAFOND_USD_DEFAUT,
                    help=f"plafond de dépense du run, en $ (défaut {PLAFOND_USD_DEFAUT})")
    ap.add_argument("--forcer", action="store_true",
                    help="avec --gabarit : écrase un classeur DÉJÀ étiqueté (destructif)")
    ap.add_argument("--inclure-saisonnier", action="store_true",
                    help="score aussi les requêtes saisonnières (sinon écartées, comme "
                         "dans le produit)")
    ap.add_argument("--cache", metavar="DB", default=None,
                    help="cache à lire et à utiliser (défaut : df-cache.db du répertoire "
                         "de données)")
    ap.add_argument(OPTION_PURGE, action="store_true",
                    help="avec --xlsx : APERÇU des fiches du jeu en cache sans pagination")
    ap.add_argument("--confirmer", action="store_true",
                    help=f"avec {OPTION_PURGE} : sauvegarde puis SUPPRIME ces fiches "
                         f"(exige --ecrites-avant)")
    ap.add_argument("--ecrites-avant", metavar="DATE", default=None,
                    help=f"avec {OPTION_PURGE} : ne vise que les fiches écrites en cache avant "
                         f"cette date (AAAA-MM-JJ ou AAAA-MM-JJTHH:MM:SS, heure locale) — la "
                         f"date du correctif du parseur")
    ap.add_argument("--rejouer", metavar="ENTREES_JSON",
                    help="rescore hors ligne les entrées capturées d'un run (0 $)")
    ap.add_argument("--criteres", metavar="JSON",
                    help="avec --rejouer : critères à essayer (défaut : "
                         "data/lowcontent_criteres.json)")
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

    if a.rejouer:
        return _rejouer(a)

    if not a.xlsx:
        ap.error("il faut --gabarit, --xlsx ou --rejouer")
    if a.confirmer and not a.purger_fiches_sans_pages:
        ap.error(f"--confirmer ne s'utilise qu'avec {OPTION_PURGE}")
    if a.ecrites_avant and not a.purger_fiches_sans_pages:
        ap.error(f"--ecrites-avant ne s'utilise qu'avec {OPTION_PURGE}")
    if a.confirmer and not a.ecrites_avant:
        ap.error("--confirmer exige --ecrites-avant <date du correctif du parseur> : sans date "
                 "butoir, les fiches légitimement sans pagination (livre audio) partiraient "
                 "aussi, et seraient rachetées au run suivant pour le même résultat")
    a.ecrites_avant_ts = None
    if a.ecrites_avant:
        try:
            a.ecrites_avant_ts = datetime.fromisoformat(a.ecrites_avant).timestamp()
        except ValueError:
            ap.error(f"--ecrites-avant illisible : {a.ecrites_avant!r} (AAAA-MM-JJ attendu)")

    etiquetees = charger_etiquettes(a.xlsx)
    if not etiquetees:
        print(f"Aucune ligne étiquetée dans {a.xlsx} — rien à calibrer.", file=sys.stderr)
        return 1

    chemin_cache = Path(a.cache) if a.cache else _chemin_cache_defaut()
    if a.purger_fiches_sans_pages:
        return _purger(a, etiquetees, chemin_cache)

    dest_voulu = Path(a.out) if a.out else _RACINE / "99-logs" / "rapport-calibration-lc.json"
    cost = CostTracker(plafond_usd=a.plafond)
    print(f"{len(etiquetees)} requête(s) étiquetée(s). Plafond du run : {a.plafond:.2f} $")

    devis = devis_calibration([e.requete for e in etiquetees],
                              ouvrir_cache_lecture(chemin_cache), a.plafond)
    _imprimer_devis(devis)
    if devis.refus:
        r = RapportCalibration(
            n_requetes=len(etiquetees), porte_franchie=False, porte_indecidable=True,
            devis=devis.model_dump(),
            avertissements=[f"refus AVANT toute dépense : {devis.refus} — rien n'a été "
                            f"dépensé : ni sonde, ni appel Anthropic, ni DataForSEO."])
        dest = _ecrire_rapport(r, dest_voulu)
        print(f"\n  rapport écrit : {dest}")
        return CODE_REFUS_AVANT_DEPENSE

    dossier = _dossier_captures()
    journal_brut = JournalCapture(dossier)
    journal_entrees: list[dict] = []

    def progress(m: str) -> None:
        print(f"  {m}")
        # La progression complète, lignes « servie(s) par le cache » comprises, à côté du
        # brut : c'est elle qui date chaque refus et chaque relecture du run.
        try:
            dossier.mkdir(parents=True, exist_ok=True)
            with open(dossier / "progression.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat(timespec='seconds')} {m}\n")
        except OSError:
            pass

    kw = dict(cost=cost, progress=progress, version=a.version,
              inclure_saisonnier=a.inclure_saisonnier, journal_brut=journal_brut,
              journal_entrees=journal_entrees)
    if a.cache:
        kw["cache_path"] = str(chemin_cache)
    code_echec = None
    try:
        r = construire_rapport(etiquetees, **kw)
    except SondeIndisponible as exc:
        # AVANT l'appel Anthropic : rien n'est parti. Surtout pas le texte « l'appel
        # Anthropic sera repayé » du cas suivant, qui ferait croire à une dépense.
        code_echec = CODE_REFUS_AVANT_DEPENSE
        r = RapportCalibration(
            n_requetes=len(etiquetees), porte_franchie=False, porte_indecidable=True,
            avertissements=[
                f"{exc}. Arrêt AVANT le classement : rien n'a été dépensé, aucun appel "
                f"Anthropic — la porte aurait été INDÉCIDABLE à coup sûr. Relancer quand "
                f"l'autocomplete répond."])
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
                # « au moins » : un PLANCHER. Les tâches créées puis non relues sont
                # imputées au pire cas là où on les connaît, mais rien ne garantit qu'aucun
                # chemin n'en ait oublié. Et un batch ASIN interrompu n'écrit AUCUNE fiche en
                # cache (elles ne s'écrivent qu'au retour du batch entier) : promettre le
                # contraire faisait relancer en croyant ne rien repayer.
                f"run interrompu ({type(exc).__name__}: {exc}) APRÈS au moins "
                f"{cost.total_usd():.4f} $ engagés — aucune mesure exploitable. Ne "
                f"touchez pas à data/lowcontent_criteres.json : relancer une fois la cause "
                f"réglée. Seules les SERP déjà relues sont en cache ; les fiches d'un batch "
                f"interrompu et l'appel Anthropic seront repayés. Brut déjà relu : {dossier}"])

    r.devis = devis.model_dump()
    r.dossier_captures = str(dossier)
    # ECRIT AVANT tout affichage. Le run vient de couter de l'argent reel : le JSON est la
    # seule trace qui compte, et il ne doit dependre d'aucune ligne decorative. L'ordre
    # inverse a existe — et `total_usd` formate comme un attribut alors que c'est une
    # methode garantissait un TypeError entre la depense et l'ecriture.
    dest = _ecrire_rapport(r, dest_voulu)
    try:
        _ecrire_captures(dossier, journal_entrees, cost, devis, a.version)
    except OSError as e:
        print(f"  ⚠ captures non écrites ({e})", file=sys.stderr)

    _imprimer(r)
    # La CLI est l'outil du développeur : le coût s'y affiche, contrairement à l'écran
    # client (§5.27).
    print(f"\n  coût réel du run : {cost.total_usd():.4f} $")
    print(f"  rapport écrit : {dest}")
    print(f"  captures du run : {dossier}")
    if journal_brut.echecs_ecriture:
        print(f"  ⚠ {journal_brut.echecs_ecriture} entrée(s) brute(s) non écrite(s) sur disque")
    if code_echec is not None:
        return code_echec
    return 0 if r.porte_franchie else 2


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
