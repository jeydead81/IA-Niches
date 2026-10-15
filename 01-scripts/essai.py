"""essai.py — l'essai gratuit : l'offre, et les règles PURES qui la protègent (2026-10-15).

Décision de Baptiste : un nouveau compte reçoit **2 recherches d'essai** (5 niches au plus chacune, donc
10 niches), **5 analyses détaillées** (verdicts, mots-clés) et rien de plus — sans carte bancaire.

Le problème de fond, dit une fois : sans carte ni téléphone, l'identité d'un visiteur est une adresse
e-mail, et une adresse se fabrique. Un proxy, un partage de connexion et dix boîtes suffisent à rejouer
l'essai à l'infini. **On ne ferme pas cette porte, on en élève le prix et on en BORNE la facture** :

1. une même boîte ne donne qu'un essai (les alias `+x` et les points de Gmail sont la même boîte) ;
2. les adresses à usage unique n'en ouvrent aucun ;
3. un domaine qui n'est pas un fournisseur grand public (le moyen le moins cher de recevoir des adresses
   sans limite : acheter un domaine) est plafonné à 3 essais par mois, sous-domaines compris ;
4. un même réseau est plafonné à 5 essais par mois — quand l'adresse du client prouve quelque chose (5 et non 3
   le 2026-10-15 : un réseau mobile partage une adresse publique entre beaucoup d'abonnés, et la règle ne retient
   de toute façon que le fraudeur paresseux — un proxy qui change d'adresse la contourne) ;
5. surtout, **un plafond GLOBAL de nouveaux essais par 24 h** (`ESSAIS_PAR_JOUR_MAX`) : quoi que fassent
   les fraudeurs, la perte quotidienne a un maximum connu. C'est la seule garde qui ne se contourne pas —
   À CONDITION qu'AUCUNE dépense d'un compte d'essai n'ait lieu avant que son essai ait DÉMARRÉ. La première
   version laissait les analyses détaillées hors de ces gardes (revue du 2026-10-15 : 120 verdicts payés
   avec une seule boîte Gmail et ses alias) ; elles exigent désormais un essai démarré, et il ne démarre que
   par une recherche (`UserStore.reserver_recherche_essai`, seul endroit qui juge).

Ce que ce module NE fait PAS : empreinte de navigateur, SMS, captcha. Le premier est du suivi à documenter
au RGPD, les deux autres de la friction pour tous ; à ajouter si l'abus est observé, pas avant.

Aucune de ces règles ne touche une base : elles vivent ici pour être testées sans SQLite
(`tests/test_essai.py`). Leur application atomique est dans `auth.UserStore.reserver_recherche_essai`.

**Règle 3 appliquée au réseau** : l'adresse du client n'est un signal que si elle est PUBLIQUE. Derrière un
proxy d'hébergeur mal réglé, tous les visiteurs arrivent avec la même adresse privée ; la compter
refuserait tout le monde au quatrième essai. Une adresse qui ne prouve rien ne produit aucune empreinte.
"""
import ipaddress
import os
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

# ── L'offre ─────────────────────────────────────────────────────────────────────────────
PLAN_ESSAI = "essai"
PLAN_ABONNE = "abonne"          # posé plus tard par le paiement ; même comportement qu'`illimite` pour l'instant
PLAN_ILLIMITE = "illimite"      # le poste de Baptiste et le premier compte (amorçage)
PLANS = (PLAN_ESSAI, PLAN_ABONNE, PLAN_ILLIMITE)

ESSAI_RECHERCHES = 2                    # lancements d'analyse, à vie
ESSAI_NICHES_PAR_RECHERCHE = 5          # donc 10 niches au total
ESSAI_APPELS_A_LA_PIECE = 5             # verdicts + mots-clés, à vie (une par niche d'une recherche)

# ── Ce qui borne la fraude ──────────────────────────────────────────────────────────────
ESSAI_PAR_RESEAU = 5                    # essais démarrés par réseau, sur FENETRE_ESSAI_S
ESSAI_PAR_DOMAINE = 3                   # idem par domaine qui n'est pas un fournisseur grand public
FENETRE_ESSAI_S = 30 * 24 * 3600
CONSERVATION_IDENTITE_S = 365 * 24 * 3600   # « un essai par boîte et par an »
FENETRE_JOUR_S = 24 * 3600              # glissante : un seau qui se vide à heure fixe se contourne en attendant
# Prudent au démarrage (aucune donnée réelle) : à monter les jours de promotion, sans toucher au code. Au plafond,
# la perte d'une journée est d'environ 3,5 à 8 $ (CALCULÉ, CLAUDE.md §2.21).
ESSAIS_PAR_JOUR_DEFAUT = 10
FENETRE_APPELS_ESSAI_S = 10 * 365 * 24 * 3600   # « à vie » pour le compteur d'appels à la pièce

_DATA = Path(__file__).resolve().parent.parent / "data"
FICHIER_JETABLES = _DATA / "domaines_jetables.txt"
FICHIER_COURANTS = _DATA / "domaines_courants.txt"
FICHIER_SUFFIXES = _DATA / "suffixes_deux_niveaux.txt"


class ReservationEssai(NamedTuple):
    """Ce que rend `UserStore.reserver_recherche_essai`. `demarre_ici` : CET appel a démarré l'essai (c'était
    la première recherche) — si le lancement échoue ensuite, c'est ce drapeau qui dit qu'il faut aussi défaire
    le démarrage, pas seulement la recherche."""
    demarre_ici: bool


class EssaiIndisponible(Exception):
    """L'essai ne peut pas être servi. Trois causes, trois sous-classes : le client lit un message
    différent pour chacune, et seule la dernière dit « revenez plus tard ».

    `cause` est le mot que l'OPÉRATEUR lit dans le journal (`essai refusé : cause=…`) pour calibrer les seuils : le
    client, lui, ne la lit jamais — détailler laisserait régler le contournement. Jamais une donnée personnelle."""
    cause = "indisponible"


class EssaiEpuise(EssaiIndisponible):
    """Les deux recherches ont été utilisées."""
    cause = "epuise"


class EssaiRefuse(EssaiIndisponible):
    """Pas d'essai pour cette identité, ce domaine ou ce réseau. Un seul message CLIENT pour les causes :
    `cause` vaut `adresse` (illisible), `jetable`, `identite`, `reseau` ou `domaine`."""

    def __init__(self, message: str = "", cause: str = "refuse"):
        super().__init__(message)
        self.cause = cause


class QuotaJournalier(EssaiIndisponible):
    """Le plafond global de nouveaux essais du jour est atteint — ça, et seulement ça, se règle en attendant."""
    cause = "quota_jour"


# ── Réglage ─────────────────────────────────────────────────────────────────────────────

def essais_par_jour_max() -> int:
    """`ESSAIS_PAR_JOUR_MAX`, lu à chaque appel. **0 ferme le robinet** (aucun nouvel essai) : ce n'est pas
    « illimité ». Une valeur illisible ou négative retombe sur le défaut — jamais sur l'absence de plafond :
    une faute de frappe ne doit pas ouvrir la vanne."""
    brut = (os.getenv("ESSAIS_PAR_JOUR_MAX") or "").strip()
    if not brut.isdigit():
        return ESSAIS_PAR_JOUR_DEFAUT
    return int(brut)


# ── Identité d'une adresse ──────────────────────────────────────────────────────────────

def _decouper(email) -> tuple[str, str]:
    if not isinstance(email, str):
        return "", ""
    propre = email.strip().lower()
    local, arobase, dom = propre.rpartition("@")
    dom = dom.rstrip(".")          # `gmail.com.` est `gmail.com` pour un résolveur : un point final ne change pas de domaine
    if not arobase or not local or not dom:
        return "", ""
    return local, dom


def domaine(email) -> str:
    return _decouper(email)[1]


def identite_courriel(email) -> str:
    """La BOÎTE derrière une adresse : `a.b+x@gmail.com`, `ab@gmail.com` et `ab@googlemail.com` y arrivent
    tous. Le `+suffixe` est ôté partout (un domaine d'entreprise qui distinguerait `a` de `a+x` est
    l'exception), les points seulement chez Gmail, seul fournisseur qui les ignore. « » si l'adresse est
    illisible — jamais une identité inventée.

    Ceci n'est PAS la normalisation du compte (`auth.normaliser_email`, qui ne touche que la casse : les
    deux adresses restent deux comptes). C'est la clé de l'ESSAI."""
    local, dom = _decouper(email)
    if not local:
        return ""
    local = local.split("+", 1)[0]
    if dom in ("gmail.com", "googlemail.com"):
        local, dom = local.replace(".", ""), "gmail.com"
    return f"{local}@{dom}" if local else ""


# ── Listes de domaines (fichiers de données, étendus sans toucher au code) ──────────────

def charger_liste(chemin) -> set[str]:
    """Un domaine par ligne ; `#` commence un commentaire. Un fichier ABSENT lève : « aucun domaine
    jetable » est la façon dont un filtre cassé se lit, et il se désactiverait sans un mot."""
    out = set()
    for ligne in Path(chemin).read_text(encoding="utf-8").splitlines():
        d = ligne.split("#", 1)[0].strip().lower()
        if d:
            out.add(d)
    return out


@lru_cache(maxsize=1)
def _jetables() -> frozenset:
    return frozenset(charger_liste(FICHIER_JETABLES))


@lru_cache(maxsize=1)
def _courants() -> frozenset:
    return frozenset(charger_liste(FICHIER_COURANTS))


@lru_cache(maxsize=1)
def _suffixes_deux_niveaux() -> frozenset:
    return frozenset(charger_liste(FICHIER_SUFFIXES))


def domaine_enregistrable(dom) -> str:
    """Le domaine qu'on ACHÈTE : `x1.mondomaine.fr` et `x2.mondomaine.fr` sont `mondomaine.fr`. Compter les
    essais par hôte exact laissait un seul domaine, avec un MX joker, fabriquer des « domaines » à 0 essai en
    nombre illimité. Deux derniers labels, trois quand ils forment un suffixe public à deux niveaux
    (`co.uk`, `asso.fr`) — sans cette liste, tous les `.co.uk` partageraient un compteur et la Grande-Bretagne
    serait refusée au quatrième essai. La bibliothèque standard n'a pas de liste des suffixes publics : celle-ci
    est un fichier de départ, étendu à la main (`data/suffixes_deux_niveaux.txt`)."""
    dom = (dom or "").strip().lower().rstrip(".")
    labels = dom.split(".")
    if len(labels) <= 2:
        return dom
    if ".".join(labels[-2:]) in _suffixes_deux_niveaux():
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def est_jetable(dom) -> bool:
    """Le domaine, ou l'un de ses parents, est un service d'adresses à usage unique. Un SOUS-domaine compte
    (`x.mailinator.com`) ; un domaine qui se contente de CONTENIR le nom (`monmailinator.com`) non."""
    dom = (dom or "").strip().lower().rstrip(".")
    if not dom:
        return False
    jetables = _jetables()
    morceaux = dom.split(".")
    return any(".".join(morceaux[i:]) in jetables for i in range(len(morceaux) - 1))


def est_courant(dom) -> bool:
    """Fournisseur grand public : des millions de gens distincts y ont une adresse, le plafonner par domaine
    refuserait des inconnus. Il est protégé autrement — ouvrir une boîte y est cher pour le fraudeur."""
    return (dom or "").strip().lower().rstrip(".") in _courants()


# ── Adresse du client ───────────────────────────────────────────────────────────────────

def empreinte_reseau(client) -> str | None:
    """L'adresse du client si elle prouve quelque chose, sinon None. Une adresse IPv4 telle quelle ; une
    adresse IPv6 ramenée à son /64 (un abonné en reçoit 2^64 : compter l'adresse exacte les laisserait
    toutes gratuites) ; une IPv4 enveloppée dans de l'IPv6 lue comme IPv4.

    None pour tout ce qui n'est pas une adresse PUBLIQUE : privée, boucle locale, partage d'opérateur
    (100.64/10), lien local, illisible, vide. Voir la règle 3 en tête de module."""
    if not isinstance(client, str):
        return None
    try:
        ip = ipaddress.ip_address(client.strip())
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if not ip.is_global:
        return None
    if isinstance(ip, ipaddress.IPv6Address):
        return str(ipaddress.ip_network(f"{ip}/64", strict=False).network_address) + "/64"
    return str(ip)
