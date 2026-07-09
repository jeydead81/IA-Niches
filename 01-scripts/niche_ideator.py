"""niche_ideator.py — le "cerveau" du scout : génère des niches LIVRE candidates
via l'API Anthropic, en raisonnant comme un auteur KDP à succès sur amazon.fr.

Deux modes :
  - graine  : un mot-clé ("ésotérisme") → concepts liés + sous-niches (tarot, anges…)
  - à partir de rien : des signaux Trends/Reddit/News → niches evergreen exploitables

Sortie structurée garantie via tool-use forcé (pas de parsing fragile). Le client
Anthropic est injectable pour les tests (aucun appel réseau en unit-test).
"""
import os

from dotenv import load_dotenv

from models import NicheCandidate, NicheList  # noqa: F401 (NicheCandidate ré-exporté)

# Modèle configurable. Défaut sonnet-5 : l'A/B live (2026-07-05, graine "ésotérisme")
# a montré une qualité à parité avec opus-4-8, pour ~2x moins cher et plus rapide.
# Repasser à "claude-opus-4-8" ou "claude-fable-5" via la variable IDEATOR_MODEL.
DEFAULT_MODEL = os.getenv("IDEATOR_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """\
Tu es un directeur éditorial senior ET un auteur KDP à succès sur Amazon.fr. \
Tu es payé pour avoir raison : l'échec commercial n'est pas une option. Tu es factuel, \
tranché, sans complaisance. Tu connais intimement le marché du livre grand public français.

MISSION : proposer des NICHES DE LIVRE exploitables sur Amazon.fr — des sujets qui se \
vendent en broché/Kindle, rédigés (100-200 pages), pour un lecteur curieux grand public.

RAISONNEMENT ATTENDU :
- Expansion LATÉRALE, pas des reformulations. D'une graine comme « ésotérisme », tu sors les \
  vrais univers connexes que les gens achètent : tarot, oracle, numérologie, cartomancie, \
  anges gardiens, lithothérapie, astrologie, runes, chamanisme… puis leurs sous-niches.
- Tu cherches les angles SOUS-EXPLOITÉS et les sous-publics précis, pas les évidences saturées.
- Chaque niche doit être réellement CHERCHÉE sur Amazon : les satellite_keywords sont des \
  requêtes plausibles que de vrais acheteurs tapent (2 à 5 par niche).

CONTRAINTES NON-NÉGOCIABLES :
- EVERGREEN uniquement. Jamais de saisonnier (Noël, été, rentrée, fêtes, événements datés).
- Format LIVRE RÉDIGÉ uniquement. Pas d'objets, de cahiers d'activités, de produits physiques, \
  de logiciels, de sujets d'actualité pure.
- EXCLUSIONS strictes (ne propose JAMAIS) : religion musulmane et autres religions à expertise \
  pointue ; politique contemporaine/partisane/électorale ; tout sujet borderline vis-à-vis des \
  conditions KDP d'Amazon ; niches d'experts ultra-techniques où un spécialiste repérerait les \
  erreurs et coulerait les notes.

IMPARTIALITÉ : ne privilégie aucun domaine a priori — santé, développement personnel, histoire, \
ésotérisme, finance, sciences, spiritualité, etc. sont à égalité. Ne suppose rien sur le profil ni \
l'expertise de l'auteur. C'est la demande réelle du marché qui doit trancher, jamais une préférence \
de domaine. Reste dans le grand public vulgarisé, quel que soit le sujet.

REQUÊTES AMAZON (crucial) : la validation se fera via l'autocomplete Amazon.fr, qui fonctionne par \
PRÉFIXE (il complète le début tapé). Donne pour chaque niche 'requete_amazon' = la requête COURTE et \
RÉELLE telle qu'un acheteur la tape dans Amazon (2 à 4 mots — ex. « rêve lucide », « sophrologie », \
« tarot de marseille »), JAMAIS un titre descriptif long. Les satellite_keywords sont d'AUTRES \
requêtes courtes réelles du même genre. Test simple : si tu ne taperais pas l'expression telle \
quelle dans Amazon, elle est mauvaise.

Pour chaque niche : le libellé 'niche', la 'requete_amazon' courte, 2-5 satellite_keywords réels, une \
rationale TRANCHÉE en une phrase (pourquoi ça marche), la catégorie, et les risques éventuels \
(TOS, expert pointu, saisonnalité suspectée). Ne remplis 'risques' que si pertinent. \
Qualité > quantité : pas de remplissage générique.
"""

# Schéma d'outil (JSON Schema "à plat", compatible tous SDK/versions Anthropic).
NICHE_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "niches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "niche": {"type": "string", "description": "Libellé lisible de l'angle / de la niche"},
                    "requete_amazon": {
                        "type": "string",
                        "description": "Requête COURTE (2-4 mots) telle que tapée sur Amazon, ex. 'rêve lucide'",
                    },
                    "satellite_keywords": {
                        "type": "array", "items": {"type": "string"},
                        "description": "2 à 5 AUTRES requêtes courtes réelles (comme tapées sur Amazon)",
                    },
                    "rationale": {"type": "string", "description": "Pourquoi c'est une bonne niche livre (1 phrase)"},
                    "categorie": {"type": "string"},
                    "risques": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["niche", "requete_amazon", "satellite_keywords", "rationale", "categorie", "risques"],
            },
        }
    },
    "required": ["niches"],
}


def build_user_prompt(seed: str | None, signals: dict | None, n: int) -> str:
    """Construit le message utilisateur selon le mode (graine ou à partir de rien)."""
    if seed:
        return (
            f"Graine fournie : « {seed} ».\n"
            f"Génère {n} niches livre : la niche centrale ET ses sous-niches / univers connexes "
            f"réellement recherchés sur Amazon.fr. Va au-delà des reformulations — explore "
            f"latéralement.\nRéponds via l'outil proposer_niches."
        )
    signals = signals or {}
    top = ", ".join(list(signals)[:40]) if signals else "(aucun signal fourni)"
    return (
        "Aucune graine imposée.\n"
        f"Voici des signaux de tendance récents (mots-clés issus de Google Trends / Reddit / "
        f"Google News FR) : {top}.\n"
        f"Fais-en émerger {n} niches livre EVERGREEN exploitables. Ne recopie pas les mots-clés "
        f"d'actualité : transforme-les en sujets de livre durables (savoir, méthode, identité, "
        f"passion, histoire).\nRéponds via l'outil proposer_niches."
    )


def _default_client():
    load_dotenv()
    import anthropic
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def generate_niches(seed: str | None = None, signals: dict | None = None,
                    n: int = 20, model: str | None = None, client=None,
                    on_usage=None) -> list[NicheCandidate]:
    """Génère des niches livre candidates. `client` (Anthropic) injectable pour les tests.
    `on_usage(input_tokens, output_tokens, model)` optionnel : coût LLM réel."""
    client = client or _default_client()
    model = model or DEFAULT_MODEL
    user = build_user_prompt(seed, signals, n)
    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        tools=[{
            "name": "proposer_niches",
            "description": "Renvoie la liste des niches livre candidates.",
            "input_schema": NICHE_INPUT_SCHEMA,
        }],
        tool_choice={"type": "tool", "name": "proposer_niches"},
        messages=[{"role": "user", "content": user}],
    )
    if on_usage is not None and getattr(resp, "usage", None) is not None:
        on_usage(getattr(resp.usage, "input_tokens", 0),
                 getattr(resp.usage, "output_tokens", 0), model)
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            return NicheList.model_validate(block.input).niches
    return []
