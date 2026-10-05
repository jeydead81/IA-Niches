"""bsr_source.py — résout le BSR d'une liste d'ASIN, avec dédup + cache + choix de source.
Source (env BSR_SOURCE) : 'scrape' (gratuit, IP résidentielle, défaut local) ou 'dataforseo'
(batché, fiable, serveur). fetch_bsr_fn injectable (tests hors-ligne + fallback scrape par ASIN)."""
import os
import time

from amazon_product import fetch_bsr_strict as _scrape_bsr
from marketplace import ACTIF

BSR_TTL_S = 30 * 24 * 3600     # 30 jours (15 jusqu'au 2026-10-05). Le cache est MUTUALISE entre tous les comptes : allonger sa duree
# Duree de memorisation d'une ABSENCE de classement. Bien plus courte que celle d'un
# rang : un livre peut entrer au classement a tout moment, et figer 30 jours une
# non-mesure nous rendrait aveugles a son arrivee. 3 jours tuent le gaspillage sans
# transformer « pas encore classe » en « jamais classe ».
ECHEC_BSR_TTL_S = 3 * 24 * 3600
# multiplie mecaniquement l'economie, et c'est gratuit au sens propre. Ce qu'on
# echange, c'est de la fraicheur -- mais le produit compare des ORDRES DE GRANDEUR
# (sous 10 000, sous 50 000, au-dela), pas un classement a la journee, et un rayon
# ne change pas de tranche en deux semaines.


def resolve_bsrs(asins, *, source=None, provider=None, fetch_bsr_fn=None, cache=None,
                 location: int = ACTIF.location_code, bsr_priority: int = 2, cost=None,
                 bsr_pause: float = 0.4, progress=None) -> dict:
    """Retour : {asin: BsrInfo|None}. Dédup, cache (par ASIN), et comptage coût pour DataForSEO.

    `None` recouvre deux choses que le CACHE, lui, doit distinguer : une fiche LUE sans
    classement (mémorisée 3 jours, c'est une mesure) et une fiche NON LUE (panne, tâche
    jamais prête, lot refusé), qui n'apprend rien et n'est jamais écrite comme absence."""
    uniq = list(dict.fromkeys(a for a in asins if a))
    out: dict = {}
    misses: list[str] = []
    for a in uniq:
        c = cache.get_bsr(a, location) if cache else None
        if c is not None:
            out[a] = c
        elif cache is not None and cache.bsr_absent(a, location):
            # DEJA sonde, sans classement exploitable. On ne saute pas l'appel parce
            # qu'on ignore le resultat -- on le saute parce qu'on le CONNAIT. C'est toute
            # la difference entre une non-mesure et une mesure negative (5.10), et c'est
            # elle qui autorise l'economie.
            out[a] = None
        else:
            misses.append(a)

    en_panne: set[str] = set()
    if misses:
        source = source or os.getenv("BSR_SOURCE", "scrape")
        if fetch_bsr_fn is not None or source == "scrape":
            fn = fetch_bsr_fn or _scrape_bsr
            for a in misses:
                try:
                    out[a] = fn(a)
                except Exception:  # noqa: BLE001 — un échec réseau/scrape sur 1 ASIN ne coule pas le run
                    out[a] = None
                    en_panne.add(a)
                if bsr_pause and fetch_bsr_fn is None:
                    time.sleep(bsr_pause)
        elif source == "dataforseo":
            if provider is None:
                raise ValueError("source=dataforseo requiert un provider")
            prio = getattr(provider, "priority", bsr_priority)
            try:
                batch = provider.product_info_batch(misses)
            except BaseException:
                # Même motif qu'`enrich_asins` : les tâches partent AVANT le poll, donc un
                # Ctrl-C en plein poll (que le fournisseur laisse remonter exprès) les laisse
                # créées et facturées. Pire cas imputé, jamais zéro (règle 2), puis on relance.
                if cost is not None:
                    cost.add_dataforseo(len(misses), prio)
                raise
            out.update(batch)
            # Seul ce que le batch a LU peut se mémoriser comme absence. Un fournisseur qui
            # ne le dit pas n'apprend rien au cache : le pire cas est de repayer, jamais de
            # figer une panne pour tous les comptes.
            lus = getattr(batch, "lus", set())
            en_panne.update(a for a in misses if batch.get(a) is None and a not in lus)
            if cost is not None:
                # Créées + peut-être créées (lot dont l'envoi a levé) : même pire cas que
                # `enrich_asins`, pour la même raison — une exception ne dit pas ce que le
                # fournisseur a facturé.
                cost.add_dataforseo(getattr(batch, "taches_creees", len(misses))
                                    + getattr(batch, "taches_incertaines", 0), prio)
        else:
            raise ValueError(f"BSR_SOURCE inconnu : {source}")

        if cache:
            for a in misses:
                if out.get(a) is not None:
                    cache.set_bsr(a, location, out[a], BSR_TTL_S)
                elif a not in en_panne:
                    # ECHEC MEMORISE, et c'est une economie reelle : sans lui, les memes
                    # ASIN sans classement repartaient en facturation a CHAQUE run,
                    # indefiniment. Un echec MESURE est une information.
                    # TTL RACCOURCI : un livre peut entrer au classement (il vient d'etre
                    # publie, ou il vient de vendre). Memoriser l'absence 15 jours nous
                    # rendrait aveugles a son arrivee ; 3 jours suffisent a tuer le
                    # gaspillage sans figer une non-mesure.
                    cache.set_bsr_absent(a, location, ECHEC_BSR_TTL_S)
        if en_panne and progress:
            progress(f"  ⚠ {len(en_panne)} classement(s) non lu(s) (panne ou fiche "
                     f"bloquée) — non mémorisé(s) comme absence, à relire au prochain run.")
    return out
