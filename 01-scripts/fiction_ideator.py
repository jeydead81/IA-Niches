"""fiction_ideator.py — propose des TRIOS fiction (sous-genre × tropes × décor) contraints
à la taxonomie versionnée. Tool-use forcé, client injectable (aucun réseau en unit-test).
La contrainte taxonomie est vérifiée CÔTÉ CODE : on demande au LLM, puis on contrôle."""
import json
import os

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
recherche Amazon (3 à 6 mots, langage naturel), jamais un titre de roman ni un slogan. \
Test simple : si tu ne la taperais pas toi-même, elle est mauvaise.

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
            out.append(FictionNiche(sous_genre=sous_genre_cle, tropes=tr[:3], decor=dec,
                                    marketplace="fr", rayon=rayon,
                                    query=query))
    return out[:n] if n else out          # `n` est un plafond, pas seulement une suggestion
