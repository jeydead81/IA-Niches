"""Prolonger la date d'expiration de lignes du cache, sans repayer — décision de Baptiste,
2026-09-29 : « il ne faut pas que le cache expire pendant nos tests ».

Le fait qui rend l'outil nécessaire : un TTL s'applique à l'ÉCRITURE. `Cache.set` stocke
`self.now() + ttl_s` en date ABSOLUE et `get` compare cette colonne ; changer une constante ne
déplace donc AUCUNE ligne déjà écrite. Les 301 fiches du run 5 (0,9 $ payés) expirent le
2026-10-03 quoi qu'on fasse aux constantes — seule une réécriture de `expires` les garde.

Même protocole que la purge ciblée (§2.14, voie A), et pour la même raison : c'est le cache
MUTUALISÉ. Aperçu par défaut, sauvegarde horodatée vérifiée AVANT écriture, `BEGIN IMMEDIATE`
avec revérification de chaque ligne, et un JOURNAL DE RESTAURATION qui garde l'ancienne date
de chaque clé — sans lui, « prolonger » serait irréversible alors que c'est un réglage d'essai.

Deux refus délibérés :
- on ne RACCOURCIT jamais par ce chemin (une date antérieure à l'expiration courante est
  refusée) : raccourcir, c'est jeter de la donnée payée, et ça ne se fait pas par l'outil qui
  s'appelle « prolonger » ;
- une ligne DÉJÀ expirée n'est pas ressuscitée. `get` la traite comme absente : la relever
  ferait resservir, à tous les comptes, une mesure dont le TTL a déjà statué. C'est une autre
  décision que celle-ci.
"""
import json
import sqlite3
import time

import pytest

from cache import Cache


# Les clés viennent des CONSTRUCTEURS du cache, jamais d'une forme réécrite à la main :
# elles portent une empreinte de schéma (§5.14) qu'une chaîne inventée ne reproduit pas, et
# le test passerait alors au vert sur des clés que le produit n'écrit jamais (§5.37).
SERP = Cache._search_key("carnet de notes", 2250, "fr_FR")
FICHE = Cache._book_key("B0TEST0001", 2250)
PERIMEE = Cache._book_key("B0PERIME01", 2250)
CLASSEMENT = "llmlc:" + "c" * 40


@pytest.fixture()
def cache_peuple(tmp_path):
    """Trois familles, une ligne déjà expirée : le cache réel en réduction."""
    chemin = tmp_path / "df-cache.db"
    c = Cache(chemin)
    c.set(SERP, {"q": 1}, 15 * 24 * 3600)
    c.set(FICHE, {"pages": 120}, 15 * 24 * 3600)
    c.set(CLASSEMENT, {"niches": []}, 15 * 24 * 3600)
    c.set(PERIMEE, {"pages": 90}, 15 * 24 * 3600)
    with sqlite3.connect(chemin) as cx:          # expirée hier, sans passer par l'API
        cx.execute("UPDATE kv SET expires=? WHERE key=?", (time.time() - 86400, PERIMEE))
    return chemin


def _expires(chemin, cle):
    with sqlite3.connect(chemin) as cx:
        ligne = cx.execute("SELECT expires FROM kv WHERE key=?", (cle,)).fetchone()
    return None if ligne is None else ligne[0]


def test_apercu_ne_modifie_rien(cache_peuple):
    from build_lowcontent_validation_set import prolonger_cache
    avant = {k: _expires(cache_peuple, k) for k in (SERP, FICHE, CLASSEMENT)}
    res = prolonger_cache(cache_peuple, jusqu_a=time.time() + 365 * 86400, tout=True)
    assert res["sauvegarde"] is None and res["prolongees"] == 0
    assert len(res["cles"]) == 3, "les 3 lignes vivantes, jamais l'expirée"
    assert {k: _expires(cache_peuple, k) for k in avant} == avant


def test_une_ligne_DEJA_expiree_n_est_pas_ressuscitee(cache_peuple):
    from build_lowcontent_validation_set import prolonger_cache
    res = prolonger_cache(cache_peuple, jusqu_a=time.time() + 365 * 86400, tout=True,
                          confirmer=True)
    assert PERIMEE not in res["cles"]
    assert _expires(cache_peuple, PERIMEE) < time.time()


def test_une_date_qui_RACCOURCIT_est_refusee_et_rien_n_est_ecrit(cache_peuple):
    from build_lowcontent_validation_set import prolonger_cache
    avant = _expires(cache_peuple, CLASSEMENT)
    with pytest.raises(ValueError, match="raccourc"):
        prolonger_cache(cache_peuple, jusqu_a=time.time() + 3600, tout=True, confirmer=True)
    assert _expires(cache_peuple, CLASSEMENT) == avant


def test_confirmer_sauvegarde_prolonge_et_laisse_de_quoi_REVENIR(cache_peuple, tmp_path):
    from build_lowcontent_validation_set import prolonger_cache
    cible = time.time() + 365 * 86400
    anciens = {k: _expires(cache_peuple, k) for k in (SERP, FICHE, CLASSEMENT)}
    res = prolonger_cache(cache_peuple, jusqu_a=cible, tout=True, confirmer=True,
                          horodatage="20260929-200000")
    assert res["prolongees"] == 3
    assert all(abs(_expires(cache_peuple, k) - cible) < 1 for k in anciens)

    sauvegarde = tmp_path / "df-cache.sauvegarde-20260929-200000.db"
    assert sauvegarde.exists(), "la sauvegarde précède toute écriture"
    assert _expires(sauvegarde, CLASSEMENT) == anciens[CLASSEMENT]

    journal = json.loads((tmp_path / "df-cache.prolongation-20260929-200000.json")
                         .read_text(encoding="utf-8"))
    assert {e["cle"]: e["expires_avant"] for e in journal["lignes"]} == anciens
    assert abs(journal["jusqu_a"] - cible) < 1


def test_sans_TOUT_seules_les_cles_du_JEU_sont_visees(cache_peuple, monkeypatch):
    """Le cache mutualisé porte aussi de la fiction et du non-fiction : geler tout le fichier
    parce qu'on teste 44 requêtes figerait des mesures qui n'ont rien à voir."""
    import build_lowcontent_validation_set as b
    from build_lowcontent_validation_set import prolonger_cache
    monkeypatch.setattr(b, "_jeu_en_cache",
                        lambda requetes, cache, n_asin, loc, lang: (1, 0, ["B0TEST0001"]))
    res = prolonger_cache(cache_peuple, jusqu_a=time.time() + 365 * 86400,
                          requetes=["carnet de notes"], confirmer=True)
    assert res["cles"] == [SERP, FICHE]
    assert _expires(cache_peuple, CLASSEMENT) < time.time() + 30 * 86400, \
        "une clé hors du jeu ne bouge pas"


# ── Branchement CLI ────────────────────────────────────────────────────────────

def test_la_CLI_en_apercu_ne_touche_a_rien(cache_peuple, capsys):
    from build_lowcontent_validation_set import main
    avant = {k: _expires(cache_peuple, k) for k in (SERP, FICHE, CLASSEMENT)}
    code = main(["--prolonger-cache", "--tout", "--jusqu-a", "2027-12-31",
                 "--cache", str(cache_peuple)])
    assert code == 0
    assert {k: _expires(cache_peuple, k) for k in avant} == avant
    sortie = capsys.readouterr().out
    assert "APERÇU" in sortie and "3" in sortie
    assert not list(cache_peuple.parent.glob("*.sauvegarde-*")), "aucune sauvegarde en aperçu"


def test_la_CLI_exige_une_date_pour_prolonger(cache_peuple):
    from build_lowcontent_validation_set import main
    with pytest.raises(SystemExit) as e:
        main(["--prolonger-cache", "--tout", "--cache", str(cache_peuple)])
    assert e.value.code == 2


def test_la_CLI_confirmee_prolonge_et_annonce_le_journal(cache_peuple, capsys):
    from build_lowcontent_validation_set import main
    code = main(["--prolonger-cache", "--tout", "--jusqu-a", "2027-12-31", "--confirmer",
                 "--cache", str(cache_peuple)])
    assert code == 0
    sortie = capsys.readouterr().out
    assert "Sauvegarde" in sortie and "journal" in sortie.lower()
    from datetime import datetime
    cible = datetime.fromisoformat("2027-12-31").timestamp()
    assert abs(_expires(cache_peuple, FICHE) - cible) < 1
