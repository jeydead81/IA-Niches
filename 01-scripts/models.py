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


class SearchItem(BaseModel):
    """Un résultat de recherche Amazon.fr (livre) normalisé (issu du provider search)."""
    rank: int | None = None
    asin: str | None = None
    title: str = ""
    url: str | None = None
    price: float | None = None
    currency: str | None = None
    rating: float | None = None            # note moyenne /5
    reviews_count: int | None = None       # nombre d'avis
    is_best_seller: bool = False
    is_amazon_choice: bool = False
    sponsored: bool = False                # True = "Sponsorisé" (à exclure des calculs §4.2)


class SearchResult(BaseModel):
    """Résultats d'une requête Amazon.fr, organiques et sponsorisés séparés."""
    keyword: str
    organic: list[SearchItem] = Field(default_factory=list)
    sponsored: list[SearchItem] = Field(default_factory=list)
    total_items: int = 0


class AngleAttaque(BaseModel):
    """Un angle d'attaque proposé par le verdict directeur éditorial."""
    angle: str
    pourquoi: str
    risque: str
    titre: str
    sous_titre: str
    direction_couverture: str = ""
    prix_suggere: str = ""                 # fourchette lisible, ex. "14,90-19,90 €"
    requete_principale: str = ""
    requetes_secondaires: list[str] = Field(default_factory=list)


class NicheVerdict(BaseModel):
    """Verdict éditorial d'une niche (directeur éditorial §7-8, sur données du scout)."""
    verdict: str                           # "Go" | "Go prudent" | "No-Go"
    confiance: int = 0                     # 1-10
    facteur_decisif: str = ""
    angles: list[AngleAttaque] = Field(default_factory=list)  # 1-3
    saturation: str = ""                   # critique stratégique Q1
    faux_concurrent: str = ""              # Q2 ("aucun" si pas de faux concurrent)
    differenciation: str = ""             # Q3 (exécution / angle / autorité)


class ScoredNiche(BaseModel):
    """Une niche entièrement évaluée (demande + concurrence + BSR réel) et scorée."""
    niche: str
    requete_amazon: str = ""
    categorie: str = ""
    satellite_keywords: list[str] = Field(default_factory=list)
    # scores (0-10)
    global_score: float = 0.0
    demande: float = 0.0
    penetration: float = 0.0
    compatibilite: float = 0.0
    priorite: str = ""                     # badge scout ("🟢 À analyser en priorité"/…), §6.3 col. "Verdict"
    # signaux
    demand_autocomplete: int = 0           # nb de complétions Amazon (canal gratuit)
    n_organic: int = 0
    n_sponsored: int = 0
    n_concurrents_cibles: int = 0          # livres organiques ciblant vraiment la requête
    avg_rating: float | None = None
    total_reviews: int | None = None
    # BSR réel (§4.1) sur le top organique
    bsr_best: int | None = None
    bsr_top5_avg: int | None = None
    bsr_worst_top10: int | None = None
    criteres_bsr_ok: bool = False
    top_asins: list[str] = Field(default_factory=list)
    verdict: NicheVerdict | None = None    # rempli pour le top-N (gate coût)


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
