"""jobs.py — magasin de travaux asynchrones (SQLite, même pattern que cache.py : connexion
par appel + WAL, sûr en concurrence car le serveur lance un thread par run).

LE point du module : aujourd'hui (M6/M7) un scout vit dans le thread de la connexion SSE —
fermer l'onglet tue le run ET perd l'argent déjà dépensé. Ici le job vit dans la base, pas
dans la requête HTTP : un client qui se déconnecte peut revenir lire l'état plus tard.

`user_id` partout dès maintenant (défaut "local") : brancher l'authentification plus tard
devient un remplissage de colonne, pas une migration (cf. plan SaaS 2026-07-21, décision §)."""
import json
import sqlite3
import time
import uuid
from pathlib import Path

from pydantic import BaseModel, Field

STATUTS = ("en_attente", "en_cours", "termine", "echec", "annule")
DEFAULT_MAX_PROGRESS = 200      # un run de 15 min log beaucoup : borne la table, pas la RAM seule


class Job(BaseModel):
    """Un travail asynchrone (scout non-fiction ou fiction). `resultat`/`cout` restent des
    dict/list JSON-génériques : jobs.py ne connaît pas la forme de ScoredNiche/FictionNicheReport,
    seul l'appelant (web/server.py) sait ce qu'il y met."""
    id: str
    user_id: str = "local"
    type: str
    params: dict = Field(default_factory=dict)
    statut: str = "en_attente"          # ∈ STATUTS
    progression: list[str] = Field(default_factory=list)
    resultat: list | dict | None = None
    cout: dict | None = None
    erreur: str | None = None
    cree_le: float
    fini_le: float | None = None
    # None = ligne anterieure a la colonne (migration) : l'appelant retombe alors
    # sur `cree_le` plutot que de la traiter comme active a l'instant.
    maj_le: float | None = None


class JobStore:
    def __init__(self, path, now=None, max_progress: int = DEFAULT_MAX_PROGRESS):
        self.path = str(path)
        self.now = now or time.time
        self.max_progress = max_progress
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as cx:
            cx.execute(
                "CREATE TABLE IF NOT EXISTS jobs ("
                " id TEXT PRIMARY KEY,"
                " user_id TEXT NOT NULL,"
                " type TEXT NOT NULL,"
                " params TEXT NOT NULL,"
                " statut TEXT NOT NULL,"
                " progression TEXT NOT NULL,"
                " resultat TEXT,"
                " cout TEXT,"
                " erreur TEXT,"
                " cree_le REAL NOT NULL,"
                " fini_le REAL,"
                # Derniere activite CONNUE. C'est elle, et non l'age, qui fait l'orphelin :
                # un run fiction dure 10 a 15 minutes, le declarer mort sur son seul age
                # tuerait des runs vivants et perdrait un travail deja paye.
                " maj_le REAL"
                ")"
            )
            # Migration d'une base ANTERIEURE a cette colonne. Baptiste a deja un jobs.db :
            # sans ce rattrapage, le serveur planterait au demarrage sur SA base et jamais
            # sur une base neuve -- donc jamais en test.
            colonnes = {r[1] for r in cx.execute("PRAGMA table_info(jobs)")}
            if "maj_le" not in colonnes:
                cx.execute("ALTER TABLE jobs ADD COLUMN maj_le REAL")

    def _conn(self):
        cx = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        cx.execute("PRAGMA journal_mode=WAL")
        return cx

    # ── écriture ──
    def create(self, type: str, params: dict, user_id: str = "local") -> str:
        jid = uuid.uuid4().hex
        with self._conn() as cx:
            cx.execute(
                "INSERT INTO jobs (id, user_id, type, params, statut, progression, "
                "resultat, cout, erreur, cree_le, fini_le) "
                "VALUES (?, ?, ?, ?, 'en_attente', '[]', NULL, NULL, NULL, ?, NULL)",
                (jid, user_id, type, json.dumps(params, ensure_ascii=False), self.now()),
            )
        return jid

    def start(self, job_id: str) -> None:
        with self._conn() as cx:
            cx.execute("UPDATE jobs SET statut='en_cours', maj_le=? WHERE id=? AND statut!='annule'",
                       (self.now(), job_id))

    def append_progress(self, job_id: str, msg: str) -> None:
        """Ajoute un message et borne la liste aux `max_progress` derniers — un run de
        15 min qui log beaucoup ne doit pas gonfler la base sans fin."""
        with self._conn() as cx:
            row = cx.execute("SELECT progression FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                return
            prog = json.loads(row[0])
            prog.append(msg)
            prog = prog[-self.max_progress:]
            cx.execute("UPDATE jobs SET progression=?, maj_le=? WHERE id=?",
                       (json.dumps(prog, ensure_ascii=False), self.now(), job_id))

    def finish(self, job_id: str, resultat, cout: dict) -> None:
        with self._conn() as cx:
            cx.execute(
                "UPDATE jobs SET statut='termine', resultat=?, cout=?, fini_le=? "
                "WHERE id=? AND statut!='annule'",
                (json.dumps(resultat, ensure_ascii=False),
                 json.dumps(cout, ensure_ascii=False), self.now(), job_id),
            )

    # Les SEULS champs qu'un appel payant « a la piece » peut ranger dans une niche d'un
    # resultat. Une liste fermee : le client choisit la niche, jamais le nom du champ ecrit.
    CHAMPS_ANNOTABLES = ("verdict", "mots_cles")

    def annoter_resultat(self, job_id: str, user_id: str, cle: str, champ: str, valeur) -> bool:
        """Range `valeur` sous `champ` dans la niche `cle` du resultat d'un travail TERMINE.

        Pourquoi : l'analyse editoriale (~0,028 $) et les mots-cles KDP (~0,006 $) sont des
        appels a la piece. Leur resultat n'existait que dans la page : rouvrir une analyse ou
        recharger le faisait disparaitre, et le bouton proposait de le repayer.

        `cle` est le nom de la niche (non-fiction) ou sa requete Amazon (low-content). Rend
        False -- sans lever -- quand il n'y a rien a annoter : travail inconnu, d'un AUTRE
        utilisateur (connaitre un identifiant ne donne aucun droit d'ecriture), sans resultat,
        ou niche absente. BEGIN IMMEDIATE : lire puis reecrire tout le resultat sans le verrou
        perdrait l'annotation d'un appel concurrent (verdict et mots-cles se demandent a
        quelques secondes d'intervalle)."""
        if champ not in self.CHAMPS_ANNOTABLES:
            return False
        with self._conn() as cx:
            cx.isolation_level = None
            cx.execute("BEGIN IMMEDIATE")
            try:
                row = cx.execute("SELECT user_id, resultat FROM jobs WHERE id=?",
                                 (job_id,)).fetchone()
                if row is None or row[0] != user_id or row[1] is None:
                    cx.execute("ROLLBACK")
                    return False
                resultat = json.loads(row[1])
                cible = None
                if isinstance(resultat, list):
                    for entree in resultat:
                        if isinstance(entree, dict) and self._est_la_niche(entree, cle):
                            cible = entree
                            break
                if cible is None:
                    cx.execute("ROLLBACK")
                    return False
                cible[champ] = valeur
                cx.execute("UPDATE jobs SET resultat=? WHERE id=?",
                           (json.dumps(resultat, ensure_ascii=False), job_id))
                cx.execute("COMMIT")
                return True
            except Exception:
                cx.execute("ROLLBACK")
                raise

    @staticmethod
    def _est_la_niche(entree: dict, cle: str) -> bool:
        niche = entree.get("niche")
        if isinstance(niche, dict):                  # low-content : requete Amazon d'abord
            return cle in (niche.get("requete_amazon"), niche.get("niche"))
        return niche == cle                          # non-fiction : le nom de la niche

    def fail(self, job_id: str, erreur: str, cout: dict | None = None) -> None:
        """L'argent dépensé avant l'échec reste imputé — sinon on facture dans le vide."""
        with self._conn() as cx:
            cx.execute(
                "UPDATE jobs SET statut='echec', erreur=?, cout=?, fini_le=? "
                "WHERE id=? AND statut!='annule'",
                (erreur, json.dumps(cout, ensure_ascii=False) if cout is not None else None,
                 self.now(), job_id),
            )

    def claim_next(self) -> "Job | None":
        """Reserve ATOMIQUEMENT le plus ancien travail en attente, ou rend None.

        Deux workers qui prendraient le meme job le paieraient DEUX fois : deux fois les
        SERP, deux fois les tokens. C'est le seul endroit du depot ou une course coute de
        l'argent reel -- d'ou BEGIN IMMEDIATE, qui prend le verrou d'ecriture AVANT le
        SELECT. Sans lui, deux processus lisent la meme ligne libre puis l'ecrivent tous
        les deux, et SQLite ne s'y oppose pas."""
        with self._conn() as cx:
            cx.isolation_level = None
            cx.execute("BEGIN IMMEDIATE")
            try:
                # EQUITE D'ABORD, chronologie ensuite. Une file purement
                # chronologique laisse un utilisateur qui lance cinq analyses occuper
                # cinq creneaux et faire attendre tout le monde derriere lui. Le plafond
                # mensuel ne protege pas de ca : il compte des analyses sur trente jours,
                # pas des creneaux a l'instant t. On sert donc celui qui en occupe le
                # MOINS, et l'anciennete ne departage qu'a egalite -- l'ordre d'arrivee
                # n'est pas supprime, il est seulement precede.
                row = cx.execute(
                    "SELECT j.id FROM jobs j WHERE j.statut='en_attente' "
                    "ORDER BY (SELECT COUNT(*) FROM jobs r "
                    "          WHERE r.statut='en_cours' AND r.user_id = j.user_id) ASC, "
                    "         j.cree_le ASC LIMIT 1").fetchone()
                if row is None:
                    cx.execute("COMMIT")
                    return None
                jid = row[0]
                # `maj_le` est pose DES la reservation : un job a peine reclame n'a pas
                # encore logue sa premiere etape, et serait vu orphelin par le worker
                # suivant.
                cx.execute("UPDATE jobs SET statut='en_cours', maj_le=? WHERE id=?",
                           (self.now(), jid))
                cx.execute("COMMIT")
            except Exception:
                cx.execute("ROLLBACK")
                raise
        return self.get(jid)

    def derniere_activite(self, job_id: str) -> float | None:
        j = self.get(job_id)
        if j is None:
            return None
        # Repli sur `cree_le` pour les lignes anterieures a la colonne : les traiter comme
        # "actives a l'instant" les rendrait immortelles.
        return j.maj_le if j.maj_le is not None else j.cree_le

    def orphelins(self, depuis_s: float = 1800) -> list["Job"]:
        """Travaux `en_cours` sans le moindre signe de vie depuis `depuis_s`.

        C'est l'ABSENCE DE PROGRESSION qui fait l'orphelin, pas l'age. Un run fiction dure
        10 a 15 minutes : trier sur l'anciennete tuerait des runs vivants."""
        limite = self.now() - depuis_s
        with self._conn() as cx:
            rows = cx.execute(
                "SELECT id, user_id, type, params, statut, progression, resultat, cout, "
                "erreur, cree_le, fini_le, maj_le FROM jobs "
                "WHERE statut='en_cours' AND COALESCE(maj_le, cree_le) < ? "
                "ORDER BY cree_le ASC", (limite,)).fetchall()
        return [self._row_to_job(r) for r in rows]

    MESSAGE_ANNULE = "Arrêtée à votre demande."

    def annuler(self, job_id: str, user_id: str) -> str:
        """Arrete UNE analyse de l'utilisateur : « annule », « deja_fini » ou « introuvable ».

        IMMEDIAT cote donnees : le statut passe a « annule » tout de suite, l'utilisateur voit son
        analyse arretee et peut la supprimer ou en relancer une. Le thread, lui, s'arrete a son
        prochain point de controle (cf. annulation.py) ; `finish`, `fail` et `start` ne font
        jamais revenir un travail annule a un autre etat.

        « introuvable » couvre aussi le travail d'un AUTRE compte (on ne confirme pas qu'un
        identifiant existe). BEGIN IMMEDIATE : un `finish` concurrent ne doit pas passer entre
        la lecture du statut et son ecriture."""
        with self._conn() as cx:
            cx.isolation_level = None
            cx.execute("BEGIN IMMEDIATE")
            try:
                row = cx.execute("SELECT user_id, statut FROM jobs WHERE id=?", (job_id,)).fetchone()
                if row is None or row[0] != user_id:
                    cx.execute("ROLLBACK")
                    return "introuvable"
                if row[1] not in ("en_attente", "en_cours"):
                    cx.execute("ROLLBACK")
                    return "deja_fini"
                cx.execute("UPDATE jobs SET statut='annule', erreur=?, fini_le=?, maj_le=? WHERE id=?",
                           (self.MESSAGE_ANNULE, self.now(), self.now(), job_id))
                cx.execute("COMMIT")
                return "annule"
            except Exception:
                cx.execute("ROLLBACK")
                raise

    def est_annule(self, job_id: str) -> bool:
        with self._conn() as cx:
            row = cx.execute("SELECT statut FROM jobs WHERE id=?", (job_id,)).fetchone()
        return bool(row) and row[0] == "annule"

    def enregistrer_cout_annule(self, job_id: str, cout: dict) -> None:
        """Le cout deja engage d'une analyse arretee : il reste sur le travail, comme pour un
        echec (l'argent parti est compte)."""
        with self._conn() as cx:
            cx.execute("UPDATE jobs SET cout=? WHERE id=? AND statut='annule'",
                       (json.dumps(cout, ensure_ascii=False), job_id))

    def supprimer(self, job_id: str, user_id: str) -> str:
        """Supprime UNE analyse de l'utilisateur : « supprime », « introuvable » ou « en_cours ».

        « introuvable » couvre aussi le travail d'un AUTRE compte : distinguer les deux
        confirmerait qu'un identifiant existe. Une analyse pas finie (en attente ou en cours)
        ne se supprime pas : son thread ecrirait ensuite dans une ligne disparue, et
        l'usage reserve ne serait jamais solde proprement.

        Ne touche NI a la consommation (usage.db : supprimer de l'ecran ne rembourse rien et ne
        doit pas liberer d'unite de plafond), NI a l'historique d'evolution des niches."""
        with self._conn() as cx:
            cx.isolation_level = None
            cx.execute("BEGIN IMMEDIATE")
            try:
                row = cx.execute("SELECT user_id, statut FROM jobs WHERE id=?", (job_id,)).fetchone()
                if row is None or row[0] != user_id:
                    cx.execute("ROLLBACK")
                    return "introuvable"
                if row[1] in ("en_attente", "en_cours"):
                    cx.execute("ROLLBACK")
                    return "en_cours"
                cx.execute("DELETE FROM jobs WHERE id=?", (job_id,))
                cx.execute("COMMIT")
                return "supprime"
            except Exception:
                cx.execute("ROLLBACK")
                raise

    # ── lecture ──
    def supprimer_utilisateur(self, user_id: str) -> int:
        """Efface tout ce qu'un compte a produit ici. Rend le nombre de lignes supprimées.

        Appelé par la clôture de compte (§2.1) : supprimer le compte sans ses données
        laisserait des lignes orphelines, rattachées à un `user_id` dont plus personne ne
        connaît l'adresse. Un compte qui n'a rien produit rend 0, sans lever — une clôture
        ne doit pas échouer sur une absence."""
        with self._conn() as cx:
            return cx.execute("DELETE FROM jobs WHERE user_id=?", (user_id,)).rowcount

    @staticmethod
    def _row_to_job(row: tuple) -> Job:
        (jid, user_id, type_, params, statut, progression, resultat, cout, erreur,
         cree_le, fini_le, maj_le) = row
        return Job(
            id=jid, user_id=user_id, type=type_, params=json.loads(params),
            statut=statut, progression=json.loads(progression),
            resultat=json.loads(resultat) if resultat is not None else None,
            cout=json.loads(cout) if cout is not None else None,
            erreur=erreur, cree_le=cree_le, fini_le=fini_le, maj_le=maj_le,
        )

    def get(self, job_id: str) -> Job | None:
        with self._conn() as cx:
            row = cx.execute(
                "SELECT id, user_id, type, params, statut, progression, resultat, cout, "
                "erreur, cree_le, fini_le, maj_le FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, user_id: str = "local", limit: int | None = None) -> list[Job]:
        """Les plus récents d'abord (recence = cree_le décroissant)."""
        sql = ("SELECT id, user_id, type, params, statut, progression, resultat, cout, "
               "erreur, cree_le, fini_le, maj_le FROM jobs WHERE user_id=? ORDER BY cree_le DESC")
        params: tuple = (user_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (user_id, limit)
        with self._conn() as cx:
            rows = cx.execute(sql, params).fetchall()
        return [self._row_to_job(r) for r in rows]


# 30 min sans le moindre signe de vie. Le run le plus long du produit (fiction, 8 trios)
# tient en 10 à 15 minutes, batch ASIN compris : le double laisse la marge d'une file
# DataForSEO lente sans laisser un zombie une journée entière.
ORPHELIN_APRES_S = 30 * 60


def recuperer_orphelins(store: JobStore, depuis_s: float = ORPHELIN_APRES_S,
                        journal=print, prefixe: str = "[worker]") -> int:
    """Passe en échec les travaux interrompus. Rend combien ont été récupérés.

    Le coût déjà mesuré est CONSERVÉ (§5.29) : le remettre à zéro ferait croire qu'un run
    interrompu était gratuit. La progression est conservée aussi — ce qui a été fait avant
    la coupure reste lisible, et c'est la seule chose qui dit à l'utilisateur où il en
    était.

    **Vit ICI et pas dans `worker.py`, alors que c'est le worker qui l'a fait naître.**
    Le serveur en a besoin aussi : en `JOBS_MODE=thread` — le défaut — il n'y a aucun
    worker, et un run coupé par un redémarrage resterait `en_cours` pour toujours. Or
    `worker.py` importe `server`, donc `server` ne peut pas importer `worker` : la
    recopier des deux côtés était la seule autre issue, et deux implémentations
    divergent. Celle qui divergerait serait justement celle qui ne tourne pas sur le
    poste où l'on teste.

    `prefixe` n'est pas cosmétique : dans un journal partagé, savoir si c'est le serveur
    ou le worker qui a récupéré un travail dit lequel des deux processus a redémarré."""
    n = 0
    for job in store.orphelins(depuis_s=depuis_s):
        store.fail(job.id,
                   "Analyse interrompue (redémarrage du service). Le travail déjà "
                   "effectué est conservé ci-dessus ; relancez pour terminer.",
                   cout=job.cout)
        journal(f"{prefixe} job {job.id} ({job.type}) récupéré : interrompu")
        n += 1
    return n
