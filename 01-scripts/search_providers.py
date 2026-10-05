"""search_providers.py — étape SEARCH (payante) derrière un seam interchangeable.

Récupère, pour une requête, les résultats Amazon.fr : organiques vs sponsorisés + ASIN
+ prix + note + avis + badges. Les ASIN alimentent ensuite le BSR gratuit. Provider par
défaut : DataForSEO (Amazon Products, task-based, ~0,003 $/requête en priority).

Le mapping (DataForSEO -> modèles normalisés) est PUR et testé contre la vraie forme de
réponse observée en live. Les appels HTTP sont injectables (aucun réseau en unit-test).
"""
import os
import re
import time
import warnings

import requests
from dotenv import load_dotenv

from annulation import verifier as verifier_annulation
from marketplace import ACTIF
from models import BsrInfo, SearchItem, SearchResult

_BASE = "https://api.dataforseo.com/v3/merchant/amazon/products"
_ASIN_BASE = "https://api.dataforseo.com/v3/merchant/amazon/asin"
# Codes de la place de marché active. Ils vivaient ici en dur, à côté de huit autres
# copies dispersées : voir `marketplace.py` pour pourquoi une seule source, et pourquoi
# une place non prête lève au lieu de rendre des chiffres faux.
DEFAULT_LOCATION = ACTIF.location_code    # 2250 = France
DEFAULT_LANGUAGE = ACTIF.language_code    # "fr_FR" et non "fr" — validé en live
COST_PER_CALL_USD = {1: 0.0015, 2: 0.003}  # standard (~45 min) / priority (~1 min)
# Maximum de tâches par task_post, documenté par DataForSEO. Au-delà, les tâches ne sont pas
# créées : 30 niches low-content × 6 ASIN (180) ou 11 trios fiction × 12 ASIN (132) le
# franchissaient, et la fin du lot perdait son enrichissement en silence.
LOT_ASIN_MAX = 100


class TaskPostRefuse(RuntimeError):
    """`task_post` REFUSÉ explicitement : aucune tâche créée, donc rien de facturé.

    C'est la SEULE panne d'une SERP que l'appelant n'impute pas. Tout le reste — poll
    épuisé, relecture illisible, Ctrl-C — survient APRÈS la création de la tâche, que
    DataForSEO facture qu'on la relise ou non. Au rejeu du 2026-09-14, cinq SERP créées puis
    non lues étaient imputées 0 $ : le coût du run mentait vers le bas (règle 2).
    Hérite de RuntimeError : les appelants qui attrapaient le RuntimeError générique ne
    changent pas."""


class AucunResultat(RuntimeError):
    """La tâche est TERMINÉE et la recherche n'a rendu AUCUN résultat (statut de tâche 40102).

    Relevé le 2026-10-05 : deux recherches fiction « expirées après 320 s — file saturée » avaient
    en réalité été terminées en quelques centièmes de seconde, `No Search Results`, `cost` 0 —
    Amazon répondait « Aucun résultat pour votre recherche dans Livres », la requête étant trop
    précise. La boucle d'attente n'acceptait que « 20000 avec résultat » et pollait donc 40 fois
    une tâche déjà finie : 640 s perdus sur un run de 915 s, puis un message FAUX.

    Ce n'est NI un refus de compte (`RefusCompte` : on cesserait d'appeler le fournisseur pour
    toutes les niches suivantes sur la foi d'UNE requête vide), NI un timeout. La tâche a été
    créée : l'appelant l'impute, par prudence — DataForSEO rapporte `cost` 0, mais rien ne mesure
    ce qui est facturé. Hérite de RuntimeError : les appelants qui attrapent `Exception` (le
    scout non-fiction, qui marque alors la niche « concurrence non mesurée », et le low-content)
    ne changent pas de comportement, ils obtiennent seulement la réponse 320 s plus tôt."""


# Statut TERMINAL observé en live (fixture réelle : tests/fixtures/serp_aucun_resultat_reel.json).
# Les statuts « en cours » (file, tâche prise) n'ont jamais été capturés ici : ils continuent
# d'être attendus, on ne reconnaît que ce qu'on a vu.
STATUT_AUCUN_RESULTAT = 40102


class RefusCompte(TaskPostRefuse):
    """Refus posé à la RACINE, sans aucune tâche : c'est le COMPTE qui est refusé (non
    vérifié 40104, identifiants, solde), pas la requête. Toutes les requêtes suivantes
    seront refusées de même : les orchestrateurs cessent alors d'appeler le fournisseur au
    lieu d'enchaîner un `task_post` par niche (31 au premier run réel). Aucune liste de
    codes : un code qu'on n'a jamais vu ne doit pas relancer la rafale."""


def _motif_refus(reponse: dict | None, tache: dict | None = None) -> str:
    """Le motif d'un refus DataForSEO, LA ou il se trouve.

    Un refus de REQUETE est pose dans la tache ; un refus de COMPTE -- compte non verifie
    (40104), identifiants refuses, solde -- est pose a la RACINE du JSON, sans aucune tache.
    Ne lire que la tache affichait « task_post refusé : None None » : c'est ce qu'a rendu,
    trente et une fois, le premier run reel de calibration (2026-09-13), alors que la reponse
    disait en toutes lettres « Please verify your account ». Le motif le plus precis prime :
    la tache, puis la racine. Aucun secret n'y figure : c'est le texte de DataForSEO, pas
    notre requete (qui, elle, porte les identifiants HTTP Basic)."""
    for source in (tache or {}, reponse or {}):
        code = source.get("status_code")
        if code is not None and code not in (20000, 20100):
            return f"{code} {source.get('status_message')}"
    racine = reponse or {}
    return (f"{racine.get('status_code')} {racine.get('status_message')} "
            f"(aucune tâche rendue)")


class _Payloads(dict):
    """`{asin: payload | None}`, plus ce que l'appelant doit IMPUTER : `taches_creees` pour
    ce qui est CERTAIN, `taches_incertaines` pour ce qui a PU être facturé.

    Un dict ordinaire pour tout le reste, les consommateurs existants n'y voient aucune
    différence. Le compte vient d'ici parce que c'est le seul endroit qui sait combien de
    tâches DataForSEO a réellement créées — donc facturées.

    Trois issues, et elles ne s'imputent pas pareil : une tâche ACCEPTÉE est facturée
    (`taches_creees`) ; un refus EXPLICITE (racine ou par tâche) ne crée rien
    (`lots_en_echec`) ; un `task_post` qui LÈVE ne dit pas ce qu'il a créé
    (`lots_exception`, comptées dans `taches_incertaines`) — la requête est partie, seule la
    réponse manque."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.taches_creees = 0
        self.taches_incertaines = 0
        self.lots_en_echec: list[tuple[int, str]] = []
        # Lots dont l'ENVOI a levé : peut-être créés, donc peut-être facturés.
        self.lots_exception: list[tuple[int, str]] = []
        # Relectures qui ont levé pendant le poll, par type ; la tâche a été relue au cycle
        # suivant, pas abandonnée.
        self.lectures_en_echec: dict[str, int] = {}
        # ASIN dont le payload a été RELU. Hors de cet ensemble, `None` est une panne, pas
        # une mesure : rien ne doit s'en mémoriser.
        self.lus: set[str] = set()


def _resolve_priority(priority: int | None) -> int:
    """Argument explicite > env DATAFORSEO_PRIORITY > défaut 2 (priority). Standard (1) coûte
    moitié prix mais peut monter à ~45 min de file : un ARBITRAGE, donc un réglage — jamais un
    défaut qui dégraderait l'usage interactif à l'insu de l'appelant (cf. plan SaaS S1)."""
    if priority is not None:
        return priority
    raw = os.getenv("DATAFORSEO_PRIORITY")
    if raw is None:
        return 2
    try:
        val = int(raw)
    except ValueError:
        warnings.warn(f"DATAFORSEO_PRIORITY={raw!r} invalide (attendu 1 ou 2) — repli sur 2.")
        return 2
    if val not in (1, 2):
        warnings.warn(f"DATAFORSEO_PRIORITY={val} hors plage (1 ou 2) — repli sur 2.")
        return 2
    return val


def _to_float(x) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _map_item(it: dict) -> SearchItem:
    rating = it.get("rating") if isinstance(it.get("rating"), dict) else {}
    return SearchItem(
        rank=it.get("rank_absolute"),
        asin=it.get("data_asin"),
        title=it.get("title") or "",
        url=it.get("url"),
        price=_to_float(it.get("price_from")),
        currency=it.get("currency"),
        rating=_to_float(rating.get("value")),
        reviews_count=rating.get("votes_count"),
        is_best_seller=bool(it.get("is_best_seller")),
        is_amazon_choice=bool(it.get("is_amazon_choice")),
        sponsored=it.get("type") == "amazon_paid",
    )


def map_dataforseo_result(result: dict) -> SearchResult:
    """Convertit un 'result' DataForSEO (merchant/amazon/products) en SearchResult
    normalisé : organiques (amazon_serp) vs sponsorisés (amazon_paid)."""
    items = (result or {}).get("items") or []
    organic, sponsored = [], []
    for it in items:
        t = it.get("type")
        if t == "amazon_serp":
            organic.append(_map_item(it))
        elif t == "amazon_paid":
            sponsored.append(_map_item(it))
    return SearchResult(
        keyword=(result or {}).get("keyword") or "",
        organic=organic,
        sponsored=sponsored,
        total_items=len(items),
    )


class DataForSEOProvider:
    """Provider search via DataForSEO Amazon Products (task-based)."""
    name = "dataforseo"

    def __init__(self, login: str | None = None, password: str | None = None,
                 priority: int | None = None, location_code: int = DEFAULT_LOCATION,
                 language_code: str = DEFAULT_LANGUAGE, journal_brut: list | None = None):
        load_dotenv()
        self.auth = (login or os.getenv("DATAFORSEO_LOGIN", ""),
                     password or os.getenv("DATAFORSEO_PASSWORD", ""))
        self.priority = _resolve_priority(priority)
        self.location_code = location_code
        self.language_code = language_code
        # Journal BRUT, éteint par défaut : les réponses telles que DataForSEO les rend, AVANT
        # tout parsing. Le run 4 a payé 185 fiches lues par un parseur fautif, et rien n'en
        # gardait le brut : corriger le parseur obligeait à tout racheter. C'est l'appelant
        # (la CLI de calibration) qui décide où l'écrire — jamais le cache partagé. Ni les
        # identifiants ni le corps posté n'y entrent : seulement ce que DataForSEO répond.
        self.journal_brut = journal_brut

    def _journaliser(self, entree: dict) -> None:
        if self.journal_brut is not None:
            self.journal_brut.append(entree)

    def _post(self, url: str, body):
        return requests.post(url, auth=self.auth, json=body, timeout=30).json()

    def _get(self, url: str):
        return requests.get(url, auth=self.auth, timeout=30).json()

    @property
    def cost_per_call(self) -> float:
        return COST_PER_CALL_USD.get(self.priority, 0.003)

    def search(self, keyword: str, depth: int = 100, books_only: bool = True,
               search_param: str | None = None,
               post_json=None, get_json=None, poll_interval: float = 8,
               max_polls: int = 40) -> SearchResult:
        """Poste une tâche puis attend le résultat (poll). HTTP injectable pour les tests.
        search_param explicite (ex. contrainte de browse node "rh=n:...") prime sur
        books_only ; sans lui, books_only=True restreint au rayon Livres (i=stripbooks)."""
        post_json = post_json or self._post
        get_json = get_json or self._get
        item = {
            "keyword": keyword,
            "location_code": self.location_code,
            "language_code": self.language_code,
            "depth": depth,
            "priority": self.priority,
        }
        if search_param:
            item["search_param"] = search_param
        elif books_only:
            item["search_param"] = "i=stripbooks"
        body = [item]
        d = post_json(_BASE + "/task_post", body)
        # Un refus aussi : son motif exact est ce qui manque le plus après coup.
        self._journaliser({"type": "serp_post", "keyword": keyword, "reponse": d})
        taches = d.get("tasks") or []
        task = taches[0] if taches else {}
        if task.get("status_code") not in (20000, 20100):
            motif = f"task_post refusé : {_motif_refus(d, task)}"
            if not taches and d.get("status_code") not in (None, 20000, 20100):
                raise RefusCompte(motif)
            raise TaskPostRefuse(motif)
        tid = task.get("id")
        for _ in range(max_polls):
            time.sleep(poll_interval)
            verifier_annulation()      # point d'arret : ici une analyse « tourne dans le vide »
            reponse = get_json(f"{_BASE}/task_get/advanced/{tid}")
            t = (reponse.get("tasks") or [{}])[0]
            if t.get("status_code") == STATUT_AUCUN_RESULTAT:
                # Tâche TERMINÉE, sans résultat : inutile d'attendre un 20000 qui ne viendra pas.
                self._journaliser({"type": "serp_get", "keyword": keyword, "tache": tid,
                                   "reponse": reponse})
                raise AucunResultat(f"Amazon ne rend aucun résultat pour « {keyword} »")
            if t.get("status_code") == 20000 and t.get("result"):
                self._journaliser({"type": "serp_get", "keyword": keyword, "tache": tid,
                                   "reponse": reponse})
                return map_dataforseo_result(t["result"][0])
        # Budget aligné sur celui du chemin ASIN (40 polls) : à 16 polls (128 s), un simple
        # ralentissement de la file DataForSEO effaçait un run entier — mesuré en live, 3
        # SERP sur 3 expirées. Le message dit le budget écoulé pour distinguer « file lente »
        # d'une vraie erreur de requête.
        raise TimeoutError(f"résultat DataForSEO non prêt après {max_polls * poll_interval:.0f} s "
                           f"(id={tid}) — file DataForSEO probablement saturée")

    def product_raw_batch(self, asins, post_json=None, get_json=None,
                          poll_interval: float = 8, max_polls: int = 40,
                          journal_brut: list | None = None) -> dict:
        """Payloads ASIN bruts de plusieurs ASIN, par task_post de LOT_ASIN_MAX au plus, collecte
        par poll. Retour : {asin: payload dict|None}. HTTP injectable. Seule boucle de poll —
        product_info_batch et le futur enrichissement fiction (M2) s'y branchent.

        `journal_brut` (à défaut, celui du fournisseur) reçoit chaque payload AU MOMENT où
        il est lu : un Ctrl-C en plein poll laisse dans la liste de l'appelant tout ce qui a
        déjà été relu, alors que le dict de retour, lui, ne serait jamais rendu."""
        asins = [a for a in asins if a]
        if not asins:
            return {}
        journal = journal_brut if journal_brut is not None else self.journal_brut
        post_json = post_json or self._post
        get_json = get_json or self._get
        pending: dict[str, str] = {}          # task_id -> asin
        lots_en_echec: list[tuple[int, str]] = []
        lots_exception: list[tuple[int, str]] = []
        # TOUS les lots partent AVANT la première lecture : la file DataForSEO est par
        # tâche, ~250 s quel que soit le volume. Poster puis poller lot par lot la ferait
        # payer une fois par lot — exactement ce que le batch unique existe pour éviter.
        for debut in range(0, len(asins), LOT_ASIN_MAX):
            lot = asins[debut:debut + LOT_ASIN_MAX]
            body = [{"asin": a, "location_code": self.location_code,
                     "language_code": self.language_code, "priority": self.priority}
                    for a in lot]
            try:
                d = post_json(_ASIN_BASE + "/task_post", body)
            except Exception as exc:              # noqa: BLE001
                # Un lot qui échoue à l'ENVOI a PU créer ses tâches : un ReadTimeout à 30 s
                # veut dire que la requête est partie et que la réponse s'est perdue. On ne
                # peut pas le savoir d'ici, donc on impute le PIRE cas (§5.29, règle 2), au
                # lieu de l'annoncer « non facturé » — le chemin SERP des trois moteurs code
                # déjà ce pire cas sur le même `_post`. Ses ASIN restent None.
                # Et on CONTINUE : les lots déjà ACCEPTÉS sont facturés, lever ici les
                # abandonnait sans relecture ni imputation, et le low-content les repayait
                # ensuite par le canal BSR (famille §5.31).
                lots_exception.append((len(lot), type(exc).__name__))
                continue
            tasks = d.get("tasks") or []
            if d.get("status_code") not in (None, 20000, 20100) or not tasks:
                # Refus de COMPTE (non verifie, identifiants, solde) : pose a la RACINE, sans
                # aucune tache. Rien n'est cree, donc rien n'est facture -- mais le batch
                # rendait des payloads vides SANS dire pourquoi, ce qu'un solde epuise en
                # cours de run aurait produit a l'identique. Le motif part a l'ecran par
                # `lots_en_echec`, que `enrich_asins` annonce deja.
                motif = _motif_refus(d)
                lots_en_echec.append((len(lot), motif))
                if not tasks and d.get("status_code") not in (None, 20000, 20100):
                    # Refus de COMPTE (meme critere que `RefusCompte` cote SERP) : les lots
                    # suivants seraient refuses de meme. Les envoyer quand meme faisait un
                    # task_post refuse de plus par lot -- la rafale qu'un compte refuse ne doit
                    # plus recevoir (suspension 40201 au run 3 ; releve au rejeu du 2026-09-14,
                    # 100 + 85). Ils sont COMPTES, pas envoyes. Une exception a l'envoi, elle,
                    # n'arrete rien : rien ne dit que le lot suivant echouera.
                    reste = len(asins) - (debut + len(lot))
                    if reste:
                        lots_en_echec.append((reste, f"{motif} — non envoyé(s) : compte refusé"))
                    break
                continue
            du_lot = set(lot)
            refusees: dict[str, int] = {}
            for i, t in enumerate(tasks):
                if t.get("status_code") not in (20000, 20100):
                    # Refus PAR TACHE : saute en silence jusqu'ici. Compte, avec son motif.
                    motif = _motif_refus({}, t)
                    refusees[motif] = refusees.get(motif, 0) + 1
                    continue
                if not t.get("id"):
                    continue
                # task_post SEMBLE faire écho à l'ASIN posté (task["data"]["asin"]) — non
                # vérifié en live, aucune réponse task_post brute n'est capturée en
                # fixture. On s'y fie quand l'écho appartient au lot posté, sinon repli sur
                # la position DANS LE LOT : un écho hors lot classerait le payload sous une
                # clé fantôme et le perdrait pour l'ASIN demandé.
                echo = (t.get("data") or {}).get("asin")
                pos = lot[i] if i < len(lot) else None
                a = echo if echo in du_lot else pos
                if a:
                    pending[t["id"]] = a
            lots_en_echec.extend((n, motif) for motif, n in refusees.items())
        out = _Payloads({a: None for a in asins})
        out.taches_creees = len(pending)      # AVANT le poll, qui vide `pending`
        out.taches_incertaines = sum(n for n, _ in lots_exception)
        out.lots_en_echec = lots_en_echec
        out.lots_exception = lots_exception
        lectures_en_echec: dict[str, int] = {}
        for _ in range(max_polls):
            if not pending:
                break
            time.sleep(poll_interval)
            verifier_annulation()      # idem : un arret ne doit pas attendre la fin du lot
            for tid in list(pending):
                try:
                    r = (get_json(f"{_ASIN_BASE}/task_get/advanced/{tid}")
                         .get("tasks") or [{}])[0]
                    pret = r.get("status_code") == 20000 and r.get("result")
                except Exception as exc:          # noqa: BLE001
                    # UNE relecture illisible (502 HTML, coupure) levait hors de la boucle
                    # et abandonnait le lot ENTIER — 185 fiches déjà facturées au run 4. La
                    # tâche reste en attente et sera relue au cycle suivant ; l'échec est
                    # compté par type. Ctrl-C (BaseException) n'est PAS attrapé ici :
                    # `enrich_asins` l'impute puis le laisse remonter.
                    nom = type(exc).__name__
                    lectures_en_echec[nom] = lectures_en_echec.get(nom, 0) + 1
                    continue
                if pret:
                    asin, payload = pending.pop(tid), r["result"][0]
                    if journal is not None:
                        journal.append({"type": "asin", "asin": asin, "tache": tid,
                                        "payload": payload})
                    out[asin] = payload
        out.lectures_en_echec = lectures_en_echec
        out.lus = {a for a, p in out.items() if p is not None}
        return out

    def product_info_batch(self, asins, post_json=None, get_json=None,
                           poll_interval: float = 8, max_polls: int = 40) -> dict:
        """BSR de plusieurs ASIN (batché). Retour : {asin: BsrInfo|None}, qui porte aussi
        `lus` — les ASIN dont la fiche a été RELUE. `None` pour un ASIN lu = pas de rang
        Livres (une mesure) ; `None` hors de `lus` = rien n'a été lu (une panne).
        `resolve_bsrs` ne mémorise l'absence que pour les premiers.

        LIMITE CONNUE, faute de capture : une tâche qui se TERMINE sur un code d'erreur (ASIN
        retiré de la vente, par exemple) n'est jamais « prête » — seul `20000` avec un
        résultat l'est. Elle attend donc les `max_polls`, sort de `lus`, et reste une panne :
        jamais mémorisée comme absence, donc réattendue (~320 s) et repayée (0,003 $, si
        DataForSEO facture une tâche en erreur — non vérifié) à chaque run. Aucune réponse de
        ce type n'est capturée dans le dépôt : en inventer le code pour la classer « lue sans
        résultat » risquerait de figer une panne passagère dans le cache mutualisé. À relever
        dans une capture brute (R5) avant d'y toucher."""
        raw = self.product_raw_batch(asins, post_json=post_json, get_json=get_json,
                                     poll_interval=poll_interval, max_polls=max_polls)
        out = _Payloads({a: (parse_asin_bsr(r) if r else None) for a, r in raw.items()})
        for attr in ("taches_creees", "lots_en_echec", "lectures_en_echec", "lus"):
            setattr(out, attr, getattr(raw, attr, getattr(out, attr)))
        return out


_BSR_KEY_HINTS = ("meilleures ventes", "best sellers rank")
# « en Livres » DOIT être le rayon principal, pas le début d'une sous-catégorie :
# un ebook affiche « n°478 des titres gratuits dans la Boutique Kindle … 5 en Livres
# électroniques de fiction criminelle » -> sans le lookahead on renvoyait 5 (faux rang).
_MAIN_RANK = re.compile(r"([\d][\d\s .]{0,12})\s*en\s+Livres(?!\s+\w)", re.I)
_SUB_RANK = re.compile(r"([\d][\d\s .]*?)\s*en\s+([A-Za-zÀ-ÿ][^\n(]{1,60})", re.I)


def _bsr_to_int(s: str) -> int | None:
    digits = re.sub(r"[^\d]", "", s or "")
    return int(digits) if digits else None


def parse_asin_bsr(result: dict) -> BsrInfo | None:
    """Extrait le rang Livres d'une réponse DataForSEO ASIN (advanced). None si pas de rang Livres."""
    items = (result or {}).get("items") or []
    item = next((it for it in items if it.get("type") == "amazon_product_info"),
                items[0] if items else None)
    if not item:
        return None
    body: dict = {}
    for sec in (item.get("product_information") or []):
        b = sec.get("body")
        if isinstance(b, dict):
            body.update(b)
    bsr_val = next((v for k, v in body.items()
                    if isinstance(v, str) and any(h in k.lower() for h in _BSR_KEY_HINTS)), None)
    if not bsr_val:
        return None
    m = _MAIN_RANK.search(bsr_val)
    rank = _bsr_to_int(m.group(1)) if m else None
    if rank is None:
        return None
    subs: list[dict] = []
    for sm in _SUB_RANK.finditer(bsr_val):
        cat = sm.group(2).strip(" .,;:()")
        if cat.lower().startswith("livres") or "voir les" in cat.lower():
            continue
        r = _bsr_to_int(sm.group(1))
        if r and cat:
            subs.append({"category": cat[:60], "rank": r})
    return BsrInfo(rank_livres=rank, asin=(result.get("asin") or item.get("data_asin")),
                   subcategories=subs[:5], raw=bsr_val[:300])


_BSR_RAYON = re.compile(r".*?(?:\ben\b|\bdans\s+la\b)\s+(.+?)\s*$", re.I | re.S)


def parse_bsr_rank(raw) -> tuple[int | None, str | None, bool]:
    """(rang, rayon, gratuit) depuis une chaîne BSR Amazon.

    Le rang PRINCIPAL est dans la tête de chaîne (avant la 1re parenthèse) ; les
    sous-catégories suivent et ne doivent jamais être prises pour le rayon.
    « titres gratuits » = classement des gratuits, PAS un rang de ventes payantes."""
    head = (raw if isinstance(raw, str) else "").split("(")[0].strip()
    if not head:
        return None, None, False
    gratuit = "gratuit" in head.lower()
    m = _BSR_RAYON.match(head)
    rayon = m.group(1).strip(" .,;:") if m else None
    num = re.search(r"([\d][\d\s .]*)", head)
    return (_bsr_to_int(num.group(1)) if num else None), rayon, gratuit


_PROVIDERS = {"dataforseo": DataForSEOProvider}


def get_provider(name: str = "dataforseo", **kwargs):
    """Renvoie une instance de provider search (seam). Défaut : dataforseo."""
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"provider search inconnu : {name} (dispo : {list(_PROVIDERS)})")
    return cls(**kwargs)
