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


class FictionNiche(BaseModel):
    """Un trio fiction : sous-genre × trope(s) × décor, sur un marketplace et un rayon."""
    sous_genre: str
    tropes: list[str] = Field(default_factory=list)     # 1..3 clés de la taxonomie
    decor: str | None = None
    marketplace: str = "fr"                             # paramètre de premier rang
    rayon: str = "kindle"                               # "kindle" | "papier" — commutable
    query: str = ""                                     # requête naturelle dérivée


class EnrichedBook(BaseModel):
    """Un livre du rayon, enrichi via l'endpoint ASIN. Le BSR porte TOUJOURS son rayon :
    les rangs « Livres » et « Boutique Kindle » ne sont pas comparables, et un classement
    « titres gratuits » n'est pas un rang de ventes payantes."""
    asin: str
    title: str
    author: str | None = None
    price: float | None = None
    reviews_count: int | None = None
    rating: float | None = None
    bsr: int | None = None
    bsr_rayon: str | None = None                        # "Boutique Kindle" | "Livres"
    bsr_gratuit: bool = False                           # rang « titres gratuits » -> hors scoring
    bsr_subcats: list[dict] = Field(default_factory=list)
    publication_date: str | None = None
    publisher: str | None = None
    langue: str | None = None
    serie_tome: int | None = None                       # clé « Livre N sur M »
    serie_total: int | None = None
    series_hint: bool = False                           # fallback heuristique
    serp_position: int = 0

    @property
    def est_serie(self) -> bool:
        # « Livre 1 sur 1 » = tome unique : Amazon le balise comme une collection d'un seul
        # titre, ce n'est PAS une série (vu sur B0GN4G414V).
        return bool((self.serie_total or 0) > 1 or self.series_hint)

    def est_payant_dans(self, rayon_vise: str) -> bool:
        """Le BSR est-il exploitable pour le scoring de ce rayon ?

        `rayon_vise` attend le LIBELLÉ AMAZON ("Boutique Kindle" | "Livres"), le même
        vocabulaire que `bsr_rayon` — PAS le paramètre interne FictionNiche.rayon
        ("kindle"/"papier"). Obtenir ce libellé via `fiction_taxonomy.label_rayon()` ;
        passer "kindle"/"papier" tel quel ne matche jamais rien et fait déclarer la
        niche morte pour TOUS les livres (piège M5)."""
        return bool(self.bsr) and not self.bsr_gratuit and self.bsr_rayon == rayon_vise


class FictionShelf(BaseModel):
    """Rayon reconstitué d'une niche fiction. Porte les compteurs d'échec : sans eux, un
    rayon amputé en silence passerait pour une niche déserte (CLAUDE.md §10)."""
    niche: FictionNiche
    search_param: str
    books: list[EnrichedBook] = Field(default_factory=list)
    asins_demandes: int = 0
    n_echecs: int = 0

    @property
    def complet(self) -> bool:
        return self.n_echecs == 0


class TropeClassification(BaseModel):
    """Classification sémantique d'un blurb, contrainte à la taxonomie."""
    asin: str
    taxonomy_version: str
    tropes: list[str] = Field(default_factory=list)
    decor: str | None = None
    other: list[str] = Field(default_factory=list)      # hors taxo -> fait évoluer la taxo
    confidence: float = 0.0


class FictionNicheReport(BaseModel):
    """Rapport complet d'une niche fiction (couches 1 et 2)."""
    niche: FictionNiche
    books: list[EnrichedBook] = Field(default_factory=list)
    classifications: list[TropeClassification] = Field(default_factory=list)
    depth_score: float = 0.0
    openness_score: float = 0.0
    saturation_trio: float = 0.0
    autocomplete_score: float = 0.0
    demand_matrix: str = ""
    series_share: float = 0.0
    price_band: list[float] = Field(default_factory=list)
    seasonality: str | None = None
    verdict: str = ""
    cost_run: float = 0.0
