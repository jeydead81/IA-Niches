"""kdp_keywords.py — les 7 mots-clés backend que l'auteur saisit dans KDP à la publication.

L'angle du module : les concurrents (Publisher Rocket, KDSPY…) génèrent des mots-clés puis
affichent un volume ESTIMÉ. Nous disposons déjà d'un canal gratuit et factuel — l'autocomplete
Amazon.fr — donc on ne devine pas : on demande au LLM ~22 candidats, on les SONDE tous pour
0 $, et un mot-clé qu'Amazon ne complète pas ne monte pas dans les 7.

Les contraintes de KDP sont vérifiées CÔTÉ CODE, jamais seulement demandées au prompt : un
modèle les oublie sous pression, exactement comme il oubliait la taxonomie dans
fiction_ideator."""
import json
import os
import re
import unicodedata

from dotenv import load_dotenv

from models import MotsClesKDP, NicheCandidate, ScoredNiche

DEFAULT_MODEL = os.getenv("KDP_KEYWORDS_MODEL", "claude-sonnet-5")

# Contrainte dure d'Amazon : au-delà, la fin de l'expression est tronquée EN SILENCE.
LIMITE_CARACTERES = 50
N_EMPLACEMENTS = 7

# Proscrits par les conditions KDP, ou sans valeur parce qu'Amazon les indexe déjà de
# toute façon (le format, la boutique). Un emplacement gaspillé sur « livre » est un
# emplacement de moins sur une vraie requête — et il n'y en a que sept.
TERMES_INTERDITS = frozenset({
    "livre", "livres", "ebook", "ebooks", "kindle", "broche", "broché", "roman gratuit",
    "gratuit", "gratuite", "promo", "promotion", "solde", "soldes",       # prix / offre
    "meilleur", "meilleure", "meilleurs", "top", "numero 1", "numéro 1",  # superlatifs
    "nouveau", "nouvelle", "nouveaute", "nouveauté", "2024", "2025", "2026",  # temporel
    "amazon", "bestseller", "best seller",
})


def _normalise(s: str) -> str:
    """Casse, espaces multiples et accents dépouillés — sert à comparer, jamais à afficher."""
    plat = unicodedata.normalize("NFKD", s or "")
    plat = "".join(c for c in plat if not unicodedata.combining(c))
    return " ".join(plat.split()).casefold()


def _mots(s: str) -> set[str]:
    return {m for m in re.split(r"[^\w]+", _normalise(s)) if len(m) > 2}


def nettoyer_candidats(candidats, titre: str = "") -> tuple[list[str], list[tuple[str, str]]]:
    """Applique les règles KDP. Rend (gardés, [(rejeté, motif)]).

    Les rejets sortent AVEC leur motif : un mot-clé écarté en silence est une décision
    invisible pour l'auteur, qui ne peut ni la comprendre ni la contester (CLAUDE.md §10)."""
    mots_titre = _mots(titre)
    gardes: list[str] = []
    rejets: list[tuple[str, str]] = []
    vus: set[str] = set()

    for brut in candidats or []:
        if not isinstance(brut, str):
            continue
        k = " ".join(brut.split())
        if not k:
            continue
        norme = _normalise(k)

        if norme in vus:
            rejets.append((k, "doublon"))
            continue
        if len(k) > LIMITE_CARACTERES:
            rejets.append((k, f"{len(k)} caractères — la limite KDP est de "
                              f"{LIMITE_CARACTERES}, Amazon tronquerait la fin"))
            continue

        interdit = next((t for t in TERMES_INTERDITS if t in norme), None)
        if interdit:
            rejets.append((k, f"terme proscrit ou déjà indexé par Amazon : « {interdit} »"))
            continue

        # Tous les mots significatifs déjà dans le titre -> l'emplacement n'apporterait rien.
        significatifs = _mots(k)
        if mots_titre and significatifs and significatifs <= mots_titre:
            rejets.append((k, "déjà présent dans le titre — Amazon l'indexe déjà"))
            continue

        vus.add(norme)
        gardes.append(k)

    return gardes, rejets


SYSTEM_PROMPT = """\
Tu es SPÉCIALISTE du référencement Amazon KDP en français. Tu produis les mots-clés \
« backend » — les 7 champs cachés qu'un auteur remplit au moment de publier, et qui \
décident de la découvrabilité du livre.

CE QUE TU PRODUIS : des EXPRESSIONS telles qu'un lecteur les tape réellement dans la barre \
de recherche Amazon, pas des étiquettes de catalogue. 3 à 5 mots. Longue traîne : \
« enquête pâtissière village breton » vaut mieux que « policier », qui est injouable.

INTERDITS (conditions KDP, ou déjà indexé par Amazon donc gaspillé) : les mots « livre », \
« ebook », « kindle », « broché », « gratuit », « meilleur », « nouveau », toute mention \
d'année, tout nom d'auteur ou de marque, tout superlatif subjectif.

NE REPRENDS PAS les mots du titre ni du sous-titre : Amazon les indexe déjà, les redonner \
gâche un des sept emplacements.

50 CARACTÈRES MAXIMUM par expression — au-delà Amazon tronque sans prévenir.

Propose 22 expressions, variées : certaines sur le thème, d'autres sur le public visé, \
d'autres sur la situation de lecture ou le ressort d'intrigue attendu.
"""

CANDIDATS_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "candidats": {
            "type": "array",
            "items": {"type": "string",
                      "description": "une expression telle qu'un lecteur la taperait"},
        }
    },
    "required": ["candidats"],
    "additionalProperties": False,          # exigé par le mode STRICT
}

# Motif du rejet porté par `rejetes` quand la réponse ne se lit pas : le seul canal que le
# dossier et l'écran affichent déjà, sans changer le modèle `MotsClesKDP`.
MOTIF_ILLISIBLE = ("réponse de l'IA illisible : les candidats ne forment pas une liste, "
                   "ils ont été ignorés")


def _json_si_texte(v):
    """Une chaîne JSON valide est DÉCODÉE (contenu du modèle, seulement sérialisé) ; le reste
    est rendu tel quel et déclaré illisible par l'appelant."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def _lib(cle) -> str:
    return str(cle or "").replace("_", " ")


def candidat_fiction(report, pitch: str = "") -> tuple[NicheCandidate, str]:
    """Le trio d'un roman, présenté au générateur comme une niche, plus son CONTEXTE en clair.

    Les clés de taxonomie se lisent en français (« enemies to lovers », jamais le tiret bas) : le
    modèle en tire des expressions qu'un lecteur tape. Le pitch donne l'ambiance, pas la lettre —
    le prompt dit de ne pas en recopier les phrases. Les mots-clés d'un roman sont le genre et ses
    ressorts, le décor, la situation de lecture : jamais un titre de roman existant."""
    n = report.niche
    tropes = [_lib(t) for t in n.tropes]
    label = " × ".join([_lib(n.sous_genre)] + tropes + ([_lib(n.decor)] if n.decor else []))
    contexte = [f"ROMAN de fiction : sous-genre « {_lib(n.sous_genre)} »"
                + (" · tropes : " + ", ".join(f"« {t} »" for t in tropes) if tropes else "")
                + (f" · décor : « {_lib(n.decor)} »" if n.decor else ""),
                "Vise le genre et ses ressorts reconnaissables, le décor, l'ambiance et la "
                "situation de lecture. Jamais un titre de roman existant."]
    if pitch:
        contexte.append("PITCH (donne l'ambiance, ne recopie pas ses phrases) : " + pitch)
    cand = NicheCandidate(niche=label, requete_amazon=n.query, categorie=f"Fiction · {_lib(n.sous_genre)}",
                          rationale="")
    return cand, "\n".join(contexte)


def build_user_prompt(scored: ScoredNiche, titre: str = "", contexte: str = "") -> str:
    lignes = [f"NICHE : {scored.niche}"]
    if scored.requete_amazon:
        lignes.append(f"Requête Amazon principale : {scored.requete_amazon}")
    if scored.categorie:
        lignes.append(f"Catégorie : {scored.categorie}")
    if scored.satellite_keywords:
        lignes.append("Requêtes satellites déjà repérées : "
                      + ", ".join(scored.satellite_keywords))
    if contexte:
        lignes.append(contexte)
    if titre:
        lignes.append(f"TITRE PRÉVU (n'en reprends pas les mots) : {titre}")
    lignes.append("\nPropose les expressions via l'outil proposer_mots_cles.")
    return "\n".join(lignes)


MOTS_AMORCE = 3


def amorce(expression: str) -> str:
    """Les MOTS_AMORCE premiers mots — c'est CE qu'on sonde, pas l'expression entière.

    L'autocomplete d'Amazon est PRÉFIXE-based : mesuré au spike M3, une expression longue
    et précise ne remonte rien (« cosy mystery boulangerie bretagne » -> 0) alors que son
    amorce est une vraie voie de recherche. Or les mots-clés backend sont par nature de la
    longue traîne : sonder l'expression complète garantissait 0 confirmation sur 7,
    constaté en live. On vérifie donc que l'amorce est cherchée — pas que la phrase
    exacte l'est, ce qu'aucun outil ne peut établir depuis l'autocomplete."""
    mots = (expression or "").split()
    return " ".join(mots[:MOTS_AMORCE])


def _default_client():
    load_dotenv()
    import anthropic
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _default_sonde(prefixe: str) -> list[str]:
    from amazon_autocomplete import fetch_suggestions
    return fetch_suggestions(prefixe)


def generer_mots_cles(scored: ScoredNiche, titre: str = "", client=None, sonde=None,
                      model: str | None = None, on_usage=None, contexte: str = "") -> MotsClesKDP:
    """7 mots-clés backend, dont les confirmés par Amazon en priorité.

    La sonde autocomplete est GRATUITE : on ne se contente donc pas de faire confiance au
    modèle, on vérifie que chaque expression est réellement complétée par Amazon. Un
    mot-clé qu'Amazon ne suggère pas est un mot-clé que personne ne tape."""
    client = client or _default_client()
    sonde = sonde or _default_sonde
    model = model or DEFAULT_MODEL

    resp = client.messages.create(
        model=model,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        # STRICT : sans lui, l'API ne garantit pas la forme de `tool_use.input` (2026-09-13).
        tools=[{
            "name": "proposer_mots_cles",
            "description": "Renvoie les expressions candidates pour les 7 emplacements KDP.",
            "strict": True,
            "input_schema": CANDIDATS_INPUT_SCHEMA,
        }],
        tool_choice={"type": "tool", "name": "proposer_mots_cles"},
        messages=[{"role": "user", "content": build_user_prompt(scored, titre, contexte)}],
    )
    if on_usage is not None and getattr(resp, "usage", None) is not None:
        on_usage(getattr(resp.usage, "input_tokens", 0),
                 getattr(resp.usage, "output_tokens", 0), model)

    bruts: list[str] = []
    illisible = False
    for block in resp.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        entree = _json_si_texte(block.input)
        candidats = (_json_si_texte(entree.get("candidats"))
                     if isinstance(entree, dict) else None)
        # JAMAIS `extend` d'une chaîne : le rejeu a produit emplacements=['c','a','r','n',
        # 'e','t','d'] sans la moindre erreur, et une sonde les « confirmait ».
        if isinstance(candidats, list):
            bruts.extend(candidats)
        else:
            illisible = True

    gardes, rejets = nettoyer_candidats(bruts, titre)
    if illisible:
        rejets.insert(0, ("(réponse du modèle)", MOTIF_ILLISIBLE))

    # Sonde gratuite : un échec réseau ne doit pas ressembler à « aucun mot ne marche ».
    confirmes: list[str] = []
    sonde_ko = False
    for k in gardes:
        try:
            suggestions = sonde(amorce(k)) or []
        except Exception:  # noqa: BLE001 — sonde indisponible : on dégrade, on ne perd rien
            sonde_ko = True
            break
        if suggestions:
            confirmes.append(k)

    if sonde_ko:
        confirmes = []
    # Les confirmés d'abord : ce sont les seuls dont on SAIT qu'ils sont tapés.
    ordonnes = confirmes + [k for k in gardes if k not in confirmes]
    return MotsClesKDP(
        emplacements=ordonnes[:N_EMPLACEMENTS],
        a_verifier=ordonnes[N_EMPLACEMENTS:],
        confirmes_par_amazon=confirmes,
        rejetes=[{"mot": m, "motif": motif} for m, motif in rejets],
        sonde_indisponible=sonde_ko,
    )
