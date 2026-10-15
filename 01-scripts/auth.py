"""auth.py — comptes email/mot de passe et sessions.

C'est le seul module du dépôt dont un défaut ne produit pas un mauvais chiffre mais une
COMPROMISSION. Les autres modules se trompent ; celui-ci fuit. D'où les partis pris
ci-dessous, tous testés dans `tests/test_auth.py` avec la menace qu'ils ferment.

**Aucune dépendance ajoutée.** `hashlib.scrypt` est dans la bibliothèque standard depuis
Python 3.6 et figure parmi les fonctions de dérivation recommandées par l'OWASP quand
argon2id n'est pas disponible. Ajouter `bcrypt` ou `argon2-cffi` aurait été défendable,
mais pas au prix d'une dépendance native de plus dans un produit qu'un client devra
installer — et scrypt correctement paramétré n'est pas le maillon faible ici.

Ce qu'on ne stocke JAMAIS :
- le mot de passe (évidemment) — seulement scrypt(mot de passe, sel propre au compte) ;
- le jeton de session en clair — seulement son SHA-256. Sans cela, lire la base suffirait
  à voler une session sans connaître le moindre mot de passe.

Ce que `verifier()` ne révèle jamais : si l'email existe. Ni par le message (il rend
`None` dans les deux cas), ni par le TEMPS DE RÉPONSE — un email inconnu déclenche quand
même une dérivation sur un leurre, sinon la rapidité de la réponse trahirait l'absence de
compte et permettrait d'énumérer les clients avec une simple liste d'adresses.

Même motif SQLite que `cache.py` / `usage.py` : connexion par appel + WAL, sûr en
concurrence (le serveur lance un thread par run).

RAPPEL D'ARCHITECTURE (CLAUDE.md) : `user_id` cloisonne `history.py`, `usage.py` et
`jobs.py` — JAMAIS `cache.py`. Le cache de scraping reste mutualisé entre tous les
comptes : c'est ce qui évite de repayer deux fois la même donnée DataForSEO, et c'est
l'économie principale à l'échelle. Y introduire un `user_id` « par cohérence » serait une
régression économique silencieuse.
"""
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

from pydantic import BaseModel

import essai

LONGUEUR_MIN_MOT_DE_PASSE = 12
# Plafond de longueur. Sans lui, un mot de passe de plusieurs mégaoctets fait tourner
# scrypt très longtemps, et quelques requêtes parallèles figent le serveur — sans
# authentification et sans coût pour l'attaquant. Mesuré en revue de sécurité.
LONGUEUR_MAX_MOT_DE_PASSE = 128
SESSION_TTL_S = 30 * 24 * 3600          # 30 jours : au-delà, on redemande le mot de passe

# Limitation des tentatives : le chemin LE PLUS COURT vers une prise de compte. Sans
# elle, un top-1000 de mots de passe se teste en ligne en moins d'une minute contre une
# adresse connue. Verrou par e-mail, sur une fenêtre glissante.
MAX_TENTATIVES = 8
FENETRE_TENTATIVES_S = 15 * 60

# Inscriptions depuis un MÊME client sur la fenêtre. Le compteur porte ici sur le client et
# non sur l'adresse : sonder mille adresses différentes ne déclencherait jamais un compteur
# par adresse, alors que c'est exactement le mode opératoire de l'énumération en masse.
MAX_INSCRIPTIONS_PAR_CLIENT = 10

# Jetons envoyés par e-mail. Un lien traîne dans une boîte, un historique, un relais : il vit peu
# (la réinitialisation donne la main sur le compte, une heure suffit) et ne sert qu'UNE fois.
TTL_JETON_VERIFICATION_S = 48 * 3600
TTL_JETON_REINITIALISATION_S = 3600
USAGES_JETON = ("verification", "reinitialisation")

# Mots de passe interdits parce qu'ils sont en tête de tous les dictionnaires d'attaque,
# y compris au-delà de 12 caractères. La revue a MESURÉ que c'est la politique de mot de
# passe — et non le réglage de scrypt — qui décide si un dictionnaire casse les comptes :
# le même dictionnaire de 10 000 entrées tombe dans les trois paramétrages de scrypt
# testés (6,9 / 34 / 60 min). Durcir scrypt sans cette liste n'aurait sauvé aucun compte.
MOTS_DE_PASSE_INTERDITS = frozenset({
    "azertyuiop", "qwertyuiop", "motdepasse", "password", "123456789", "1234567890",
    "12345678901", "123456789012", "azerty123456", "motdepasse1", "administrateur",
    "bonjour12345", "iloveyou1234", "0000000000", "1111111111", "aaaaaaaaaaaa",
    "abcdefghijkl", "password1234", "motdepasse12", "azertyuiop12", "qwertyuiop12",
    "loulou123456", "soleil123456", "chouchou1234", "motdepasse123", "azertyuiop123",
})

# Paramètres scrypt. n=2^14 -> 128*r*n = 16 Mo de mémoire par vérification et ~45 ms sur le
# poste de mesure : assez coûteux pour rendre une attaque par dictionnaire pénible, assez
# rapide pour ne pas transformer une connexion en attente. Ils sont ÉCRITS DANS LA BASE avec
# chaque empreinte (colonne `params`) : les durcir plus tard ne doit pas invalider les
# comptes existants, c'est la raison d'être de cette colonne.
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN = 2 ** 14, 8, 1, 32

# Volontairement permissif : le seul juge de la validité d'une adresse est le serveur de
# messagerie. On écarte ce qui est manifestement faux (pas d'arobase, pas de point dans le
# domaine, partie vide) plutôt que d'inventer une grammaire RFC 5322 qui rejetterait des
# adresses légitimes — un client qui ne peut pas s'inscrire ne se plaint pas, il part.
# Volontairement permissive (« le seul juge de la validité d'une adresse est le serveur de messagerie »),
# SAUF les délimiteurs d'adresse : `msg["To"] = "a,b@x.com"` s'analyse en DEUX destinataires, et une
# inscription ferait alors envoyer le lien de vérification à un tiers (revue du 2026-10-06).
_EMAIL = re.compile(r'^[^@\s,;:<>()\[\]\\"]+@[^@\s,;:<>()\[\]\\"]+\.[^@\s,;:<>()\[\]\\"]+$')


class EmailInvalide(ValueError):
    pass


class EmailDejaPris(ValueError):
    pass


class MotDePasseFaible(ValueError):
    pass


class IdentifiantsInvalides(ValueError):
    """Le mot de passe ACTUEL ne correspond pas. Distincte de `MotDePasseFaible` : l'une dit
    « vous n'êtes pas qui vous prétendez », l'autre « votre nouveau mot de passe ne tient
    pas ». Les confondre ferait afficher la politique à qui n'a pas prouvé son identité."""


class TropDeTentatives(ValueError):
    """L'e-mail a épuisé son quota d'essais sur la fenêtre courante."""
    pass


class Compte(BaseModel):
    """Un compte, sans rien de secret : ce type est sérialisable vers l'interface."""
    user_id: str
    email: str
    cree_le: float = 0.0
    # Défaut PESSIMISTE : une adresse n'est vérifiée que lorsqu'un lien envoyé à elle a servi.
    email_verifie: bool = False
    # Défaut PESSIMISTE aussi : un compte dont on ignore le plan est un essai, jamais un illimité.
    plan: str = essai.PLAN_ESSAI


def valider_mot_de_passe(mot_de_passe) -> str:
    """Applique la politique de mot de passe. Rend la valeur, ou lève MotDePasseFaible.

    L'ordre des contrôles compte : la longueur MAXIMALE passe avant tout le reste, parce
    que son rôle est précisément d'éviter de lancer scrypt sur une entrée démesurée."""
    if not isinstance(mot_de_passe, str):
        raise MotDePasseFaible("le mot de passe doit être du texte")
    if len(mot_de_passe) > LONGUEUR_MAX_MOT_DE_PASSE:
        raise MotDePasseFaible(
            f"le mot de passe ne doit pas dépasser {LONGUEUR_MAX_MOT_DE_PASSE} caractères")
    if len(mot_de_passe) < LONGUEUR_MIN_MOT_DE_PASSE:
        raise MotDePasseFaible(
            f"le mot de passe doit faire au moins {LONGUEUR_MIN_MOT_DE_PASSE} caractères")
    if mot_de_passe.strip().lower() in MOTS_DE_PASSE_INTERDITS:
        raise MotDePasseFaible(
            "ce mot de passe est trop courant — il figure en tête des dictionnaires "
            "utilisés pour attaquer les comptes")
    return mot_de_passe


def normaliser_email(email: str) -> str:
    """Casse et espaces retirés. « Baptiste@Example.COM » et « baptiste@example.com » sont
    le même compte : sinon un client se crée un doublon sans comprendre où est passé son
    historique. On ne touche PAS à la partie locale au-delà de la casse (pas de retrait des
    points ni du +suffixe) : ce serait un choix de fournisseur, pas une règle générale."""
    if not isinstance(email, str):
        return ""
    return email.strip().lower()


class UserStore:
    def __init__(self, path, now=None):
        self.path = str(path)
        self.now = now or time.time
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as cx:
            cx.execute(
                "CREATE TABLE IF NOT EXISTS comptes ("
                " user_id TEXT PRIMARY KEY,"
                " email TEXT NOT NULL UNIQUE,"
                " sel BLOB NOT NULL,"
                " empreinte BLOB NOT NULL,"
                " params TEXT NOT NULL,"          # durcir scrypt plus tard sans tout casser
                " cree_le REAL NOT NULL,"
                " email_verifie INTEGER NOT NULL DEFAULT 0,"
                # Le plan : `essai` (défaut — côté sûr), `abonne`, `illimite`. Voir essai.py.
                " plan TEXT NOT NULL DEFAULT 'essai',"
                " essai_recherches INTEGER NOT NULL DEFAULT 0,"   # recherches d'essai prises
                " essai_id INTEGER"                              # ligne de `essais` (NULL = pas démarré)
                ")"
            )
            # Base créée avant la colonne : ses comptes sont LOCAUX (aucune instance n'a jamais été
            # exposée), les déclarer non vérifiés ne ferait que verrouiller leur propriétaire
            # dehors. `creer_compte` pose toujours la valeur explicitement : ce DEFAULT 1 ne vaut
            # que pour les lignes qui existaient.
            colonnes = {r[1] for r in cx.execute("PRAGMA table_info(comptes)")}
            if "email_verifie" not in colonnes:
                cx.execute("ALTER TABLE comptes ADD COLUMN email_verifie "
                           "INTEGER NOT NULL DEFAULT 1")
            if "plan" not in colonnes:
                self._migrer_plan(cx)
            cx.execute(
                "CREATE TABLE IF NOT EXISTS essais ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                # Empreintes HMAC (jamais l'adresse, le domaine ni le réseau en clair), SANS lien vers le
                # compte : supprimer un compte ne doit pas rendre l'essai qu'il a consommé.
                " identite TEXT NOT NULL,"
                " domaine TEXT NOT NULL,"
                " reseau TEXT,"                     # NULL : l'adresse du client ne prouvait rien
                " demarre_le REAL NOT NULL"
                ")"
            )
            cx.execute("CREATE INDEX IF NOT EXISTS idx_essais_identite ON essais (identite)")
            cx.execute("CREATE INDEX IF NOT EXISTS idx_essais_reseau ON essais (reseau, demarre_le)")
            cx.execute("CREATE INDEX IF NOT EXISTS idx_essais_domaine ON essais (domaine, demarre_le)")
            cx.execute("CREATE INDEX IF NOT EXISTS idx_essais_date ON essais (demarre_le)")
            cx.execute("CREATE TABLE IF NOT EXISTS meta (cle TEXT PRIMARY KEY, valeur BLOB NOT NULL)")
            cx.execute(
                "CREATE TABLE IF NOT EXISTS jetons_courriel ("
                " empreinte TEXT PRIMARY KEY,"       # SHA-256, jamais le jeton en clair
                " user_id TEXT NOT NULL,"
                " usage TEXT NOT NULL,"
                " cree_le REAL NOT NULL,"
                " expire_le REAL NOT NULL,"
                " utilise INTEGER NOT NULL DEFAULT 0"
                ")"
            )
            cx.execute("CREATE INDEX IF NOT EXISTS idx_jetons_user "
                       "ON jetons_courriel (user_id, usage)")
            cx.execute(
                "CREATE TABLE IF NOT EXISTS sessions ("
                " jeton_empreinte TEXT PRIMARY KEY,"   # SHA-256, jamais le jeton en clair
                " user_id TEXT NOT NULL,"
                " cree_le REAL NOT NULL,"
                " expire_le REAL NOT NULL"
                ")"
            )
            cx.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user "
                       "ON sessions (user_id)")
            cx.execute(
                "CREATE TABLE IF NOT EXISTS tentatives ("
                " email TEXT NOT NULL,"
                " horodatage REAL NOT NULL"
                ")"
            )
            cx.execute("CREATE INDEX IF NOT EXISTS idx_tentatives "
                       "ON tentatives (email, horodatage)")

    def _conn(self):
        cx = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        cx.execute("PRAGMA journal_mode=WAL")
        return cx

    @staticmethod
    def _migrer_plan(cx) -> None:
        """Base créée avant la colonne `plan` : ses comptes sont LOCAUX (aucune instance n'a jamais été
        exposée), les passer en essai verrouillerait leur propriétaire dehors de son propre outil. Ils
        deviennent `illimite` ; tout compte créé ensuite est `essai` (DEFAULT de la colonne).

        ALTER et UPDATE dans UNE transaction, colonnes relues DEDANS : deux processus qui ouvrent la base
        en même temps ne doivent pas faire repasser en illimité un compte d'essai créé entre-temps."""
        cx.execute("BEGIN IMMEDIATE")
        try:
            colonnes = {r[1] for r in cx.execute("PRAGMA table_info(comptes)")}
            if "plan" not in colonnes:
                cx.execute("ALTER TABLE comptes ADD COLUMN plan TEXT NOT NULL DEFAULT 'essai'")
                cx.execute("UPDATE comptes SET plan='illimite'")
            if "essai_recherches" not in colonnes:
                cx.execute("ALTER TABLE comptes ADD COLUMN essai_recherches INTEGER NOT NULL DEFAULT 0")
            if "essai_id" not in colonnes:
                cx.execute("ALTER TABLE comptes ADD COLUMN essai_id INTEGER")
            cx.execute("COMMIT")
        except Exception:
            cx.execute("ROLLBACK")
            raise

    # ── Mots de passe ───────────────────────────────────────────────────────────────

    def _deriver(self, mot_de_passe: str, sel: bytes,
                 n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> bytes:
        """Dérivation scrypt. Extraite en méthode pour deux raisons : elle est appelée sur
        un leurre quand le compte n'existe pas (cf. `verifier`), et un test vérifie qu'elle
        l'est bien — c'est ce qui garantit l'égalité des temps de réponse."""
        return hashlib.scrypt(mot_de_passe.encode("utf-8"), salt=sel,
                              n=n, r=r, p=p, dklen=SCRYPT_DKLEN,
                              maxmem=132 * r * n + 1024)

    # ── Comptes ─────────────────────────────────────────────────────────────────────

    def creer_compte(self, email: str, mot_de_passe: str, plan: str = essai.PLAN_ESSAI) -> Compte:
        """`plan` vaut `essai` sauf demande : c'est l'APPELANT qui décide qu'un compte est illimité (le
        premier compte, par amorçage), jamais un défaut de ce magasin."""
        if plan not in essai.PLANS:
            raise ValueError(f"plan inconnu : « {plan} » (attendu : {', '.join(essai.PLANS)})")
        propre = normaliser_email(email)
        if not _EMAIL.match(propre):
            raise EmailInvalide("adresse e-mail invalide")
        valider_mot_de_passe(mot_de_passe)

        sel = secrets.token_bytes(16)          # sel PAR COMPTE : une table pré-calculée ne
        empreinte = self._deriver(mot_de_passe, sel)   # casse alors qu'un seul compte
        compte = Compte(user_id=uuid.uuid4().hex, email=propre, cree_le=self.now(), plan=plan)
        params = f"scrypt:{SCRYPT_N}:{SCRYPT_R}:{SCRYPT_P}"
        try:
            with self._conn() as cx:
                cx.execute("INSERT INTO comptes (user_id, email, sel, empreinte, params, "
                           "cree_le, email_verifie, plan) VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                           (compte.user_id, propre, sel, empreinte, params, compte.cree_le, plan))
        except sqlite3.IntegrityError as e:
            raise EmailDejaPris(f"un compte existe déjà pour « {propre} »") from e
        return compte

    # ── Limitation des tentatives ───────────────────────────────────────────────────

    def tentatives_recentes(self, cle: str) -> int:
        """Nombre d'échecs récents pour une clé. La clé est un e-mail pour la connexion,
        une adresse IP pour l'inscription — le choix dépend de ce qu'on protège : un
        compte ciblé dans un cas, le service entier dans l'autre."""
        return self._tentatives_recentes(cle)

    def noter_tentative(self, cle: str) -> None:
        self._noter_tentative(cle)

    @staticmethod
    def _cle_connexion(email: str) -> str:
        """Clé de la connexion dans la table des tentatives. L'« e-mail » d'une connexion est un
        texte LIBRE tapé par n'importe qui : noté tel quel, `reinit:victime@x.com` ou `ip:1.2.3.4`
        remplissait le compteur d'un autre usage (revue du 2026-10-06). Le préfixe `login:` fait que
        rien de ce qu'on saisit ici ne peut atteindre les clés `ip:`, `reinit:`, `verif:`."""
        return f"login:{email}"

    def _tentatives_recentes(self, email: str) -> int:
        with self._conn() as cx:
            return cx.execute("SELECT COUNT(*) FROM tentatives WHERE email=? AND "
                              "horodatage>?",
                              (email, self.now() - FENETRE_TENTATIVES_S)).fetchone()[0]

    def _noter_tentative(self, email: str) -> None:
        with self._conn() as cx:
            cx.execute("INSERT INTO tentatives (email, horodatage) VALUES (?, ?)",
                       (email, self.now()))
            # Purge opportuniste : c'est le seul moment où on touche cette table, elle ne
            # doit pas croître indéfiniment.
            cx.execute("DELETE FROM tentatives WHERE horodatage<?",
                       (self.now() - FENETRE_TENTATIVES_S,))

    def _oublier_tentatives(self, email: str) -> None:
        with self._conn() as cx:
            cx.execute("DELETE FROM tentatives WHERE email=?", (email,))

    def verifier(self, email: str, mot_de_passe: str) -> Compte | None:
        """Rend le compte, ou None. NE DIT JAMAIS lequel des deux a échoué — ni par le
        message, ni par le temps de réponse (voir le leurre plus bas).

        Lève `TropDeTentatives` au-delà de MAX_TENTATIVES échecs sur la fenêtre. C'est un
        état DISTINCT de « identifiants faux », que l'appelant traduit en 429 et non en
        401. Une connexion réussie remet le compteur à zéro."""
        propre = normaliser_email(email)
        if not isinstance(mot_de_passe, str):
            return None
        if len(mot_de_passe) > LONGUEUR_MAX_MOT_DE_PASSE:
            # Refusé AVANT scrypt : c'est tout l'intérêt du plafond de longueur.
            return None
        if self._tentatives_recentes(self._cle_connexion(propre)) >= MAX_TENTATIVES:
            raise TropDeTentatives(
                "trop de tentatives de connexion — réessayez dans quelques minutes")
        with self._conn() as cx:
            ligne = cx.execute(
                "SELECT user_id, sel, empreinte, params, cree_le, email_verifie, plan "
                "FROM comptes WHERE email=?", (propre,)).fetchone()

        if ligne is None:
            # Leurre : sans cette dérivation, répondre à un email inconnu serait
            # instantané et à un email connu lent — le temps de réponse suffirait à
            # énumérer les clients. On paie donc le même prix dans les deux cas.
            self._deriver(mot_de_passe or "", b"leurre-de-temps-constant")
            self._noter_tentative(self._cle_connexion(propre))
            return None

        user_id, sel, empreinte, params, cree_le, verifie, plan = ligne
        n, r, p = _lire_params(params)
        candidat = self._deriver(mot_de_passe or "", sel, n=n, r=r, p=p)
        # compare_digest et non « == » : une comparaison qui s'arrête au premier octet
        # différent laisse deviner l'empreinte octet par octet.
        if not hmac.compare_digest(candidat, empreinte):
            self._noter_tentative(self._cle_connexion(propre))
            return None
        self._oublier_tentatives(self._cle_connexion(propre))
        return Compte(user_id=user_id, email=propre, cree_le=cree_le, email_verifie=bool(verifie),
                      plan=plan)

    def compte(self, user_id: str) -> Compte | None:
        with self._conn() as cx:
            ligne = cx.execute("SELECT user_id, email, cree_le, email_verifie, plan FROM comptes "
                               "WHERE user_id=?", (user_id,)).fetchone()
        return (Compte(user_id=ligne[0], email=ligne[1], cree_le=ligne[2],
                       email_verifie=bool(ligne[3]), plan=ligne[4]) if ligne else None)

    def plan_de(self, user_id: str) -> str | None:
        """Le plan d'un compte, ou None s'il n'existe pas."""
        with self._conn() as cx:
            ligne = cx.execute("SELECT plan FROM comptes WHERE user_id=?", (user_id,)).fetchone()
        return ligne[0] if ligne else None

    def definir_plan(self, user_id: str, plan: str) -> None:
        """Change le plan d'un compte. C'est le point d'entrée du futur paiement (un webhook posera
        `abonne`), et de l'administration à la main. Ne touche pas aux compteurs d'essai."""
        if plan not in essai.PLANS:
            raise ValueError(f"plan inconnu : « {plan} » (attendu : {', '.join(essai.PLANS)})")
        with self._conn() as cx:
            cx.execute("UPDATE comptes SET plan=? WHERE user_id=?", (plan, user_id))

    def compte_par_email(self, email) -> Compte | None:
        """Le compte d'une adresse (casse et espaces ignorés), ou None. Sert à la demande de
        réinitialisation, dont la réponse ne doit JAMAIS dire si l'adresse existe."""
        propre = normaliser_email(email)
        if not propre:
            return None
        with self._conn() as cx:
            ligne = cx.execute("SELECT user_id FROM comptes WHERE email=?", (propre,)).fetchone()
        return self.compte(ligne[0]) if ligne else None

    def n_comptes(self) -> int:
        with self._conn() as cx:
            return cx.execute("SELECT COUNT(*) FROM comptes").fetchone()[0]

    def changer_mot_de_passe(self, email: str, ancien: str, nouveau: str,
                             garder: str | None = None) -> None:
        """Redéfinit le mot de passe. Exige l'ANCIEN, applique la politique, et ferme les
        autres sessions.

        Fermer les sessions n'est pas du zèle : on change son mot de passe précisément quand
        on craint qu'une session traîne ailleurs, et un jeton reste valide 30 jours. `garder`
        épargne la session COURANTE — se faire déconnecter de l'écran où l'on vient de taper
        son nouveau mot de passe se lirait comme un échec.

        L'identité est vérifiée AVANT la politique : afficher les règles de mot de passe à
        qui n'a pas prouvé qui il est serait une fuite gratuite."""
        compte = self.verifier(email, ancien)
        if compte is None:
            raise IdentifiantsInvalides("mot de passe actuel incorrect")
        valider_mot_de_passe(nouveau)
        sel = secrets.token_bytes(16)
        empreinte = self._deriver(nouveau, sel)
        params = f"scrypt:{SCRYPT_N}:{SCRYPT_R}:{SCRYPT_P}"
        with self._conn() as cx:
            cx.execute("UPDATE comptes SET sel=?, empreinte=?, params=? WHERE user_id=?",
                       (sel, empreinte, params, compte.user_id))
            if garder:
                cx.execute("DELETE FROM sessions WHERE user_id=? AND jeton_empreinte<>?",
                           (compte.user_id, _empreinte_jeton(garder)))
            else:
                cx.execute("DELETE FROM sessions WHERE user_id=?", (compte.user_id,))
            # Un lien de réinitialisation demandé AVANT ce changement ne doit pas pouvoir reprendre
            # la main APRÈS : on change son mot de passe précisément quand on craint pour le compte.
            cx.execute("DELETE FROM jetons_courriel WHERE user_id=? AND usage='reinitialisation'",
                       (compte.user_id,))

    def supprimer_compte(self, email: str, mot_de_passe: str) -> str:
        """Efface le compte et ses sessions. Rend le `user_id` supprimé, pour que l'appelant
        puisse effacer les données qui lui appartiennent ailleurs (historique, consommation,
        travaux) — ce magasin ne connaît que les comptes.

        Exige le mot de passe : une session volée ne doit pas pouvoir détruire le compte,
        c'est la seule action irréversible du produit."""
        compte = self.verifier(email, mot_de_passe)
        if compte is None:
            raise IdentifiantsInvalides("mot de passe incorrect")
        with self._conn() as cx:
            cx.execute("DELETE FROM sessions WHERE user_id=?", (compte.user_id,))
            cx.execute("DELETE FROM jetons_courriel WHERE user_id=?", (compte.user_id,))
            cx.execute("DELETE FROM comptes WHERE user_id=?", (compte.user_id,))
            cx.execute("DELETE FROM tentatives WHERE email=?", (self._cle_connexion(compte.email),))
        return compte.user_id

    # ── Essai gratuit (règles : essai.py) ───────────────────────────────────────────

    def _cle_empreinte(self) -> bytes:
        """La clé des empreintes d'essai, tirée au hasard UNE fois et rangée dans la base. Un SHA-256 nu
        d'une adresse se retrouve en testant une liste d'adresses : avec une clé que la base seule ne livre
        pas à qui lit ailleurs une copie, il faut aussi la clé. (Quiconque lit CETTE base lit les deux : ce
        n'est pas un coffre, c'est de la pseudonymisation — l'adresse ne traîne pas en clair, c'est tout.)"""
        with self._conn() as cx:
            cx.execute("INSERT OR IGNORE INTO meta (cle, valeur) VALUES ('empreinte', ?)",
                       (secrets.token_bytes(32),))
            return bytes(cx.execute("SELECT valeur FROM meta WHERE cle='empreinte'").fetchone()[0])

    def _empreinte(self, nature: str, valeur: str, cle: bytes | None = None) -> str:
        """HMAC-SHA256 de `valeur`, séparé par `nature` : la même chaîne n'a pas la même empreinte comme
        identité, domaine ou réseau."""
        cle = cle or self._cle_empreinte()
        return hmac.new(cle, f"{nature}\x00{valeur}".encode("utf-8"), hashlib.sha256).hexdigest()

    def reserver_recherche_essai(self, user_id: str, client: str | None = None,
                                 par_jour_max: int | None = None):
        """Prend UNE des deux recherches d'essai, ATOMIQUEMENT. Rend None pour un compte qui n'est pas en
        essai (rien à compter ni à refuser).

        La première recherche DÉMARRE l'essai : c'est là, et seulement là, qu'on juge l'identité, le domaine, le
        réseau et le plafond global du jour. Un compte créé et jamais utilisé ne pèse sur personne.

        `BEGIN IMMEDIATE` prend le verrou d'écriture AVANT de compter, comme `UsageMeter.reserver_analyse` : sans
        lui, vingt comptes qui démarrent ensemble lisent tous « 2 essais aujourd'hui » et passent tous. Les
        empreintes (qui lisent la base) sont calculées AVANT, hors transaction.

        Lève `EssaiEpuise`, `EssaiRefuse` ou `QuotaJournalier` ; rien n'est alors consommé."""
        if par_jour_max is None:
            par_jour_max = essai.essais_par_jour_max()
        with self._conn() as cx:
            ligne = cx.execute("SELECT email, plan FROM comptes WHERE user_id=?", (user_id,)).fetchone()
        if ligne is None or ligne[1] != essai.PLAN_ESSAI:
            return None
        email = ligne[0]
        identite_claire, dom = essai.identite_courriel(email), essai.domaine(email)
        reseau = essai.empreinte_reseau(client)
        cle = self._cle_empreinte()
        h_identite = self._empreinte("identite", identite_claire, cle)
        # Le domaine qu'on ACHÈTE, pas l'hôte : `x1.mondomaine.fr`, `x2.mondomaine.fr`… sont un seul domaine.
        h_domaine = self._empreinte("domaine", essai.domaine_enregistrable(dom), cle)
        h_reseau = self._empreinte("reseau", reseau, cle) if reseau else None
        maintenant = self.now()

        with self._conn() as cx:
            cx.isolation_level = None
            cx.execute("BEGIN IMMEDIATE")
            try:
                ligne = cx.execute("SELECT plan, essai_recherches, essai_id FROM comptes "
                                   "WHERE user_id=?", (user_id,)).fetchone()
                if ligne is None or ligne[0] != essai.PLAN_ESSAI:
                    cx.execute("ROLLBACK")
                    return None
                _, prises, essai_id = ligne
                if prises >= essai.ESSAI_RECHERCHES:
                    raise essai.EssaiEpuise("les recherches d'essai sont toutes utilisées")
                demarre_ici = False
                if essai_id is None:
                    cx.execute("DELETE FROM essais WHERE demarre_le<?",
                               (maintenant - essai.CONSERVATION_IDENTITE_S,))
                    depuis = maintenant - essai.FENETRE_ESSAI_S
                    # Minimisation : le réseau et le domaine ne servent qu'à la fenêtre de 30 jours, l'identité
                    # seule est gardée un an. Purge opportuniste (comme `tentatives`) : elle a lieu à chaque départ.
                    cx.execute("UPDATE essais SET domaine='', reseau=NULL WHERE demarre_le<? "
                               "AND (domaine<>'' OR reseau IS NOT NULL)", (depuis,))
                    if (not identite_claire or essai.est_jetable(dom)
                            or cx.execute("SELECT 1 FROM essais WHERE identite=?",
                                          (h_identite,)).fetchone()
                            or (h_reseau is not None and cx.execute(
                                "SELECT COUNT(*) FROM essais WHERE reseau=? AND demarre_le>=?",
                                (h_reseau, depuis)).fetchone()[0] >= essai.ESSAI_PAR_RESEAU)
                            or (not essai.est_courant(dom) and cx.execute(
                                "SELECT COUNT(*) FROM essais WHERE domaine=? AND demarre_le>=?",
                                (h_domaine, depuis)).fetchone()[0] >= essai.ESSAI_PAR_DOMAINE)):
                        raise essai.EssaiRefuse("pas d'essai pour cette adresse ou ce réseau")
                    # Le plafond du jour vient APRÈS : « revenez demain » à quelqu'un qui n'aura jamais
                    # droit à l'essai serait un mensonge qui le ferait revenir.
                    if cx.execute("SELECT COUNT(*) FROM essais WHERE demarre_le>=?",
                                  (maintenant - essai.FENETRE_JOUR_S,)).fetchone()[0] >= par_jour_max:
                        raise essai.QuotaJournalier("plafond de nouveaux essais atteint pour aujourd'hui")
                    cur = cx.execute("INSERT INTO essais (identite, domaine, reseau, demarre_le) "
                                     "VALUES (?, ?, ?, ?)", (h_identite, h_domaine, h_reseau, maintenant))
                    cx.execute("UPDATE comptes SET essai_id=? WHERE user_id=?",
                               (cur.lastrowid, user_id))
                    demarre_ici = True
                cx.execute("UPDATE comptes SET essai_recherches=essai_recherches+1 WHERE user_id=?",
                           (user_id,))
                cx.execute("COMMIT")
                return essai.ReservationEssai(demarre_ici=demarre_ici)
            except Exception:
                cx.execute("ROLLBACK")
                raise

    def rendre_recherche_essai(self, user_id: str, annuler_demarrage: bool = False) -> None:
        """Redonne UNE recherche : le lancement a échoué avant de livrer quoi que ce soit (même règle que
        les niches : ce qui n'a rien coûté ni rien rendu ne se décompte pas). Sans effet hors essai, jamais
        sous zéro.

        `annuler_demarrage` : le lancement a échoué avant qu'AUCUNE analyse ne parte, et c'est ce même appel
        qui avait démarré l'essai — on défait aussi le démarrage, pour qu'un refus ne pèse ni sur le plafond
        du jour ni sur l'identité. Après une analyse partie, l'identité reste consommée."""
        with self._conn() as cx:
            cx.isolation_level = None
            cx.execute("BEGIN IMMEDIATE")
            try:
                ligne = cx.execute("SELECT plan, essai_recherches, essai_id FROM comptes "
                                   "WHERE user_id=?", (user_id,)).fetchone()
                if ligne is None or ligne[0] != essai.PLAN_ESSAI:
                    cx.execute("ROLLBACK")
                    return
                _, prises, essai_id = ligne
                prises = max(0, prises - 1)
                if annuler_demarrage and essai_id is not None and prises == 0:
                    cx.execute("DELETE FROM essais WHERE id=?", (essai_id,))
                    cx.execute("UPDATE comptes SET essai_id=NULL, essai_recherches=0 WHERE user_id=?",
                               (user_id,))
                else:
                    cx.execute("UPDATE comptes SET essai_recherches=? WHERE user_id=?",
                               (prises, user_id))
                cx.execute("COMMIT")
            except Exception:
                cx.execute("ROLLBACK")
                raise

    def situation_essai(self, user_id: str) -> dict | None:
        """Ce qu'il reste d'un essai, pour l'afficher. None hors essai."""
        with self._conn() as cx:
            ligne = cx.execute("SELECT plan, essai_recherches, essai_id FROM comptes "
                               "WHERE user_id=?", (user_id,)).fetchone()
        if ligne is None or ligne[0] != essai.PLAN_ESSAI:
            return None
        return {"recherches_restantes": max(0, essai.ESSAI_RECHERCHES - ligne[1]),
                "recherches_max": essai.ESSAI_RECHERCHES,
                "niches_par_recherche": essai.ESSAI_NICHES_PAR_RECHERCHE,
                "analyses_detaillees_max": essai.ESSAI_APPELS_A_LA_PIECE,
                "demarre": ligne[2] is not None}

    # ── Jetons envoyés par e-mail ───────────────────────────────────────────────────

    def creer_jeton_courriel(self, user_id: str, usage: str, ttl_s: float | None = None) -> str:
        """Rend le jeton EN CLAIR (à poser dans un lien) et n'en garde que l'empreinte, comme
        pour les sessions : lire la base ne doit pas permettre de réinitialiser un mot de passe.

        Un nouveau jeton REMPLACE les précédents non utilisés du même usage : « renvoyer le lien »
        ne doit pas laisser traîner deux liens valides."""
        if usage not in USAGES_JETON:
            raise ValueError(f"usage de jeton inconnu : « {usage} »")
        if ttl_s is None:
            ttl_s = (TTL_JETON_VERIFICATION_S if usage == "verification"
                     else TTL_JETON_REINITIALISATION_S)
        jeton = secrets.token_urlsafe(32)
        maintenant = self.now()
        with self._conn() as cx:
            cx.execute("DELETE FROM jetons_courriel WHERE user_id=? AND usage=? AND utilise=0",
                       (user_id, usage))
            cx.execute("INSERT INTO jetons_courriel (empreinte, user_id, usage, cree_le, "
                       "expire_le) VALUES (?, ?, ?, ?, ?)",
                       (_empreinte_jeton(jeton), user_id, usage, maintenant, maintenant + ttl_s))
        return jeton

    def _consommer_jeton(self, cx, jeton, usage: str) -> str | None:
        """Marque le jeton utilisé ET rend son `user_id`, ou None. UN seul UPDATE conditionnel :
        deux requêtes simultanées avec le même lien ne passent pas toutes les deux."""
        if not isinstance(jeton, str) or not jeton.strip():
            return None
        empreinte = _empreinte_jeton(jeton)
        cur = cx.execute("UPDATE jetons_courriel SET utilise=1 WHERE empreinte=? AND usage=? "
                         "AND utilise=0 AND expire_le>?", (empreinte, usage, self.now()))
        if cur.rowcount != 1:
            return None
        return cx.execute("SELECT user_id FROM jetons_courriel WHERE empreinte=?",
                          (empreinte,)).fetchone()[0]

    def _jeton_valable(self, jeton, usage: str) -> bool:
        """Lecture SEULE : le jeton existe, sert cet usage, n'est pas utilisé et n'a pas expiré."""
        if not isinstance(jeton, str) or not jeton.strip():
            return False
        with self._conn() as cx:
            return cx.execute("SELECT 1 FROM jetons_courriel WHERE empreinte=? AND usage=? "
                              "AND utilise=0 AND expire_le>?",
                              (_empreinte_jeton(jeton), usage, self.now())).fetchone() is not None

    def verifier_email_par_jeton(self, jeton) -> Compte | None:
        """Consomme un lien de vérification et marque l'adresse vérifiée. None si le lien est
        inconnu, expiré ou déjà servi — sans dire lequel."""
        with self._conn() as cx:
            user_id = self._consommer_jeton(cx, jeton, "verification")
            if user_id is None:
                return None
            cx.execute("UPDATE comptes SET email_verifie=1 WHERE user_id=?", (user_id,))
        return self.compte(user_id)

    def reinitialiser_mot_de_passe_par_jeton(self, jeton, nouveau) -> Compte | None:
        """Consomme un lien de réinitialisation et pose le nouveau mot de passe. None si le lien
        est inconnu, expiré, déjà servi ou d'un autre usage.

        La politique est appliquée AVANT de consommer le lien : un mot de passe refusé ne doit
        pas obliger à tout redemander. Lève `MotDePasseFaible` — la page le montre, il ne dit
        rien sur la validité du lien (la politique s'applique avant de le lire).

        Ferme TOUTES les sessions (on oublie son mot de passe aussi quand on craint qu'un tiers
        ait la main sur le compte), remet les tentatives à zéro et marque l'adresse vérifiée : un
        lien consommé prouve l'accès à la boîte."""
        valider_mot_de_passe(nouveau)
        # Le lien est contrôlé AVANT scrypt (~45 ms, 16 Mo) : cette route n'exige pas de session, et
        # dériver pour un lien inconnu en faisait un amplificateur de coût pour n'importe qui. Le
        # contrôle ne consomme rien ; la consommation, elle, reste atomique plus bas.
        if not self._jeton_valable(jeton, "reinitialisation"):
            return None
        sel = secrets.token_bytes(16)
        empreinte = self._deriver(nouveau, sel)
        params = f"scrypt:{SCRYPT_N}:{SCRYPT_R}:{SCRYPT_P}"
        with self._conn() as cx:
            user_id = self._consommer_jeton(cx, jeton, "reinitialisation")
            if user_id is None:
                return None
            cx.execute("UPDATE comptes SET sel=?, empreinte=?, params=?, email_verifie=1 "
                       "WHERE user_id=?", (sel, empreinte, params, user_id))
            cx.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            email = cx.execute("SELECT email FROM comptes WHERE user_id=?",
                               (user_id,)).fetchone()[0]
            cx.execute("DELETE FROM tentatives WHERE email=?", (self._cle_connexion(email),))
        return self.compte(user_id)

    # ── Sessions ────────────────────────────────────────────────────────────────────

    def creer_session(self, user_id: str, ttl_s: float = SESSION_TTL_S) -> str:
        """Rend le jeton EN CLAIR (à poser dans un cookie) et n'en garde que l'empreinte.
        Le jeton ne pourra plus jamais être relu depuis la base : c'est voulu."""
        jeton = secrets.token_urlsafe(32)
        maintenant = self.now()
        with self._conn() as cx:
            cx.execute("INSERT INTO sessions (jeton_empreinte, user_id, cree_le, expire_le) "
                       "VALUES (?, ?, ?, ?)",
                       (_empreinte_jeton(jeton), user_id, maintenant, maintenant + ttl_s))
        return jeton

    def session_valide(self, jeton: str) -> str | None:
        """Rend le user_id, ou None si le jeton est inconnu, vide ou expiré."""
        if not (jeton or "").strip():
            return None
        with self._conn() as cx:
            ligne = cx.execute("SELECT user_id, expire_le FROM sessions WHERE "
                               "jeton_empreinte=?", (_empreinte_jeton(jeton),)).fetchone()
        if ligne is None or ligne[1] <= self.now():
            return None
        return ligne[0]

    def fermer_session(self, jeton: str) -> None:
        """Ne ferme QUE cette session : se déconnecter du téléphone ne doit pas déconnecter
        l'ordinateur."""
        with self._conn() as cx:
            cx.execute("DELETE FROM sessions WHERE jeton_empreinte=?",
                       (_empreinte_jeton(jeton),))

    def purger_sessions_expirees(self) -> int:
        with self._conn() as cx:
            cur = cx.execute("DELETE FROM sessions WHERE expire_le<=?", (self.now(),))
            return cur.rowcount


def _empreinte_jeton(jeton: str) -> str:
    """SHA-256 nu, sans sel ni étirement — et c'est correct ici : le jeton est déjà 256 bits
    d'aléa cryptographique, pas un secret choisi par un humain. L'étirer coûterait du temps
    à chaque requête sans rien gagner (il n'existe pas de dictionnaire de jetons)."""
    return hashlib.sha256((jeton or "").encode("utf-8")).hexdigest()


def _lire_params(params: str) -> tuple[int, int, int]:
    """Relit les paramètres scrypt écrits avec l'empreinte, pour pouvoir les durcir un jour
    sans invalider les comptes déjà créés. Format inconnu -> défauts courants."""
    try:
        algo, n, r, p = (params or "").split(":")
        if algo != "scrypt":
            raise ValueError(algo)
        return int(n), int(r), int(p)
    except (ValueError, AttributeError):
        return SCRYPT_N, SCRYPT_R, SCRYPT_P
