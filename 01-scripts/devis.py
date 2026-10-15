"""devis.py — coût MAXIMAL d'un run, estimé AVANT de dépenser un centime.

Le plafond de coût par run existait déjà, et il s'arrêtait proprement. Mais s'arrêter
proprement au milieu, c'est quand même rendre un rapport tronqué à quelqu'un qui a payé
son plafond entier. Un client qui choisit « Approfondi » en fiction se sentirait floué —
et il aurait raison : rien ne l'avait prévenu avant qu'il clique.

Ce module renverse la garde. On estime le PIRE cas en amont et on refuse tout de suite, en
disant quel volume tiendrait. Le plafond en cours de run reste, mais comme filet de dernier
recours (panne, tempête de retries, tarif qui change chez le fournisseur) — plus comme mode
de fonctionnement nominal.

LE MODÈLE EST CALÉ SUR LES MESURES DU DÉPÔT, pas sur une intuition. Les postes LLM viennent
de `jobs.db` (tarif STANDARD de Sonnet, 3/15 $ par million de jetons, en vigueur depuis le
2026-08-31 : le tarif d'introduction, 2/10, faisait croire le LLM 1,5 fois moins cher) :

    scout NF, 6 recherches   LLM 0,0383 $ (mesuré 2026-10-03) + 24 tâches    = 0,110 $  (calculé)
    fiction 5 trios, 12 fiches   0,171 $ DataForSEO + 0,1585 $ LLM           = 0,3295 $ (mesuré 2026-10-05)
    low-content, 3 et 6 niches   LLM 0,0564 $ / 0,0504 $ (mesuré)

Avant cette correction (2026-10-05) la part LLM valait 0,012 $ pour les trois moteurs et
0,001 $ par livre classé : le devis annonçait 0,227 $ pour un run fiction de 5 trios qui en
coûtait 0,33, et laissait passer 11 trios à 0,485 $ quand ils en coûtent ~0,69 — au-delà du
plafond de 0,60 $ par run, donc le rapport partiel facturé que ce module existe pour éviter.

Un modèle qui ne reproduit pas les mesures refuserait des runs au hasard : c'est ce que
`test_le_modele_reproduit_les_mesures_du_depot` protège.

Le devis MAJORE volontairement. Il suppose zéro cache, alors qu'en pratique le cache
mutualisé sert une grande part des requêtes. C'est le prix de la garantie « jamais de
rapport partiel » : mieux vaut refuser un run qui serait finalement passé que d'en tronquer
un qui avait été promis entier.
"""
from search_providers import COST_PER_CALL_USD

# Coût d'UN appel DataForSEO en priority (le défaut). Une SERP comme un ASIN.
_TARIF = COST_PER_CALL_USD[2]

# Postes LLM, MESURÉS (jobs.db) et non devinés. Un appel d'idéation par run, dont le coût
# dépend du moteur : sa consigne, sa taxonomie et sa réponse n'ont rien de commun.
#   scout : 0,0390 $ (3 niches) et 0,0383 $ (6 niches) — 2 235 jetons entrants, 2 107 sortants
#   fiction : 0,0149 $ — quatre runs du 2026-10-05 échoués APRÈS l'idéation, avant tout rayon
#   lowcontent : 0,0564 $ (3 niches), 0,0504 $ (6) ; la part qui grandit avec n est ajoutée plus bas
_LLM_IDEATOR = {"scout": 0.039, "fiction": 0.015, "lowcontent": 0.045}
# Classification d'une quatrième de couverture : (0,1585 − 0,0149) $ / 52 livres = 0,00276 $
# (run fiction mesuré du 2026-10-05, tarif standard). Arrondi au-dessus : un devis est un pire cas.
_LLM_CLASSIF_PAR_LIVRE = 0.0028

# La réponse du classement low-content grandit avec n : UN appel, mais une niche de plus à
# rendre. Constante lue dans l'ideator (`_budget_reponse`) et tarif lu dans la grille de
# `cost_tracker` — jamais recopiés : deux copies divergent. Tarif de sortie le plus ÉLEVÉ
# des deux (intro / standard) : un devis est un pire cas.
from cost_tracker import _LLM_PRICES
from lowcontent_ideator import DEFAULT_MODEL as _MODELE_LC, _JETONS_PAR_NICHE

_PRIX_LC = _LLM_PRICES.get(_MODELE_LC) or _LLM_PRICES["claude-sonnet-5"]
_SORTIE_USD_PAR_JETON = max(_PRIX_LC["out"], _PRIX_LC.get("out_std", _PRIX_LC["out"])) / 1e6

# Ce que chaque scout consomme par unité de volume. Ces constantes DOIVENT suivre les
# orchestrateurs : `n_bsr_per_niche` (scout_master), `n_top` (fiction_master) et
# `n_enrich_per_niche` (lowcontent_master).
_MODELES = {
    "scout": {
        "cle": "n_search", "defaut": 6,
        "alias": "search",            # nom historique, accepté par POST /api/jobs (§5.22)
        "asin_par_unite": 3,          # scout_master.n_bsr_per_niche
        "classif_par_unite": 0,       # pas de lecture de quatrièmes en non-fiction
    },
    "fiction": {
        "cle": "n_niches", "defaut": 8,
        "asin_par_unite": 10,         # fiction_serp_provider.n_top (tests/test_reglage_10_fiches_30_jours.py)
        "classif_par_unite": 10,      # une classification par livre du rayon
    },
    "lowcontent": {
        "cle": "n_search", "defaut": 6,
        "asin_par_unite": 6,          # lowcontent_master.n_enrich_per_niche
        "classif_par_unite": 0,       # le LLM classe des REQUÊTES, pas des livres
        "jetons_sortie_par_unite": _JETONS_PAR_NICHE,   # une niche de plus à rendre
    },
}


class PLAFOND_DEPASSE(ValueError):
    """Le run coûterait plus que le plafond. Levée AVANT toute dépense.

    Porte le volume qui tiendrait : « trop cher » laisserait l'utilisateur deviner, et
    c'est la seule forme de refus qui ne lui fasse pas perdre son temps."""


def _volume(type_: str, params: dict) -> tuple[dict, int]:
    modele = _MODELES.get(type_)
    if modele is None:
        # Deviner un modèle de coût pour un scout inconnu produirait un devis INVENTÉ,
        # présenté à l'utilisateur comme une garantie.
        raise ValueError(f"aucun modèle de coût pour le type « {type_} » "
                         f"(connus : {sorted(_MODELES)})")
    params = params or {}
    brut = params.get(modele["cle"], params.get(modele.get("alias"), modele["defaut"]))
    try:
        n = int(brut)
    except (TypeError, ValueError):
        n = modele["defaut"]
    return modele, max(1, n)


def ventilation_max_estimee(type_: str, params: dict | None = None) -> dict:
    """Les postes du devis, séparés. La CLI de calibration y lit le poste LLM au lieu de
    le recopier : elle remplace SERP et fiches par ce que le cache lui dit réellement."""
    modele, n = _volume(type_, params or {})
    n_asin = n * modele["asin_par_unite"]
    n_classif = n * modele["classif_par_unite"]
    ideator = _LLM_IDEATOR[type_]
    llm = (ideator                        # un seul appel d'idéation par run
           + n_classif * _LLM_CLASSIF_PAR_LIVRE
           + n * modele.get("jetons_sortie_par_unite", 0) * _SORTIE_USD_PAR_JETON)
    return {"n": n, "n_asin": n_asin, "serp_usd": n * _TARIF,
            "asin_usd": n_asin * _TARIF, "llm_usd": llm,
            "_classif": n_classif, "_jetons": n * modele.get("jetons_sortie_par_unite", 0)}


def cout_max_estime(type_: str, params: dict | None = None) -> float:
    """Coût maximal en dollars, cache supposé VIDE.

    Suppose aussi `BSR_SOURCE=dataforseo`, c'est-à-dire la configuration de production :
    en local le scraping est gratuit et le run coûte moins, mais un devis calé sur le
    poste de Baptiste ne protégerait personne en production."""
    v = ventilation_max_estimee(type_, params)
    return round(
        v["serp_usd"]                     # une SERP par niche
        + v["asin_usd"]                   # les fiches ASIN (BSR, éditeur, prix, pages)
        + _LLM_IDEATOR[type_]             # un seul appel d'idéation par run
        + v["_classif"] * _LLM_CLASSIF_PAR_LIVRE
        + v["_jetons"] * _SORTIE_USD_PAR_JETON,
        4)


def volume_maximal(type_: str, plafond: float) -> int:
    """Le plus grand volume dont le devis tient sous `plafond`.

    Ne descend jamais sous 1 : refuser tout run serait un service mort, et l'utilisateur
    ne comprendrait pas pourquoi. Si même une unité dépasse, c'est le PLAFOND qu'il faut
    relever, et le message doit le dire plutôt que d'annoncer « maximum : 0 »."""
    modele, _ = _volume(type_, {})
    n = 1
    while cout_max_estime(type_, {modele["cle"]: n + 1}) <= plafond:
        n += 1
        if n > 10_000:                    # garde-fou : jamais de boucle infinie
            break
    return n


def verifier_devis(type_: str, params: dict | None = None,
                   plafond: float | None = None) -> float:
    """Lève `PLAFOND_DEPASSE` si le run ne peut pas tenir. Rend le devis sinon.

    `plafond=None` (plafond désactivé) ne bloque personne : le devis reste informatif."""
    estime = cout_max_estime(type_, params or {})
    if plafond is None or estime <= plafond:
        return estime
    modele, demande = _volume(type_, params or {})
    maxi = volume_maximal(type_, plafond)
    raise PLAFOND_DEPASSE(
        f"cette analyse peut coûter jusqu'à {estime:.2f} $, au-delà de votre plafond de "
        f"{plafond:.2f} $ par analyse. Vous avez demandé {demande} ; le maximum qui tient "
        f"est {maxi}. Rien n'a été lancé, et rien n'a été dépensé.")
