"""Revue du correctif de calibration — ce que les mutants et les relectures ont laissé passer.

ARGENT
- Garde prédictif du batch ASIN : le master calculait « à relire » sur une première lecture
  du cache, puis `enrich_asins` relisait et postait TOUT ce qui manquait à cet instant, sans
  aucun `verifier`. Les 185 fiches du run 4 expirent dans la même seconde : une phase 4 à
  cheval sur cet instant achetait 0,555 $ au-delà du plafond. En fiction, aucune vérification
  n'existait avant le batch. Le garde vit désormais dans `enrich_asins`, juste avant l'envoi,
  et rend les fiches servies par le cache au lieu de lever.
- `resolve_bsrs` (canal dataforseo) n'imputait rien sur un Ctrl-C pendant le poll : les
  tâches étaient créées, donc facturées.
- Une écriture de cache qui lève (`database is locked`) dans `enrich_asins` jetait tout le
  batch déjà payé ; le low-content rachetait ensuite ces ASIN par le canal BSR (§5.31).
- La purge supprimait aussi les fiches LÉGITIMEMENT sans pagination (livre audio
  B0FS7JQNJ6), rachetées à chaque cycle purge + run pour le même None.

CAPTURES ET GARDES DE TEST
- Le dossier des captures suivait `--out` : hors de 99-logs/, rien ne l'excluait de git.
- Rien ne vérifiait que la CLI transmet le journal brut au run réel (mutant survivant).
- La sauvegarde de purge copie -wal et -shm : aucun test ne le prouvait.
- Le garde « le vrai cache n'est jamais ciblé » lisait des chaînes dans son propre source.

Données : captures RÉELLES v2 (`fixtures/fiction/v2_asin_payloads.json`), classeur RÉEL
(lecture seule). Sont INVENTÉS et déclarés là où ils servent : la SERP qui aligne les ASIN v2
sous une requête, les fournisseurs espions, l'horloge du cache qui avance, l'erreur SQLite
d'écriture, les fiches fiction `A0`/`A1`/`A2`.
"""
import json
import sqlite3
import subprocess
import time
from datetime import datetime

import pytest

import build_lowcontent_validation_set as cli
from cache import BOOK_TTL_S, Cache
from cost_tracker import CostTracker
from fiction_books import parse_enriched_book
from models import EnrichedBook
from tests.outils_calibration import (ASINS_V2, LOC, PAYLOADS, RACINE, XLSX_REEL, cles,
                                      etiquetees_reelles)
from tests.test_master_lowcontent_cache import (_ASIN_LIVRES, _REQUETE, _ProvInterdit,
                                                _cache_garni, _niche)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


class _ProvCompteur(_ProvInterdit):
    """Rend les payloads RÉELS, et compte chaque envoi de lot."""

    def product_raw_batch(self, asins, **kw):
        self.appels.append(("batch", list(asins)))
        return {a: PAYLOADS[a] for a in asins}


def _run_lc(tmp_path, monkeypatch, *, plafond, cache_factory, provider, progress):
    import lowcontent_master
    from autocomplete_expand import Suggestion
    monkeypatch.setattr(lowcontent_master, "Cache", cache_factory)
    bsr_appels = []
    out = lowcontent_master.run_lowcontent_scout(
        seed="carnet", cache_path=str(tmp_path / "df-cache.db"), provider=provider,
        cost=CostTracker(plafond_usd=plafond), bsr_pause=0,
        expand_fn=lambda *a, **k: [Suggestion(requete=_REQUETE, parent="", profondeur=0,
                                              n_enfants=4)],
        ideate=lambda **k: [_niche(_REQUETE)],
        fetch_bsr_fn=lambda asin: bsr_appels.append(asin) or None, progress=progress)
    return out, bsr_appels


# ══ Garde prédictif DANS enrich_asins ════════════════════════════════════════════

def test_une_fiche_qui_EXPIRE_entre_le_devis_et_le_batch_n_est_pas_achetee_sans_verifier(
        tmp_path, monkeypatch):
    """Horloge INVENTÉE : le cache est valide pendant le devis de la phase 4, puis toutes
    les fiches expirent à l'instant où l'enrichissement démarre — le run 4 expire en bloc
    le 2026-09-29 à 10:47:26. Plafond 0,010 $ : six fiches à relire valent 0,018 $."""
    t0 = time.time()
    _cache_garni(tmp_path, en_cache=_ASIN_LIVRES, serp_asins=_ASIN_LIVRES)
    etat = {"expire": False}

    def horloge():
        return t0 + BOOK_TTL_S + 10 if etat["expire"] else t0

    etapes = []

    def progress(m):
        etapes.append(m)
        if m.startswith("Enrichissement de"):
            etat["expire"] = True

    prov = _ProvCompteur()
    _run_lc(tmp_path, monkeypatch, plafond=0.010, provider=prov, progress=progress,
            cache_factory=lambda p: Cache(p, now=horloge))
    assert not any(a == "batch" for a, _ in prov.appels), "batch acheté sans vérifier"
    assert any("plafond de coût atteint" in e for e in etapes), etapes


def test_fiction_le_batch_ASIN_est_verifie_AVANT_l_envoi_et_le_cache_sert_quand_meme(
        tmp_path):
    from fiction_master import run_fiction_scout
    from fiction_serp_provider import enrich_asins
    from tests.test_fiction_master import _faux_classify, _faux_ideate, _faux_probe
    cache = Cache(tmp_path / "c.db")
    cache.set_book("A0", LOC, EnrichedBook(asin="A0", title="T", blurb="b"), BOOK_TTL_S)
    prov, etapes = _ProvCompteur(), []
    # L'ideator factice impute ~0,001 $ de jetons. 1 SERP prévue (0,003 $) passe sous
    # 0,005 $ ; 2 ASIN à relire (0,006 $) non.
    rapports = run_fiction_scout(
        "cosy_mystery", n_niches=1, ideate=_faux_ideate,
        serp_fn=lambda niche, **kw: ("rh=n:1", ["A0", "A1", "A2"]),
        enrich_fn=lambda asins, **kw: enrich_asins(asins, prov, **kw),
        classify=_faux_classify, probe=_faux_probe, cache=cache,
        cost=CostTracker(plafond_usd=0.005), progress=etapes.append)
    assert prov.appels == []
    assert len(rapports) == 1
    assert any("plafond de coût atteint" in e for e in etapes), etapes


# ══ resolve_bsrs : Ctrl-C pendant le poll ════════════════════════════════════════

def test_resolve_bsrs_impute_le_pire_cas_sur_un_ctrl_c_pendant_le_batch():
    from bsr_source import resolve_bsrs
    from cost_tracker import dataforseo_cost_usd

    class _Prov:
        priority = 2

        def product_info_batch(self, asins):
            raise KeyboardInterrupt

    cost = CostTracker(plafond_usd=None)
    with pytest.raises(KeyboardInterrupt):
        resolve_bsrs(["A1", "A2"], source="dataforseo", provider=_Prov(), cost=cost,
                     bsr_pause=0)
    assert cost.breakdown()["dataforseo_calls"] == 2
    assert cost.total_usd() == pytest.approx(dataforseo_cost_usd(2, 2))


# ══ Écriture de cache qui lève ═══════════════════════════════════════════════════

class _CacheSansEcriture(Cache):
    """Erreur INVENTÉE, forme réelle de sqlite3 au-delà du timeout de 10 s."""

    def set_book(self, *a, **k):
        raise sqlite3.OperationalError("database is locked")


def test_enrich_asins_rend_le_batch_paye_meme_si_le_cache_refuse_l_ecriture(tmp_path):
    from fiction_serp_provider import enrich_asins
    trois = _ASIN_LIVRES[:3]
    etapes, cost = [], CostTracker(plafond_usd=None)
    out = enrich_asins(trois, _ProvCompteur(), cache=_CacheSansEcriture(tmp_path / "c.db"),
                       cost=cost, progress=etapes.append)
    assert set(out) == set(trois)
    assert out[trois[0]].pages == parse_enriched_book(PAYLOADS[trois[0]]).pages
    assert cost.breakdown()["dataforseo_calls"] == 3
    assert any("3" in e and "cache" in e and "écrite" in e for e in etapes), etapes


def test_lowcontent_une_ecriture_de_cache_en_echec_ne_fait_pas_racheter_par_le_canal_BSR(
        tmp_path, monkeypatch):
    _cache_garni(tmp_path, en_cache=[], serp_asins=_ASIN_LIVRES)
    etapes = []
    out, bsr_appels = _run_lc(tmp_path, monkeypatch, plafond=None, provider=_ProvCompteur(),
                              progress=etapes.append, cache_factory=_CacheSansEcriture)
    assert bsr_appels == [], "les ASIN payés au batch ont été redemandés au canal BSR"
    assert out and out[0].part_indie is not None


# ══ Purge : seulement les fiches écrites AVANT le correctif du parseur ═══════════

def _cache_dates(chemin):
    """Deux fiches du jeu sans pages écrites il y a deux jours (ancien parseur), les autres
    sans pages écrites maintenant (parseur corrigé : vraie absence, comme le livre audio)."""
    from tests.test_calibration_purge_captures import _cache_de_purge
    _cache_de_purge(chemin)
    il_y_a_deux_jours = time.time() - 2 * 24 * 3600
    ancien = Cache(chemin, now=lambda: il_y_a_deux_jours)
    from tests.outils_calibration import livre_v2
    vieilles = ASINS_V2[:2]
    for a in vieilles:
        ancien.set_book(a, LOC, livre_v2(a, sans_pages=True), BOOK_TTL_S)
    return {Cache._book_key(a, LOC) for a in vieilles}


def test_purge_ne_vise_que_les_fiches_ecrites_avant_la_date_butoir(tmp_path, capsys):
    chemin = tmp_path / "cache.db"
    vieilles = _cache_dates(chemin)
    avant = cles(chemin)
    hier = _iso(time.time() - 24 * 3600)
    code = cli.main(["--xlsx", str(XLSX_REEL), "--cache", str(chemin),
                     "--purger-fiches-sans-pages", "--confirmer", "--ecrites-avant", hier])
    assert code == 0
    assert set(avant) - set(cles(chemin)) == vieilles


def test_purge_confirmer_sans_date_butoir_est_refusee_et_ne_touche_a_rien(tmp_path, capsys):
    chemin = tmp_path / "cache.db"
    _cache_dates(chemin)
    avant = cles(chemin)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--xlsx", str(XLSX_REEL), "--cache", str(chemin),
                  "--purger-fiches-sans-pages", "--confirmer"])
    assert exc.value.code == 2
    assert "--ecrites-avant" in capsys.readouterr().err
    assert cles(chemin) == avant


def test_purge_apercu_avec_date_butoir_ne_compte_que_les_anciennes(tmp_path):
    chemin = tmp_path / "cache.db"
    vieilles = _cache_dates(chemin)
    requetes = [e.requete for e in etiquetees_reelles()]
    visees = cli.fiches_sans_pages(requetes, cli.ouvrir_cache_lecture(chemin),
                                   ecrites_avant=time.time() - 24 * 3600)
    assert set(visees) == vieilles


# ══ Captures : hors de git QUEL QUE SOIT --out ════════════════════════════════════

def test_les_captures_ne_suivent_pas_out(tmp_path, monkeypatch):
    from tests.test_calibration_purge_captures import _classeur, _run_espion
    monkeypatch.setattr(cli, "construire_rapport", _run_espion())
    sortie = tmp_path / "ailleurs" / "r.json"
    sortie.parent.mkdir()
    cli.main(["--xlsx", str(_classeur(tmp_path)), "--cache", str(tmp_path / "vide.db"),
              "--out", str(sortie)])
    assert not (sortie.parent / "captures").exists()
    dossiers = list(cli.RACINE_CAPTURES.glob("calibration-*"))
    assert len(dossiers) == 1
    assert json.loads(sortie.read_text("utf-8"))["dossier_captures"] == str(dossiers[0])


def test_le_chemin_REELLEMENT_rendu_par_defaut_est_ignore_par_git(monkeypatch):
    monkeypatch.setattr(cli, "RACINE_CAPTURES", cli._RACINE_CAPTURES_DEFAUT)
    dossier = cli._dossier_captures()
    assert not dossier.exists()               # calculer un chemin ne crée rien
    for nom in ("asin.jsonl", "serp.jsonl", "classement.jsonl", "entrees.json",
                "progression.log"):
        rel = (dossier / nom).relative_to(RACINE).as_posix()
        try:
            r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=RACINE,
                               capture_output=True, timeout=30)
        except FileNotFoundError:
            pytest.fail("git introuvable : impossible de vérifier que les captures sont ignorées")
        assert r.returncode == 0, f"{rel} n'est PAS ignoré par git"


# ══ La CLI transmet le journal brut au run réel ══════════════════════════════════

def test_construire_rapport_transmet_le_journal_brut_au_run():
    from autocomplete_expand import Suggestion
    recus = []

    def run(**kw):
        recus.append(kw)
        return []

    journal = cli.JournalCapture.__new__(cli.JournalCapture)
    list.__init__(journal)
    etq = etiquetees_reelles()[:2]
    cli.construire_rapport(etq, run=run, journal_brut=journal,
                           sonde=lambda rs, **k: [Suggestion(requete=q, parent="",
                                                             profondeur=0, n_enfants=3)
                                                  for q in rs])
    assert len(recus) == 1
    assert recus[0].get("journal_brut") is journal


# ══ Purge : la sauvegarde porte ce qui n'est encore QUE dans le -wal ═════════════

def test_la_sauvegarde_de_purge_porte_les_cles_encore_dans_le_WAL(tmp_path):
    from tests.test_calibration_purge_captures import _cache_de_purge
    chemin = tmp_path / "cache.db"
    Cache(chemin)                                       # table créée et reportée
    tenue = sqlite3.connect(chemin)
    try:
        tenue.execute("PRAGMA wal_autocheckpoint=0")
        tenue.execute("SELECT count(*) FROM kv").fetchone()
        attendues = _cache_de_purge(chemin)             # écrit pendant que `tenue` vit
        assert (tmp_path / "cache.db-wal").stat().st_size > 0
        code = cli.main(["--xlsx", str(XLSX_REEL), "--cache", str(chemin),
                         "--purger-fiches-sans-pages", "--confirmer",
                         "--ecrites-avant", _iso(time.time() + 24 * 3600)])
        assert code == 0
    finally:
        tenue.close()
    sauvegarde = next(p for p in tmp_path.iterdir()
                      if "sauvegarde" in p.name and p.name.endswith(".db"))
    assert attendues <= set(cles(sauvegarde))


# ══ Le vrai cache n'est jamais la cible d'un test (garde de COMPORTEMENT) ═════════

def test_le_garde_de_test_refuse_une_purge_du_vrai_cache(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    with pytest.raises(AssertionError, match="vrai cache"):
        cli.purger_fiches_sans_pages([], RACINE / "99-logs" / "df-cache.db")
    with pytest.raises(AssertionError, match="vrai cache"):
        cli.main(["--xlsx", str(XLSX_REEL), "--purger-fiches-sans-pages"])
