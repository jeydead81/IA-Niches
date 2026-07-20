"""fiction_classifier.py — lit les quatrièmes de couverture d'un rayon et en extrait
tropes/décor. Tool-use forcé, client injectable (aucun réseau en unit-test).

Asymétrie assumée avec fiction_ideator.py : l'ideator INVENTE des trios, donc une clé hors
taxonomie y est un bruit qu'on écarte. Le classifieur OBSERVE de vrais livres : un trope
hors taxonomie vu en vrai est une information qui fait évoluer la taxonomie, pas un déchet
-> il part dans `other`, jamais à la poubelle (cf. plan M4)."""
import os

from dotenv import load_dotenv

from fiction_taxonomy import sous_genre as _sous_genre, valid_keys
from models import EnrichedBook, TropeClassification

DEFAULT_MODEL = os.getenv("FICTION_CLASSIFIER_MODEL", "claude-sonnet-5")

# Le LLM rend parfois littéralement le nom du champ (« other », « autre ») au lieu d'une
# observation — vu en live. Une méta-clé du schéma n'est pas un trope : la conserver ferait
# croire à un trope hors taxonomie récurrent et fausserait l'évolution de la taxonomie.
_META_CLES = {"other", "autre", "none", "aucun", "n/a", "null"}


def _est_meta(cle) -> bool:
    return not isinstance(cle, str) or not cle.strip() or cle.strip().lower() in _META_CLES

SYSTEM_PROMPT = """\
Tu es un ÉDITEUR DE FICTION francophone qui LIT les quatrièmes de couverture d'un rayon \
Amazon.fr pour savoir ce que chaque livre PROMET réellement au lecteur.

MISSION : pour chaque quatrième de couverture fournie, extraire les tropes et le décor \
qu'elle promet — pas ce que tu imaginerais toi-même, ce que CE texte précis annonce.

RÈGLE ABSOLUE — NE FORCE JAMAIS UNE CLÉ APPROCHANTE. Une clé de la liste plaquée de force \
sur un livre qui ne la promet pas est bien PIRE qu'une case vide : elle fait croire à une \
saturation qui n'existe pas. Si rien ne colle vraiment, laisse vide et note ce que tu \
observes dans `other`.

DÉCOR — il doit être ÉCRIT dans le texte, pas déduit d'une ambiance. Choisis la clé la plus \
SPÉCIFIQUE qui corresponde vraiment au lieu nommé. Si le lieu du livre n'a aucune clé, \
laisse `decor` VIDE et mets le lieu réel dans `other`. Exemples de fautes à ne pas commettre :
- « cosy mystery écossais » -> l'Écosse n'a PAS de clé : decor vide, other = ["ecosse"]. \
Surtout pas une autre région au hasard.
- « l'île de Beauté » (la Corse) -> c'est une ÎLE : la clé « ile » existe, prends-la, \
pas « montagne » parce qu'on y parle de maquis.

TROPES — 3 au maximum, les plus SAILLANTS, ceux qui distinguent CE livre des autres du \
rayon. N'empile pas les tropes constitutifs du genre (dans un cosy mystery, « enquêtrice \
amatrice » et « petite communauté » sont presque toujours vrais : ne les cite que s'ils \
sont vraiment mis en avant par le texte). Six tropes sur un livre = tu as décrit le genre, \
pas le livre.

`confidence` : ta confiance réelle dans CETTE lecture (0 à 1). Un blurb vague et \
promotionnel qui ne dit rien de l'intrigue mérite une confiance basse, dis-le.

FILTRE NON-ROMAN : certains produits d'un rayon romans ne sont pas des romans (jeu, cahier \
de coloriage, guide pratique...). Si le texte ne promet pas une HISTOIRE à lire, marque \
est_roman=false et explique pourquoi dans hors_sujet — ne le classe pas en tropes.

N'invente JAMAIS un ASIN absent de la liste fournie : tu ne peux classer QUE les livres \
numérotés ci-dessous, aucun autre.
"""

LIVRES_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "livres": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "asin": {"type": "string", "description": "ASIN exact fourni"},
                    "tropes": {"type": "array", "items": {"type": "string"},
                               "description": "tropes promis par CE blurb, liste ou hors liste"},
                    "decor": {"type": "string", "description": "décor promis, si identifiable"},
                    "est_roman": {"type": "boolean",
                                  "description": "false si ce n'est pas un roman (jeu, cahier...)"},
                    "hors_sujet": {"type": "string",
                                   "description": "pourquoi, quand est_roman est false"},
                    "confidence": {"type": "number", "description": "0 à 1"},
                },
                "required": ["asin", "tropes"],
            },
        }
    },
    "required": ["livres"],
}


def build_user_prompt(sous_genre_cle: str, livres: list[EnrichedBook],
                      version: str = "fr_v1") -> str:
    """Injecte les clés autorisées du sous-genre et numérote les blurbs par ASIN."""
    sg = _sous_genre(sous_genre_cle, version)
    tropes, decors = valid_keys(sous_genre_cle, version)
    blurbs = "\n\n".join(f"[{b.asin}] {b.blurb}" for b in livres)
    return (
        f"SOUS-GENRE : {sous_genre_cle} ({sg['label']})\n\n"
        "TROPES DE RÉFÉRENCE (utilise-les en priorité, `other` sinon) :\n- "
        + "\n- ".join(tropes) + "\n\n"
        "DÉCORS DE RÉFÉRENCE (utilise-les en priorité, `other` sinon) :\n- "
        + "\n- ".join(decors) + "\n\n"
        "QUATRIÈMES DE COUVERTURE (une par ASIN) :\n\n" + blurbs + "\n\n"
        "Classe CHAQUE livre ci-dessus, et uniquement ceux-ci, via l'outil classer_livres."
    )


def _default_client():
    load_dotenv()
    import anthropic
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def classify_books(books: list[EnrichedBook], sous_genre_cle: str, version: str = "fr_v1",
                   model: str | None = None, client=None,
                   on_usage=None) -> list[TropeClassification]:
    """Classifie en un seul appel batché les livres du rayon qui ont un blurb.
    Clés connues -> tropes/décor ; clés inconnues -> other (jamais perdues) ;
    ASIN halluciné par le LLM -> ignoré (il ne peut pas ajouter un livre au rayon)."""
    livres = [b for b in books if b.blurb]
    if not livres:
        return []                          # aucun blurb -> aucun appel, rien à payer
    client = client or _default_client()
    model = model or DEFAULT_MODEL
    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        temperature=0,          # instrument de mesure : pas de variation d'un run à l'autre
        system=SYSTEM_PROMPT,
        tools=[{
            "name": "classer_livres",
            "description": "Renvoie la classification tropes/décor de chaque livre.",
            "input_schema": LIVRES_INPUT_SCHEMA,
        }],
        tool_choice={"type": "tool", "name": "classer_livres"},
        messages=[{"role": "user",
                   "content": build_user_prompt(sous_genre_cle, livres, version)}],
    )
    if on_usage is not None and getattr(resp, "usage", None) is not None:
        on_usage(getattr(resp.usage, "input_tokens", 0),
                 getattr(resp.usage, "output_tokens", 0), model)

    tropes_ok, decors_ok = valid_keys(sous_genre_cle, version)
    asins_envoyes = {b.asin for b in livres}
    out: list[TropeClassification] = []
    for block in resp.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        for l in ((block.input or {}).get("livres") or []):
            asin = l.get("asin")
            if asin not in asins_envoyes:
                continue                    # ASIN hors du lot -> le LLM ne peut pas inventer un livre
            tropes_in = [t for t in dict.fromkeys(l.get("tropes") or [])
                         if not _est_meta(t)]                        # dédup, ordre préservé
            decor_in = l.get("decor") or None
            if _est_meta(decor_in):
                decor_in = None

            other = [t for t in tropes_in if t not in tropes_ok]
            if decor_in and decor_in not in decors_ok:
                other.append(decor_in)

            out.append(TropeClassification(
                asin=asin,
                taxonomy_version=version,
                tropes=[t for t in tropes_in if t in tropes_ok],
                decor=decor_in if decor_in in decors_ok else None,
                other=other,
                confidence=l.get("confidence") or 0.0,
                est_roman=l.get("est_roman", True),
                hors_sujet=l.get("hors_sujet") or "",
            ))
    return out
