"""server.py — backend FastAPI de l'UI IA-Niches.
Sert la page unique et expose les deux scouts par des TRAVAUX asynchrones
(POST /api/jobs, puis flux reconnectable sur /api/jobs/{id}/stream).

Il a existé un second chemin, en flux direct (GET /api/scout, GET /api/fiction), qui
streamait le run dans la connexion HTTP. Il a été RETIRÉ : deux chemins pour le même
travail, dont un seul exercé par l'interface, c'est une dette — le chemin non emprunté
dérive sans que personne s'en aperçoive. C'est exactement ce qui est arrivé aux
contraintes de composition fiction, présentes sur le flux direct et absentes du chemin
asynchrone. Ne pas le réintroduire : sa file de progression mourait avec la requête,
donc fermer l'onglet perdait un run de 15 minutes.

Lancer :  uvicorn server:app --reload   (depuis le dossier web/)
   ou     python web/server.py
"""
import json
import logging
import os
from contextlib import asynccontextmanager
import sys
import tempfile
import threading
import asyncio
import time
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse

# rend le moteur (01-scripts) importable + charge les secrets quel que soit le cwd
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "01-scripts"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(_ROOT / ".env")
from scout_master import run_scout  # noqa: E402
from fiction_master import run_fiction_scout  # noqa: E402
from lowcontent_master import run_lowcontent_scout  # noqa: E402
from lowcontent_taxonomy import (load_taxonomy as load_taxonomy_lc,  # noqa: E402
                                 valid_formats as valid_formats_lc)
from niche_verdict import generate_verdict  # noqa: E402
from fiction_verdict import generate_fiction_verdict, raison_non_mesure  # noqa: E402
from lowcontent_verdict import generate_lowcontent_verdict  # noqa: E402
from kdp_keywords import generer_mots_cles  # noqa: E402
from fiction_scoring import NON_CONCLUANTES, relire_resultat_fiction  # noqa: E402
from fiction_taxonomy import load_taxonomy, valid_keys  # noqa: E402
from fiction_ideator import ContraintesTrio  # noqa: E402
import storage  # noqa: E402
from cost_tracker import CostTracker  # noqa: E402
import search_providers as _sp  # noqa: E402
from devis import PLAFOND_DEPASSE, ventilation_max_estimee, verifier_devis  # noqa: E402
from notification import notifier_fin_de_job
from models import FictionNicheReport, LowContentScored, ScoredNiche  # noqa: E402
from positioning_pdf import build_positioning_pdf  # noqa: E402
from dossier_pdf import build_dossier_pdf  # noqa: E402
from categories import suggerer_categories  # noqa: E402
from jobs import JobStore, recuperer_orphelins  # noqa: E402
from progression_publique import liste_publique, texte_public  # noqa: E402
from annulation import Annulation, controle_du_travail  # noqa: E402
import annulation as _annulation  # noqa: E402
from usage import PlafondAtteint, UsageMeter  # noqa: E402
from history import NicheHistory  # noqa: E402
from auth import (EmailDejaPris, EmailInvalide, IdentifiantsInvalides,  # noqa: E402
                  MAX_INSCRIPTIONS_PAR_CLIENT,
                  MotDePasseFaible, SESSION_TTL_S, TropDeTentatives, UserStore)

@asynccontextmanager
async def _cycle_de_vie(app: FastAPI):
    """Ce qui tourne au démarrage du service, et rien à l'arrêt.

    Le démarrage est le seul moment où l'on SAIT qu'un redémarrage vient d'avoir lieu —
    et sur un hébergeur, un redémarrage arrive à chaque déploiement.

    `lifespan` et non `@app.on_event("startup")`, qui est déprécié : une API sur le départ
    finit par ne plus se déclencher du tout, et un hook qui ne se déclenche plus est
    exactement la panne muette que ce code existe pour empêcher.

    Limite connue et assumée : un run coupé moins de 30 minutes avant le redémarrage n'est
    pas encore un orphelin (c'est l'absence de progression qui le définit, pas l'âge — un
    run fiction VIVANT dure 15 minutes) et attendra le redémarrage suivant. Un balayage
    périodique le rattraperait ; il n'existe pas, et c'est un manque, pas une décision."""
    _recuperer_travaux_interrompus()
    yield


app = FastAPI(title="IA-Niches", lifespan=_cycle_de_vie)
_HERE = Path(__file__).resolve().parent

# Chemins des magasins asynchrones (plan SaaS S2/S3). De simples constantes Path : la
# construction du JobStore/UsageMeter (et donc la création du fichier) est différée à
# l'intérieur de chaque endpoint — jamais à l'import du module, sinon importer server.py
# en test écrirait déjà des fichiers réels dans le dépôt (cf. cache.py, même principe :
# connexion/instance par appel, jamais une instance partagée figée à l'import).
# Le RÉPERTOIRE, lui, vient de `storage` : en hébergement il doit pointer un volume
# persistant, et un seul chemin resté en dur suffirait à faire repartir une base sur le
# disque éphémère du conteneur pendant que les autres suivent le volume. `storage.base()`
# est appelé ici, à l'import : sous APP_ENV=prod sans DATA_DIR il LÈVE, donc le serveur
# refuse de démarrer plutôt que de perdre les comptes au déploiement suivant — même
# posture que `_verifier_config_prod`, appelé lui aussi à l'import.
_JOBS_DB = storage.base("jobs.db")
_USAGE_DB = storage.base("usage.db")
_HISTORY_DB = storage.base("history.db")
_USERS_DB = storage.base("comptes.db")

# Plafond de runs SIMULTANES en mode thread. Sans lui, le serveur lancait un fil par job
# sans aucune limite : dix utilisateurs, c'etait dix runs DataForSEO de front et autant
# d'ecrivains SQLite concurrents. Le job attend son creneau en restant "en_attente" --
# le marquer "en cours" avant de demarrer montrerait a l'utilisateur une analyse commencee
# qui ne progresse pas, sans lui dire si elle est bloquee ou seulement lente.
RUNS_SIMULTANES_DEFAUT = 5
_CRENEAUX: dict[int, threading.Semaphore] = {}
_CRENEAUX_VERROU = threading.Lock()


def _creneaux() -> threading.Semaphore:
    """Un semaphore par valeur de limite, cree a la demande. La limite est lue a chaque
    appel (jamais figee a l'import) pour rester testable et modifiable sans redemarrage."""
    try:
        n = int(os.getenv("RUNS_SIMULTANES_MAX", "") or RUNS_SIMULTANES_DEFAUT)
    except ValueError:
        n = RUNS_SIMULTANES_DEFAUT
    n = max(1, n)
    with _CRENEAUX_VERROU:
        if n not in _CRENEAUX:
            _CRENEAUX[n] = threading.Semaphore(n)
        return _CRENEAUX[n]


def _plafond_usd_par_run() -> float | None:
    """Le plafond de cout par run, lu a CHAQUE appel (jamais fige a l'import : il doit
    pouvoir changer sans redemarrage, et rester testable)."""
    from cost_tracker import _plafond_par_defaut
    return _plafond_par_defaut()


def _mode_jobs() -> str:
    """"thread" (defaut) = le serveur execute lui-meme ; "worker" = il se contente
    d'empiler, un processus worker prendra le relais.

    Le DEFAUT reste "thread" : sur le poste de Baptiste il n'y a pas de second processus,
    et exiger d'en lancer un casserait l'usage local du jour au lendemain. Lu a CHAQUE
    appel et non a l'import : une constante figee a l'import rendrait la variable
    intestable et surtout non modifiable sans redemarrage."""
    return "worker" if (os.getenv("JOBS_MODE") or "").strip().lower() == "worker" else "thread"


COOKIE_SESSION = "ia_niches_session"

# Bornes des paramètres de volume. Le plafond mensuel compte des ANALYSES, pas des
# appels payants : sans ces bornes, une seule « analyse » avec search=9999 déclenche des
# milliers de requêtes DataForSEO tout en ne consommant qu'une unité du plafond. Borner
# le volume est donc la seule protection réelle du MONTANT (revue de sécurité 2026-08-03).
# Le nombre d'IDÉES est fixé, pas offert au réglage : c'est le nombre de RECHERCHES qui
# décide de la facture (~0,003 $ par niche, plus le lot BSR), pas celui d'idées.
#
# Fixé à 10 sur MESURE, pas sur intuition (30 niches sur « bien-être », 2026-08-03) :
#   vivier 10 -> top-4 demand_score [19, 12, 11, 11]
#   vivier 20 -> top-4 demand_score [19, 15, 12, 12]
#   vivier 30 -> top-4 demand_score [19, 15, 13, 12]
# Dans les TROIS cas, les 4 niches retenues sont déjà toutes au-dessus du plafond du
# scoring (`min(demand_score, 10)`, scoring.py) : élargir le vivier change QUELLES niches
# sont testées, jamais leur note sur l'axe demande. Gain mesuré : nul.
# Le coût, lui, est réel : 0,0459 $ mesuré pour 30 niches, soit ~0,0015 $ par niche — la
# sortie du LLM croît avec n. Passer de 10 à 20 coûterait ~+0,015 $ par run, autant que
# toute la phase DataForSEO d'un run à 4 recherches, pour rien.
# Ce réglage sera à revoir SI le plafond de `min(demand_score, 10)` est relevé : c'est lui
# qui rend le classement aveugle au-delà de 10 suggestions, pas la taille du vivier.
IDEES_PAR_RUN = 10
MAX_IDEES = 30
MAX_RECHERCHES = 20
# 11 et non 20 : c'est le plus grand nombre de trios dont le devis (devis.py) tient sous
# PLAFOND_USD_PAR_RUN. Au-dela, le run atteindrait le plafond en cours de route et rendrait
# un rapport PARTIEL a quelqu'un qui a paye son plafond entier -- ce qui se lit comme une
# arnaque, pas comme une protection. La fiction est le seul scout concerne : elle paie
# 12 ASIN ET une classification de quatrieme de couverture PAR NICHE.
# test_devis.py tient cette borne et le plafond ensemble ; ne pas la relever sans relever
# le plafond, sinon la promesse "jamais de rapport partiel" tombe en silence.
MAX_NICHES_FICTION = 11
# Meme borne que le non-fiction : le poste qui coute est le nombre de niches
# CONFRONTEES a Amazon, pas le nombre de requetes lues dans l'arbre (gratuit).
MAX_RECHERCHES_LC = 20
# La graine part dans un prompt LLM. 80 caracteres couvrent largement un theme reel ;
# au-dela ce n'est plus une graine, c'est une charge utile (meme garde que A5).
MAX_LONGUEUR_GRAINE = 80


# Limiteur de debit sur les endpoints payants A LA PIECE (/api/verdict,
# /api/kdp-keywords, /api/dossier avec mots-cles). Ils imputent n_analyses=0 -- et c'est
# juste, ils COMPLETENT une analyse deja comptee -- mais la consequence est qu'ils sont
# INATTEIGNABLES par le plafond mensuel : 200 verdicts coutent 5,60 $ sans qu'aucun garde
# ne bronche.
#
# C'EST UN GARDE-FOU, PAS UNE GRILLE TARIFAIRE, exactement comme PLAFOND_ANALYSES_MENSUEL
# dont le docstring dit deja « garde-fou contre l'utilisateur a 500 analyses, pas une
# grille tarifaire ». Il n'engage AUCUNE decision commerciale : quand le modele
# d'abonnement existera, il le remplacera ou le laissera comme filet.
#
# Le defaut est ANCRE, pas invente : une analyse rend jusqu'a MAX_RECHERCHES niches, et un
# utilisateur peut legitimement vouloir un verdict sur chacune. Deux analyses entieres
# decortiquees d'affilee, c'est 40 appels. Au-dela dans la MEME heure, ce n'est plus
# quelqu'un qui lit des resultats.
TYPES_A_LA_PIECE = ("verdict", "kdp", "kdp_keywords", "dossier")
DEBIT_FENETRE_S = 3600
DEBIT_APPELS_MAX_DEFAUT = 2 * MAX_RECHERCHES


def _debit_max() -> int:
    """Lu a chaque appel. 0 desactive explicitement ; une valeur illisible retombe sur le
    defaut plutot que d'ouvrir la vanne en silence."""
    try:
        return int(os.getenv("DEBIT_APPELS_MAX", "") or DEBIT_APPELS_MAX_DEFAUT)
    except ValueError:
        return DEBIT_APPELS_MAX_DEFAUT


def _reserver_appel(user_id: str, type_: str) -> int:
    """Verifie le debit PUIS reserve, en une seule porte d'entree pour les trois endpoints.

    429 et non 400 : ce n'est pas la requete qui est fautive, c'est le rythme. Distinguer
    les deux permet a l'utilisateur de comprendre qu'il lui suffit d'attendre.

    Un appel REFUSE ne reserve rien : sinon un client qui insiste se verrouillerait
    lui-meme de plus en plus longtemps, ce qui punirait l'impatience plutot que l'abus."""
    maxi = _debit_max()
    m = UsageMeter(_USAGE_DB)
    if maxi > 0 and m.compter(user_id, TYPES_A_LA_PIECE, DEBIT_FENETRE_S) >= maxi:
        raise HTTPException(
            status_code=429,
            detail=f"trop d'analyses a la piece en une heure ({maxi} maximum). Ce n'est "
                   f"pas votre demande qui pose probleme, c'est le rythme : attendez "
                   f"quelques minutes et reessayez. Rien n'a ete depense.")
    return m.reserver(user_id, type_)



def _plafond_analyses_mensuel() -> int | None:
    """Plafond mensuel glissant PAR utilisateur — garde-fou contre la queue de distribution
    (l'utilisateur à 500 analyses), pas une grille tarifaire. Défaut prudent : pas de
    plafond configuré -> illimité (mais journalisé, cf. usage.py)."""
    raw = os.getenv("PLAFOND_ANALYSES_MENSUEL")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _cookie_securise(request: Request) -> bool:
    """`Secure` interdit au navigateur d'envoyer le cookie en clair sur HTTP.

    DÉDUIT du protocole, et non lu dans un réglage. C'était auparavant une variable à 0 par
    défaut, documentée « à passer à 1 au déploiement » : autant dire un jeton de 30 jours
    diffusé en clair le jour où quelqu'un oublie de la lire. Ce qui s'oublie doit se
    déduire — et le protocole est connu à chaque requête.

    `X-Forwarded-Proto` est consulté parce qu'un serveur derrière un proxy TLS voit du HTTP
    en interne alors que le navigateur, lui, parle en HTTPS. `COOKIE_SECURE=1` reste
    disponible pour FORCER le drapeau derrière un proxy qui n'annonce rien ; il ne peut plus
    le désactiver."""
    if os.getenv("COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes", "oui"):
        return True
    protocole = (request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
                 or request.url.scheme)
    return protocole.lower() == "https"


def _poser_session(request: Request, reponse: Response, jeton: str) -> None:
    """httponly : hors de portée de tout JavaScript, donc involable par injection de script.
    samesite=lax : le cookie ne part pas sur une requête POST venue d'un autre site, ce qui
    ferme la falsification de requête (CSRF) sans avoir à gérer un jeton anti-CSRF séparé."""
    reponse.set_cookie(COOKIE_SESSION, jeton, max_age=int(SESSION_TTL_S), httponly=True,
                       samesite="lax", secure=_cookie_securise(request), path="/")


def _borner(nom: str, valeur: int, maxi: int) -> int:
    """Refuse plutôt que de rogner en silence : un utilisateur qui demande 9999 doit
    savoir qu'il ne l'aura pas, sinon il croira avoir payé pour 9999."""
    if not isinstance(valeur, int) or valeur < 1 or valeur > maxi:
        raise HTTPException(
            status_code=400,
            detail=f"{nom} doit être un entier entre 1 et {maxi} (reçu : {valeur})")
    return valeur


def origine_sure(request: Request) -> None:
    """Refuse les requêtes déclenchées depuis un AUTRE site.

    Le lancement d'un run dépense de l'argent réel. SameSite=Lax laisse partir le cookie
    sur une navigation de premier niveau : sans ce garde, une page malveillante pourrait
    déclencher un run facturé sur le compte de la victime. Le cookie seul ne suffit pas.
    (Le risque était plus direct encore du temps des endpoints de flux direct, qui étaient
    des GET : une simple balise <img> suffisait.)

    On s'appuie sur `Sec-Fetch-Site`, envoyé par tous les navigateurs actuels et NON
    falsifiable par une page (c'est un en-tête interdit au script). Absent = client hors
    navigateur (curl, tests) : on laisse passer, car un client hors navigateur ne subit
    pas de CSRF — il n'a pas de cookie ambiant à voler."""
    site = request.headers.get("sec-fetch-site", "").lower()
    if site and site not in ("same-origin", "same-site", "none"):
        raise HTTPException(status_code=403,
                            detail="requête refusée : elle vient d'un autre site")
    origine = request.headers.get("origin")
    if origine:
        from urllib.parse import urlparse
        hote_origine = urlparse(origine).netloc.lower()
        hote_requete = (request.headers.get("host") or "").lower()
        if hote_origine and hote_requete and hote_origine != hote_requete:
            raise HTTPException(status_code=403,
                                detail="requête refusée : elle vient d'un autre site")


def _contraintes_fiction(sous_genre: str, tropes, decor, libre) -> ContraintesTrio:
    """Construit les contraintes de composition ET les valide contre la taxonomie.

    Partagée par les DEUX chemins (SSE et travail asynchrone) : c'est exactement la
    divergence qu'on vient de payer. Le compositeur de trio n'avait été branché que sur le
    chemin SSE, si bien que basculer l'interface sur les travaux asynchrones l'aurait rendu
    décoratif du jour au lendemain, sans le moindre message.

    Une clé inconnue LÈVE : les menus étant peuplés depuis la taxonomie, elle ne peut venir
    que d'une requête forgée. L'ignorer ferait croire à l'auteur que sa contrainte est
    appliquée."""
    if isinstance(tropes, str):
        tropes = tropes.split(",")
    liste = [t.strip() for t in (tropes or []) if isinstance(t, str) and t.strip()]
    c = ContraintesTrio(tropes=liste, decor=(decor or None), libre=(libre or ""))
    tropes_ok, decors_ok = valid_keys(sous_genre)
    inconnus = [t for t in c.tropes if t not in tropes_ok]
    if inconnus or (c.decor and c.decor not in decors_ok):
        raise HTTPException(status_code=400,
                            detail=f"contrainte hors taxonomie : {inconnus or c.decor}")
    return c


_LOG = logging.getLogger("ia-niches")


def _verifier_config_prod() -> None:
    """Refuse de demarrer en production avec une source de BSR intenable en datacenter.

    BSR_SOURCE=scrape (le DEFAUT) lit les fiches Amazon depuis une IP residentielle :
    gratuit sur le poste de Baptiste, bloque depuis un hebergeur. Et l'echec y est MUET --
    resolve_bsrs attrape l'exception par ASIN et rend None, parce qu'un echec ne doit
    jamais couler un run (5.29). Consequence en prod : le service ne plante pas, il rend
    des rapports d'apparence normale dont TOUS les BSR manquent, donc des rayons qui se
    lisent comme depourvus de classement. C'est la regle 3 industrialisee.

    Refuser de demarrer est la seule issue lisible : une alerte au premier run arriverait
    apres avoir facture une analyse fausse."""
    if (os.getenv("APP_ENV") or "").strip().lower() != "prod":
        return
    src = (os.getenv("BSR_SOURCE") or "scrape").strip().lower()
    if src != "dataforseo":
        raise RuntimeError(
            f"APP_ENV=prod exige BSR_SOURCE=dataforseo (recu : « {src} »). Le "
            f"scraping des fiches Amazon suppose une IP residentielle : depuis un "
            f"datacenter il echoue en silence et rend des rapports sans aucun BSR, qui "
            f"se lisent comme des rayons sans classement.")


_verifier_config_prod()


def _notifier(user_id: str, type_: str, statut: str, job_id: str,
              journal=None) -> None:
    """Prévient l'auteur que son analyse est finie. Ne lève JAMAIS.

    L'adresse est relue depuis `comptes.db` au moment de l'envoi plutôt que portée par le
    job : le job ne stocke qu'un `user_id`, et y recopier une adresse en ferait une
    donnée personnelle de plus, dupliquée dans une base qui n'en a pas besoin.

    Un compte absent (`"local"`, compte supprimé) ne notifie personne et ne lève pas —
    l'analyse a bien eu lieu, elle est en base, et l'écran la montre."""
    try:
        compte = UserStore(_USERS_DB).compte(user_id)
        notifier_fin_de_job(email=getattr(compte, "email", None), type_=type_,
                            statut=statut, job_id=job_id, journal=journal)
    except Exception:  # noqa: BLE001 — un run payé et réussi ne doit pas devenir un échec
        pass


def _erreur_publique(e: BaseException) -> str:
    """Le texte d'une exception ne sort JAMAIS vers le client.

    Le message d'une erreur réseau porte régulièrement l'URL appelée, et l'URL DataForSEO
    porte les identifiants HTTP Basic : une panne de fournisseur suffisait donc à afficher
    un secret à l'écran, sans qu'aucune ligne du code n'ait « logué un secret ». Le champ
    `erreur` d'un job est lu par DEUX chemins (GET /api/jobs/{id} et le flux SSE) : il doit
    être assaini à la source, pas à l'affichage.

    Le client reçoit une RÉFÉRENCE, pas un silence — sans elle, un utilisateur qui signale
    « ça a planté » ne donne rien de raccrochable à une ligne de log. Même famille que
    `_corps_json` (§2.7) : un chemin non prévu ne renseigne ni l'utilisateur, ni l'attaquant.
    """
    ref = uuid4().hex[:8]
    _LOG.exception("incident %s", ref, exc_info=e)
    return f"Erreur interne (ref {ref})"


# ── Solde du fournisseur de données ─────────────────────────────────────────────────────────────
# Run fiction du 2026-10-05 : compte à sec (−0,05 $), cinq recherches refusées « 40200 ». Avant
# d'échouer, le run avait dépensé l'appel de génération des trios et consommé une unité de plafond.
# Un contrôle GRATUIT (`appendix/user_data`) avant de lancer l'évite — et dit la cause.
_SOLDE_TTL_S = 30                 # une recharge du compte doit se voir en moins d'une minute
_SOLDE_CACHE = {"t": 0.0, "v": None}


def _lire_solde() -> float | None:
    """Le solde du fournisseur, mis en cache `_SOLDE_TTL_S` secondes : le contrôle est gratuit
    mais lance une requête réseau, et une rafale de lancements ne doit pas en faire une chacun.
    None = illisible (cf. `search_providers.lire_solde`) ; mis en cache aussi, pour qu'un
    fournisseur lent ne soit pas interrogé à chaque lancement."""
    maintenant = time.monotonic()
    if _SOLDE_CACHE["t"] and maintenant - _SOLDE_CACHE["t"] < _SOLDE_TTL_S:
        return _SOLDE_CACHE["v"]
    valeur = _sp.lire_solde()
    _SOLDE_CACHE.update(t=maintenant, v=valeur)
    return valeur


async def _verifier_solde(type_: str, params: dict) -> None:
    """Refuse (503) AVANT toute dépense quand le solde du fournisseur ne couvre pas les RECHERCHES
    du run — une par niche, jamais servies par le cache en fiction : ce qui échouera à coup sûr.
    Les fiches, que le cache peut servir, ne sont pas comptées : on ne refuse pas ce qui pourrait
    réussir. Un solde ILLISIBLE laisse passer (règle 3 : un contrôle qui n'a pas pu se faire n'est
    pas un solde vide). Le client ne lit ni le fournisseur ni un montant ; hors production,
    l'opérateur — seul utilisateur — lit la cause."""
    solde = await asyncio.to_thread(_lire_solde)      # `post_job` est async : pas de réseau bloquant
    if solde is None:
        return
    besoin = ventilation_max_estimee(type_, params)["serp_usd"]
    if solde >= besoin:
        return
    _LOG.error("solde du compte de données insuffisant : %.4f $ pour des recherches estimées à "
               "%.4f $ (%s) — lancement refusé, aucune dépense", solde, besoin, type_)
    detail = ("Le service de données est momentanément indisponible. Rien n'a été lancé : aucune "
              "analyse n'a été décomptée. Réessayez dans quelques minutes.")
    if (os.getenv("APP_ENV") or "").strip().lower() != "prod":
        detail += " (Hors production : le solde du compte de données est épuisé.)"
    raise HTTPException(status_code=503, detail=detail)


def _verifier_plafond(user_id: str, n_analyses: int = 1) -> None:
    """Vérifié AVANT de dépenser, sur TOUT chemin payant.

    `UsageMeter.autorise` n'avait qu'un seul site d'appel — `POST /api/jobs` — que
    l'interface n'emprunte jamais. Le plafond ne protégeait donc que le chemin que
    personne n'utilise, pendant que les quatre endpoints réellement utilisés dépensaient
    librement. Toute nouvelle dépense doit passer par ici."""
    usage = UsageMeter(_USAGE_DB, plafond_analyses=_plafond_analyses_mensuel())
    if not usage.autorise(user_id, n_analyses=n_analyses):
        raise HTTPException(status_code=429, detail="plafond mensuel atteint")


def _imputer(user_id: str, type_: str, cout_usd: float, n_analyses: int) -> None:
    """Impute une dépense DÉJÀ faite. Appelé même en cas d'échec du run : l'argent est
    parti, le compteur doit le dire."""
    UsageMeter(_USAGE_DB).enregistrer(user_id, type_, cout_usd, n_analyses=n_analyses)


async def _corps_json(request: Request) -> dict:
    """Corps JSON, ou 400. Sans ce garde, un corps non-JSON ou un objet mal typé remonte
    en 500 : une trace exposée, et le signal donné à l'attaquant qu'il a trouvé un chemin
    non prévu."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — JSON illisible
        raise HTTPException(status_code=400, detail="corps de requête JSON attendu")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="corps de requête JSON attendu")
    return body


def _inscriptions_ouvertes() -> bool:
    """Fermé par DÉFAUT. Le plafond mensuel est PAR utilisateur : un compte de plus, c'est
    un plafond neuf. Laisser l'inscription libre revenait donc à offrir une dépense
    illimitée à un anonyme, et chaque analyse coûte de l'argent réel.

    Le premier compte passe toujours (amorçage) : sur une installation neuve il n'y a
    personne pour ouvrir les inscriptions, et une porte fermée à double tour rendrait le
    produit inutilisable. À rouvrir explicitement le jour où le paiement sera branché."""
    return os.getenv("INSCRIPTIONS_OUVERTES", "").strip().lower() in ("1", "true", "yes", "oui")


def _client_distant(request: Request) -> str:
    return (request.client.host if request.client else "") or "inconnu"


def _identifiants(body: dict) -> tuple[str, str]:
    """Extrait e-mail et mot de passe en exigeant du TEXTE. Un client qui envoie un nombre
    ou une liste fait une requête malformée : 400. Sans ce garde, la valeur descendait
    jusqu'aux fonctions de hachage et remontait en 500 — une trace exposée, et le signal
    donné à l'attaquant qu'il a trouvé un chemin non prévu."""
    email, mdp = body.get("email"), body.get("mot_de_passe")
    if not isinstance(email, str) or not isinstance(mdp, str):
        raise HTTPException(status_code=400,
                            detail="« email » et « mot_de_passe » doivent être du texte")
    return email, mdp


def utilisateur_courant(request: Request) -> str:
    """LA source unique du `user_id`. Il vient EXCLUSIVEMENT du cookie de session.

    Avant l'authentification, plusieurs endpoints acceptaient un `user_id` fourni par le
    client (corps de `POST /api/jobs`, paramètre de requête de `/api/usage`, `/api/jobs`
    et `/api/history`). C'était une faille et pas un détail : le plafond mensuel étant
    vérifié sur ce `user_id`, il suffisait d'en envoyer un neuf à chaque appel pour
    dépenser sans aucune limite, et de deviner celui d'un autre pour lire son historique.
    Ne JAMAIS réintroduire un paramètre `user_id` sur un endpoint."""
    uid = UserStore(_USERS_DB).session_valide(request.cookies.get(COOKIE_SESSION, ""))
    if uid is None:
        raise HTTPException(status_code=401, detail="authentification requise")
    return uid


def _adopter_donnees_locales(user_id: str) -> None:
    """Réattribue au PREMIER compte créé les données accumulées sous `user_id="local"`
    avant l'authentification.

    Sans cela, mettre l'authentification en service ferait perdre à Baptiste son
    antériorité — or l'antériorité est exactement ce que l'historique sert à mesurer : une
    niche vue une seule fois ne rend aucun delta. Réservé au premier compte : au second,
    ce serait faire hériter chaque nouveau client de l'historique du précédent."""
    import sqlite3
    for chemin, table in ((_HISTORY_DB, "passages"), (_USAGE_DB, "usage"),
                          (_JOBS_DB, "jobs")):
        if not Path(chemin).exists():
            continue
        try:
            with sqlite3.connect(str(chemin), timeout=10) as cx:
                cx.execute(f"UPDATE {table} SET user_id=? WHERE user_id='local'", (user_id,))
        except sqlite3.Error:
            # Une base absente ou d'un autre schéma ne doit pas faire échouer une
            # inscription : la reprise est un confort, la création de compte est le service.
            pass


@app.post("/api/auth/inscription", status_code=201)
async def api_inscription(request: Request, response: Response):
    origine_sure(request)
    body = await _corps_json(request)
    store = UserStore(_USERS_DB)
    premier = store.n_comptes() == 0
    if not premier and not _inscriptions_ouvertes():
        # Message IDENTIQUE quelle que soit l'adresse : renvoyer 409 « déjà pris » sur une
        # adresse connue et 201 sur une inconnue faisait de l'inscription un oracle
        # d'énumération, qui annulait l'anti-énumération soignée de la connexion.
        raise HTTPException(status_code=403,
                            detail="les inscriptions sont fermées sur cette instance")
    if not premier:
        # Inscriptions ouvertes : on ne PEUT pas cacher qu'une adresse est prise sans mentir
        # à l'utilisateur légitime. On empêche alors l'énumération EN MASSE — la limitation
        # porte sur le client, car sonder mille adresses distinctes ne déclencherait aucun
        # compteur par adresse.
        cle = f"ip:{_client_distant(request)}"
        if store.tentatives_recentes(cle) >= MAX_INSCRIPTIONS_PAR_CLIENT:
            raise HTTPException(status_code=429,
                                detail="trop d'inscriptions depuis ce poste — réessayez plus tard")
        store.noter_tentative(cle)
    # La reprise des données « local » doit être DEMANDÉE. Elle était automatique pour le
    # premier compte créé : sur une instance exposée, le premier visiteur venu devenait
    # propriétaire de l'historique et de la consommation de Baptiste (revue de sécurité).
    demande_reprise = bool(body.get("reprendre_donnees_locales"))
    email, mdp = _identifiants(body)
    try:
        compte = store.creer_compte(email, mdp)
    except EmailDejaPris as e:
        raise HTTPException(status_code=409, detail=str(e))
    except (EmailInvalide, MotDePasseFaible) as e:
        raise HTTPException(status_code=400, detail=str(e))
    premier = premier and demande_reprise
    if premier:
        _adopter_donnees_locales(compte.user_id)
    _poser_session(request, response, store.creer_session(compte.user_id))
    return {"user_id": compte.user_id, "email": compte.email,
            "donnees_locales_reprises": premier}


@app.post("/api/auth/connexion")
async def api_connexion(request: Request, response: Response):
    origine_sure(request)
    body = await _corps_json(request)
    store = UserStore(_USERS_DB)
    email, mdp = _identifiants(body)
    try:
        compte = store.verifier(email, mdp)
    except TropDeTentatives as e:
        # 429 et non 401 : l'utilisateur légitime qui s'est trompé doit comprendre que
        # c'est le rythme qui bloque, pas son mot de passe.
        raise HTTPException(status_code=429, detail=str(e))
    if compte is None:
        # UN SEUL message pour les deux causes : distinguer « email inconnu » de « mot de
        # passe faux » laisserait énumérer les clients avec une liste d'adresses.
        raise HTTPException(status_code=401, detail="e-mail ou mot de passe incorrect")
    _poser_session(request, response, store.creer_session(compte.user_id))
    return {"user_id": compte.user_id, "email": compte.email}


@app.post("/api/auth/deconnexion", status_code=204)
def api_deconnexion(request: Request, response: Response) -> Response:
    """Ferme la session côté serveur ET retire le cookie. Effacer le seul cookie ne
    suffirait pas : le jeton resterait valide pour quiconque en aurait gardé copie."""
    UserStore(_USERS_DB).fermer_session(request.cookies.get(COOKIE_SESSION, ""))
    reponse = Response(status_code=204)
    reponse.delete_cookie(COOKIE_SESSION, path="/")
    return reponse


@app.post("/api/auth/mot-de-passe", status_code=204)
async def api_changer_mot_de_passe(request: Request,
                                   user_id: str = Depends(utilisateur_courant)) -> Response:
    """Change le mot de passe. Exige l'ANCIEN — une session volée ne doit pas suffire à
    verrouiller le propriétaire hors de son compte — et referme les AUTRES sessions, la
    courante exceptée : on change son mot de passe précisément quand on craint qu'un jeton
    traîne ailleurs, et un jeton vit 30 jours.

    `origine_sure` comme l'inscription et la connexion : `SameSite=Lax` laisse partir le
    cookie sur une navigation de premier niveau, et un changement de mot de passe déclenché
    depuis un site tiers prendrait le compte."""
    origine_sure(request)
    body = await _corps_json(request)
    ancien, nouveau = body.get("ancien"), body.get("nouveau")
    if not isinstance(ancien, str) or not isinstance(nouveau, str):
        raise HTTPException(status_code=400,
                            detail="« ancien » et « nouveau » doivent être du texte")
    magasin = UserStore(_USERS_DB)
    compte = magasin.compte(user_id)
    if compte is None:
        raise HTTPException(status_code=401, detail="authentification requise")
    try:
        magasin.changer_mot_de_passe(compte.email, ancien, nouveau,
                                     garder=request.cookies.get(COOKIE_SESSION, ""))
    except IdentifiantsInvalides:
        # 401 et non 400 : c'est l'identité qui est refusée, pas la forme de la requête.
        raise HTTPException(status_code=401, detail="mot de passe actuel incorrect")
    except MotDePasseFaible as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(status_code=204)


@app.post("/api/auth/compte/suppression", status_code=204)
async def api_supprimer_compte(request: Request,
                               user_id: str = Depends(utilisateur_courant)) -> Response:
    """Clôture le compte ET efface ce qu'il a produit : travaux, consommation, historique.

    Exige le mot de passe : c'est la seule action irréversible du produit, une session volée
    ne doit pas pouvoir l'exercer. Le cache des rayons Amazon n'est PAS touché — il est
    mutualisé, ne porte aucun `user_id`, et ne contient que des pages publiques ; l'effacer
    ferait repayer tous les autres comptes (§1).

    Les trois effacements suivent la suppression du compte : si l'un d'eux échouait, le
    compte serait déjà parti et l'utilisateur ne pourrait plus rien réclamer. On les fait
    donc après, et une panne y laisse des lignes orphelines plutôt qu'un compte fantôme
    encore ouvert."""
    origine_sure(request)
    body = await _corps_json(request)
    mdp = body.get("mot_de_passe")
    if not isinstance(mdp, str):
        raise HTTPException(status_code=400, detail="« mot_de_passe » doit être du texte")
    magasin = UserStore(_USERS_DB)
    compte = magasin.compte(user_id)
    if compte is None:
        raise HTTPException(status_code=401, detail="authentification requise")
    try:
        magasin.supprimer_compte(compte.email, mdp)
    except IdentifiantsInvalides:
        raise HTTPException(status_code=401, detail="mot de passe incorrect")
    JobStore(_JOBS_DB).supprimer_utilisateur(user_id)
    UsageMeter(_USAGE_DB).supprimer_utilisateur(user_id)
    NicheHistory(_HISTORY_DB).supprimer_utilisateur(user_id)
    reponse = Response(status_code=204)
    reponse.delete_cookie(COOKIE_SESSION, path="/")
    return reponse


@app.get("/api/auth/moi")
def api_moi(user_id: str = Depends(utilisateur_courant)):
    compte = UserStore(_USERS_DB).compte(user_id)
    if compte is None:
        raise HTTPException(status_code=401, detail="authentification requise")
    return {"user_id": compte.user_id, "email": compte.email}


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse((_HERE / "index.html").read_text(encoding="utf-8"))


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _consigner_scout(results, user_id: str) -> None:
    """Consigne chaque niche pour l'historique. Sans enregistrement AUTOMATIQUE, la
    fonction n'existerait que sur le papier : personne n'appellera `enregistrer()` à la
    main après chaque run."""
    h = NicheHistory(_HISTORY_DB)
    for r in results:
        # Une niche dont la SERP a échoué porte des zéros non mesurés. Les consigner
        # injecterait un point faux dans la série : le passage suivant, mesuré celui-là,
        # produirait un delta spectaculaire et mensonger (« la niche s'est densifiée »)
        # alors que seule la panne a cessé. Un point qu'on sait faux est pire qu'un trou.
        if not r.concurrence_mesuree:
            continue
        h.enregistrer(user_id, "scout", r.niche, {
            "global_score": r.global_score, "bsr_best": r.bsr_best,
            "bsr_top5_avg": r.bsr_top5_avg, "n_concurrents_cibles": r.n_concurrents_cibles,
        })


def _consigner_lowcontent(results, user_id: str) -> None:
    """Historique low-content. Une niche dont la concurrence n'a PAS ete mesuree est
    exclue : un point qu'on sait faux produirait au passage suivant un delta
    spectaculaire et mensonger (meme regle que _consigner_scout)."""
    h = NicheHistory(_HISTORY_DB)
    for r in results:
        if not r.concurrence_mesuree:
            continue
        h.enregistrer(user_id, "lowcontent", r.niche.niche, {
            "global_score": r.global_score, "demande": r.demande,
            "penetration": r.penetration, "rentabilite": r.rentabilite,
            "bsr_best": r.bsr_best, "n_concurrents_cibles": r.n_concurrents_cibles,
        })


def _consigner_fiction(rapports, user_id: str) -> None:
    h = NicheHistory(_HISTORY_DB)
    for r in rapports:
        # Un point qu'on sait faux n'entre pas dans la série : des zéros (non mesurable) ou un
        # livre unique (mesure mince), enregistrés, feraient lire au passage suivant un delta
        # spectaculaire et mensonger — même règle que la non-fiction (`concurrence_mesuree`).
        if r.demand_matrix in NON_CONCLUANTES:
            continue
        # Cle du TRIO, pas sa requete : plusieurs trios d'un meme decor partagent la meme requete
        # courte, et leurs series ne se comparent pas (saturation_trio depend de LEURS tropes).
        h.enregistrer(user_id, "fiction", r.niche.cle, {
            "depth_score": r.depth_score, "openness_score": r.openness_score,
            "saturation_trio": r.saturation_trio, "series_share": r.series_share,
        })


@app.get("/api/fiction/taxonomie/{sous_genre}")
def fiction_taxonomie(sous_genre: str, user_id: str = Depends(utilisateur_courant)):
    """Tropes et décors autorisés pour un sous-genre — alimente les menus déroulants
    du compositeur de trio. Même principe que /api/fiction/sous-genres : la taxonomie
    est la source de vérité UNIQUE, jamais une liste dupliquée en dur côté JS."""
    if sous_genre not in load_taxonomy().get("sous_genres", {}):
        raise HTTPException(status_code=400,
                            detail=f"sous-genre inconnu : « {sous_genre} »")
    tropes, decors = valid_keys(sous_genre)
    return {"sous_genre": sous_genre, "tropes": tropes, "decors": decors}


@app.get("/api/lowcontent/formats")
def lowcontent_formats(user_id: str = Depends(utilisateur_courant)):
    """Source de verite unique du selecteur de format. Jamais de liste dupliquee en dur
    cote JS : elle se perimerait a la premiere taxonomie v2.

    `norme` est expose pour que l'UI pose son badge sans re-deduire la taxonomie."""
    formats = load_taxonomy_lc()["formats"]
    return sorted(
        ({"cle": c, "label": f["label"], "famille": f["famille"],
          "norme": bool(f["norme"]), "effort": f["effort"]}
         for c, f in formats.items()),
        key=lambda f: (f["famille"], f["label"]))


@app.get("/api/fiction/sous-genres")
def fiction_sous_genres(user_id: str = Depends(utilisateur_courant)):
    """Peuple le sélecteur fiction de l'UI depuis la taxonomie (source de vérité unique) —
    jamais une liste dupliquée en dur côté JS, qui se périmerait à la moindre taxo v2."""
    sgs = load_taxonomy().get("sous_genres", {})
    return [{"cle": cle, "label": sg.get("label", cle)} for cle, sg in sorted(sgs.items())]


# ── Travaux asynchrones (plan SaaS S4) ──────────────────────────────────────────────────
# LE point de ce bloc, et désormais le SEUL chemin de lancement : le run est écrit dans le
# magasin de travaux (SQLite, jobs.db) à chaque étape, au lieu d'être streamé dans une file
# en mémoire qui mourait avec la requête HTTP — un client déconnecté perdait alors toute
# trace exploitable du run, résultat ET coût.
# POST rend un id tout de suite, le thread continue seul, GET peut être interrogé n'importe
# quand ensuite — y compris après une déconnexion complète du client d'origine.

def _run_scout_job(params: dict, progress, cost, user_id: str) -> list:
    # `ideas`/`search` sont les noms de l'endpoint SSE historique : les accepter aussi,
    # sinon un client qui reprend ces noms voit son plafond silencieusement ignoré et paie
    # les défauts (6 recherches au lieu de 2 demandées). Divergence constatée en live.
    n_ideas = _borner("n_ideas", params.get("n_ideas", params.get("ideas", 12)), MAX_IDEES)
    n_search = _borner("n_search", params.get("n_search", params.get("search", 6)),
                       MAX_RECHERCHES)
    results = run_scout(seed=params.get("seed") or None, n_ideas=n_ideas,
                        n_search=n_search, progress=progress, cost=cost)
    _consigner_scout(results, user_id)
    return [r.model_dump() for r in results]


def _run_fiction_job(params: dict, progress, cost, user_id: str) -> list:
    sous_genre = params.get("sous_genre", "")
    sgs = load_taxonomy().get("sous_genres", {})
    if sous_genre not in sgs:
        # Échoue AVANT tout appel payant : capté par le worker comme un échec de job
        # normal (coût nul imputé), jamais une 500 opaque.
        raise ValueError(f"sous-genre inconnu : « {sous_genre} » (dispo : {sorted(sgs)})")
    n_niches = _borner("n_niches", params.get("n_niches", 8), MAX_NICHES_FICTION)
    contraintes = _contraintes_fiction(sous_genre, params.get("tropes"),
                                       params.get("decor"), params.get("libre"))
    rapports = run_fiction_scout(sous_genre, n_niches=n_niches,
                                 rayon=params.get("rayon", "kindle"),
                                 contraintes=contraintes,
                                 progress=progress, cost=cost)
    payload = []
    for r in rapports:
        d = r.model_dump()
        d["autocomplete_score"] = r.autocomplete_score       # cf. /api/fiction : property non sérialisée
        payload.append(d)
    _consigner_fiction(rapports, user_id)
    return payload


# Les deux runners reçoivent le user_id ET consignent l'historique : le chemin asynchrone
# est celui qu'on RECOMMANDE (il survit à la fermeture de l'onglet et vérifie le plafond),
# donc c'est précisément lui qui doit alimenter l'historique. Le laisser muet — l'état
# initial, trouvé en revue — vidait la fonction de sa substance pour l'usage nominal.
def _borner_texte(nom: str, valeur, maxi: int = MAX_LONGUEUR_GRAINE) -> str:
    """Borne un texte libre AVANT qu'il n'atteigne un prompt LLM.

    La graine n'etait bornee que sur le chemin low-content. Or ces textes partent dans le
    prompt d'ideation et se facturent AU TOKEN : un texte de plusieurs milliers de
    caracteres a ete mesure jusqu'a ~2 $ pour un run dont le devis annoncait 0,08 $. Le
    devis ne modelise pas la taille des textes de l'utilisateur -- c'est donc la borne qui
    doit la tenir, pas lui.

    REFUSE plutot que de rogner, comme `_borner` : quelqu'un qui colle un texte de 5 000
    caracteres doit savoir qu'il ne sera pas analyse, pas decouvrir que seuls ses 80
    premiers l'ont ete."""
    if valeur is None:
        return ""
    if not isinstance(valeur, str):
        raise HTTPException(status_code=400,
                            detail=f"{nom} doit etre du texte (recu : {type(valeur).__name__})")
    if len(valeur) > maxi:
        raise HTTPException(
            status_code=400,
            detail=f"{nom} doit faire au plus {maxi} caracteres (recu : {len(valeur)})")
    return valeur


def _valider_volumes(type_: str, params: dict) -> None:
    """Valide tout ce qui peut l'être AVANT de créer le job et de rendre 202.

    Levée depuis le thread détaché, une erreur de paramètre arriverait après un 202 déjà
    rendu : l'utilisateur ne verrait qu'un job en échec, sans savoir que c'est sa saisie
    qui est en cause."""
    if type_ == "scout":
        _borner_texte("seed", params.get("seed"))
        _borner("n_ideas", params.get("n_ideas", params.get("ideas", 12)), MAX_IDEES)
        _borner("n_search", params.get("n_search", params.get("search", 6)),
                MAX_RECHERCHES)
    elif type_ == "lowcontent":
        _borner("n_search", params.get("n_search", 6), MAX_RECHERCHES_LC)
        _borner_texte("seed", params.get("seed"))
        # Format valide ICI, pas dans le runner. Levee depuis le thread detache, la 400
        # arriverait apres un 202 deja rendu : l'utilisateur verrait une analyse
        # "lancee" qui rate, sans comprendre que sa saisie etait fautive.
        cle = params.get("format_cle") or ""
        if cle and cle not in valid_formats_lc():
            raise HTTPException(
                status_code=400,
                detail=f"format low-content inconnu : \u00ab {cle} \u00bb "
                       f"(dispo : {valid_formats_lc()})")
    elif type_ == "fiction":
        _borner_texte("libre", params.get("libre"))
        _borner("n_niches", params.get("n_niches", 8), MAX_NICHES_FICTION)
        # Le sous-genre est validé ICI, pas seulement dans le runner. Le flux direct
        # rendait une 400 immédiate ; en ne gardant que le chemin asynchrone, laisser la
        # validation au thread détaché donnerait un 202 suivi d'un job en échec —
        # l'utilisateur verrait une analyse « lancée » qui rate, sans comprendre que sa
        # saisie était fautive.
        sgs = load_taxonomy().get("sous_genres", {})
        if params.get("sous_genre") not in sgs:
            raise HTTPException(
                status_code=400,
                detail=f"sous-genre inconnu : « {params.get('sous_genre', '')} » "
                       f"(dispo : {sorted(sgs)})")
        _contraintes_fiction(params.get("sous_genre", ""), params.get("tropes"),
                             params.get("decor"), params.get("libre"))


def _run_lowcontent_job(params: dict, progress, cost, user_id: str) -> list:
    """Scout low-content. Meme forme que les deux autres runners : les bornes sont deja
    validees par _valider_volumes, ce runner ne re-decide rien."""
    results = run_lowcontent_scout(
        seed=params.get("seed") or None,
        format_cle=params.get("format_cle") or None,
        n_search=_borner("n_search", params.get("n_search", 6), MAX_RECHERCHES_LC),
        inclure_saisonnier=bool(params.get("inclure_saisonnier")),
        progress=progress, cost=cost)
    _consigner_lowcontent(results, user_id)
    return [r.model_dump() for r in results]


_JOB_RUNNERS = {"scout": _run_scout_job, "fiction": _run_fiction_job,
                "lowcontent": _run_lowcontent_job}


@app.post("/api/jobs", status_code=202)
async def post_job(request: Request, user_id: str = Depends(utilisateur_courant)):
    """Lance un travail asynchrone : le client reçoit un id IMMÉDIATEMENT (jamais 15 min
    d'attente HTTP bloquante). Le thread du job est détaché de CETTE requête : il persiste
    sa progression/son résultat/son coût dans le magasin, pas dans une queue en mémoire liée
    à la connexion — fermer l'onglet ne l'arrête pas et ne perd pas l'argent déjà dépensé."""
    origine_sure(request)
    body = await _corps_json(request)
    type_ = body.get("type")
    runner = _JOB_RUNNERS.get(type_)
    if runner is None:
        raise HTTPException(
            status_code=400,
            detail=f"type de job inconnu : « {type_} » (dispo : {sorted(_JOB_RUNNERS)})")
    # Le user_id vient de la SESSION, jamais du corps de la requête. Lire body["user_id"]
    # laissait n'importe quel client changer d'identité à chaque appel et contourner le
    # plafond mensuel, vérifié juste en dessous. Une clé "user_id" envoyée par le client
    # est désormais ignorée (elle est retirée de params comme avant, sans jamais être lue).

    # Le plafond est vérifié AVANT de dépenser (§4 du plan SaaS), jamais après coup.
    params = {k: v for k, v in body.items() if k not in ("type", "user_id")}
    # DEVIS AVANT DEPENSE. Le plafond en cours de run s'arretait proprement, mais rendait
    # quand meme un rapport TRONQUE a quelqu'un qui avait paye son plafond entier -- et
    # rien ne l'avait prevenu avant qu'il clique. On refuse donc en amont, en disant quel
    # volume tiendrait. Le plafond en cours de run reste, comme filet de dernier recours
    # (panne, tempete de retries, tarif qui change chez le fournisseur).
    try:
        verifier_devis(type_, params, plafond=_plafond_usd_par_run())
    except PLAFOND_DEPASSE as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Bornes validées AVANT de créer le job : levée depuis le thread détaché, la 400
    # arriverait après un 202 déjà rendu, donc invisible pour le client.
    _valider_volumes(type_, params)
    # Solde du fournisseur : APRES les refus de saisie (une 400 n'est pas un diagnostic de service),
    # AVANT la réservation de l'unité de plafond et avant tout appel payant.
    await _verifier_solde(type_, params)

    # RESERVATION ATOMIQUE, et elle vient EN DERNIER. `autorise()` puis imputation a la
    # fin du run laissait entre les deux la duree entiere de l'analyse : une rafale de
    # requetes voyait toutes le meme compteur, celui d'avant la premiere, et passait en
    # entier. Ici la place est prise DANS la transaction de controle.
    #
    # Placee APRES la validation des volumes et le devis : une saisie fautive ou un run
    # trop gros est refuse sans consommer d'unite de plafond -- sinon l'utilisateur
    # paierait ses erreurs de frappe.
    try:
        ligne_usage = UsageMeter(
            _USAGE_DB, plafond_analyses=_plafond_analyses_mensuel()
        ).reserver_analyse(user_id, type_)
    except PlafondAtteint as e:
        raise HTTPException(status_code=429, detail=str(e))

    store = JobStore(_JOBS_DB)
    job_id = store.create(type_, params, user_id=user_id)

    def worker() -> None:
        # Connexion/instance par appel (même pattern que cache.py) : sûr en concurrence,
        # ce thread ne partage aucun objet Python avec la requête qui l'a lancé.
        job_store = JobStore(_JOBS_DB)
        # Attend un creneau AVANT de marquer le job demarre : sinon l'utilisateur
        # verrait une analyse « en cours » qui ne progresse pas, sans savoir si elle
        # est bloquee ou seulement lente. Tant qu'il attend, son statut reste
        # « en attente », ce qui est exactement ce qui se passe.
        # L'issue est retenue pour notifier APRÈS avoir rendu le créneau : le pool n'en
        # tient que `RUNS_SIMULTANES_MAX`, et un dialogue SMTP lent — jusqu'à 20 s de
        # délai d'attente — les garderait aux frais de ceux qui font la queue. Le travail
        # est fini, la place doit être rendue.
        statut = "echec"
        with _creneaux():
            job_store.start(job_id)           # sans effet sur un travail deja annule
            cost = CostTracker()
            if job_store.est_annule(job_id):
                # Arrete pendant l'attente d'un creneau : rien n'a tourne, rien n'est depense.
                # La reservation est soldee a zero, l'unite de plafond reste prise.
                UsageMeter(_USAGE_DB).solder(ligne_usage, 0.0)
                statut = "annule"
            else:
                # Point de controle PROPRE A CE FIL : l'arret demande par l'utilisateur est lu en
                # base (au plus une fois par seconde) a chaque message de progression, avant
                # chaque phase payante et a chaque cycle d'attente du fournisseur.
                _annulation.installer(controle_du_travail(job_store, job_id))

                def progress(msg: str) -> None:
                    _annulation.verifier()
                    job_store.append_progress(job_id, msg)

                try:
                    resultat = runner(params, progress, cost, user_id)
                    b = cost.breakdown()
                    # L'usage est imputé AVANT de marquer le job terminé. L'ordre inverse ouvrait
                    # une course : un client qui interroge dès qu'il voit « termine » lisait un
                    # compteur pas encore à jour, donc un total périmé juste après son run — et
                    # deux runs lancés coup sur coup pouvaient passer sous un plafond déjà atteint.
                    # « Terminé » doit impliquer « compté ».
                    # SOLDE la reservation : la place a deja ete prise a la creation.
                    # Imputer une seconde ligne consommerait DEUX unites par run.
                    UsageMeter(_USAGE_DB).solder(ligne_usage, b["usd"])
                    if job_store.est_annule(job_id):
                        # Arrete JUSTE avant la fin : le resultat est jete, le cout reste compte.
                        job_store.enregistrer_cout_annule(job_id, b)
                        statut = "annule"
                    else:
                        job_store.finish(job_id, resultat, b)
                        statut = "termine"
                except Annulation:
                    # BaseException : arrivee d'un point de controle. L'argent deja engage reste
                    # impute et l'unite de plafond reste prise -- arreter ne rembourse rien, sinon
                    # « lancer puis arreter » serait gratuit.
                    b = cost.breakdown()
                    UsageMeter(_USAGE_DB).solder(ligne_usage, b["usd"])
                    job_store.enregistrer_cout_annule(job_id, b)
                    statut = "annule"
                except Exception as e:  # noqa: BLE001 — l'argent déjà dépensé doit rester imputé
                    b = cost.breakdown()
                    # L'argent parti reste compte, et la place reste prise : un echec ne
                    # rembourse pas une unite de plafond, sinon un run qui echoue en boucle
                    # serait gratuit.
                    UsageMeter(_USAGE_DB).solder(ligne_usage, b["usd"])
                    job_store.fail(job_id, _erreur_publique(e), cout=b)
                finally:
                    _annulation.retirer()

        # Hors du créneau. Ne lève jamais : le run est payé, compté et en base.
        if statut != "annule":          # l'auteur l'a arretee lui-meme : rien a lui annoncer
            _notifier(user_id, type_, statut, job_id)

    if _mode_jobs() == "worker":
        # Empile SEULEMENT. Sans ce garde, serveur ET worker executeraient le meme job :
        # deux fois les SERP, deux fois les tokens. `claim_next` protege de la course
        # entre deux workers, mais c'est ICI qu'on decide QUI travaille -- donc avant de
        # lancer le moindre fil, jamais depuis l'interieur de celui-ci.
        return {"id": job_id}

    threading.Thread(target=worker, daemon=True).start()
    return {"id": job_id}


def _job_public(job) -> dict:
    """Le travail tel qu'un CLIENT peut le lire : la progression sans les mentions du
    mecanisme de mutualisation (cache, dedup) -- cf. progression_publique. Le brut reste en
    base, pour le diagnostic."""
    d = job.model_dump()
    d["progression"] = liste_publique(job.progression)
    d["erreur"] = texte_public(job.erreur)       # meme frontiere : jamais le nom du fournisseur
    if job.type == "fiction":
        # Un resultat enregistre AVANT « mesure mince » est relu sous la regle d'aujourd'hui.
        d["resultat"] = relire_resultat_fiction(d.get("resultat"))
    return d


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, user_id: str = Depends(utilisateur_courant)):
    """404 — et non 403 — quand le job appartient à quelqu'un d'autre : distinguer les
    deux confirmerait à l'attaquant que l'identifiant existe."""
    job = JobStore(_JOBS_DB).get(job_id)
    if job is None or job.user_id != user_id:
        raise HTTPException(status_code=404, detail="job inconnu")
    return _job_public(job)


@app.post("/api/jobs/{job_id}/annuler", status_code=204)
def annuler_job(job_id: str, request: Request, user_id: str = Depends(utilisateur_courant)):
    """Arrete UNE analyse de la session (« il faut pouvoir arreter une analyse qui bug ou tourne
    dans le vide »). IMMEDIAT cote donnees ; le thread s'arrete a son prochain point de controle
    (annulation.py). L'argent deja engage reste impute et l'unite de plafond reste prise.

    404 -- jamais 403 -- pour le travail d'un autre compte ; 409 si l'analyse est deja finie ;
    `origine_sure` comme tout ce qui modifie des donnees."""
    origine_sure(request)
    issue = JobStore(_JOBS_DB).annuler(job_id, user_id)
    if issue == "introuvable":
        raise HTTPException(status_code=404, detail="job inconnu")
    if issue == "deja_fini":
        raise HTTPException(status_code=409, detail="Cette analyse est déjà terminée.")
    return Response(status_code=204)


@app.delete("/api/jobs/{job_id}", status_code=204)
def supprimer_job(job_id: str, request: Request, user_id: str = Depends(utilisateur_courant)):
    """Supprime UNE analyse de l'utilisateur de la session (« Mes analyses »).

    404 -- et non 403 -- pour le travail d'un autre compte : distinguer les deux confirmerait
    que l'identifiant existe. 409 pour une analyse pas finie (cf. JobStore.supprimer). La
    consommation (usage.db) et l'historique d'evolution des niches ne sont PAS touches :
    supprimer de l'ecran ne rembourse rien et ne libere aucune unite de plafond.
    `origine_sure` comme tout ce qui modifie des donnees : le cookie seul ne suffit pas."""
    origine_sure(request)
    issue = JobStore(_JOBS_DB).supprimer(job_id, user_id)
    if issue == "introuvable":
        raise HTTPException(status_code=404, detail="job inconnu")
    if issue == "en_cours":
        raise HTTPException(status_code=409,
                            detail="Cette analyse est encore en cours : attendez la fin pour la supprimer.")
    return Response(status_code=204)


@app.get("/api/jobs")
def list_jobs(limit: int = 20, user_id: str = Depends(utilisateur_courant)):
    return [_job_public(j) for j in JobStore(_JOBS_DB).list_jobs(user_id=user_id, limit=limit)]


@app.get("/api/usage")
def usage(user_id: str = Depends(utilisateur_courant)):
    """Consommation du mois glissant. Un plafond qui bloque sans que l'utilisateur ait pu
    voir où il en était serait vécu comme une panne, pas comme une limite."""
    r = UsageMeter(_USAGE_DB).resume(user_id)
    return r.model_dump() if hasattr(r, "model_dump") else dict(r)


@app.get("/api/jobs/{job_id}/stream")
def stream_job(job_id: str, user_id: str = Depends(utilisateur_courant)):
    """SSE branché sur la progression du magasin — RECONNECTABLE. L'état vient de la base
    et non d'une file en mémoire liée à UNE connexion : une reconnexion relit donc la
    progression depuis le début, à tout moment, y compris longtemps après le POST
    d'origine. C'est ce qui permet à l'interface de reprendre un run après un
    rechargement, et ce que l'ancien flux direct ne pouvait pas offrir."""
    def stream():
        store = JobStore(_JOBS_DB)
        envoyes = 0
        while True:
            job = store.get(job_id)
            # Le job d'un autre compte est traité comme inexistant — et non refusé —
            # pour ne pas confirmer qu'un identifiant est valide. Sans ce garde,
            # connaître un id suffisait à lire le résultat et le coût du run d'autrui.
            if job is not None and job.user_id != user_id:
                job = None
            if job is None:
                yield _sse("error", "job inconnu")
                yield _sse("done", {})
                return
            # Filtre AVANT de compter : `envoyes` indexe la liste PUBLIQUE, sinon une ligne
            # retiree decalerait tout ce qui suit (et rejouerait ou sauterait des messages).
            publique = liste_publique(job.progression)
            for msg in publique[envoyes:]:
                yield _sse("progress", msg)
            envoyes = len(publique)
            if job.statut == "termine":
                yield _sse("result", relire_resultat_fiction(job.resultat)
                           if job.type == "fiction" else job.resultat)
                yield _sse("cost", job.cout)
                yield _sse("done", {})
                return
            if job.statut == "annule":
                yield _sse("error", "Analyse arrêtée à votre demande.")
                yield _sse("done", {})
                return
            if job.statut == "echec":
                yield _sse("error", texte_public(job.erreur))
                yield _sse("done", {})
                return
            time.sleep(0.3)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _content_disposition(name: str) -> str:
    """En-tête Content-Disposition sûr : nom ASCII (fallback) + filename* RFC 5987 (UTF-8).
    Garantit un en-tête encodable en latin-1 (exigence Starlette) même avec « œ », accents, etc."""
    base = (name or "niche").strip()
    ascii_name = "".join(c for c in base if c.isascii() and (c.isalnum() or c in " -_")).strip()
    ascii_name = ascii_name[:40] or "niche"
    utf8 = quote((base[:60] or "niche") + ".pdf")
    return f"attachment; filename=\"{ascii_name}.pdf\"; filename*=UTF-8''{utf8}"


def _conserver_dans_travail(request: Request, user_id: str, champ: str, valeur: dict) -> bool | None:
    """Range un resultat PAYE a la piece (verdict, mots-cles) dans le travail qui l'a vu naitre.

    Sans `?job=`, rend None et ne fait rien : le comportement d'origine, sans etat, est
    strictement inchange. Avec, le SERVEUR ecrit ce qu'il vient de produire (jamais ce que
    la page dirait) et seulement dans un travail de la session : `user_id` vient du cookie.

    Un echec d'ecriture ne fait JAMAIS echouer la reponse : elle a ete facturee des le retour
    du modele, la perdre serait pire que ne pas l'avoir gardee. On rend False, que la page
    peut dire.
    """
    job_id = (request.query_params.get("job") or "").strip()
    if not job_id:
        return None
    cle = (request.query_params.get("cle") or "")[:300]
    try:
        return JobStore(_JOBS_DB).annoter_resultat(job_id, user_id, cle, champ, valeur)
    except Exception as e:  # noqa: BLE001 — voir docstring
        _LOG.warning("resultat non conserve (%s) : %s", champ, type(e).__name__)
        return False


@app.post("/api/verdict")
async def api_verdict(request: Request, user_id: str = Depends(utilisateur_courant)):
    """Analyse éditoriale d'UNE niche, à la demande (sans état : la niche arrive entière
    dans le body). Mesuré à 0,0283 $ pièce : les générer d'avance pour le top-3 pesait
    78 % du coût d'un run, pour des analyses que l'utilisateur ne lisait pas. On ne paie
    donc que la niche sur laquelle il clique."""
    body = await _corps_json(request)
    # Dispatch sur `type`, defaut "scout" pour compat : un client existant n'envoie pas ce
    # champ et doit continuer a fonctionner. UN SEUL endpoint pour les deux verdicts --
    # en creer un seccond ferait diverger les gardes de plafond, comme l'a montre 5257323.
    type_ = (body.pop("type", None) or "scout").strip().lower()
    if type_ not in ("scout", "lowcontent", "fiction"):
        raise HTTPException(status_code=400,
                            detail=f"type de verdict inconnu : « {type_} »")
    if type_ == "fiction":
        # La page renvoie la carte telle qu'elle l'a reçue : `autocomplete_score` (propriété
        # ré-injectée par _run_fiction_job) et `analyse` (déjà rangée) ne sont pas des champs du
        # rapport, que le modèle REFUSE (extra="forbid"). On ne garde que ses champs : un corps
        # forgé n'a de toute façon aucun moyen d'y glisser autre chose.
        body = {k: v for k, v in body.items() if k in FictionNicheReport.model_fields}
    try:
        scored = {"lowcontent": LowContentScored, "fiction": FictionNicheReport,
                  "scout": ScoredNiche}[type_].model_validate(body)
    except Exception:  # noqa: BLE001 — body invalide -> 400 propre (jamais un 500)
        raise HTTPException(status_code=400, detail="niche invalide")
    raison = raison_non_mesure(scored) if type_ == "fiction" else None
    if raison is not None:
        # AVANT toute réservation : rien n'est dépensé ni décompté du débit horaire, et surtout
        # aucun verdict ne sort d'une absence de mesure — « non mesuré » n'est pas « mort »
        # (règle 3). Zéro livre OU trop peu : deux phrases. La carte masque déjà le bouton ;
        # ceci tient pour un client hors page, et pour un résultat ancien dont la carte n'a pas
        # l'état « mesure mince ».
        raise HTTPException(status_code=400, detail=f"{raison} Rien n'a été dépensé.")
    # Appel LLM facturé. Il ne CONSOMME pas d'unité d'analyse (il complète une analyse
    # déjà payée, d'où n_analyses=0 à l'imputation) mais il EXIGE une marge : un compte au
    # plafond ne doit pas pouvoir continuer à faire tourner le LLM indéfiniment.
    _verifier_plafond(user_id)
    ligne = _reserver_appel(user_id, "verdict")
    cost = CostTracker()
    fabrique = {"lowcontent": generate_lowcontent_verdict, "fiction": generate_fiction_verdict,
                "scout": generate_verdict}[type_]
    try:
        verdict = fabrique(scored, on_usage=lambda i, o, m: cost.add_llm(m, i, o))
    except Exception as e:  # noqa: BLE001 — la réponse a pu être PAYÉE avant de lever
        raise HTTPException(status_code=502, detail=_erreur_publique(e)) from None
    finally:
        # Soldé même quand la lecture lève : les jetons sont facturés dès la réponse, et
        # une réservation laissée à 0 $ effaçait la dépense d'usage.db (§5.29).
        UsageMeter(_USAGE_DB).solder(ligne, cost.total_usd())
    reponse = {**verdict.model_dump(), "_cout": cost.breakdown()}
    # Un résultat fiction porte DÉJÀ un `verdict` : le texte du moteur et ses réserves (rayon
    # incomplet, sous-genre fantôme). L'objet du modèle se range à côté, sous `analyse`.
    conserve = _conserver_dans_travail(request, user_id,
                                       "analyse" if type_ == "fiction" else "verdict",
                                       verdict.model_dump())
    if conserve is not None:
        reponse["_conserve"] = conserve
    return reponse


@app.get("/api/history")
def history(niche: str = "", user_id: str = Depends(utilisateur_courant)):
    """Historique d'une niche et lecture de son évolution.

    Une niche vue une seule fois rend `delta: null` avec un 200 : « pas encore de recul »
    est une réponse, pas un échec — une 404 pousserait l'interface à afficher une erreur
    là où il n'y a qu'une absence de comparaison possible."""
    h = NicheHistory(_HISTORY_DB)
    d = h.delta(user_id, niche)
    return {"niche": niche,
            "passages": h.historique(user_id, niche),
            "delta": d.model_dump() if d else None}


@app.post("/api/kdp-keywords")
async def api_kdp_keywords(request: Request, user_id: str = Depends(utilisateur_courant)):
    """Les 7 mots-clés backend KDP d'une niche, à la demande (sans état, ~0,006 $).

    Les candidats sont confirmés gratuitement par l'autocomplete Amazon : le coût imputé
    ne couvre que l'appel LLM, la vérification ne coûte rien."""
    body = await _corps_json(request)
    # Meme dispatch que /api/verdict : `type` absent = non-fiction (compat). En low-content la
    # requete, la categorie et les satellites vivent sur `scored.niche` (LowContentNiche) : c'est
    # elle qui part au generateur, comme pour le dossier -- le LowContentScored entier leve avant
    # l'appel.
    type_ = (body.pop("type", None) or "scout").strip().lower()
    if type_ not in ("scout", "lowcontent"):
        raise HTTPException(status_code=400, detail=f"type de mots-clés inconnu : « {type_} »")
    try:
        scored = (LowContentScored if type_ == "lowcontent" else ScoredNiche).model_validate(body)
    except Exception:  # noqa: BLE001 — body invalide -> 400 propre (jamais un 500)
        raise HTTPException(status_code=400, detail="niche invalide")
    _verifier_plafond(user_id)
    ligne = _reserver_appel(user_id, "kdp_keywords")          # même raisonnement que /api/verdict
    cost = CostTracker()
    try:
        mots = generer_mots_cles(scored.niche if type_ == "lowcontent" else scored,
                                 titre=(scored.niche.niche if type_ == "lowcontent" else scored.niche),
                                 on_usage=lambda i, o, m: cost.add_llm(m, i, o))
    except Exception as e:  # noqa: BLE001 — même raisonnement que /api/verdict
        raise HTTPException(status_code=502, detail=_erreur_publique(e)) from None
    finally:
        UsageMeter(_USAGE_DB).solder(ligne, cost.total_usd())
    reponse = {**mots.model_dump(), "_cout": cost.breakdown()}
    conserve = _conserver_dans_travail(request, user_id, "mots_cles", mots.model_dump())
    if conserve is not None:
        reponse["_conserve"] = conserve
    return reponse


@app.post("/api/dossier")
async def api_dossier(request: Request, user_id: str = Depends(utilisateur_courant)):
    """Dossier de niche en trois pages : le marche, l'angle, la publication.

    Trois choses que l'auteur n'avait nulle part et qui etaient DEJA payees : contre qui
    il publie (top_books), quoi ecrire dans les 7 champs KDP, et ou ranger le livre.

    Les mots-cles ne sont generes QUE si on les demande (0,006 $ l'appel) : le defaut ne
    doit pas depenser a l'insu de l'utilisateur. Les categories, elles, se deduisent des
    BSR deja collectes -- cout 0 $, donc cochees par defaut cote UI."""
    body = await _corps_json(request)
    type_ = (body.get("type") or "scout").strip().lower()
    if type_ not in ("scout", "lowcontent"):
        raise HTTPException(status_code=400,
                            detail=f"type de dossier inconnu : « {type_} »")
    try:
        modele = LowContentScored if type_ == "lowcontent" else ScoredNiche
        scored = modele.model_validate(body.get("niche") or {})
    except Exception:  # noqa: BLE001 — body invalide -> 400 propre (jamais un 500)
        raise HTTPException(status_code=400, detail="niche invalide")

    titre = scored.niche.niche if type_ == "lowcontent" else scored.niche

    cats = None
    if body.get("inclure_categories", True):
        # Deduites des sous-categories BSR portees par les livres du top : la donnee est
        # deja payee, la relire ne coute rien et n'appelle personne.
        from models import BsrInfo
        cats = suggerer_categories(
            [BsrInfo(rank_livres=b.bsr or 1, asin=b.asin, subcategories=b.bsr_subcats)
             for b in scored.top_books if b.bsr_subcats], n=5)

    mots = None
    if body.get("inclure_mots_cles"):
        # Appel LLM facture. Il n'entame pas le quota d'ANALYSES (il complete une analyse
        # deja comptee) mais il EXIGE une marge : un compte au plafond ne doit pas pouvoir
        # continuer a faire tourner le LLM.
        # La reservation vit DANS ce bloc : un dossier sans mots-cles ne depense rien,
        # et le brider serait gratuit en cout mais couteux en usage.
        _verifier_plafond(user_id)
        ligne = _reserver_appel(user_id, "dossier")
        cost = CostTracker()
        try:
            # En low-content, la requete, la categorie et les satellites vivent sur
            # `scored.niche` (LowContentNiche) : passer le LowContentScored entier levait
            # AVANT l'appel, avale ci-dessous -- dossier sans mots-cles, creneau consomme.
            mots = generer_mots_cles(scored.niche if type_ == "lowcontent" else scored,
                                     titre=titre,
                                     on_usage=lambda i, o, m: cost.add_llm(m, i, o))
        except Exception as e:  # noqa: BLE001 — le document reste utile sans eux (5.29)
            _LOG.warning("mots-cles indisponibles pour le dossier : %s", e)
            mots = None
        UsageMeter(_USAGE_DB).solder(ligne, cost.total_usd())

    with tempfile.TemporaryDirectory() as d:
        chemin = build_dossier_pdf(scored, f"{d}/dossier.pdf", mots_cles=mots,
                                   categories=cats)
        pdf_bytes = chemin.read_bytes()
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": _content_disposition(titre)})


@app.post("/api/pdf")
async def api_pdf(request: Request, user_id: str = Depends(utilisateur_courant)):
    """Rend le one-pager PDF d'une niche à la volée (stateless : la niche est fournie
    en entier dans le body, aucune persistance côté serveur)."""
    try:
        data = await request.json()
        scored = ScoredNiche.model_validate(data)
    except Exception:  # noqa: BLE001 — body invalide -> 400 propre (jamais un 500)
        raise HTTPException(status_code=400, detail="niche invalide")
    # Alias historique : un client tiers peut l'appeler, et la casser sans prevenir
    # n'apporterait rien. Elle sert le MEME document que /api/dossier -- deux generateurs
    # divergeraient, et ce depot sait ce que ca coute.
    with tempfile.TemporaryDirectory() as d:
        p = build_dossier_pdf(scored, f"{d}/dossier.pdf")
        pdf_bytes = p.read_bytes()
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": _content_disposition(scored.niche)})


def _recuperer_travaux_interrompus(store: JobStore | None = None) -> int:
    """Passe en échec les runs qu'un redémarrage a coupés. Appelée AU DÉMARRAGE.

    En local, un redémarrage du serveur est un événement rare. Sur un hébergeur, c'est le
    cas NOMINAL : chaque déploiement reconstruit et relance le service. Or la récupération
    n'avait qu'un appelant, `worker.boucle()`, alors que le mode par défaut est `thread` :
    sans worker, un run coupé restait `en_cours` POUR TOUJOURS. L'utilisateur voyait une
    analyse éternellement en cours, son unité de plafond consommée, et rien ne le lui
    disait — exactement la forme de panne que ce dépôt combat partout ailleurs.

    En `JOBS_MODE=worker`, on ne touche à rien : c'est le worker qui exécute, donc lui qui
    récupère (il le fait au démarrage de sa boucle). Que les deux s'en chargent ferait
    passer en échec, depuis le serveur, un travail que le worker vient de reprendre.

    Aucune exception ne remonte : refuser de démarrer parce qu'un vieux travail traîne
    ferait tomber le service entier pour une ligne de ménage. La récupération est un
    confort, servir les clients est le service — même arbitrage que
    `_adopter_donnees_locales`."""
    if _mode_jobs() == "worker":
        return 0
    try:
        return recuperer_orphelins(store or JobStore(_JOBS_DB),
                                   journal=_LOG.info, prefixe="[serveur]")
    except Exception:  # noqa: BLE001 — le ménage ne doit jamais empêcher de démarrer
        _LOG.exception("récupération des travaux interrompus impossible")
        return 0


def _hote() -> str:
    """L'interface d'écoute. DÉDUITE en production, comme le drapeau `Secure` du cookie.

    `127.0.0.1` est le bon défaut sur le poste de Baptiste et le mauvais dans un
    conteneur : le routeur de l'hébergeur parle au service depuis l'extérieur du
    processus, donc écouter la boucle locale rend le déploiement MUET — la construction
    réussit, les journaux sont propres, et rien ne répond jamais. Une variable à penser
    au déploiement est une variable qu'on oublie (c'est l'histoire de `COOKIE_SECURE`) :
    `APP_ENV=prod` dit déjà « je suis en exposition », qu'elle décide aussi de ça.

    Un `HOST` explicite prime toujours : la déduction est un défaut, pas une contrainte."""
    explicite = (os.getenv("HOST") or "").strip()
    if explicite:
        return explicite
    return "0.0.0.0" if (os.getenv("APP_ENV") or "").strip().lower() == "prod" else "127.0.0.1"


if __name__ == "__main__":
    import uvicorn
    # PORT par variable d'environnement : un port figé à 8000 empêche de lancer deux
    # instances et bloque tout hébergement (les plateformes imposent leur PORT).
    try:
        port = int(os.getenv("PORT", "8000"))
    except ValueError:
        port = 8000
    uvicorn.run(app, host=_hote(), port=port)
