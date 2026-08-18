"""models.py — types partagés du scout v2 (Pydantic).
Le Plan 2 y ajoutera SearchResult, ScoredNiche."""
import unicodedata

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class LowContentNiche(NicheCandidate):
    """Une niche LOW-CONTENT : un trio format x theme x public sur une requete reelle.

    Herite de `NicheCandidate` pour une raison precise, pas par commodite : la phase 2
    gratuite du scout non-fiction (`niche_validator.validate_niches`) consomme des
    `NicheCandidate` et n'a pas besoin d'etre touchee. Heriter plutot que dupliquer, c'est
    reutiliser le gate gratuit tel quel -- celui qui garantit qu'aucune niche non validee
    ne coute un appel payant.

    `source` distingue deux choses qui ne se lisent PAS pareil :
    - "autocomplete" : la requete vient de l'arbre, donc des gens la tapent vraiment ;
    - "ideation" : le modele l'a proposee, c'est une hypothese qu'Amazon n'a pas confirmee.
    Les confondre effacerait la distinction qui justifie tout le mecanisme low-content.

    `other_libelle` joue le meme role que `TropeClassification.other` : une requete
    inclassable n'est pas un dechet, c'est LE signal qui fera evoluer la taxonomie en v2.
    La jeter perdrait l'information la plus utile du run."""
    format_cle: str = "other"              # cle de la taxo LC, ou "other"
    other_libelle: str = ""                # rempli seulement si format_cle == "other"
    theme: str = ""
    public: str = ""
    source: Literal["autocomplete", "ideation"] = "autocomplete"
    # Position dans l'arbre d'autocomplete. Zero est ici une valeur JUSTE pour une niche
    # issue de l'ideation (elle n'a pas ete trouvee dans une traine), pas une mesure
    # manquante deguisee : c'est `source` qui dit laquelle des deux on regarde.
    profondeur_autocomplete: int = 0
    n_enfants_autocomplete: int = 0


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


class TopBook(BaseModel):
    """Un concurrent du top ORGANIQUE, avec de quoi le juger sans re-payer une SERP.

    `top_asins` ne portait que des identifiants : l'UI, le Dossier PDF et le verdict
    devaient soit re-interroger Amazon, soit se passer des concurrents -- c'est-a-dire
    priver l'auteur de la seule chose qu'il veut voir, contre QUI il publierait.

    `bsr` a None quand le classement n'a pas ete resolu. Jamais 0 : zero serait le
    MEILLEUR classement possible, donc un BSR manquant se lirait comme un best-seller
    (5.10). `sponsored` reste dans le modele bien qu'il vaille toujours False ici : le
    jour ou un appelant voudra montrer les sponsorises a part, le champ dira lequel est
    lequel plutot que de laisser deviner."""
    asin: str
    title: str = ""
    url: str = ""
    price: float | None = None
    rating: float | None = None
    reviews_count: int | None = None
    bsr: int | None = None
    sponsored: bool = False


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
    # False = la SERP n'a pas répondu (solde épuisé, file en panne) : les compteurs de
    # concurrence valent 0 parce que RIEN n'a été mesuré, pas parce que le rayon est vide.
    # Défaut pessimiste, comme AutocompleteSignal.mesure : un champ jamais renseigné doit
    # se lire « non mesuré », jamais « mesuré à zéro ».
    concurrence_mesuree: bool = False
    # Fourchette de prix du rayon (organiques seulement). `None` = aucun prix connu, JAMAIS
    # 0 : un prix absent tiré à zéro ferait croire à un rayon bradé. `n_prix_connus` dit sur
    # combien de livres la fourchette porte réellement — sans lui, « 9,99-19,99 » sur deux
    # livres se lit comme « 9,99-19,99 » sur vingt.
    prix_min: float | None = None
    prix_median: float | None = None
    prix_max: float | None = None
    n_prix_connus: int = 0
    # Ce que disent les suggestions Amazon, au-delà de leur nombre. Drapeaux, pas score.
    terme_dominant: str | None = None
    part_dominante: float = 0.0
    intention_informationnelle: bool = False
    marqueurs_informationnels: list[str] = Field(default_factory=list)
    top_asins: list[str] = Field(default_factory=list)
    # Les concurrents du top organique, ordre de la SERP conserve : la position EST une
    # donnee, la reclasser par BSR ou par prix effacerait ce qu'Amazon montre a l'acheteur.
    top_books: list[TopBook] = Field(default_factory=list)
    verdict: NicheVerdict | None = None    # rempli pour le top-N (gate coût)


class LowContentScored(BaseModel):
    """Une niche low-content entierement evaluee, sur QUATRE axes.

    Deux axes de plus qu'en non-fiction, parce que deux questions n'y existent pas :
    - RENTABILITE : sous 9,99 EUR de prix catalogue, KDP verse 50 % au lieu de 60 %, et le
      cout d'impression se deduit ensuite. Un rayon a 6,99 EUR peut etre demande et ne
      rien rapporter.
    - FAISABILITE : un carnet quadrille et un cahier d'activites illustre ne se produisent
      pas dans le meme monde. Le non-fiction n'a pas ce probleme (tout est du texte).

    Trois champs peuvent valoir None, et c'est LE point du modele. `0.0` sur `part_indie`
    voudrait dire "aucun livre indie dans ce rayon" -- une mesure, et une mauvaise
    nouvelle. `None` dit "aucun editeur n'a pu etre lu" -- une absence. Le scoring
    n'applique aucun bonus ni malus sur None (5.10), et l'ecran doit le dire au lieu
    d'afficher un zero."""
    niche: LowContentNiche

    # scores (0-10)
    global_score: float = 0.0
    demande: float = 0.0
    penetration: float = 0.0
    rentabilite: float = 0.0
    faisabilite: float = 0.0
    priorite: str = ""

    # demande
    demand_autocomplete: int = 0
    n_organic: int = 0
    n_sponsored: int = 0
    n_concurrents_cibles: int = 0

    # penetration -- l'asymetrie du rayon low-content
    n_variantes_quasi_identiques: int = 0
    part_indie: float | None = None                    # None = aucun editeur lu
    part_editeurs_traditionnels: float | None = None
    n_editeur_inconnu: int = 0                         # sur combien la part NE porte pas
    part_moins_12_mois: float | None = None

    # rentabilite
    prix_median: float | None = None
    prix_sous_seuil_60pct: bool = False                # drapeau de bareme, pas un jugement
    redevance_estimee: float | None = None
    pages_median: int | None = None

    # BSR (memes criteres 4.1 qu'en non-fiction)
    bsr_best: int | None = None
    bsr_top_avg: int | None = None
    bsr_worst: int | None = None
    criteres_bsr_ok: bool = False
    total_reviews: int | None = None

    # Comme en non-fiction : False = la SERP n'a pas repondu, pas "rayon vide".
    concurrence_mesuree: bool = False

    top_books: list[TopBook] = Field(default_factory=list)
    # Contrairement au non-fiction ou `risques` est un champ MORT (4.2), il voyage ici
    # jusqu'au score : ip_marque et tos valent -2 sur le global, saisonnier -1.
    risques: list[str] = Field(default_factory=list)
    verdict: NicheVerdict | None = None


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
    # Lecture du CONTENU des suggestions (cf. niche_validator.lire_suggestions).
    # DRAPEAUX, jamais des points de score : les ajouter au score serait un jugement
    # déguisé en mesure, comme pour la fourchette de prix.
    terme_dominant: str | None = None       # mot hors requête présent dans >= la moitié
    part_dominante: float = 0.0
    intention_informationnelle: bool = False
    marqueurs_informationnels: list[str] = Field(default_factory=list)


class MotsClesKDP(BaseModel):
    """Les 7 emplacements de mots-clés backend KDP, plus ce qui n'y est pas entré.

    `rejetes` porte le MOTIF de chaque écart : un mot-clé retiré en silence est une
    décision que l'auteur ne peut ni comprendre ni contester (CLAUDE.md §10)."""
    emplacements: list[str] = Field(default_factory=list)          # <= 7, <= 50 caractères
    a_verifier: list[str] = Field(default_factory=list)            # volume à confirmer à la main
    confirmes_par_amazon: list[str] = Field(default_factory=list)  # sondés avec succès (gratuit)
    rejetes: list[dict] = Field(default_factory=list)              # [{"mot":…, "motif":…}]
    # True = autocomplete injoignable : rien n'est CONFIRMÉ, les emplacements restent des
    # paris. Sans ce drapeau, une sonde en panne se lirait comme « aucun mot ne marche ».
    sonde_indisponible: bool = False


class FictionNiche(BaseModel):
    """Un trio fiction : sous-genre × trope(s) × décor, sur un marketplace et un rayon."""
    sous_genre: str
    tropes: list[str] = Field(default_factory=list)     # 1..3 clés de la taxonomie
    decor: str | None = None
    marketplace: str = "fr"                             # paramètre de premier rang
    rayon: str = "kindle"                               # "kindle" | "papier" — commutable
    query: str = ""                                     # requête naturelle dérivée


class AutocompleteProbe(BaseModel):
    """Une requête sondée. `echec`/`erreur` renseignés = la sonde n'a rien mesuré ;
    ce n'est PAS la même chose que zéro suggestion (CLAUDE.md §10)."""
    requete: str
    suggestions: list[str] = Field(default_factory=list)
    echec: bool = False
    erreur: str | None = None

    @staticmethod
    def _norm(s: str) -> str:
        """Casse, espaces ET diacritiques : les requêtes viennent d'un LLM en français
        naturel alors qu'Amazon suggère indifféremment « francais » et « français ».
        Sans ce dépouillement, la même donnée change de note d'un cran entier."""
        plat = unicodedata.normalize("NFKD", s or "")
        plat = "".join(c for c in plat if not unicodedata.combining(c))
        return " ".join(plat.split()).casefold()

    @property
    def echo(self) -> bool:
        """Amazon renvoie souvent la requête elle-même : présence = le terme existe,
        mais sans aucune expansion (signal faible, pas nul)."""
        return any(self._norm(s) == self._norm(self.requete) for s in self.suggestions)

    @property
    def extras(self) -> list[str]:
        """Suggestions autres que l'écho, dédupliquées — la vraie mesure d'intérêt.
        Deux fois la même suggestion ne fait pas deux signaux."""
        n = self._norm(self.requete)
        vus: dict[str, str] = {}
        for s in self.suggestions:
            k = self._norm(s)
            if k != n and k not in vus:
                vus[k] = s
        return list(vus.values())


class AutocompleteSignal(BaseModel):
    """Soft signal M5. Le spike M0 §V3 est formel : ne gate JAMAIS seul."""
    niche_query: str
    score: float = 0.0                     # 0 / 0.5 / 1
    probes: list[AutocompleteProbe] = Field(default_factory=list)
    sous_genre_cherche: bool | None = None  # barreau 2 : None si non sondé
    # Défaut PESSIMISTE : un signal jamais sondé doit se lire « je n'ai rien mesuré », pas
    # « absent ». Sinon le score 0 par défaut est indiscernable d'un 0 mesuré, et la
    # garantie vendue à M5 (ne pas confondre les deux) ne vaut rien.
    mesure: bool = False

    @property
    def libelle(self) -> str:
        if not self.mesure:
            return "non mesuré (sonde en échec)"
        return {1.0: "expansions", 0.5: "écho seul"}.get(self.score, "absent")


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
    # Sans interet en fiction, ils SONT le produit en low-content : la redevance KDP se
    # calcule sur le nombre de pages (cout d'impression fixe sous 110 pages, au-dela cout
    # par page) et le format papier decide de la grille. `dimensions` reste du TEXTE brut :
    # "15.24 x 0.71 x 22.86 cm" est ce qu'Amazon affiche, et l'ordre des axes n'est garanti
    # nulle part -- le decouper en trois flottants inventerait une precision absente.
    pages: int | None = None
    dimensions: str | None = None
    format_papier: str | None = None       # libelle Amazon : "Broche", "Relie", "Poche"
    langue: str | None = None
    serie_tome: int | None = None                       # clé « Livre N sur M »
    serie_total: int | None = None
    series_hint: bool = False                           # fallback heuristique
    serp_position: int = 0
    blurb: str | None = None  # items[0].description — entrée du classifieur M4 (100 % de couverture mesurée au spike)

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
    est_roman: bool = True          # False = jeu, coloriage, cahier… -> hors scoring
    hors_sujet: str = ""            # pourquoi, quand est_roman est False
    # Étiquette humaine obtenue par VALIDATION TACITE : le relecteur a déclaré avoir lu la
    # ligne et ne l'a pas corrigée. C'est un accord réel, mais établi autrement qu'une
    # correction explicite — la provenance doit rester visible dans le rapport, sinon on ne
    # distingue plus « relu et validé » de « jamais regardé » (le piège A3/A4).
    valide_tacitement: bool = False
    # Saisie humaine (xlsx de validation) qui ne matche AUCUNE clé de la taxonomie même
    # après normalisation : une FAUTE DE SAISIE à corriger, distincte de `other` (qui, lui,
    # signale une vraie observation hors taxo côté IA et fait évoluer la taxonomie).
    fautes_saisie: list[str] = Field(default_factory=list)


class FictionNicheReport(BaseModel):
    """Rapport complet d'une niche fiction (couches 1 et 2)."""
    # extra interdit : un champ mal nommé (ex. l'ancien `autocomplete_score`) serait
    # sinon avalé en silence, laissant croire que la note est portée alors qu'elle est
    # perdue. Mieux vaut lever à la construction.
    model_config = ConfigDict(extra="forbid")

    niche: FictionNiche
    books: list[EnrichedBook] = Field(default_factory=list)
    classifications: list[TropeClassification] = Field(default_factory=list)
    depth_score: float = 0.0
    openness_score: float = 0.0
    saturation_trio: float = 0.0
    # Le SIGNAL entier, pas sa note : un float perdrait `mesure` et `sous_genre_cherche`,
    # et 0.0 redeviendrait à la fois le défaut et le verdict « absent ».
    autocomplete: AutocompleteSignal | None = None
    demand_matrix: str = ""
    series_share: float = 0.0
    price_band: list[float] = Field(default_factory=list)
    seasonality: str | None = None
    verdict: str = ""
    cost_run: float = 0.0

    @property
    def autocomplete_score(self) -> float | None:
        """None tant que la sonde n'a rien mesuré — M5 doit trancher explicitement au
        lieu de recevoir un 0.0 qui ressemble à un verdict."""
        if self.autocomplete is None or not self.autocomplete.mesure:
            return None
        return self.autocomplete.score
