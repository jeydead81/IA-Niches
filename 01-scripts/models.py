"""models.py — types partagés du scout v2 (Pydantic).
Le Plan 2 y ajoutera NicheCandidate, SearchResult, ScoredNiche."""
from pydantic import BaseModel, Field


class BsrInfo(BaseModel):
    """Classement des ventes d'une fiche produit amazon.fr (bloc 'Classement
    des meilleures ventes')."""
    asin: str | None = None
    rank_livres: int                       # rang dans la catégorie racine "Livres"
    subcategories: list[dict] = Field(default_factory=list)  # [{"category": str, "rank": int}]
    raw: str | None = None                 # extrait texte pour debug/transparence
