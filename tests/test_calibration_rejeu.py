"""R26, R13, R20, R25 — lire un run APRÈS coup sans le repayer, et le lire juste.

- R26 : `score_lowcontent` recalcule depuis la SERP, les fiches, les BSR et la date. Le rapport
  du run 4 n'en gardait rien : format, risques et `n_enfants` par niche sont perdus, et
  l'écart de Spearman avec les rejeux reste inattribuable. Le master remplit désormais un
  journal des ENTRÉES du scoring, et `--rejouer` rescore hors ligne. Un rejeu ne peut JAMAIS
  afficher PORTE FRANCHIE : des seuils ajustés sur le jeu même ne se valident pas sur lui.
- R13 : après le run 4, le rapport disait « aucune fiche exploitable » (faux : l'éditeur était
  lu sur 31 niches) et « le cache ne repaiera que ce qui manque » (faux : il resservait les
  mêmes fiches mal lues). Relancer tel quel reproduisait le run à l'identique.
- R20 + R25 : des DIAGNOSTICS par étiquette (compteurs de bonus, médianes d'axes), sans seuil
  et sans effet sur la porte : c'est Baptiste qui juge.

Données : captures RÉELLES v2 (fiches), classeur RÉEL (requêtes et étiquettes). Inventés et
déclarés : la forme des SERP, l'ideator et le fournisseur factices, les distributions de
`part_indie` reprises des chiffres du plan (24×1,0, 3×0,8333, 1×0,8, 1×0,333, 2×0,2).
"""
import json
import sys
import types
from datetime import date

import pytest

import build_lowcontent_validation_set as cli
import lowcontent_scoring
from autocomplete_expand import Suggestion
from lowcontent_validation import RapportCalibration, rapport_calibration
from models import LowContentNiche, LowContentScored
from tests.outils_calibration import (PAYLOADS, asins_de, etiquetees_reelles, etiquetees_run4,
                                      serp_v2)


# ══ R26 — journal des entrées et rejeu ═══════════════════════════════════════════

class _Fournisseur:
    location_code, language_code, priority = 2250, "fr_FR", 2

    def __init__(self):
        self.requetes = []

    def search(self, q, books_only=True):
        self.requetes.append(q)
        return serp_v2(q, asins_de(len(self.requetes) - 1))

    def product_raw_batch(self, asins):
        return {a: PAYLOADS[a] for a in asins}


class _Fige(date):
    @classmethod
    def today(cls):
        return date(2026, 9, 14)          # jour du run 4 : le test ne se périme pas


class _Lointain(date):
    """Date système du SCORING pendant le run : loin du jour du master. Sans elle, un master
    qui oublie de passer `aujourdhui` retombait sur `date.today()` — et les dates de
    publication des captures v2 ne changent de classe qu'hors de 2026-06-23..2027-02-09 :
    le garde était aveugle des mois durant (mutant survivant le 2026-09-14)."""
    @classmethod
    def today(cls):
        return date(2031, 1, 1)


def _run_bout_en_bout(monkeypatch, journal, etapes):
    """Le VRAI master, fournisseur et ideator factices. La « morte » porte un risque TOS
    (−2 sur le global) pour que le jeu soit ordonné et que la porte s'ouvre au rejeu."""
    import lowcontent_master
    from ip_filter import filtrer_ip
    from lowcontent_master import run_lowcontent_scout
    monkeypatch.setattr(lowcontent_master, "date", _Fige)
    monkeypatch.setattr(lowcontent_scoring, "date", _Lointain)
    etq = [e for e in etiquetees_reelles()
           if not filtrer_ip([Suggestion(requete=e.requete)])[1]]
    jeu = [next(e for e in etq if e.etiquette == "bonne"),
           next(e for e in etq if e.etiquette == "morte")]
    mortes = {e.requete for e in jeu if e.etiquette == "morte"}

    def ideate(suggestions=None, **kw):
        return [LowContentNiche(niche=s.requete, requete_amazon=s.requete, rationale="r",
                                categorie="c", format_cle="journal_suivi", theme="t",
                                public="adulte", n_enfants_autocomplete=s.n_enfants,
                                risques=["tos"] if s.requete in mortes else [])
                for s in suggestions]

    scorees = []

    def run(**kw):
        out = run_lowcontent_scout(use_cache=False, ideate=ideate, provider=_Fournisseur(),
                                   fetch_bsr_fn=lambda *a, **k: None, **kw)
        scorees.extend(out)
        return out

    r = cli.construire_rapport(
        jeu, run=run, progress=etapes.append, journal_entrees=journal,
        inclure_saisonnier=True,
        sonde=lambda rs, **kw: [Suggestion(requete=q, parent="", profondeur=0, n_enfants=3)
                                for q in rs])
    return jeu, r, scorees


def test_R26_le_journal_porte_une_entree_complete_par_niche(monkeypatch):
    journal, etapes = [], []
    jeu, r, scorees = _run_bout_en_bout(monkeypatch, journal, etapes)
    niches = [e for e in journal if e["type"] == "niche"]
    assert len(niches) == len(scorees) == 2
    for e in niches:
        assert e["niche"]["format_cle"] == "journal_suivi"
        assert "risques" in e["niche"] and "n_enfants_autocomplete" in e["niche"]
        assert e["search"]["organic"] and e["livres"]
        assert e["etiquette"] in ("bonne", "morte") and e["aujourdhui"]
    # Le « Lecture … autour de « validation » » du master ne décrivait rien de réel ici.
    assert not any("autour de « validation »" in m for m in etapes)


def _entrees_sur_disque(tmp_path, monkeypatch):
    journal = []
    jeu, r, scorees = _run_bout_en_bout(monkeypatch, journal, [])
    chemin = tmp_path / "entrees.json"
    chemin.write_text(json.dumps({"entrees": journal}, ensure_ascii=False), encoding="utf-8")
    return chemin, journal, r, scorees


def test_R26_le_rejeu_rend_les_memes_scores_SANS_fournisseur_ni_ideator_ni_date(
        tmp_path, monkeypatch, capsys):
    chemin, journal, r0, scorees = _entrees_sur_disque(tmp_path, monkeypatch)

    def leve(nom):
        m = types.ModuleType(nom)

        def __getattr__(attr):
            raise AssertionError(f"le rejeu a touché {nom}.{attr}")
        m.__getattr__ = __getattr__
        return m

    # Deux gardes cumulés. Le remplacement de `sys.modules` ne voit que les imports
    # PARESSEUX ; un nom déjà lié au chargement (`from lowcontent_ideator import _norm` dans
    # la CLI) lui échappe. Les méthodes de CLASSE du fournisseur et le client Anthropic, eux,
    # sont atteints quelle que soit la liaison : ce sont les seules portes vers le réseau.
    import lowcontent_ideator as ideator_reel
    import search_providers as fournisseur_reel

    def reseau(*a, **k):
        raise AssertionError("le rejeu a tenté un appel payant")
    monkeypatch.setattr(fournisseur_reel.DataForSEOProvider, "_post", reseau)
    monkeypatch.setattr(fournisseur_reel.DataForSEOProvider, "_get", reseau)
    monkeypatch.setattr(ideator_reel, "_default_client", reseau)
    for nom in ("lowcontent_master", "search_providers", "lowcontent_ideator"):
        monkeypatch.setitem(sys.modules, nom, leve(nom))

    class _Futur(date):
        @classmethod
        def today(cls):
            return date(2031, 1, 1)

    # Sans la date archivée, une autre date système change la part de livres récents.
    niche = next(e for e in journal if e["type"] == "niche")
    from lowcontent_validation import entrees_vers_arguments
    args = entrees_vers_arguments(niche)
    a_2031 = lowcontent_scoring.score_lowcontent(**{**args, "aujourdhui": "2031-01-01"})
    assert a_2031.part_moins_12_mois != lowcontent_scoring.score_lowcontent(**args).part_moins_12_mois

    monkeypatch.setattr(lowcontent_scoring, "date", _Futur)
    from lowcontent_validation import rescorer_entrees
    rescores = {s.niche.requete_amazon: s for _, s in rescorer_entrees(journal)}
    for s in scorees:
        assert rescores[s.niche.requete_amazon].global_score == s.global_score
        assert rescores[s.niche.requete_amazon].part_moins_12_mois == s.part_moins_12_mois

    sortie = tmp_path / "rejeu.json"
    code = cli.main(["--rejouer", str(chemin), "--out", str(sortie)])
    rj = json.loads(sortie.read_text(encoding="utf-8"))
    assert rj["spearman"] == r0.spearman and rj["rejeu"] is True
    assert code == 2


def test_R26_un_rejeu_ne_peut_JAMAIS_afficher_PORTE_FRANCHIE(tmp_path, monkeypatch, capsys):
    chemin, journal, r0, _ = _entrees_sur_disque(tmp_path, monkeypatch)
    assert r0.porte_franchie is True, "le jeu doit franchir la porte pour que le test morde"
    sortie = tmp_path / "rejeu.json"
    code = cli.main(["--rejouer", str(chemin), "--out", str(sortie)])
    out = capsys.readouterr().out
    rj = json.loads(sortie.read_text(encoding="utf-8"))
    assert rj["porte_franchie"] is False and rj["rejeu"] is True
    assert "PORTE FRANCHIE" not in out and "REJEU" in out
    assert code == 2


def test_R26_un_rejeu_avec_un_critere_abaisse_change_la_penetration(tmp_path, monkeypatch):
    from lowcontent_scoring import charger_criteres
    from lowcontent_validation import rejouer_entrees, rescorer_entrees
    _, journal, _, scorees = _entrees_sur_disque(tmp_path, monkeypatch)
    criteres = charger_criteres()
    criteres["cibles_max"] = -1
    avant = {s.niche.requete_amazon: s.penetration for s in scorees}
    apres = {s.niche.requete_amazon: s.penetration
             for _, s in rescorer_entrees(journal, criteres=criteres)}
    assert any(apres[q] != avant[q] for q in avant)
    assert rejouer_entrees(journal, criteres=criteres).porte_franchie is False


def test_R26_sans_journal_le_master_ne_change_pas():
    import inspect
    from lowcontent_master import run_lowcontent_scout
    assert inspect.signature(run_lowcontent_scout).parameters["journal_entrees"].default is None


# ══ R13 — les avertissements disent la cause ═════════════════════════════════════

def _scored(requete, score, **kw):
    n = LowContentNiche(niche=requete, requete_amazon=requete, rationale="r", categorie="c",
                        format_cle="journal_suivi", theme="t", public="adulte",
                        n_enfants_autocomplete=3)
    base = dict(niche=n, global_score=score, concurrence_mesuree=True,
                priorite="🟢 À analyser en priorité" if score >= 7.5 else "🔴 Faible")
    base.update(kw)
    return LowContentScored(**base)


def _paires_run4(**kw):
    etq = etiquetees_run4()
    ordinal = {"morte": 0, "mauvaise": 1, "bonne": 2}
    return [(e.etiquette, _scored(e.requete, 3.0 + ordinal[e.etiquette] + i * 0.01, **kw))
            for i, e in enumerate(etq)]


def test_R13_run_4_la_cause_est_la_LECTURE_pas_l_enrichissement():
    r = rapport_calibration(_paires_run4(part_indie=1.0, redevance_estimee=None))
    texte = " | ".join(r.avertissements)
    assert "aucune fiche exploitable" not in texte
    assert "ne repaiera que ce qui manque" not in texte
    assert "repayé" in texte and "LECTURE" in texte
    assert r.porte_indecidable is True


def test_R13_miroir_enrichissement_tombe_garde_aucune_fiche_exploitable():
    r = rapport_calibration(_paires_run4(part_indie=None, redevance_estimee=None))
    assert any("aucune fiche exploitable" in a for a in r.avertissements)


def test_R13_une_morte_indecidable_ne_promet_plus_un_cache_qui_repare():
    paires = [("bonne", _scored("b", 8.0, part_indie=0.7, redevance_estimee=3.0))]
    r = rapport_calibration(paires, non_rendues=[("mot code", "morte")])
    texte = " | ".join(r.avertissements)
    assert "ne repaiera que ce qui manque" not in texte and "INDÉCIDABLE" in texte


def _sortie_cli(tmp_path, monkeypatch, capsys, rapport):
    monkeypatch.setattr(cli, "construire_rapport", lambda *a, **k: rapport)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "donnees"))
    from tests.outils_calibration import XLSX_REEL
    code = cli.main(["--xlsx", str(XLSX_REEL), "--out", str(tmp_path / "r.json"),
                     "--cache", str(tmp_path / "vide.db")])
    return code, capsys.readouterr().out


def test_R13_conseil_final_LECTURE_quand_l_editeur_est_lu_mais_pas_la_redevance(
        tmp_path, monkeypatch, capsys):
    rapport = RapportCalibration(n_requetes=31, n_calibrees=31, spearman=0.35,
                                 n_part_indie_mesuree=31, n_redevance_mesuree=0,
                                 porte_indecidable=True)
    code, out = _sortie_cli(tmp_path, monkeypatch, capsys, rapport)
    assert code == 2
    assert "LECTURE" in out and "--purger-fiches-sans-pages" in out
    assert "corriger data/lowcontent_criteres.json" not in out


def test_R13_conseil_final_COMPTE_quand_toutes_les_SERP_sont_tombees(
        tmp_path, monkeypatch, capsys):
    rapport = RapportCalibration(n_requetes=31, n_calibrees=0, n_non_mesurees=31,
                                 porte_indecidable=True)
    code, out = _sortie_cli(tmp_path, monkeypatch, capsys, rapport)
    assert code == 2
    assert "compte DataForSEO" in out
    assert "corriger data/lowcontent_criteres.json" not in out


# ══ R20 + R25 — diagnostics sans seuil ═══════════════════════════════════════════

def _distribution_reelle():
    """Répartition du plan (R20) posée sur les étiquettes réelles : 9 mortes, 15 mauvaises,
    7 bonnes. Les valeurs sous 0,5 tombent sur 1 morte et 2 mauvaises."""
    parts = {"morte": [1.0] * 8 + [0.2],
             "mauvaise": [1.0] * 11 + [0.8333, 0.8, 0.333, 0.2],
             "bonne": [1.0] * 5 + [0.8333, 0.8333]}
    etq = etiquetees_run4()
    assert {e: sum(1 for x in etq if x.etiquette == e) for e in parts} == {
        e: len(v) for e, v in parts.items()}
    ordinal = {"morte": 0, "mauvaise": 1, "bonne": 2}
    paires = []
    for i, e in enumerate(etq):
        paires.append((e.etiquette, _scored(
            e.requete, 2.0 + 2 * ordinal[e.etiquette] + i * 0.01,
            part_indie=parts[e.etiquette].pop(), redevance_estimee=2.5)))
    return paires


def test_R20_compteurs_de_bonus_part_indie_par_etiquette_sans_effet_sur_la_porte():
    paires = _distribution_reelle()
    r = rapport_calibration(paires)
    assert r.signaux["morte"]["n_bonus_part_indie"] == 8
    assert r.signaux["mauvaise"]["n_bonus_part_indie"] == 13
    assert r.signaux["bonne"]["n_bonus_part_indie"] == 7
    assert r.signaux["morte"]["part_indie_min"] == pytest.approx(0.2)
    assert r.signaux["bonne"]["part_indie_min"] == pytest.approx(0.8333)
    assert r.signaux["mauvaise"]["part_indie_max"] == pytest.approx(1.0)
    # Jeu ordonné, aucune morte en vert, rayon lu : la porte s'ouvre, diagnostics ou pas.
    assert r.porte_franchie is True and r.porte_indecidable is False


def test_R20_crit3_et_afflux_de_recents_comptes_par_etiquette():
    paires = [("morte", _scored("d", 2.0, bsr_worst=80_000, part_moins_12_mois=0.7)),
              ("morte", _scored("e", 2.1, bsr_worst=20_000, part_moins_12_mois=0.1)),
              ("bonne", _scored("b", 8.0, bsr_worst=None))]
    r = rapport_calibration(paires)
    assert r.signaux["morte"]["n_crit3"] == 1 and r.signaux["bonne"]["n_crit3"] == 0
    assert r.signaux["morte"]["n_malus_recents"] == 1


def test_R25_medianes_d_axes_par_etiquette_et_mise_en_garde_fixe():
    paires = [("morte", _scored("d", 3.0, demande=3.0, penetration=5.0)),
              ("mauvaise", _scored("m", 4.0, demande=8.0, penetration=2.0)),
              ("bonne", _scored("b", 5.0, demande=6.0, penetration=7.0,
                                part_indie=0.7, redevance_estimee=3.0))]
    sans = rapport_calibration(paires)
    assert sans.signaux["mauvaise"]["demande"] > sans.signaux["bonne"]["demande"]
    assert sans.signaux["mauvaise"]["penetration"] < sans.signaux["bonne"]["penetration"]
    assert "rentabilite" in sans.signaux["bonne"] and "faisabilite" in sans.signaux["bonne"]
    assert any("Spearman global" in a for a in sans.avertissements)
