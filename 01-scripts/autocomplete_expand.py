"""autocomplete_expand.py — descend l'arbre des complétions amazon.fr. GRATUIT.

Renversement par rapport au scout non-fiction. Là-bas, le LLM propose et l'autocomplete
valide. En low-content ça ne tient pas : la tête de requête (« livre coloriage »,
« registre ») est morte ou tenue par des éditeurs, et l'argent est trois crans plus bas
dans la traîne (« coloriage licorne 3 ans fille », « registre du personnel obligatoire »).
Un LLM à qui on demande des requêtes long-tail invente aussi la demande qui va avec.
Amazon, lui, ne complète que ce que des gens tapent réellement, et il le donne pour rien.

D'où l'ordre inversé du low-content : on descend l'arbre D'ABORD, le LLM CLASSE ensuite
(`lowcontent_ideator`). Il ne peut plus inventer une demande qui n'existe pas.

`n_enfants` est le signal que cet arbre apporte et qu'aucun comptage de suggestions ne
donne : une requête que les acheteurs affinent ENCORE porte une intention plus forte
qu'une requête terminale. Il faut avoir descendu l'arbre pour le connaître.

Endpoint non officiel : `max_probes` est un plafond DUR, et la pause entre sondes n'est
pas décorative.
"""
import string
import time
import unicodedata
from dataclasses import dataclass

from amazon_autocomplete import fetch_suggestions as _fetch_suggestions

# 7 jours : une traîne de requêtes bouge à l'échelle de la saison, pas de la journée.
# Aligné sur le cache livre (BOOK_TTL_S) plutôt que sur le cache BSR (3 j), qui suit un
# classement quotidien — ici on met en cache ce que les gens CHERCHENT, pas un rang.
AUTOCOMPLETE_TTL_S = 7 * 24 * 3600

# Plafond par défaut. À 0,4 s de pause, 80 sondes = ~32 s : la limite haute de ce qu'on
# peut faire attendre avant une phase payante qui, elle, dure des minutes.
MAX_PROBES_DEFAUT = 80


@dataclass(frozen=True)
class Suggestion:
    """Une requête réelle trouvée dans l'arbre, avec sa position dedans.

    `parent` et `profondeur` disent D'OÙ elle vient : une requête de profondeur 2 est une
    précision apportée par des acheteurs sur une requête qui en portait déjà une.
    `n_enfants` dit si elle est elle-même encore affinée."""
    requete: str
    parent: str = ""
    profondeur: int = 0
    n_enfants: int = 0


def _plat(texte: str) -> str:
    """Casse et accents dépouillés — même normalisation que `niche_validator._plat`.

    Amazon rend « Livre Coloriage Adulte » et « livre coloriage adulte » comme deux
    complétions distinctes. Les sonder toutes les deux double le budget pour zéro
    information nouvelle."""
    s = unicodedata.normalize("NFKD", texte or "")
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).lower().split())


def _sonder(prefixe: str, fetch, cache, progress) -> list[str]:
    """Une sonde, servie par le cache si possible.

    Le cache est mutualisé entre tous les comptes, comme tout `cache.py` (§5.15) : deux
    clients qui explorent le même rayon ne resondent pas Amazon."""
    if cache is not None:
        garde = cache.get_autocomplete(prefixe)
        if garde is not None:
            return garde
    progress(f"Complétions Amazon « {prefixe} »…")
    # Pas de try/except : si la sonde LÈVE, on laisse remonter. Avaler l'échec ici
    # rendrait une liste vide, que l'appelant lirait « personne ne cherche ça » —
    # l'inversion exacte que §5.10 interdit.
    sugg = list(fetch(prefixe))
    if cache is not None:
        cache.set_autocomplete(prefixe, sugg, AUTOCOMPLETE_TTL_S)
    return sugg


def expand(seed: str, fetch=None, depth: int = 2, alphabet: bool = True,
           max_probes: int = MAX_PROBES_DEFAUT, pause: float = 0.4,
           cache=None, progress=None) -> list[Suggestion]:
    """Descend l'arbre des complétions depuis `seed`. Rend les requêtes RÉELLES trouvées.

    `alphabet=True` sonde aussi « seed a », « seed b »… : Amazon ne rend qu'une dizaine de
    complétions par préfixe, donc la fin de l'alphabet ne sort jamais du préfixe seul.
    C'est ce qui fait apparaître « livre coloriage zen » là où « livre coloriage » ne
    montrait que les cinq premières.

    La graine elle-même n'est jamais rendue : c'est le point de départ, pas une trouvaille.
    La compter ferait passer pour demandée une requête que personne n'a suggérée.

    Une liste vide ne conclut RIEN. C'est à l'appelant de dire « pas de traîne mesurée »,
    jamais « pas de demande »."""
    seed = (seed or "").strip()
    if not seed:
        return []
    fetch = fetch or _fetch_suggestions
    progress = progress or (lambda _m: None)

    vues: set[str] = {_plat(seed)}          # la graine ne peut pas se re-proposer
    sondes = 0
    trouvees: dict[str, Suggestion] = {}    # clé normalisée -> Suggestion

    def budget_restant() -> bool:
        return sondes < max_probes

    # Niveau 0 : la graine, plus éventuellement les 26 amorces alphabétiques.
    prefixes = [seed] + ([f"{seed} {l}" for l in string.ascii_lowercase] if alphabet else [])
    # (prefixe_a_sonder, requete_parente, profondeur_des_enfants)
    file: list[tuple[str, str, int]] = [(p, seed, 1) for p in prefixes]

    while file and budget_restant():
        prefixe, parent, prof = file.pop(0)
        if not budget_restant():
            break
        sugg = _sonder(prefixe, fetch, cache, progress)
        sondes += 1
        if pause and sondes < max_probes:
            time.sleep(pause)

        enfants_retenus = 0
        for s in sugg:
            k = _plat(s)
            if not k or k in vues:
                continue
            enfants_retenus += 1
            vues.add(k)
            trouvees[k] = Suggestion(requete=s.strip(), parent=parent, profondeur=prof)
            if prof < depth:
                file.append((s.strip(), s.strip(), prof + 1))

        # `n_enfants` du PARENT : on ne peut le connaître qu'après l'avoir sondé. Les
        # amorces alphabétiques ne comptent pas comme des enfants du parent — elles
        # sondent le même noeud sous un autre angle, pas un noeud plus profond.
        kp = _plat(prefixe)
        if kp in trouvees and prefixe == parent:
            trouvees[kp] = Suggestion(requete=trouvees[kp].requete,
                                      parent=trouvees[kp].parent,
                                      profondeur=trouvees[kp].profondeur,
                                      n_enfants=enfants_retenus)

    out = sorted(trouvees.values(), key=lambda s: (s.profondeur, s.requete))
    progress(f"{len(out)} requête(s) réelle(s) trouvée(s) en {sondes} sonde(s) "
             f"(gratuit).")
    return out
