"""fiction_ideator.py — propose des TRIOS fiction (sous-genre × tropes × décor) contraints
à la taxonomie versionnée. Tool-use forcé, client injectable (aucun réseau en unit-test).
La contrainte taxonomie est vérifiée CÔTÉ CODE : on demande au LLM, puis on contrôle."""
import json
import os
import re
import unicodedata

from dotenv import load_dotenv

from pydantic import BaseModel, Field

from fiction_taxonomy import sous_genre as _sous_genre, valid_keys
from models import FictionNiche


class ContraintesTrio(BaseModel):
    """Ce que l'AUTEUR impose au trio, quand il le compose lui-même.

    Deux modes coexistent volontairement : « propose-moi des trios » (aucune contrainte,
    comportement d'origine) et « je compose le mien ». Le second ne remplace pas le
    premier — des menus SEULS produiraient des trios morts, puisque rien ne garantit qu'un
    décor donné se combine avec un trope donné dans un marché réel. L'IA garde donc son
    rôle : trouver des combinaisons plausibles À L'INTÉRIEUR des contraintes.

    `libre` sort de la taxonomie par nature (l'auteur tape ce qu'il veut). On l'accepte et
    on le signale au modèle comme une piste, sans jamais l'imposer comme clé : le
    classifieur range déjà les clés inconnues dans `other`, et c'est ce signal-là qui fait
    évoluer la taxonomie."""
    tropes: list[str] = Field(default_factory=list)   # clés imposées, vérifiées côté code
    decor: str | None = None                          # clé imposée, vérifiée côté code
    libre: str = ""                                   # texte de l'auteur, hors taxonomie

    def vide(self) -> bool:
        return not self.tropes and not self.decor and not self.libre.strip()

DEFAULT_MODEL = os.getenv("FICTION_IDEATOR_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """\
Tu es un ÉDITEUR DE FICTION francophone et un auteur à succès sur Amazon.fr (KDP). Tu \
connais intimement ce que les lectrices et lecteurs français achètent réellement.

MISSION : proposer des TRIOS exploitables — sous-genre × trope(s) × décor — pour un NOUVEAU \
roman. Un trio est une PROMESSE DE LECTURE précise, pas un thème vague.

CONTRAINTE ABSOLUE : tu ne proposes QUE des tropes et des décors présents dans les listes \
fournies. Aucune invention, aucune variante, aucune traduction : les clés exactes. Tout trio \
contenant une clé hors liste sera rejeté automatiquement.

RAISONNEMENT ATTENDU :
- Combine 1 à 3 tropes qui se renforcent (pas trois tropes qui racontent trois livres).
- Le décor doit CHANGER la promesse, pas être un décor de carte postale interchangeable.
- Cherche les combinaisons sous-exploitées : un trope porteur dans un décor qu'on ne voit \
  jamais avec lui vaut mieux qu'un empilement d'évidences.
- EVERGREEN de préférence. Si un trio est saisonnier (Noël, été), assume-le et dis-le dans \
  la rationale.

REQUÊTE AMAZON : la 'query' doit être ce qu'un lecteur TAPE réellement dans la barre de \
recherche Amazon : 2 à 4 mots AU TOTAL, qui COMMENCE par la requête de référence du rayon \
(donnée dans le message), suivie d'UN ou deux mots concrets — le décor, ou l'ancrage le plus \
reconnaissable, tel qu'il figurerait dans un titre. Jamais un titre de roman ni un slogan. \
Plus la requête est longue, moins Amazon rend de livres : au-delà de quatre mots, ou sans la \
requête de référence, la recherche ne rend souvent aucun résultat. Les ressorts du trio \
(« reconstruction », « héritage », « deuil ») sont mesurés par la lecture des quatrièmes de \
couverture : ils n'ont pas à figurer dans la requête.

Une 'rationale' TRANCHÉE d'une phrase par trio : pourquoi ça se vendrait.
"""

TRIOS_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "trios": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tropes": {"type": "array", "items": {"type": "string"},
                               "description": "1 à 3 clés de tropes, EXACTEMENT comme fournies"},
                    "decor": {"type": "string", "description": "une clé de décor fournie"},
                    "query": {"type": "string", "description": "ce qu'un lecteur tape sur Amazon"},
                    "rationale": {"type": "string"},
                },
                "required": ["tropes", "decor", "query", "rationale"],
                "additionalProperties": False,      # exigé par le mode STRICT
            },
        }
    },
    "required": ["trios"],
    "additionalProperties": False,
}


# Une requête de trio rend des livres si elle COMMENCE par la requête de référence du rayon et
# reste courte. Mesuré le 2026-10-05 sur les deux runs fiction enregistrés : les deux requêtes
# écrites hors de cette tête (« roman reprise ferme famille », « roman nouvelle vie île
# recommencer ») n'ont rendu AUCUN résultat sur Amazon (statut 40102) ; celles de 5 à 6 mots en
# ont rendu 0, 2, 3 ou 9, dont 8 hors sujet ; et sur l'autocomplete seule la tête est tapée par
# de vrais lecteurs. Le prompt le demande, le CODE le garantit.
MAX_MOTS_REQUETE = 4

_MOTS_VIDES = frozenset({
    "a", "au", "aux", "avec", "ce", "cette", "d", "dans", "de", "des", "du", "en", "et", "l",
    "la", "le", "les", "ou", "par", "pour", "qui", "que", "sa", "sans", "ses", "son", "sur",
    "un", "une"})


def _plat(mot: str) -> str:
    """Casse et diacritiques dépouillés : le modèle écrit « Académie », la clé dit « academie »."""
    decompose = unicodedata.normalize("NFKD", mot or "")
    return "".join(c for c in decompose if not unicodedata.combining(c)).casefold()


def _mots(texte: str) -> list[str]:
    return re.findall(r"\w+", texte or "")


def cle_requete(query: str) -> str:
    """Identité d'une REQUÊTE : mots sans casse ni diacritiques. Deux requêtes qui n'en font
    qu'une pour Amazon n'en font qu'une pour nous — c'est la clé qui permet à `fiction_master`
    de ne payer qu'une recherche pour tous les trios qui la partagent."""
    return " ".join(_plat(m) for m in _mots(query))


def requete_courte(query: str, tete: str, decor: str | None = None,
                   max_mots: int = MAX_MOTS_REQUETE) -> str:
    """La requête du trio, ramenée à `max_mots` mots AU PLUS et COMMENÇANT par `tete` (la
    requête de référence du sous-genre).

    Une requête déjà conforme est rendue TELLE QUELLE. Sinon on la reconstruit : la tête, puis
    les mots concrets du modèle (sans mots vides, sans doublon, sans les mots de la tête), ceux
    qui recoupent le DÉCOR du trio d'abord — c'est le mot le plus concret et le plus conforme au
    trio, celui qu'un titre porte —, puis les autres dans l'ordre d'origine, dans la limite de
    la place laissée par la tête (au moins un mot). Idempotente. Une tête vide ne change rien.

    Deux trios de même décor obtiennent la MÊME requête, et c'est voulu : une requête courte
    décrit un rayon, pas un trio. Revue adverse du 2026-10-05 : les rendre uniques — en écartant le
    trio (11 demandés, 7 rendus), ou en glissant sur un mot de ressort (un rayon sans rapport avec
    le décor) — était pire. L'identité d'un trio est `FictionNiche.cle`, la recherche payée est
    partagée par l'orchestrateur.

    Le choix des mots gardés est une HEURISTIQUE, pas une mesure : elle ne dit pas que la
    requête rendue ramène plus de livres (non mesuré, aucune recherche payée pour le vérifier),
    seulement qu'elle n'a plus les deux défauts observés — trop longue, sans la tête."""
    tete_mots = _mots(tete)
    if not tete_mots:
        return query
    tete_plat = [_plat(m) for m in tete_mots]
    q_mots = _mots(query)
    if len(q_mots) <= max_mots and [_plat(m) for m in q_mots[:len(tete_mots)]] == tete_plat:
        return query
    place = max(1, max_mots - len(tete_mots))
    mots_decor = {_plat(m) for m in _mots((decor or "").replace("_", " "))
                  if _plat(m) not in _MOTS_VIDES and len(m) > 2}
    vus, extras = set(tete_plat), []
    for m in q_mots:
        n = _plat(m)
        if n in vus or n in _MOTS_VIDES or len(n) < 2:
            continue
        vus.add(n)
        extras.append(m)
    choisis = ([m for m in extras if _plat(m) in mots_decor]
               + [m for m in extras if _plat(m) not in mots_decor])[:place]
    return " ".join(tete_mots + choisis)


def _json_si_texte(v):
    """Une chaîne JSON valide est DÉCODÉE (contenu du modèle, seulement sérialisé) ; le reste
    est rendu tel quel et écarté par l'appelant, jamais deviné."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def build_user_prompt(sous_genre_cle: str, n: int = 8, rayon: str = "kindle",
                      version: str = "fr_v1",
                      contraintes: "ContraintesTrio | None" = None) -> str:
    """Injecte la liste EXACTE des clés autorisées, puis les contraintes de l'auteur.

    Une clé imposée hors taxonomie LÈVE. Les menus étant peuplés depuis la taxonomie, une
    clé inconnue ne peut venir que d'une requête forgée à la main : l'ignorer en silence
    ferait croire à l'auteur que sa contrainte a été appliquée."""
    sg = _sous_genre(sous_genre_cle, version)
    tropes, decors = valid_keys(sous_genre_cle, version)
    base = (
        f"SOUS-GENRE : {sous_genre_cle} ({sg['label']})\n"
        f"Marketplace : fr · rayon : {rayon}\n"
        f"Requête de référence du rayon : « {sg['query_fr']} »\n\n"
        "TROPES AUTORISÉS (aucun autre) :\n- " + "\n- ".join(tropes) + "\n\n"
        "DÉCORS AUTORISÉS (aucun autre) :\n- " + "\n- ".join(decors) + "\n\n"
    )
    c = contraintes or ContraintesTrio()
    if not c.vide():
        inconnus = [t for t in c.tropes if t not in tropes]
        if inconnus:
            raise ValueError(f"trope(s) hors taxonomie : {inconnus}")
        if c.decor and c.decor not in decors:
            raise ValueError(f"décor hors taxonomie : {c.decor}")
        lignes = ["CONTRAINTES DE L'AUTEUR — elles s'IMPOSENT à TOUS les trios :"]
        if c.tropes:
            lignes.append(f"- chaque trio DOIT contenir : {', '.join(c.tropes)}")
        if c.decor:
            lignes.append(f"- le décor est IMPOSÉ : {c.decor}")
        if c.libre.strip():
            lignes.append(
                f"- piste libre de l'auteur, à intégrer si elle est crédible dans ce "
                f"rayon : « {c.libre.strip()} ». Ce n'est PAS une clé de taxonomie : "
                f"sers-t'en pour orienter la requête et la rationale, jamais comme trope "
                f"ou comme décor.")
        lignes.append("Si ces contraintes ne laissent AUCUNE combinaison crédible sur ce "
                      "marché, rends une liste VIDE plutôt que des trios de remplissage.")
        base += "\n".join(lignes) + "\n\n"
    return base + f"Propose {n} trios distincts via l'outil proposer_trios."


def _default_client():
    load_dotenv()
    import anthropic
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def contraintes_impossibles(trios: list, contraintes: "ContraintesTrio | None") -> bool:
    """Aucun trio ET des contraintes posées = impossibilité de COMPOSITION.

    À ne surtout pas confondre avec un verdict de marché : rien n'a été mesuré à ce stade,
    aucune requête Amazon n'a été lancée. Rendre une liste vide sans le dire laisserait
    lire « ce marché est mort » là où il faut lire « vos contraintes ne se combinent pas »."""
    return not trios and bool(contraintes and not contraintes.vide())


def generate_trios(sous_genre_cle: str, n: int = 8, rayon: str = "kindle",
                   model: str | None = None, client=None, on_usage=None,
                   version: str = "fr_v1",
                   contraintes: "ContraintesTrio | None" = None) -> list[FictionNiche]:
    """Trios contraints à la taxonomie ET aux contraintes de l'auteur.

    Les deux contrôles sont faits CÔTÉ CODE, jamais seulement demandés au prompt : un
    modèle oublie une consigne sous pression, et rendre un trio qui ne porte pas le trope
    imposé, c'est répondre à côté de la question de l'auteur."""
    client = client or _default_client()
    model = model or DEFAULT_MODEL
    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        # STRICT : sans lui, l'API ne garantit pas la forme de `tool_use.input` (des objets
        # rendus en TEXTE ont fait lever lowcontent_ideator APRÈS l'appel payé, 2026-09-13).
        tools=[{
            "name": "proposer_trios",
            "description": "Renvoie les trios fiction proposés.",
            "strict": True,
            "input_schema": TRIOS_INPUT_SCHEMA,
        }],
        tool_choice={"type": "tool", "name": "proposer_trios"},
        messages=[{"role": "user",
                   "content": build_user_prompt(sous_genre_cle, n, rayon, version,
                                                contraintes)}],
    )
    if on_usage is not None and getattr(resp, "usage", None) is not None:
        on_usage(getattr(resp.usage, "input_tokens", 0),
                 getattr(resp.usage, "output_tokens", 0), model)
    tropes_ok, decors_ok = valid_keys(sous_genre_cle, version)
    tete_requete = _sous_genre(sous_genre_cle, version).get("query_fr", "")
    c = contraintes or ContraintesTrio()
    out: list[FictionNiche] = []
    for block in resp.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        entree = _json_si_texte(block.input)
        trios = _json_si_texte(entree.get("trios")) if isinstance(entree, dict) else None
        if not isinstance(trios, list):
            continue                           # réponse illisible -> rien d'inventé
        for t in trios:
            if not isinstance(t, dict):
                continue                       # trio hors schéma (texte…) -> écarté
            tropes_brut = t.get("tropes") or []
            if isinstance(tropes_brut, str):
                tropes_brut = [tropes_brut]    # une chaîne EST un trope, pas des lettres
            if not isinstance(tropes_brut, list):
                continue
            tr = list(dict.fromkeys(x for x in tropes_brut if isinstance(x, str)))
            dec = t.get("decor") or None
            query = t.get("query") or ""
            if (dec is not None and not isinstance(dec, str)) or not isinstance(query, str):
                continue                       # champ mal typé -> écarté, jamais deviné
            if not tr or not set(tr) <= set(tropes_ok):
                continue                       # trope hors taxonomie -> écarté
            if dec and dec not in decors_ok:
                continue                       # décor hors taxonomie -> écarté
            if c.tropes and not set(c.tropes) <= set(tr):
                continue                       # trope imposé absent -> écarté
            if c.decor and dec != c.decor:
                continue                       # décor imposé non respecté -> écarté
            # Court et ancré sur la requête de référence : on corrige la requête, on ne jette pas
            # le trio (c'est elle qui était mal écrite, pas la combinaison).
            query = requete_courte(query, tete_requete, dec)
            out.append(FictionNiche(sous_genre=sous_genre_cle, tropes=tr[:3], decor=dec,
                                    marketplace="fr", rayon=rayon,
                                    query=query))
    return out[:n] if n else out          # `n` est un plafond, pas seulement une suggestion
