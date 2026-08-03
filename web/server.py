"""server.py — backend FastAPI de l'UI IA-Niches.
Sert la page unique et expose le scout en SSE (progression live + résultats).

Lancer :  uvicorn server:app --reload   (depuis le dossier web/)
   ou     python web/server.py
"""
import json
import os
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse

# rend le moteur (01-scripts) importable + charge les secrets quel que soit le cwd
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "01-scripts"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(_ROOT / ".env")
from scout_master import run_scout  # noqa: E402
from fiction_master import run_fiction_scout  # noqa: E402
from niche_verdict import generate_verdict  # noqa: E402
from kdp_keywords import generer_mots_cles  # noqa: E402
from fiction_taxonomy import load_taxonomy  # noqa: E402
from cost_tracker import CostTracker  # noqa: E402
from models import ScoredNiche  # noqa: E402
from positioning_pdf import build_positioning_pdf  # noqa: E402
from jobs import JobStore  # noqa: E402
from usage import UsageMeter  # noqa: E402
from history import NicheHistory  # noqa: E402
from auth import (EmailDejaPris, EmailInvalide, MAX_INSCRIPTIONS_PAR_CLIENT,  # noqa: E402
                  MotDePasseFaible, SESSION_TTL_S, TropDeTentatives, UserStore)

app = FastAPI(title="IA-Niches")
_HERE = Path(__file__).resolve().parent

# Chemins des magasins asynchrones (plan SaaS S2/S3). De simples constantes Path : la
# construction du JobStore/UsageMeter (et donc la création du fichier) est différée à
# l'intérieur de chaque endpoint — jamais à l'import du module, sinon importer server.py
# en test écrirait déjà des fichiers réels dans le dépôt (cf. cache.py, même principe :
# connexion/instance par appel, jamais une instance partagée figée à l'import).
_JOBS_DB = _ROOT / "99-logs" / "jobs.db"
_USAGE_DB = _ROOT / "99-logs" / "usage.db"
_HISTORY_DB = _ROOT / "99-logs" / "history.db"
_USERS_DB = _ROOT / "99-logs" / "comptes.db"

COOKIE_SESSION = "ia_niches_session"

# Bornes des paramètres de volume. Le plafond mensuel compte des ANALYSES, pas des
# appels payants : sans ces bornes, une seule « analyse » avec search=9999 déclenche des
# milliers de requêtes DataForSEO tout en ne consommant qu'une unité du plafond. Borner
# le volume est donc la seule protection réelle du MONTANT (revue de sécurité 2026-08-03).
# Le nombre d'IDÉES est fixé, pas offert au réglage : l'ideator est UN SEUL appel LLM quel
# que soit le nombre demandé, donc en proposer 20 plutôt que 10 coûte des millièmes de
# dollar et améliore le tri gratuit qui suit. C'est le nombre de RECHERCHES qui pèse
# (~0,003 $ par niche, plus le lot BSR) : c'est donc le seul que l'utilisateur choisit.
IDEES_PAR_RUN = 20
MAX_IDEES = 30
MAX_RECHERCHES = 20
MAX_NICHES_FICTION = 20


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

    `/api/scout` et `/api/fiction` sont des GET qui dépensent de l'argent réel. Or
    SameSite=Lax laisse partir le cookie sur une navigation de premier niveau : une page
    malveillante qui fait `window.open('http://127.0.0.1:8000/api/scout?...')` déclenche
    donc un run facturé sur le compte de la victime. Le cookie seul ne suffit pas ici.

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


def _consigner_fiction(rapports, user_id: str) -> None:
    h = NicheHistory(_HISTORY_DB)
    for r in rapports:
        h.enregistrer(user_id, "fiction", r.niche.query, {
            "depth_score": r.depth_score, "openness_score": r.openness_score,
            "saturation_trio": r.saturation_trio, "series_share": r.series_share,
        })


@app.get("/api/scout")
def scout(request: Request, seed: str = "", ideas: int = IDEES_PAR_RUN, search: int = 4,
          user_id: str = Depends(utilisateur_courant)):
    """Lance le scout dans un thread et streame la progression + le résultat en SSE."""
    origine_sure(request)
    ideas = _borner("ideas", ideas, MAX_IDEES)
    search = _borner("search", search, MAX_RECHERCHES)
    _verifier_plafond(user_id)
    q: "queue.Queue" = queue.Queue()

    def progress(msg: str) -> None:
        q.put(("progress", msg))

    def worker() -> None:
        cost = CostTracker()
        try:
            results = run_scout(seed=(seed or None), n_ideas=ideas, n_search=search,
                                progress=progress, cost=cost)
            _consigner_scout(results, user_id)
            q.put(("result", [r.model_dump() for r in results]))
            q.put(("cost", cost.breakdown()))
        except Exception as e:  # noqa: BLE001
            q.put(("error", f"{type(e).__name__}: {e}"))
        finally:
            # Imputé dans tous les cas : en échec aussi, l'argent est déjà parti.
            _imputer(user_id, "scout", cost.breakdown()["usd"], n_analyses=1)
            q.put(("done", None))

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        yield _sse("progress", "Démarrage du scout…")
        while True:
            kind, payload = q.get()
            if kind == "done":
                yield _sse("done", {})
                break
            yield _sse(kind, payload)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/fiction/sous-genres")
def fiction_sous_genres(user_id: str = Depends(utilisateur_courant)):
    """Peuple le sélecteur fiction de l'UI depuis la taxonomie (source de vérité unique) —
    jamais une liste dupliquée en dur côté JS, qui se périmerait à la moindre taxo v2."""
    sgs = load_taxonomy().get("sous_genres", {})
    return [{"cle": cle, "label": sg.get("label", cle)} for cle, sg in sorted(sgs.items())]


@app.get("/api/fiction")
def fiction(request: Request, sous_genre: str = "", n_niches: int = 8,
            rayon: str = "kindle", user_id: str = Depends(utilisateur_courant)):
    """Lance le scout fiction dans un thread, streame en SSE — même contrat que /api/scout
    (progress / result / cost / error / done)."""
    # Validation AVANT de lancer quoi que ce soit : un sous-genre inconnu (ou absent) doit
    # rendre une 400 explicite, jamais la KeyError 500 que lèverait fiction_taxonomy.sous_genre().
    origine_sure(request)
    n_niches = _borner("n_niches", n_niches, MAX_NICHES_FICTION)
    sgs = load_taxonomy().get("sous_genres", {})
    if sous_genre not in sgs:
        raise HTTPException(status_code=400,
                            detail=f"sous-genre inconnu : « {sous_genre} » (dispo : {sorted(sgs)})")
    _verifier_plafond(user_id)

    q: "queue.Queue" = queue.Queue()

    def progress(msg: str) -> None:
        q.put(("progress", msg))

    def worker() -> None:
        cost = CostTracker()
        try:
            rapports = run_fiction_scout(sous_genre, n_niches=n_niches, rayon=rayon,
                                         progress=progress, cost=cost)
            payload = []
            for r in rapports:
                d = r.model_dump()
                # autocomplete_score est une @property (non sérialisée par model_dump) :
                # None tant que la sonde n'a rien mesuré — ne JAMAIS la laisser retomber à
                # 0 par omission, un utilisateur lirait ça comme un verdict (CLAUDE.md §10).
                d["autocomplete_score"] = r.autocomplete_score
                payload.append(d)
            _consigner_fiction(rapports, user_id)
            q.put(("result", payload))
            q.put(("cost", cost.breakdown()))
        except Exception as e:  # noqa: BLE001
            q.put(("error", f"{type(e).__name__}: {e}"))
        finally:
            _imputer(user_id, "fiction", cost.breakdown()["usd"], n_analyses=1)
            q.put(("done", None))

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        yield _sse("progress", "Démarrage du scout fiction…")
        while True:
            kind, payload = q.get()
            if kind == "done":
                yield _sse("done", {})
                break
            yield _sse(kind, payload)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Travaux asynchrones (plan SaaS S4) ──────────────────────────────────────────────────
# LE point de ce bloc : /api/scout et /api/fiction ci-dessus streament la progression dans
# une queue.Queue qui ne vit QUE le temps de la requête HTTP — rien n'est persisté nulle
# part, donc un client qui se déconnecte perd toute trace exploitable du run (résultat ET
# coût). Ici le run est écrit dans le magasin de travaux (SQLite, jobs.db) à chaque étape :
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
    rapports = run_fiction_scout(sous_genre, n_niches=n_niches,
                                 rayon=params.get("rayon", "kindle"),
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
def _valider_volumes(type_: str, params: dict) -> None:
    """Applique les bornes aux paramètres de volume d'un job, avant tout lancement."""
    if type_ == "scout":
        _borner("n_ideas", params.get("n_ideas", params.get("ideas", 12)), MAX_IDEES)
        _borner("n_search", params.get("n_search", params.get("search", 6)),
                MAX_RECHERCHES)
    elif type_ == "fiction":
        _borner("n_niches", params.get("n_niches", 8), MAX_NICHES_FICTION)


_JOB_RUNNERS = {"scout": _run_scout_job, "fiction": _run_fiction_job}


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
    usage = UsageMeter(_USAGE_DB, plafond_analyses=_plafond_analyses_mensuel())
    if not usage.autorise(user_id, n_analyses=1):
        raise HTTPException(
            status_code=429,
            detail=f"plafond mensuel atteint pour l'utilisateur « {user_id} »")

    params = {k: v for k, v in body.items() if k not in ("type", "user_id")}
    # Bornes validées AVANT de créer le job : levée depuis le thread détaché, la 400
    # arriverait après un 202 déjà rendu, donc invisible pour le client.
    _valider_volumes(type_, params)
    store = JobStore(_JOBS_DB)
    job_id = store.create(type_, params, user_id=user_id)

    def worker() -> None:
        # Connexion/instance par appel (même pattern que cache.py) : sûr en concurrence,
        # ce thread ne partage aucun objet Python avec la requête qui l'a lancé.
        job_store = JobStore(_JOBS_DB)
        job_store.start(job_id)
        cost = CostTracker()

        def progress(msg: str) -> None:
            job_store.append_progress(job_id, msg)

        try:
            resultat = runner(params, progress, cost, user_id)
            b = cost.breakdown()
            # L'usage est imputé AVANT de marquer le job terminé. L'ordre inverse ouvrait
            # une course : un client qui interroge dès qu'il voit « termine » lisait un
            # compteur pas encore à jour, donc un total périmé juste après son run — et
            # deux runs lancés coup sur coup pouvaient passer sous un plafond déjà atteint.
            # « Terminé » doit impliquer « compté ».
            _imputer(user_id, type_, b["usd"], n_analyses=1)
            job_store.finish(job_id, resultat, b)
        except Exception as e:  # noqa: BLE001 — l'argent déjà dépensé doit rester imputé
            b = cost.breakdown()
            _imputer(user_id, type_, b["usd"], n_analyses=1)
            job_store.fail(job_id, f"{type(e).__name__}: {e}", cout=b)

    threading.Thread(target=worker, daemon=True).start()
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, user_id: str = Depends(utilisateur_courant)):
    """404 — et non 403 — quand le job appartient à quelqu'un d'autre : distinguer les
    deux confirmerait à l'attaquant que l'identifiant existe."""
    job = JobStore(_JOBS_DB).get(job_id)
    if job is None or job.user_id != user_id:
        raise HTTPException(status_code=404, detail="job inconnu")
    return job.model_dump()


@app.get("/api/jobs")
def list_jobs(limit: int = 20, user_id: str = Depends(utilisateur_courant)):
    return [j.model_dump() for j in JobStore(_JOBS_DB).list_jobs(user_id=user_id, limit=limit)]


@app.get("/api/usage")
def usage(user_id: str = Depends(utilisateur_courant)):
    """Consommation du mois glissant. Un plafond qui bloque sans que l'utilisateur ait pu
    voir où il en était serait vécu comme une panne, pas comme une limite."""
    r = UsageMeter(_USAGE_DB).resume(user_id)
    return r.model_dump() if hasattr(r, "model_dump") else dict(r)


@app.get("/api/jobs/{job_id}/stream")
def stream_job(job_id: str, user_id: str = Depends(utilisateur_courant)):
    """SSE branché sur la progression du magasin — RECONNECTABLE : contrairement à
    /api/scout et /api/fiction (queue en mémoire propre à une connexion), l'état lu ici
    vient du magasin persistant, donc une reconnexion peut relire la progression à tout
    moment, y compris longtemps après la requête POST d'origine."""
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
            for msg in job.progression[envoyes:]:
                yield _sse("progress", msg)
            envoyes = len(job.progression)
            if job.statut == "termine":
                yield _sse("result", job.resultat)
                yield _sse("cost", job.cout)
                yield _sse("done", {})
                return
            if job.statut == "echec":
                yield _sse("error", job.erreur)
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


@app.post("/api/verdict")
async def api_verdict(request: Request, user_id: str = Depends(utilisateur_courant)):
    """Analyse éditoriale d'UNE niche, à la demande (sans état : la niche arrive entière
    dans le body). Mesuré à 0,0283 $ pièce : les générer d'avance pour le top-3 pesait
    78 % du coût d'un run, pour des analyses que l'utilisateur ne lisait pas. On ne paie
    donc que la niche sur laquelle il clique."""
    try:
        scored = ScoredNiche.model_validate(await request.json())
    except Exception:  # noqa: BLE001 — body invalide -> 400 propre (jamais un 500)
        raise HTTPException(status_code=400, detail="niche invalide")
    # Appel LLM facturé. Il ne CONSOMME pas d'unité d'analyse (il complète une analyse
    # déjà payée, d'où n_analyses=0 à l'imputation) mais il EXIGE une marge : un compte au
    # plafond ne doit pas pouvoir continuer à faire tourner le LLM indéfiniment.
    _verifier_plafond(user_id)
    cost = CostTracker()
    verdict = generate_verdict(scored, on_usage=lambda i, o, m: cost.add_llm(m, i, o))
    UsageMeter(_USAGE_DB).enregistrer(user_id, "verdict", cost.total_usd(), n_analyses=0)
    return {**verdict.model_dump(), "_cout": cost.breakdown()}


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
    try:
        scored = ScoredNiche.model_validate(await request.json())
    except Exception:  # noqa: BLE001 — body invalide -> 400 propre (jamais un 500)
        raise HTTPException(status_code=400, detail="niche invalide")
    _verifier_plafond(user_id)          # même raisonnement que /api/verdict
    cost = CostTracker()
    mots = generer_mots_cles(scored, titre=scored.niche,
                             on_usage=lambda i, o, m: cost.add_llm(m, i, o))
    UsageMeter(_USAGE_DB).enregistrer(user_id, "kdp_keywords", cost.total_usd(), n_analyses=0)
    return {**mots.model_dump(), "_cout": cost.breakdown()}


@app.post("/api/pdf")
async def api_pdf(request: Request, user_id: str = Depends(utilisateur_courant)):
    """Rend le one-pager PDF d'une niche à la volée (stateless : la niche est fournie
    en entier dans le body, aucune persistance côté serveur)."""
    try:
        data = await request.json()
        scored = ScoredNiche.model_validate(data)
    except Exception:  # noqa: BLE001 — body invalide -> 400 propre (jamais un 500)
        raise HTTPException(status_code=400, detail="niche invalide")
    with tempfile.TemporaryDirectory() as d:
        p = build_positioning_pdf(scored, f"{d}/positioning.pdf")
        pdf_bytes = p.read_bytes()
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": _content_disposition(scored.niche)})


if __name__ == "__main__":
    import uvicorn
    # HOST et PORT par variable d'environnement : un port figé à 8000 empêche de lancer
    # deux instances et bloque tout hébergement (les plateformes imposent leur PORT).
    # Défauts inchangés pour l'usage local : 127.0.0.1:8000.
    try:
        port = int(os.getenv("PORT", "8000"))
    except ValueError:
        port = 8000
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=port)
