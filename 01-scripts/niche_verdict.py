"""niche_verdict.py — verdict éditorial d'une niche (directeur éditorial CLAUDE.md §7-8),
appliqué sur les DONNÉES DU SCOUT (pas de screenshots). Tool-use forcé, client injectable."""
import os

from dotenv import load_dotenv

from models import NicheVerdict, ScoredNiche  # noqa: F401

DEFAULT_MODEL = os.getenv("VERDICT_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """\
Tu es un DIRECTEUR ÉDITORIAL SENIOR et analyste concurrentiel pour un grand éditeur français. \
Tu tranches l'angle d'attaque optimal pour positionner un NOUVEAU LIVRE sur Amazon.fr dans une \
niche donnée. L'échec commercial n'est pas une option : tu es payé pour avoir raison.

DONNÉES : tu reçois les métriques déjà calculées d'un scout automatique (BSR des livres \
ORGANIQUES du top, demande, concurrence, titres concurrents). Les livres SPONSORISÉS ont DÉJÀ \
été écartés des calculs. Ne réclame pas de screenshots : raisonne sur ces chiffres.

POSTURE : factuel, tranché, sans complaisance. Pas de compliments gratuits. Quantifie ce qui \
peut l'être. Signale les zones d'incertitude. Impartial : ne privilégie aucun domaine a priori.

CRITÈRES DE DEMANDE (rappel) : une niche est forte si le top organique a au moins 1 BSR < 10 000 \
(demande prouvée), une moyenne < 50 000 (marché actif), ET au moins 1 BSR > 50 000 (« place à \
prendre » : un livre mal positionné mais bien classé = détronnable par une meilleure exécution).

TU PRODUIS (via l'outil rendre_verdict, OBLIGATOIRE) :
- verdict : "Go" / "Go prudent" / "No-Go" + confiance /10 + LE facteur décisif (la seule chose \
  qui fera la différence).
- 2 à 3 ANGLES d'attaque classés par priorité, chacun : l'angle (1 phrase), pourquoi ça marche \
  (justif. factuelle), le risque principal, un TITRE + SOUS-TITRE de travail concrets, la \
  direction de couverture, une fourchette de prix, la requête Amazon principale visée + 1-3 \
  requêtes secondaires (logique de titre multi-requêtes pour maximiser la surface de capture).
- CRITIQUE STRATÉGIQUE : saturation (non / oui mais bonne → différenciation par angle / oui et \
  morte → skip) ; faux_concurrent (un livre qui semble dominer mais dont la force vient d'une \
  niche voisine — donc battable sur LA requête ; "aucun" sinon) ; differenciation (par exécution \
  / par angle / par autorité — tranche laquelle est prioritaire).

Les titres et angles doivent être ACTIONNABLES : un auteur doit pouvoir s'y mettre directement.
"""

VERDICT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["Go", "Go prudent", "No-Go"]},
        "confiance": {"type": "integer", "description": "1 à 10"},
        "facteur_decisif": {"type": "string", "description": "LA chose qui fera la différence"},
        "angles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "angle": {"type": "string"},
                    "pourquoi": {"type": "string"},
                    "risque": {"type": "string"},
                    "titre": {"type": "string"},
                    "sous_titre": {"type": "string"},
                    "direction_couverture": {"type": "string"},
                    "prix_suggere": {"type": "string"},
                    "requete_principale": {"type": "string"},
                    "requetes_secondaires": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["angle", "pourquoi", "risque", "titre", "sous_titre",
                             "direction_couverture", "prix_suggere", "requete_principale",
                             "requetes_secondaires"],
            },
        },
        "saturation": {"type": "string"},
        "faux_concurrent": {"type": "string", "description": "'aucun' si pas de faux concurrent"},
        "differenciation": {"type": "string"},
    },
    "required": ["verdict", "confiance", "facteur_decisif", "angles", "saturation",
                 "faux_concurrent", "differenciation"],
}


def build_user_prompt(scored: ScoredNiche, search=None) -> str:
    """Formate les données du scout en brief pour le directeur éditorial."""
    titres = []
    if search is not None:
        titres = [o.title for o in search.organic if o.title][:12]
    lignes = [
        f"NICHE : {scored.niche}",
        f"Requête Amazon : « {scored.requete_amazon or scored.niche} » | catégorie : {scored.categorie}",
        f"Scores scout /10 : global {scored.global_score} · demande {scored.demande} · "
        f"pénétration {scored.penetration} · compatibilité {scored.compatibilite}",
        f"Demande : {scored.demand_autocomplete} complétions Amazon · "
        f"note moyenne {scored.avg_rating} · {scored.total_reviews} avis cumulés (top organique)",
        f"BSR organique (Livres) : meilleur {scored.bsr_best} · moyenne top {scored.bsr_top5_avg} · "
        f"plus haut {scored.bsr_worst_top10} · critères §4.1 remplis : "
        f"{'OUI' if scored.criteres_bsr_ok else 'non'}",
        f"Concurrence : {scored.n_organic} résultats organiques · "
        f"{scored.n_concurrents_cibles} concurrents ciblant vraiment la requête · "
        f"{scored.n_sponsored} sponsorisés écartés des calculs",
    ]
    if titres:
        lignes.append("Titres concurrents organiques du top :\n- " + "\n- ".join(titres))
    else:
        lignes.append("(titres concurrents non disponibles — raisonne sur les métriques)")
    lignes.append("\nRends ton verdict via l'outil rendre_verdict.")
    return "\n".join(lignes)


def _default_client():
    load_dotenv()
    import anthropic
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def generate_verdict(scored: ScoredNiche, search=None, model: str | None = None,
                     client=None, on_usage=None) -> NicheVerdict:
    """Verdict éditorial d'une niche. `client` injectable. `on_usage(in,out,model)` optionnel."""
    client = client or _default_client()
    model = model or DEFAULT_MODEL
    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        tools=[{
            "name": "rendre_verdict",
            "description": "Renvoie le verdict éditorial structuré de la niche.",
            "input_schema": VERDICT_INPUT_SCHEMA,
        }],
        tool_choice={"type": "tool", "name": "rendre_verdict"},
        messages=[{"role": "user", "content": build_user_prompt(scored, search)}],
    )
    if on_usage is not None and getattr(resp, "usage", None) is not None:
        on_usage(getattr(resp.usage, "input_tokens", 0),
                 getattr(resp.usage, "output_tokens", 0), model)
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            return NicheVerdict.model_validate(block.input)
    return NicheVerdict(verdict="No-Go", confiance=0, facteur_decisif="(pas de sortie LLM)")
