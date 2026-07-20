"""fiction_ideator.py — propose des TRIOS fiction (sous-genre × tropes × décor) contraints
à la taxonomie versionnée. Tool-use forcé, client injectable (aucun réseau en unit-test).
La contrainte taxonomie est vérifiée CÔTÉ CODE : on demande au LLM, puis on contrôle."""
import os

from dotenv import load_dotenv

from fiction_taxonomy import sous_genre as _sous_genre, valid_keys
from models import FictionNiche

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
            },
        }
    },
    "required": ["trios"],
}


def build_user_prompt(sous_genre_cle: str, n: int = 8, rayon: str = "kindle",
                      version: str = "fr_v1") -> str:
    """Injecte la liste EXACTE des clés autorisées pour ce sous-genre."""
    sg = _sous_genre(sous_genre_cle, version)
    tropes, decors = valid_keys(sous_genre_cle, version)
    return (
        f"SOUS-GENRE : {sous_genre_cle} ({sg['label']})\n"
        f"Marketplace : fr · rayon : {rayon}\n"
        f"Requête de référence du rayon : « {sg['query_fr']} »\n\n"
        "TROPES AUTORISÉS (aucun autre) :\n- " + "\n- ".join(tropes) + "\n\n"
        "DÉCORS AUTORISÉS (aucun autre) :\n- " + "\n- ".join(decors) + "\n\n"
        f"Propose {n} trios distincts via l'outil proposer_trios."
    )


def _default_client():
    load_dotenv()
    import anthropic
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def generate_trios(sous_genre_cle: str, n: int = 8, rayon: str = "kindle",
                   model: str | None = None, client=None, on_usage=None,
                   version: str = "fr_v1") -> list[FictionNiche]:
    """Trios contraints à la taxonomie. Tout trio hors taxonomie est ÉCARTÉ côté code."""
    client = client or _default_client()
    model = model or DEFAULT_MODEL
    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        tools=[{
            "name": "proposer_trios",
            "description": "Renvoie les trios fiction proposés.",
            "input_schema": TRIOS_INPUT_SCHEMA,
        }],
        tool_choice={"type": "tool", "name": "proposer_trios"},
        messages=[{"role": "user",
                   "content": build_user_prompt(sous_genre_cle, n, rayon, version)}],
    )
    if on_usage is not None and getattr(resp, "usage", None) is not None:
        on_usage(getattr(resp.usage, "input_tokens", 0),
                 getattr(resp.usage, "output_tokens", 0), model)
    tropes_ok, decors_ok = valid_keys(sous_genre_cle, version)
    out: list[FictionNiche] = []
    for block in resp.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        for t in ((block.input or {}).get("trios") or []):
            tr = list(dict.fromkeys(t.get("tropes") or []))   # dédup, ordre préservé
            dec = t.get("decor") or None
            if not tr or not set(tr) <= set(tropes_ok):
                continue                       # trope hors taxonomie -> écarté
            if dec and dec not in decors_ok:
                continue                       # décor hors taxonomie -> écarté
            out.append(FictionNiche(sous_genre=sous_genre_cle, tropes=tr[:3], decor=dec,
                                    marketplace="fr", rayon=rayon,
                                    query=t.get("query") or ""))
    return out[:n] if n else out          # `n` est un plafond, pas seulement une suggestion
