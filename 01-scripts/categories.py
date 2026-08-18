"""categories.py — catégories Amazon suggérées à partir des BSR déjà collectés.

La donnée était déjà payée et personne ne la lisait. Chaque `BsrInfo` du top porte ses
sous-catégories de classement : les livres qui marchent dans un rayon DISENT dans quelles
catégories ils sont rangés. Les agréger coûte 0 $ et n'appelle aucun LLM — c'est
exactement le genre de signal que la règle 9 (économie de coût) demande d'exploiter avant
d'envisager un appel payant de plus.

Ce que ce module NE fait PAS, volontairement : recommander. Il constate une fréquence et
un meilleur rang. « 3 livres du top sont rangés ici » est une observation ; « publie ici »
serait un conseil que la donnée ne soutient pas — les catégories du top sont celles de
livres DÉJÀ installés, pas forcément celles où une place est libre. Le nom des clés rendues
(`n_livres`, `meilleur_rang`) dit ce qui a été compté, pas ce qu'il faut en faire.

Fonction pure : aucune E/S, aucun réseau, aucun état.
"""
import unicodedata

# Écartées d'office. « Livres » est la catégorie RACINE : aucune décision à y prendre,
# tout livre y est. « Voir les 100 premiers » est un lien de navigation qu'Amazon glisse
# dans le même bloc de texte — le parseur amont le filtre déjà, mais ce module reçoit
# aussi des BsrInfo construits ailleurs (cache ancien, autre source) et ne doit pas
# dépendre du filtrage de son appelant.
_EXCLUES = ("livres", "voir les")


def _cle(libelle: str) -> str:
    """Clé de regroupement : casse, espaces et accents dépouillés.

    Amazon n'est pas régulier sur la casse d'un même libellé. Deux entrées pour la même
    catégorie diviseraient sa fréquence par deux et la feraient passer derrière une
    catégorie réellement plus rare — l'inverse de ce que la fonction mesure."""
    plat = unicodedata.normalize("NFKD", libelle or "")
    plat = "".join(c for c in plat if not unicodedata.combining(c))
    return " ".join(plat.lower().split())


def suggerer_categories(bsrs, n: int = 3) -> list[dict]:
    """[{category, n_livres, meilleur_rang}], les plus fréquentes d'abord.

    `bsrs` accepte des `None` : `resolve_bsrs` rend `{asin: BsrInfo|None}` et le None est
    le cas NORMAL d'un ASIN dont le classement n'a pas pu être lu, pas une anomalie.

    Tri : fréquence décroissante, puis meilleur rang croissant. La fréquence prime parce
    qu'elle dit que le rayon VIT dans cette catégorie ; le rang ne départage qu'à égalité.

    Une liste vide ne conclut RIEN : c'est une absence de mesure, pas « aucune catégorie
    pertinente » (§5.10). L'affichage doit le dire ainsi."""
    agg: dict[str, dict] = {}
    for info in bsrs or []:
        if info is None:
            continue
        for sub in getattr(info, "subcategories", None) or []:
            libelle = str(sub.get("category") or "").strip(" .,;:")
            rang = sub.get("rank")
            if not libelle or not isinstance(rang, int) or rang <= 0:
                continue
            k = _cle(libelle)
            if not k or any(k.startswith(x) for x in _EXCLUES):
                continue
            e = agg.get(k)
            if e is None:
                # On garde le PREMIER libellé rencontré, pas la clé dépouillée : « Diabète »
                # est ce que l'auteur verra dans KDP, « diabete » ne l'est pas.
                agg[k] = {"category": libelle, "n_livres": 1, "meilleur_rang": rang}
            else:
                e["n_livres"] += 1
                e["meilleur_rang"] = min(e["meilleur_rang"], rang)

    return sorted(agg.values(),
                  key=lambda c: (-c["n_livres"], c["meilleur_rang"]))[:n]
