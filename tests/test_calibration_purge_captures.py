"""R2 (voie A) et R5 (écriture) — ne plus jamais repayer une fiche à cause d'un parseur.

R2 — les 185 fiches du run 4 ont été lues par un parseur qui ne trouvait pas la pagination,
et le cache MUTUALISÉ les ressert jusqu'au 29/09 : l'empreinte de clé suit les NOMS des champs,
pas la logique du parseur (§5.14). Décision de Baptiste : un outil de purge CIBLÉE, aperçu par
défaut, qui ne supprime qu'avec `--confirmer --ecrites-avant <date>`, après sauvegarde, et
EXACTEMENT les clés `book:` valides des ASIN du jeu dont `pages` est None et qui ont été écrites
avant la date butoir (une fiche lue par le parseur corrigé sans pagination est une vraie
absence, pas un défaut de lecture). Jamais `search:`, jamais `clf:`, jamais une
autre fiche. Il n'est exécuté ici que sur des COPIES temporaires.

R5 — le brut de ces 185 fiches est perdu. Pendant un run `--xlsx`, la CLI écrit sous
`99-logs/captures/calibration-<horodatage>/` — quel que soit `--out`, pour rester hors de git —
les bruts ASIN, SERP et classement
(JSONL, ligne écrite AU MOMENT où le crochet la reçoit, donc avant parsing), les entrées de
scoring et la ventilation du coût. Jamais dans le cache partagé.

Données : captures RÉELLES v2 (seules à fonder une assertion `.pages` sur le parseur), classeur
RÉEL, état RÉEL du cache après le run 4 (`outils_calibration.cache_run4_reel` : des fiches DÉJÀ
parsées par l'ancien parseur, jamais données au parseur ici). Inventés et déclarés :
les identifiants `B0HORSJEU1`, `B0HORSJEU2` et `B0EXPIRE01` (fiches réelles recopiées sous
un autre ASIN), la forme des SERP, les espions de `construire_rapport`.
"""
import json
import time
from datetime import datetime

import pytest

import build_lowcontent_validation_set as cli
from cache import Cache
from lowcontent_validation import RapportCalibration
from tests.outils_calibration import (ASINS_V2, LOC, LANG, PAYLOADS, XLSX_REEL, cache_run4_reel,
                                      cles, etiquetees_reelles, livre_v2)

_TTL = 15 * 24 * 3600


def _demain() -> str:
    return datetime.fromtimestamp(time.time() + 24 * 3600).isoformat(timespec="seconds")


def _cache_de_purge(chemin):
    """Trois requêtes réelles. Ce qui DOIT partir : les fiches sans pages parmi les 6 premiers
    organiques. Ce qui doit RESTER : une fiche utile du jeu, une fiche sans pages hors jeu,
    un 7e organique sans pages, une fiche du jeu déjà expirée, les SERP et un `clf:`."""
    from models import SearchItem, SearchResult
    q = [e.requete for e in etiquetees_reelles()][:3]
    c = Cache(chemin)

    def serp(requete, asins):
        return SearchResult(keyword=requete, organic=[
            SearchItem(rank=i, asin=a, title=f"titre {a}", price=9.99)
            for i, a in enumerate(asins, 1)])

    c.set_search(q[0], LOC, LANG, serp(q[0], ASINS_V2[0:5] + ["B0EXPIRE01"]), _TTL)
    c.set_search(q[1], LOC, LANG, serp(q[1], ASINS_V2[3:8] + [ASINS_V2[0]]), _TTL)
    c.set_search(q[2], LOC, LANG, serp(q[2], ASINS_V2[1:7] + ["B0HORSJEU2"]), _TTL)
    utile = ASINS_V2[7]
    for a in ASINS_V2:
        c.set_book(a, LOC, livre_v2(a, sans_pages=(a != utile)), _TTL)
    for a in ("B0HORSJEU1", "B0HORSJEU2"):
        c.set_book(a, LOC, livre_v2(ASINS_V2[0], sans_pages=True).model_copy(
            update={"asin": a}), _TTL)
    c.set_book("B0EXPIRE01", LOC, livre_v2(ASINS_V2[0], sans_pages=True).model_copy(
        update={"asin": "B0EXPIRE01"}), -10)
    c.set("clf:fr_v1:claude-sonnet-5:x:y:" + ASINS_V2[0], {"tropes": []}, _TTL)
    attendues = {Cache._book_key(a, LOC) for a in ASINS_V2 if a != utile}
    return attendues


def test_R2_les_cles_visees_sont_EXACTEMENT_celles_du_jeu_sans_pages(tmp_path):
    chemin = tmp_path / "cache.db"
    attendues = _cache_de_purge(chemin)
    requetes = [e.requete for e in etiquetees_reelles()]
    visees = cli.fiches_sans_pages(requetes, cli.ouvrir_cache_lecture(chemin))
    assert set(visees) == attendues


def test_R2_APERCU_par_defaut_ne_touche_a_rien(tmp_path, capsys):
    chemin = tmp_path / "cache.db"
    attendues = _cache_de_purge(chemin)
    avant = cles(chemin)
    code = cli.main(["--xlsx", str(XLSX_REEL), "--cache", str(chemin),
                     "--purger-fiches-sans-pages"])
    out = capsys.readouterr().out
    assert code == 0
    assert cles(chemin) == avant
    assert str(len(attendues)) in out and "--confirmer" in out
    assert not list(tmp_path.glob("*sauvegarde*"))


def test_R2_CONFIRMER_sauvegarde_puis_supprime_exactement_les_cles_visees(tmp_path, capsys):
    chemin = tmp_path / "cache.db"
    attendues = _cache_de_purge(chemin)
    avant = cles(chemin)
    code = cli.main(["--xlsx", str(XLSX_REEL), "--cache", str(chemin),
                     "--purger-fiches-sans-pages", "--confirmer", "--ecrites-avant", _demain()])
    assert code == 0
    apres = cles(chemin)
    assert set(avant) - set(apres) == attendues
    assert {k: avant[k] for k in apres} == apres, "une clé restante a changé"
    sauvegardes = [p for p in tmp_path.iterdir() if "sauvegarde" in p.name
                   and p.name.endswith(".db")]
    assert len(sauvegardes) == 1
    assert set(cles(sauvegardes[0])) == set(avant)


def test_R2_sur_l_etat_REEL_du_run_4_seules_les_185_fiches_du_jeu_partent(tmp_path, capsys):
    """État réel du cache après le run 4 : 31 SERP, 185 fiches toutes sans pagination, 84
    classifications. Inconditionnel — plus de branche qui s'éteint une fois le vrai cache
    purgé, et plus de test ignoré sur un clone neuf."""
    copie = cache_run4_reel(tmp_path)
    requetes = [e.requete for e in etiquetees_reelles()]
    visees = cli.fiches_sans_pages(requetes, cli.ouvrir_cache_lecture(copie))
    assert len(visees) == 185 and all(k.startswith("book:") for k in visees)
    avant = cles(copie)
    code = cli.main(["--xlsx", str(XLSX_REEL), "--cache", str(copie),
                     "--purger-fiches-sans-pages", "--confirmer", "--ecrites-avant", _demain()])
    assert code == 0
    apres = cles(copie)
    assert set(avant) - set(apres) == set(visees)
    assert {k: v for k, v in avant.items() if k.startswith("search:")} == {
        k: v for k, v in apres.items() if k.startswith("search:")}
    assert {k: v for k, v in avant.items() if k.startswith("clf:")} == {
        k: v for k, v in apres.items() if k.startswith("clf:")}
    assert sum(k.startswith("search:") for k in apres) == 31
    assert sum(k.startswith("clf:") for k in apres) == 84


# ══ R5 — captures de run ═════════════════════════════════════════════════════════

def test_R5_la_capture_ecrit_la_ligne_AU_MOMENT_de_l_append(tmp_path):
    journal = cli.JournalCapture(tmp_path / "cap")
    a = ASINS_V2[1]
    journal.append({"type": "asin", "asin": a, "payload": PAYLOADS[a]})
    lignes = (tmp_path / "cap" / "asin.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lignes) == 1
    lu = json.loads(lignes[0])
    assert json.dumps(lu["payload"], sort_keys=True) == json.dumps(PAYLOADS[a], sort_keys=True)
    assert len(journal) == 1


def test_R5_enrich_asins_ecrit_le_brut_dans_le_fichier_de_run(tmp_path):
    from cost_tracker import CostTracker
    from fiction_serp_provider import enrich_asins

    class _Prov:
        location_code, priority = 2250, 2

        def product_raw_batch(self, asins):
            return {x: PAYLOADS[x] for x in asins}

    journal = cli.JournalCapture(tmp_path / "cap")
    enrich_asins(["1923235036"], _Prov(), cost=CostTracker(), journal_brut=journal)
    brut = json.loads((tmp_path / "cap" / "asin.jsonl").read_text("utf-8").splitlines()[0])
    from fiction_books import parse_enriched_book
    assert parse_enriched_book(brut["payload"]).pages == 335


def _classeur(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from lowcontent_validation import exporter_gabarit
    chemin = exporter_gabarit(tmp_path / "v.xlsx")
    wb = openpyxl.load_workbook(chemin)
    wb.active["A7"], wb.active["C7"] = "carnet de voyage", "bonne"
    wb.save(chemin)
    return chemin


def _run_espion(exception=None):
    def construire(*a, cost=None, journal_brut=None, journal_entrees=None, **k):
        journal_brut.append({"type": "classement", "source": "api", "inputs": [{"niches": []}]})
        journal_brut.append({"type": "serp_get", "keyword": "carnet de voyage",
                             "reponse": {"tasks": []}})
        journal_brut.append({"type": "asin", "asin": ASINS_V2[1],
                             "payload": PAYLOADS[ASINS_V2[1]]})
        journal_entrees.append({"type": "non_rendue", "requete": "carnet de voyage",
                                "etiquette": "bonne"})
        cost.add_dataforseo(7, 2)
        if exception is not None:
            raise exception
        return RapportCalibration(n_requetes=1)
    return construire


@pytest.mark.parametrize("exception", [None, RuntimeError("après paiement"),
                                       KeyboardInterrupt()])
def test_R5_un_run_xlsx_laisse_ses_captures_meme_s_il_leve(tmp_path, monkeypatch, exception):
    monkeypatch.setattr(cli, "construire_rapport", _run_espion(exception))
    sortie = tmp_path / "sortie" / "r.json"
    sortie.parent.mkdir()
    cli.main(["--xlsx", str(_classeur(tmp_path)), "--cache", str(tmp_path / "vide.db"),
              "--out", str(sortie)])
    # Racine des captures redirigée vers tmp_path par conftest : jamais 99-logs/captures réel.
    dossiers = list(cli.RACINE_CAPTURES.glob("calibration-*"))
    assert len(dossiers) == 1
    d = dossiers[0]
    for nom in ("asin.jsonl", "serp.jsonl", "classement.jsonl"):
        assert (d / nom).read_text("utf-8").strip(), nom
    assert json.loads((d / "entrees.json").read_text("utf-8"))["entrees"]
    cout = json.loads((d / "cout.json").read_text("utf-8"))
    assert cout["dataforseo_calls"] == 7 and cout["devis"]["total_usd"] > 0
    r = json.loads(sortie.read_text("utf-8"))
    assert r["dossier_captures"] == str(d)
