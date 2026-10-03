"""Ce que la PROGRESSION montre aux utilisateurs : jamais le mécanisme de mutualisation.

Décision de Baptiste (2026-10-03, capture d'une analyse en cours) : « j'ai pas envie que les
utilisateurs sachent qu'on utilise un cache ». Des lignes comme « 0/19 fiche(s) servie(s) par
le cache, 19 à relire chez Amazon » ou « (0 économisé(s) par dédup inter-niches) » disent
comment le produit est construit — et donc comment il gagne sa marge.

Le filtre vit à la FRONTIÈRE client (lecture d'un travail, flux SSE), pas dans les moteurs :
- le brut reste dans `jobs.db` et dans la CLI. C'est un diagnostic utile : après un correctif de
  parseur, la ligne « N/M fiche(s) servie(s) par le cache » est l'alerte qui dit que des fiches
  mal lues sont resservies (CLAUDE.md §5.38) ;
- ça couvre aussi les travaux déjà enregistrés avant ce filtre.

Les avertissements qui concernent le RÉSULTAT (compte refusé, niche écartée, rayon amputé)
restent : seule la mention du cache est retirée de leur phrase.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from progression_publique import liste_publique, message_public  # noqa: E402


# ── Les messages réels des moteurs (copiés des sources) ──────────────────────────────

@pytest.mark.parametrize("msg", [
    "0/19 fiche(s) servie(s) par le cache, 19 à relire chez Amazon.",
    "4/6 recherche(s) Amazon servie(s) par le cache — non relue(s).",
    "Classement repris du cache (0 appel) : mêmes requêtes, même modèle, même consigne.",
    "12 quatrième(s) de couverture déjà classée(s) — non repayée(s).",
    "  ⚠ SERP non mise en cache (disque plein).",
    "  ⚠ classement non mis en cache (OperationalError).",
    "⚠ 3/19 fiche(s) lue(s) mais non écrite(s) en cache (écriture refusée) — utilisées pour ce run, à relire au prochain.",
])
def test_ces_lignes_n_atteignent_jamais_l_utilisateur(msg):
    assert message_public(msg) is None


@pytest.mark.parametrize("avant,apres", [
    ("Enrichissement de 19 ASIN uniques en UN seul batch (0 économisé(s) par dédup inter-niches, sur 19 demandés)…",
     "Enrichissement de 19 fiches livres en un seul lot…"),
    ("Enrichissement de 40 ASIN uniques en UN seul batch (6 économisé(s) par dédup inter-niches)…",
     "Enrichissement de 40 fiches livres en un seul lot…"),
    ("  ⚠ compte refusé — plus aucun appel au fournisseur, cache seul.",
     "  ⚠ Service de données indisponible : les niches restantes ne seront pas mesurées."),
    ("⚠ 4 ASIN non enrichis : compte DataForSEO refusé — ni envoyés, ni facturés (15 servi(s) par le cache).",
     "⚠ 4 fiche(s) non lue(s) : accès au service de données refusé."),
    ("⚠ plafond de coût atteint : 9 ASIN non envoyés, ni facturés, ni enrichis (10 servi(s) par le cache).",
     "⚠ Limite de l'analyse atteinte : 9 fiche(s) non lue(s)."),
    ("⚠ 2 sonde(s) en panne sur 31 — traîne partielle, rien n'a été mis en cache pour elles.",
     "⚠ 2 sonde(s) en panne sur 31 — traîne partielle."),
])
def test_la_mention_du_cache_est_retiree_la_phrase_reste(avant, apres):
    """Un avertissement sur le RÉSULTAT ne disparaît pas : seule la mention du mécanisme part."""
    assert message_public(avant) == apres


@pytest.mark.parametrize("msg", [
    "Génération de niches par l'IA (graine : animaux)…",
    "[2/6] Concurrence Amazon « deuil animal »…",
    "⚠ La réponse est incomplète : relancez l'analyse.",
    "Scout terminé (6 recherches Amazon).",
])
def test_les_autres_messages_passent_tels_quels(msg):
    assert message_public(msg) == msg


def test_aucune_sortie_publique_ne_contient_le_mot_cache():
    brut = ["0/19 fiche(s) servie(s) par le cache, 19 à relire chez Amazon.",
            "Enrichissement de 19 ASIN uniques en UN seul batch (0 économisé(s) par dédup inter-niches)…",
            "  ⚠ x — plus aucun appel au fournisseur, cache seul.",
            "⚠ 4 ASIN : ni facturés (15 servi(s) par le cache)."]
    for ligne in liste_publique(brut):
        assert "cache" not in ligne.lower() and "dédup" not in ligne.lower()


def test_liste_publique_garde_l_ordre_et_ne_modifie_pas_l_original():
    brut = ["a", "0/3 fiche(s) servie(s) par le cache, 3 à relire chez Amazon.", "b"]
    copie = list(brut)
    assert liste_publique(brut) == ["a", "b"]
    assert brut == copie


def test_un_message_non_texte_ne_fait_pas_planter_le_filtre():
    assert liste_publique([None, 3, "ok"]) == ["ok"]


# ── La frontière : API et flux SSE ───────────────────────────────────────────────────

_BRUT = ["Génération de niches par l'IA (graine : animaux)…",
         "0/19 fiche(s) servie(s) par le cache, 19 à relire chez Amazon.",
         "Enrichissement de 19 ASIN uniques en UN seul batch (0 économisé(s) par dédup inter-niches)…",
         "  ⚠ search échec (timeout) — niche scorée sans concurrence."]


def _client(monkeypatch, tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    from jobs import JobStore
    from tests.conftest import isoler_bases, ouvrir_session
    isoler_bases(monkeypatch, server, tmp_path)
    c = TestClient(server.app, raise_server_exceptions=False)
    uid = ouvrir_session(c)
    s = JobStore(server._JOBS_DB)
    jid = s.create("scout", {}, user_id=uid)
    for m in _BRUT:
        s.append_progress(jid, m)
    s.finish(jid, [], {})
    return c, server, jid, s


def test_la_lecture_d_un_travail_ne_montre_pas_le_cache(monkeypatch, tmp_path):
    c, server, jid, _ = _client(monkeypatch, tmp_path)
    prog = c.get(f"/api/jobs/{jid}").json()["progression"]
    assert len(prog) == 3 and not any("cache" in m.lower() or "dédup" in m.lower() for m in prog)
    assert any("recherche indisponible" in m for m in prog), "l avertissement sur le résultat reste"


def test_la_liste_des_travaux_ne_montre_pas_le_cache(monkeypatch, tmp_path):
    c, server, jid, _ = _client(monkeypatch, tmp_path)
    prog = c.get("/api/jobs").json()[0]["progression"]
    assert not any("cache" in m.lower() for m in prog)


def test_le_flux_sse_ne_montre_pas_le_cache(monkeypatch, tmp_path):
    c, server, jid, _ = _client(monkeypatch, tmp_path)
    corps = c.get(f"/api/jobs/{jid}/stream").text
    assert "servie(s) par le cache" not in corps and "dédup" not in corps
    assert "Génération de niches" in corps and "recherche indisponible" in corps


def test_le_brut_reste_en_base_pour_le_diagnostic(monkeypatch, tmp_path):
    """Le filtre est à la LECTURE : la ligne qui alerte après un correctif de parseur
    (§5.38) reste lisible pour qui ouvre jobs.db."""
    c, server, jid, s = _client(monkeypatch, tmp_path)
    assert any("servie(s) par le cache" in m for m in s.get(jid).progression)


# ═══ Fournisseurs et jargon : « il faut les masquer » (Baptiste, 2026-10-03) ════════════
#
# L'utilisateur n'a pas à lire « DataForSEO », « SERP », « ASIN », « batch », « task_post »,
# « max_tokens » ni la raison brute d'un refus du fournisseur (R30 du CLAUDE.md : « la
# progression cliente recopie encore le motif brut du fournisseur : à filtrer à la frontière
# client avant l'ouverture des inscriptions »). Même frontière que le cache : à la LECTURE.

from progression_publique import texte_public  # noqa: E402


@pytest.mark.parametrize("avant,apres", [
    ("  ⚠ BSR non récupérés : compte DataForSEO refusé.",
     "  ⚠ BSR non récupérés : accès au service de données refusé."),
    ("⚠ 3 niche(s) non mesurée(s) : compte DataForSEO refusé (40104 Please verify your account).",
     "⚠ 3 niche(s) non mesurée(s) : service de données indisponible."),
    ("[2/5] SERP « cosy mystery montagne »…", "[2/5] Recherche « cosy mystery montagne »…"),
    ("  ⚠ échec SERP sur « romance » : ReadTimeout — niche écartée, rayons déjà payés conservés.",
     "  ⚠ recherche impossible sur « romance » : niche écartée."),
    ("Enrichissement de 19 ASIN uniques en UN seul batch…",
     "Enrichissement de 19 fiches livres en un seul lot…"),
    ("  ⚠ search échec (ReadTimeout: HTTPSConnectionPool(host='api.dataforseo.com')) — niche scorée sans concurrence.",
     "  ⚠ recherche indisponible — niche scorée sans concurrence."),
    ("  ⚠ task_post refusé : 40104 Please verify your account — plus aucun appel au fournisseur.",
     "  ⚠ Service de données indisponible : les niches restantes ne seront pas mesurées."),
    ("⚠ 12 ASIN non envoyés : lot refusé à l'envoi (HTTP 503) — ni facturés, ni enrichis.",
     "⚠ 12 fiche(s) non demandée(s) : le service de données a refusé la demande."),
    ("⚠ 8 ASIN non relus : l'envoi du lot a levé (ReadTimeout) — peut-être facturés côté fournisseur, imputés au pire cas.",
     "⚠ 8 fiche(s) non lue(s) : le service de données n'a pas répondu."),
    ("⚠ 3 relecture(s) de résultat illisible(s) pendant le poll (JSONDecodeError×3) — tâches relues au cycle suivant, lot complet.",
     "⚠ Certaines lectures ont dû être relancées automatiquement."),
    ("  ⚠ plafond de coût atteint — BSR non récupérés, niches scorées sans classement.",
     "  ⚠ Classements de vente non récupérés : limite de l'analyse atteinte, niches notées sans classement."),
    ("⚠ réponse tronquée (max_tokens) : le modèle n'a pas pu rendre toutes les niches demandées (31). Celles qui manquent n'ont été écartées par AUCUN filtre — relancer avec moins de requêtes.",
     "⚠ réponse de l'IA coupée : l'IA n'a pas pu rendre toutes les niches demandées (31). Celles qui manquent n'ont été écartées par AUCUN filtre — relancer avec moins de requêtes."),
])
def test_les_fournisseurs_et_le_jargon_sont_masques_la_phrase_reste(avant, apres):
    assert message_public(avant) == apres


_INTERDITS = ("dataforseo", "serp", "asin", "batch", "task_post", "payload", "http", "max_tokens",
              "fournisseur", "poll", "anthropic", "token")


def _messages_des_moteurs():
    """Tous les messages `progress(...)` écrits dans les moteurs, lus dans leur SOURCE : un
    message ajouté demain est testé sans qu'on ait à y penser."""
    import re
    racine = Path(__file__).resolve().parent.parent / "01-scripts"
    out = []
    for f in ("scout_master.py", "fiction_master.py", "lowcontent_master.py", "fiction_serp_provider.py",
              "lowcontent_ideator.py", "autocomplete_expand.py", "fiction_classifier.py",
              "bsr_source.py", "search_providers.py"):
        src = (racine / f).read_text(encoding="utf-8")
        for m in re.finditer(r"progress\(", src):
            i, prof = m.end(), 1
            j = i
            while j < len(src) and prof:
                prof += {"(": 1, ")": -1}.get(src[j], 0)
                j += 1
            appel = src[i:j - 1]
            morceaux = re.findall(r'f?"((?:[^"\\]|\\.)*)"', appel)
            if morceaux:
                texte = re.sub(r"\{[^}]*\}", "x", "".join(morceaux))
                out.append(texte)
    return out


def test_le_corpus_des_messages_moteurs_est_bien_lu():
    msgs = _messages_des_moteurs()
    assert len(msgs) > 40 and any("SERP" in m for m in msgs) and any("DataForSEO" in m for m in msgs)


def test_aucun_message_des_moteurs_ne_laisse_passer_un_fournisseur_ou_du_jargon():
    fautes = []
    for brut in _messages_des_moteurs():
        pub = message_public(brut)
        if pub is None:
            continue
        for mot in _INTERDITS:
            if mot in pub.lower():
                fautes.append((mot, brut[:80], pub[:80]))
    assert not fautes, fautes


def test_une_url_ou_un_identifiant_n_atteint_jamais_le_client():
    pub = message_public("⚠ échec https://user:secret@api.dataforseo.com/v3/x : boom")
    assert pub is not None and "http" not in pub and "secret" not in pub and "dataforseo" not in pub.lower()


def test_texte_public_assainit_aussi_les_erreurs_d_un_travail():
    """`erreur` d'un job est lue par l'API et le flux SSE : même frontière, même filtre."""
    assert "dataforseo" not in texte_public("compte DataForSEO refusé").lower()
    assert texte_public(None) is None
    assert texte_public("Erreur interne (ref ab12cd34)") == "Erreur interne (ref ab12cd34)"
    assert texte_public("Analyse interrompue (redémarrage du service).") == "Analyse interrompue (redémarrage du service)."


def test_l_erreur_d_un_travail_est_assainie_a_la_lecture_et_dans_le_flux(monkeypatch, tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import server
    from jobs import JobStore
    from tests.conftest import isoler_bases, ouvrir_session
    isoler_bases(monkeypatch, server, tmp_path)
    c = TestClient(server.app, raise_server_exceptions=False)
    uid = ouvrir_session(c)
    s = JobStore(server._JOBS_DB)
    jid = s.create("scout", {}, user_id=uid)
    s.fail(jid, "task_post refusé : compte DataForSEO non vérifié (40104)")
    assert "dataforseo" not in c.get(f"/api/jobs/{jid}").json()["erreur"].lower()
    assert "dataforseo" not in c.get(f"/api/jobs/{jid}/stream").text.lower()
    assert "dataforseo" not in str(c.get("/api/jobs").json()).lower()


def test_les_codes_de_livres_du_classifieur_ne_sortent_pas_sur_l_ecran():
    """Le moteur garde les identifiants dans son message (diagnostic, CLI) ; l'utilisateur lit
    une phrase sans codes."""
    brut = "⚠ 1/20 livres à la réponse illisible (champ hors schéma), écartés : ['B0ABC12345']"
    assert message_public(brut) == "⚠ 1/20 livres non classés : la réponse de l'IA les concernant était illisible."
