"""Devis AVANT de lancer — pour qu'un rapport partiel ne puisse plus arriver.

Le plafond de coût par run existait déjà, et il s'arrêtait proprement. Mais s'arrêter
proprement au milieu, c'est quand même rendre un rapport tronqué à quelqu'un qui a payé
son plafond entier. Un client qui choisit « Approfondi » en fiction se sentirait floué —
et il aurait raison, puisque rien ne l'avait prévenu.

Le devis renverse la garde : on estime le PIRE cas avant de dépenser un centime, et on
refuse en amont si ça dépasse. Le plafond en cours de run reste, mais comme filet de
dernier recours (panne, tempête de retries), plus comme mode de fonctionnement nominal.

LE test qui valide tout le reste est `test_le_modele_reproduit_les_mesures_du_depot` : un
modèle de coût qui ne retombe pas sur les chiffres mesurés en live ne vaut rien, et
refuserait des runs au hasard.
"""
import pytest

from devis import PLAFOND_DEPASSE, cout_max_estime, verifier_devis, volume_maximal


# ── Le modèle colle-t-il au réel ? ─────────────────────────────────────────────

@pytest.mark.parametrize("type_,params,attendu,tolerance,source", [
    # Scout non-fiction, 6 recherches : LLM MESURÉ à 0,0383 $ (jobs.db, 2026-10-03, tarif
    # standard de Sonnet depuis le 2026-08-31) + 6 SERP + 18 fiches BSR à 0,003 $ (production).
    ("scout", {"n_search": 6}, 0.1103, 0.12, "calculé : LLM mesuré + 24 tâches"),
    # Fiction 5 trios à 12 fiches : le point MESURÉ du 2026-10-05 (jobs.db) = 0,3295 $ dont
    # 0,171 $ DataForSEO (57 appels) et 0,1585 $ LLM (31 486 jetons entrants, 4 269 sortants).
    # Tolérance plus large : le devis ne suppose AUCUNE dédup entre niches (52 fiches payées
    # sur 60 possibles), c'est le prix de la garantie « jamais de rapport partiel ».
    ("fiction", {"n_niches": 5}, 0.3295, 0.20, "MESURÉ en live"),
])
def test_le_modele_reproduit_les_mesures_du_depot(type_, params, attendu, tolerance, source,
                                                  monkeypatch):
    """Un modèle qui ne retombe pas sur les chiffres mesurés refuserait des runs au
    hasard. Le devis vise le PIRE cas, donc il doit majorer un peu — jamais sous-estimer.

    Les mesures fiction ont été prises à 12 fiches par niche ; le défaut est 10 depuis le
    2026-10-05 (décision de Baptiste). Le modèle doit les retrouver PARAMÉTRÉ à 12 : c'est ce
    qui prouve qu'il suit la réalité, et non son réglage du jour.

    Les anciens points (scout 0,084 $, fiction 0,153 $ / 0,409 $) datent du tarif
    d'introduction de Sonnet, terminé le 31/08/2026 : le LLM coûte 1,5 fois plus depuis, et
    le devis le sous-estimait d'un facteur 2,3 à 2,6 sur la fiction."""
    if type_ == "fiction":
        from devis import _MODELES
        monkeypatch.setitem(_MODELES["fiction"], "asin_par_unite", 12)
        monkeypatch.setitem(_MODELES["fiction"], "classif_par_unite", 12)
    estime = cout_max_estime(type_, params)
    assert estime == pytest.approx(attendu, rel=tolerance), f"{source} : {attendu} $"
    assert estime >= attendu * 0.95, "le devis ne doit jamais SOUS-estimer"


@pytest.mark.parametrize("type_,params,llm_mesure,source", [
    ("scout", {"n_search": 6}, 0.0383, "jobs.db 2026-10-03, 2 235 jetons entrants, 2 107 sortants"),
    ("scout", {"n_search": 3}, 0.0390, "jobs.db 2026-10-02"),
    ("lowcontent", {"n_search": 3}, 0.0564, "jobs.db 2026-10-02 (le plus cher des trois runs)"),
    ("lowcontent", {"n_search": 6}, 0.0504, "jobs.db 2026-10-03"),
    # Fiction : l'idéation seule vaut 0,0149 $ (4 runs échoués avant la classification) ;
    # le reste du run mesuré, (0,1585 − 0,0149) / 52 livres, donne 0,00276 $ par livre.
    ("fiction", {"n_niches": 5}, 0.1585, "jobs.db 2026-10-05, 52 livres classés"),
])
def test_la_part_llm_du_devis_ne_sous_estime_aucun_run_mesure(type_, params, llm_mesure, source,
                                                              monkeypatch):
    """La part LLM était une constante unique de 0,012 $ pour les trois moteurs, calée sur
    le tarif d'introduction. Mesuré : le non-fiction coûte 0,038 $ d'idéation à lui seul, le
    low-content 0,05 $. Un devis qui sous-estime laisse passer un run que le plafond de 0,60 $
    coupera en route — le rapport partiel facturé que tout ce module existe pour éviter."""
    from devis import _MODELES, ventilation_max_estimee
    if type_ == "fiction":                       # mesuré à 12 fiches, réglage du jour : 10
        monkeypatch.setitem(_MODELES["fiction"], "asin_par_unite", 12)
        monkeypatch.setitem(_MODELES["fiction"], "classif_par_unite", 12)
    llm = ventilation_max_estimee(type_, params)["llm_usd"]
    assert llm >= llm_mesure * 0.99, f"{source} : le devis annonce {llm:.4f} $ de LLM"
    assert llm <= llm_mesure * 1.6, "le devis ne doit pas non plus gonfler sans mesure"


def test_le_devis_lit_aussi_le_nom_historique_du_volume_non_fiction():
    """`POST /api/jobs` accepte `search` comme `n_search` (§5.22). Le devis ne lisait que
    `n_search` : un client envoyant `search: 20` était devisé pour 6 recherches et lancé pour
    20. Le plafond par run restait le filet, mais le devis est censé refuser AVANT."""
    assert (cout_max_estime("scout", {"search": 20})
            == cout_max_estime("scout", {"n_search": 20})
            > cout_max_estime("scout", {}))


def test_le_devis_croit_avec_le_volume():
    assert (cout_max_estime("fiction", {"n_niches": 3})
            < cout_max_estime("fiction", {"n_niches": 8})
            < cout_max_estime("fiction", {"n_niches": 15}))


def test_le_scout_non_fiction_tient_largement_sous_le_plafond():
    """Vérifié à sa borne serveur : le non-fiction n'a jamais pu produire de rapport
    partiel, et ne le doit toujours pas."""
    assert cout_max_estime("scout", {"n_search": 20}) < 0.60


def test_la_fiction_depasse_le_plafond_des_le_preset_approfondi():
    """LE scénario qui motive ce module. 8 trios, c'est le preset « Approfondi » : un
    client qui le choisit payait son plafond et recevait un rapport tronqué."""
    assert cout_max_estime("fiction", {"n_niches": 8}) < 0.60      # ça passe, de peu
    assert cout_max_estime("fiction", {"n_niches": 15}) > 0.60     # le formulaire, non


def test_un_type_inconnu_leve():
    """Deviner un modèle de coût pour un scout qu'on ne connaît pas produirait un devis
    inventé, présenté comme une garantie."""
    with pytest.raises(ValueError):
        cout_max_estime("scout_du_futur", {})


# ── Le garde ───────────────────────────────────────────────────────────────────

def test_un_run_qui_tient_passe():
    verifier_devis("scout", {"n_search": 20}, plafond=0.60)


def test_un_run_trop_gros_est_refuse_AVANT_de_depenser():
    with pytest.raises(PLAFOND_DEPASSE):
        verifier_devis("fiction", {"n_niches": 20}, plafond=0.60)


def test_le_refus_dit_le_volume_qui_TIENDRAIT():
    """« trop cher » laisse l'utilisateur deviner. Lui donner le nombre qui passe, c'est
    la seule forme de refus qui ne lui fasse pas perdre son temps."""
    with pytest.raises(PLAFOND_DEPASSE) as e:
        verifier_devis("fiction", {"n_niches": 20}, plafond=0.60)
    msg = str(e.value)
    assert str(volume_maximal("fiction", 0.60)) in msg   # le volume maximal qui tient (lu, pas figé)
    assert "20" in msg          # ce qu'il a demandé


def test_sans_plafond_rien_n_est_refuse():
    """`PLAFOND_USD_PAR_RUN` peut être desactive : le devis ne doit alors bloquer personne."""
    verifier_devis("fiction", {"n_niches": 20}, plafond=None)


def test_volume_maximal_est_le_plus_grand_qui_TIENT():
    n = volume_maximal("fiction", plafond=0.60)
    assert cout_max_estime("fiction", {"n_niches": n}) <= 0.60
    assert cout_max_estime("fiction", {"n_niches": n + 1}) > 0.60


def test_volume_maximal_ne_descend_jamais_sous_un():
    """Un plafond absurde ne doit pas rendre 0 : refuser tout run serait un service mort,
    et l'utilisateur ne comprendrait pas pourquoi."""
    assert volume_maximal("fiction", plafond=0.001) >= 1


# ── Cohérence avec les bornes du serveur ───────────────────────────────────────

def test_aucune_borne_de_volume_ne_promet_un_run_qui_serait_tronque():
    """LE test transverse. Si une borne serveur autorise un volume dont le devis dépasse
    le plafond, l'interface propose quelque chose que le serveur refusera — ou pire,
    lancera et tronquera. Les deux valeurs vivent dans deux fichiers : rien ne les tient
    ensemble à part ce test."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))
    import server
    from cost_tracker import PLAFOND_USD_PAR_RUN_DEFAUT as P

    for type_, cle, borne in (("scout", "n_search", server.MAX_RECHERCHES),
                              ("fiction", "n_niches", server.MAX_NICHES_FICTION),
                              ("lowcontent", "n_search", server.MAX_RECHERCHES_LC)):
        estime = cout_max_estime(type_, {cle: borne})
        assert estime <= P, (f"{type_} : la borne {borne} coûterait jusqu'à "
                             f"{estime:.3f} $ pour un plafond de {P} $ — l'utilisateur "
                             f"recevrait un rapport partiel")


# ── Bout en bout : le refus arrive AVANT toute dépense ─────────────────────────

def test_un_run_trop_gros_est_refuse_par_l_API_sans_creer_de_job(tmp_path, monkeypatch):
    """Le point de tout le module : l'utilisateur est prévenu AVANT de cliquer sur un run
    qui l'aurait tronqué, et aucun job n'est même créé."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))
    from tests.test_server_jobs import _client_with_isolated_dbs
    from jobs import JobStore

    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    monkeypatch.setenv("PLAFOND_USD_PAR_RUN", "0.20")

    r = client.post("/api/jobs", json={"type": "fiction", "sous_genre": "cosy_mystery",
                                       "n_niches": 10})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "plafond" in detail.lower() and "maximum" in detail.lower()
    assert "rien n" in detail.lower()          # « rien n'a été lancé »
    assert JobStore(server._JOBS_DB).list_jobs(limit=50) == []


def test_un_run_qui_tient_passe_par_l_API(tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))
    from tests.test_server_jobs import _client_with_isolated_dbs

    client, server = _client_with_isolated_dbs(monkeypatch, tmp_path)
    monkeypatch.setenv("PLAFOND_USD_PAR_RUN", "0.60")
    monkeypatch.setattr(server, "run_scout",
                        lambda seed=None, progress=None, cost=None, **kw: [])
    assert client.post("/api/jobs", json={"type": "scout", "seed": "x",
                                          "n_search": 20}).status_code == 202


def test_le_FORMULAIRE_ne_propose_jamais_un_volume_refusable():
    """Le test qui manquait, et la remarque est juste : proposer 15 trios pour les refuser
    ensuite, c'est de la friction pure. Le maximum SAISISSABLE doit tenir, pour que le
    refus du devis soit inatteignable depuis l'interface — il ne reste alors que comme
    garde contre une requête forgée ou un client tiers.

    Les bornes vivent dans TROIS endroits : le `max` du champ HTML, la constante serveur,
    et le plafond de coût. Ce test est le seul lien entre les trois."""
    import re
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))
    from cost_tracker import PLAFOND_USD_PAR_RUN_DEFAUT as P

    html = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text("utf-8")

    for champ, type_, cle in (("search", "scout", "n_search"),
                              ("fic-n", "fiction", "n_niches"),
                              ("lc-search", "lowcontent", "n_search")):
        m = re.search(rf'id="{champ}"[^>]*max="(\d+)"', html)
        assert m, f"champ #{champ} sans max explicite"
        maxi = int(m.group(1))
        estime = cout_max_estime(type_, {cle: maxi})
        assert estime <= P, (
            f"#{champ} laisse saisir {maxi}, ce qui coûterait jusqu'à {estime:.3f} $ "
            f"pour un plafond de {P} $ : l'utilisateur se ferait refuser sa saisie")


def test_les_presets_tiennent_tous_sous_le_plafond():
    """Un preset refusé serait pire qu'un champ trop permissif : l'utilisateur n'a même
    pas saisi de chiffre, il a cliqué sur un bouton que le produit lui proposait."""
    import json
    import re
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))
    from cost_tracker import PLAFOND_USD_PAR_RUN_DEFAUT as P

    html = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text("utf-8")
    presets = json.loads(re.search(r"const PRESETS\s*=\s*(\{.*?\});", html, re.S).group(1))

    for scout, cle in (("scout", "n_search"), ("fiction", "n_niches"),
                       ("lowcontent", "n_search")):
        for nom, v in presets[scout].items():
            estime = cout_max_estime(scout, {cle: v["n"]})
            assert estime <= P, (f"preset {scout}/{nom} = {v['n']} coûterait jusqu'à "
                                 f"{estime:.3f} $ (plafond {P} $)")
