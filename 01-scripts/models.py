"""models.py — types partagés du scout v2 (Pydantic).
Le Plan 2 y ajoutera SearchResult, ScoredNiche."""
from pydantic import BaseModel, Field


class BsrInfo(BaseModel):
    """Classement des ventes d'une fiche produit amazon.fr (bloc 'Classement
    des meilleures ventes')."""
    rank_livres: int                       # rang dans la catégorie racine "Livres"
    asin: str | None = None
    subcategories: list[dict] = Field(default_factory=list)  # [{"category": str, "rank": int}]
    raw: str | None = None                 # extrait texte pour debug/transparence


class NicheCandidate(BaseModel):
    """Une niche livre candidate proposée par l'ideator LLM (avant validation Amazon)."""
    niche: str                              # libellé lisible de l'angle / de la niche
    requete_amazon: str = ""                # requête COURTE telle que tapée sur Amazon (2-4 mots)
    satellite_keywords: list[str] = Field(default_factory=list)  # autres requêtes courtes réelles
    rationale: str                          # pourquoi c'est une bonne niche livre (1 phrase)
    categorie: str                          # ex. "santé", "développement personnel", "histoire"
    risques: list[str] = Field(default_factory=list)  # flags (TOS, expert pointu, saisonnier suspecté…)


class NicheList(BaseModel):
    """Enveloppe de la sortie structurée de l'ideator."""
    niches: list[NicheCandidate] = Field(default_factory=list)


class NicheValidation(BaseModel):
    """Une niche confrontée à l'autocomplete Amazon.fr (preuve de demande réelle)."""
    niche: str
    requete_amazon: str = ""
    categorie: str
    satellite_keywords: list[str] = Field(default_factory=list)
    amazon_suggestions: list[str] = Field(default_factory=list)  # complétions réelles renvoyées par Amazon
    demand_score: int = 0                   # nb de suggestions Amazon distinctes surfacées
    queries_hit: int = 0                    # nb de requêtes (niche+satellites) qu'Amazon auto-complète
    validated: bool = False                 # True si Amazon auto-complète au moins une requête
