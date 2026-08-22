"""marketplace.py — source unique de « sur quelle place de marché travaille-t-on ».

La réponse était écrite à neuf endroits : `location_code=2250` dans les trois
orchestrateurs et dans `bsr_source`, `language_code="fr_FR"` dans deux d'entre eux,
l'identifiant de marketplace et l'hôte d'autocomplete dans `amazon_autocomplete`, le
domaine des fiches dans `amazon_product` et dans les deux constructeurs d'URL de
`TopBook`. En oublier un ne casse rien : ça mélange deux marchés dans un même rapport,
sans erreur et sans trace.

**Ce module ne rend PAS le produit multi-marché, et c'est délibéré.** Il rassemble ce qui
peut l'être et rend visible ce qui ne l'est pas. Six choses du dépôt sont
irréductiblement françaises :

1. les **browse nodes** de `data/fiction_taxonomy_fr_v1.json` — identifiants de rayon
   propres à amazon.fr, sans équivalent transposable ;
2. les **libellés de rayon** (« Boutique Kindle », « Livres ») que `est_payant_dans` et
   `label_rayon` comparent au texte rendu par Amazon (§5.4) ;
3. les **barèmes d'impression KDP** de `data/kdp_print_costs.json`, relevés en EUROS sur
   le barème européen — le barème américain a d'autres bandes et d'autres montants ;
4. les **mots saisonniers** de la taxonomie low-content (« noel », « paques »,
   « vacances ») ;
5. le **corpus du filtre IP** (`data/exclusions_ip.md`), bâti sur les marques et
   franchises vues sur amazon.fr ;
6. les **prompts** des cinq modules LLM, qui écrivent « à succès sur amazon.fr » et
   raisonnent en euros.

Aucune de ces six ne lèverait sur une SERP américaine. Elles rendraient des chiffres :
un rayon fiction filtré sur un browse node inexistant, une redevance calculée au barème
européen, un filtre saisonnier qui cherche « noel » dans « christmas planner », un filtre
IP aveugle aux franchises américaines. Faux, plausibles, silencieux — la faute que la
règle 3 interdit, appliquée à la configuration plutôt qu'à la mesure.

D'où le choix : **une place de marché non prête LÈVE**, en disant ce qui manque. Bloquer
au démarrage coûte une minute ; un rapport faux coûte un livre publié dans le vide.
"""
from __future__ import annotations

import os

from pydantic import BaseModel


class MarketplaceIndisponible(RuntimeError):
    """Bascule demandée vers une place de marché que le dépôt ne sait pas encore servir."""


class Marketplace(BaseModel):
    model_config = {"frozen": True}

    cle: str
    domaine: str                    # amazon.fr
    location_code: int              # code DataForSEO
    language_code: str              # « fr_FR » et non « fr » — validé en live
    marketplace_id: str             # identifiant de l'autocomplete public
    devise: str
    prete: bool
    # Ce qui manque pour que cette place devienne utilisable. Vide si `prete`.
    manques: tuple[str, ...] = ()

    def url_fiche(self, asin: str) -> str:
        return f"https://www.{self.domaine}/dp/{asin}"

    def url_completion(self) -> str:
        return f"https://completion.{self.domaine}/api/2017/suggestions"


_MANQUES_HORS_FR = (
    "taxonomie fiction : browse nodes et libellés de rayon propres à amazon.fr "
    "(data/fiction_taxonomy_fr_v1.json)",
    "taxonomie low-content : mots saisonniers et libellés en français "
    "(data/lowcontent_taxonomy_fr_v1.json)",
    "barèmes d'impression KDP relevés en EUROS sur le barème européen "
    "(data/kdp_print_costs.json) — bandes et montants différents hors zone euro",
    "corpus du filtre IP bâti sur les marques vues sur amazon.fr "
    "(data/exclusions_ip.md)",
    "prompts des cinq modules LLM, qui écrivent « amazon.fr » et raisonnent en euros",
    "seuils de scoring calés sur des rayons français mesurés en live",
)

MARKETPLACES: dict[str, Marketplace] = {
    "fr": Marketplace(
        cle="fr", domaine="amazon.fr", location_code=2250, language_code="fr_FR",
        marketplace_id="A13V1IB3VIYZZH", devise="EUR", prete=True),
    # Décrit et NON prêt. Les deux codes DataForSEO sont justes ; c'est tout le reste du
    # dépôt qui ne suit pas. Le décrire sert à ce que la bascule échoue avec un message
    # utile plutôt qu'avec un KeyError.
    "com": Marketplace(
        cle="com", domaine="amazon.com", location_code=2840, language_code="en_US",
        marketplace_id="ATVPDKIKX0DER", devise="USD", prete=False,
        manques=_MANQUES_HORS_FR),
}

DEFAUT = "fr"


def marketplace_actif() -> Marketplace:
    """Lit `MARKETPLACE` (défaut « fr »). Lève si la place n'existe pas ou n'est pas prête.

    Une valeur vide retombe sur le défaut : `MARKETPLACE=` dans un `.env` est un oubli,
    pas une demande de bascule."""
    cle = (os.getenv("MARKETPLACE") or DEFAUT).strip().lower() or DEFAUT
    m = MARKETPLACES.get(cle)
    if m is None:
        raise MarketplaceIndisponible(
            f"MARKETPLACE={cle!r} inconnue. Places décrites : "
            f"{', '.join(sorted(MARKETPLACES))}.")
    if not m.prete:
        details = "\n  - ".join(m.manques)
        raise MarketplaceIndisponible(
            f"MARKETPLACE={cle!r} ({m.domaine}) n'est pas prête. Les codes DataForSEO "
            f"sont justes, mais le reste du dépôt est français et rendrait des chiffres "
            f"FAUX sans lever :\n  - {details}\n"
            f"Tant que ces points ne sont pas traités, rester sur MARKETPLACE=fr.")
    return m


# Résolu à l'import, comme les défauts de modèle. Contrairement à eux (§5.21), ça ne pose
# pas de problème d'ordre : `web/server.py` appelle `load_dotenv()` AVANT ses imports
# moteur, et la CLI n'a pas à basculer de place de marché en cours de run.
ACTIF = MARKETPLACES[DEFAUT]
