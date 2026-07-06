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
    niche: str                              # libellé de la niche / requête centrale
    satellite_keywords: list[str] = Field(default_factory=list)  # requêtes réelles proches
    rationale: str                          # pourquoi c'est une bonne niche livre (1 phrase)
    categorie: str                          # ex. "santé", "développement personnel", "histoire"
    pharma: bool = False                    # relève de l'avantage pharmacien (santé/nutrition/bien-être)
    risques: list[str] = Field(default_factory=list)  # flags (TOS, expert pointu, saisonnier suspecté…)


class NicheList(BaseModel):
    """Enveloppe de la sortie structurée de l'ideator."""
    niches: list[NicheCandidate] = Field(default_factory=list)
