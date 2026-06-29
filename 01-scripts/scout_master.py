"""
scout_master.py
---------------
Orchestrateur du scout KDP. Lance les 5 étapes dans l'ordre,
applique tous les garde-fous, génère le rapport Excel final.

Usage :
  python scout_master.py                                        # Scout complet
  python scout_master.py --dry-run                              # Test 1 crédit uniquement
  python scout_master.py --tiktok "tag1,tag2"                   # Avec input TikTok manuel
  python scout_master.py --focus "nutrition sportive,sport santé"  # Focus sur un domaine

Option --focus :
  Injecte des seeds prioritaires en tête de file autocomplete.
  Le script appelle d'abord l'autocomplete sur chaque terme focus pour découvrir
  le champ lexical réel (ce que les gens cherchent sur Amazon), puis traite
  ces suggestions comme des seeds supplémentaires à fort poids.
  Coût estimé : ~6 crédits par terme focus (niveau 1 + expansion).
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Ajout du dossier scripts au path (chemin absolu pour éviter les erreurs de cwd)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import credits_tracker as ct
from credits_tracker import BudgetExceededError, get_remaining_estimate, get_session_credits
import trends_fr
import reddit_fr
import news_fr
import amazon_autocomplete
import amazon_search
from report_builder import build_excel_report

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "02-veille-hebdo" / "raw-data"
REPORTS_DIR = BASE_DIR / "02-veille-hebdo" / "rapports"

# ── SEEDS KDP ─────────────────────────────────────────────────────────────────
# Expressions-seeds qui vont alimenter l'autocomplete Amazon.
# L'autocomplete retournera les vraies requêtes des utilisateurs → ce sont les niches.
# Organisées par thème pour couvrir tous les axes de la non-fiction FR.

KDP_SEEDS = [
    # Santé / médical / bien-être (avantage pharmacien Baptiste)
    "guérir naturellement", "médecine douce", "médecine naturelle", "plantes médicinales",
    "microbiote intestinal", "santé intestinale", "jeûne intermittent", "jeûne thérapeutique",
    "alimentation anti-inflammatoire", "régime cétogène", "alimentation saine",
    "compléments alimentaires", "vitamines et minéraux", "système immunitaire",
    "anxiété naturellement", "dépression naturelle", "stress chronique",
    "sommeil profond", "insomnie naturelle", "fatigue chronique",
    "cholestérol naturellement", "diabète type 2", "hypertension naturelle",
    "maigrir durablement", "perdre du poids", "perte de poids",
    # Développement personnel / psychologie
    "guérir enfant intérieur", "blessures d'enfance", "trauma guérison",
    "attachement amoureux", "relations toxiques", "manipulation émotionnelle",
    "intelligence émotionnelle", "confiance en soi", "estime de soi",
    "stoïcisme pratique", "philosophie stoïcienne", "ikigai japonais",
    "discipline personnelle", "habitudes positives", "procrastination vaincre",
    "pleine conscience", "méditation débutant", "minimalisme vie",
    "burn-out guérison", "haut potentiel intellectuel", "hypersensibilité",
    "autisme adulte", "tdah adulte", "neuroatypique",
    # Spiritualité / ésotérisme (non-islamique)
    "magie blanche débutant", "wicca initiation", "lithothérapie cristaux",
    "énergies guérison", "loi d'attraction", "manifestation abondance",
    "numérologie débutant", "astrologie débutant", "tarot initiation",
    "chamanisme occidental", "méditation chamanique",
    # Histoire / sciences vulgarisées
    "histoire france méconnue", "seconde guerre mondiale résistance",
    "mythologie grecque", "mythologie nordique", "mythologie égyptienne",
    "empire romain chute", "révolution française secrets",
    "physique quantique vulgarisé", "neurosciences vulgarisées",
    "intelligence artificielle comprendre", "univers cosmologie",
    # Finance / business
    "liberté financière", "indépendance financière", "investir bourse débutant",
    "immobilier investissement", "crypto-monnaie débutant",
    "créer entreprise", "entrepreneur succès", "marketing digital",
    # Société / autres
    "décroissance sobriété", "effondrement résilience", "autonomie alimentaire",
    "éducation positive enfants", "parentalité bienveillante",
    "couple communication", "sexualité épanouissement",
    "végétalisme éthique", "zéro déchet maison",
]

# Exclusions strictes (section 4.4 CLAUDE.md)
EXCLUSIONS_HARD = [
    "noël", "noel", "christmas", "été", "rentrée", "halloween", "paques", "pâques",
    "saint-valentin", "fête des mères", "fête des pères",
    "ramadan", "islam", "islamique", "coran", "quran", "mosquée",
    "élection", "parti politique", "macron", "lepen", "vote",
    "malware", "hack", "exploit", "ransomware",
]

# Mots trop génériques pour être des niches KDP (parasites des sources d'actualité)
GENERIC_WORDS = {
    "france", "français", "française", "français", "monde", "pays", "ville",
    "livre", "livres", "auteur", "roman", "édition", "lecture",
    "aujourd", "semaine", "mois", "année", "années", "temps", "jour", "jours",
    "faire", "avoir", "être", "aller", "venir", "savoir", "voir", "dire",
    "nouveau", "nouvelle", "premiers", "première", "premier", "grand", "grande",
    "petit", "petite", "article", "titre", "suite", "point", "liste", "page",
    "million", "milliard", "euro", "euros", "millions", "milliards",
    "gouvernement", "ministre", "président", "politique", "parti",
    "programme", "projet", "rapport", "résultat", "résultats",
    "données", "information", "informations", "question", "problème",
    "situation", "exemple", "raison", "moment", "moyen", "manière",
    "chose", "choses", "personne", "personnes", "homme", "femme", "enfant",
    "gens", "monde", "société", "groupe", "équipe", "service", "système",
    "niveau", "nombre", "part", "effet", "objectif", "mesure", "travail",
    "semaines", "jours", "heures", "minutes", "secondes",
}

# Catégories avantage pharmacien (bonus +1 au score)
PHARMA_CATEGORIES = [
    "santé", "médecin", "médical", "nutrition", "bien-être", "bienetre",
    "pharmacolog", "médicament", "traitement", "maladie", "thérapie",
    "microbiote", "vitamine", "complément alimentaire", "régime", "diète",
]


def _merge_keywords(*sources: dict) -> dict:
    """Fusionne les mots-clés de plusieurs sources, additionne les scores."""
    merged = {}
    for source in sources:
        for kw, score in source.items():
            merged[kw] = merged.get(kw, 0) + (score if isinstance(score, (int, float)) else 1)
    return merged


def _filter_keywords(keywords: dict) -> dict:
    """
    Applique les exclusions strictes, filtre les mots trop courts et les génériques.
    Ne garde que les mots-clés qui peuvent réellement être des niches KDP.
    """
    filtered = {}
    for kw, score in keywords.items():
        kw_lower = kw.lower().strip()

        # Longueur minimale
        if len(kw) < 5:
            continue

        # Exclusions saisonnalité / TOS / politique
        if any(excl in kw_lower for excl in EXCLUSIONS_HARD):
            continue

        # Mots génériques parasites
        if kw_lower in GENERIC_WORDS:
            continue

        # Rejeter les mots qui ressemblent à de l'actualité pure (verbe conjugué court, etc.)
        # Un mot-clé KDP doit pouvoir être le sujet d'un livre : nom, concept, méthode
        # Heuristique : au moins 5 lettres, pas uniquement des lettres communes
        if len(kw) < 6 and not any(c in kw_lower for c in "àâçéèêëîïôùûüæœ"):
            continue

        filtered[kw] = score
    return filtered


def _is_pharma_niche(keyword: str) -> bool:
    kw_lower = keyword.lower()
    return any(cat in kw_lower for cat in PHARMA_CATEGORIES)


def _score_niche(kw: str, kw_score: float, search_data: dict) -> dict:
    """
    Calcule le score sur 3 axes (section 6.5 CLAUDE.md).
    Retourne un dict avec tous les détails du scoring.
    """
    organic = search_data.get("organic", [])
    sponsored = search_data.get("sponsored", [])
    bsr_stats = search_data.get("bsr_stats", {})
    total_results = search_data.get("total_results", "")

    # ── AXE 1 : Demande (0.4) ────────────────────────────────────────────────
    demand_score = min(10, max(1, kw_score / 5))

    # Bonus BSR
    if bsr_stats.get("bsr_best") and bsr_stats["bsr_best"] < 5_000:
        demand_score = min(10, demand_score + 2)
    elif bsr_stats.get("bsr_best") and bsr_stats["bsr_best"] < 10_000:
        demand_score = min(10, demand_score + 1)

    if bsr_stats.get("criteres_ok"):
        demand_score = min(10, demand_score + 1)

    # ── AXE 2 : Pénétration (0.4) ────────────────────────────────────────────
    penetre_score = 5.0  # base neutre

    # Nombre de résultats totaux
    try:
        nb_results = int(str(total_results).replace(",", "").replace(" ", "")) if total_results else 0
        if nb_results > 10_000:
            penetre_score -= 3
        elif nb_results > 5_000:
            penetre_score -= 1
        elif nb_results < 1_000:
            penetre_score += 2
    except (ValueError, TypeError):
        pass

    # Nombre de concurrents organiques ciblés (estimation)
    nb_organic_targeted = len([p for p in organic if kw.lower() in p.get("title", "").lower()])
    if nb_organic_targeted > 50:
        penetre_score -= 2
    elif nb_organic_targeted > 30:
        penetre_score -= 1
    elif nb_organic_targeted < 10:
        penetre_score += 2

    # Signal "place à prendre" : un livre BSR > 50k dans le top
    if bsr_stats.get("critere_3_worst_gt_50k"):
        penetre_score += 1.5

    # Beaucoup de sponsorisés = concurrence organique faible
    if len(sponsored) >= 3:
        penetre_score += 0.5

    penetre_score = max(1, min(10, penetre_score))

    # ── AXE 3 : Compatibilité livre (0.2) ────────────────────────────────────
    compat_score = 7.0  # défaut : sujet neutre
    kw_lower = kw.lower()
    incompatible_signals = ["recette", "cuisine", "jeu", "jouet", "accessoire", "logiciel", "application"]
    if any(s in kw_lower for s in incompatible_signals):
        compat_score = 3.0
    good_signals = ["guide", "méthode", "comprendre", "histoire", "philosophie", "psychologie", "santé", "bien-être"]
    if any(s in kw_lower for s in good_signals):
        compat_score = 9.0

    # ── Score global ─────────────────────────────────────────────────────────
    global_score = (demand_score * 0.4) + (penetre_score * 0.4) + (compat_score * 0.2)

    # Bonus pharmacien
    pharma_bonus = 1.0 if _is_pharma_niche(kw) else 0.0
    global_score = min(10, global_score + pharma_bonus)

    # Verdict
    if global_score >= 7.5:
        verdict = "🟢 À analyser en priorité"
    elif global_score >= 6.0:
        verdict = "🟡 Intéressant — à évaluer"
    else:
        verdict = "🔴 Score faible"

    return {
        "keyword": kw,
        "global_score": round(global_score, 2),
        "demand_score": round(demand_score, 2),
        "penetre_score": round(penetre_score, 2),
        "compat_score": round(compat_score, 2),
        "pharma_bonus": pharma_bonus,
        "bsr_best": bsr_stats.get("bsr_best"),
        "bsr_top5_avg": bsr_stats.get("bsr_top5_avg"),
        "bsr_worst_top10": bsr_stats.get("bsr_worst_top10"),
        "total_results": total_results,
        "nb_organic": len(organic),
        "nb_sponsored": len(sponsored),
        "nb_organic_targeted": nb_organic_targeted,
        "criteres_bsr_ok": bsr_stats.get("criteres_ok", False),
        "verdict": verdict,
    }


def _expand_focus_terms(focus_terms: list[str], output_dir: Path) -> list[str]:
    """
    Expansion sémantique des termes focus via Amazon autocomplete.

    Pour chaque terme focus (ex: "nutrition sportive"), appelle l'autocomplete
    Amazon pour découvrir le champ lexical réel : ce que les utilisateurs
    cherchent vraiment sur Amazon autour de ce sujet.

    Les suggestions retournées deviennent des seeds prioritaires qui s'ajoutent
    aux KDP_SEEDS standards en tête de file.

    Coût : 2 crédits par terme focus (direct + "livre [focus]").
    Les suggestions sont ensuite traitées comme des seeds normaux (niveau 1+2).
    """
    expanded = []
    print(f"\n[focus] Expansion sémantique de {len(focus_terms)} terme(s) focus via Amazon autocomplete...")

    for term in focus_terms:
        # Appel direct sur le terme focus
        try:
            sugg_direct = amazon_autocomplete.fetch_autocomplete(term)
            expanded.extend(sugg_direct)
            print(f"[focus] '{term}' → {len(sugg_direct)} suggestions : {sugg_direct[:4]}")
        except BudgetExceededError as e:
            print(f"[focus] 🛑 Budget atteint pendant expansion focus : {e}")
            break
        except Exception as e:
            print(f"[focus] ⚠️ Erreur sur '{term}' : {e}")

        # Appel "livre [focus]" pour cibler l'intention d'achat livre
        try:
            sugg_livre = amazon_autocomplete.fetch_autocomplete(f"livre {term}")
            expanded.extend(sugg_livre)
        except (BudgetExceededError, Exception):
            pass

    # Déduplique, filtre les termes trop courts ou génériques
    seen = set()
    unique = []
    for s in expanded:
        s_clean = s.strip().lower()
        if s_clean not in seen and len(s_clean) >= 5 and len(s_clean.split()) >= 1:
            seen.add(s_clean)
            unique.append(s)

    print(f"[focus] {len(unique)} seeds focus uniques extraits du champ lexical Amazon\n")
    return unique


def run_scout(dry_run: bool = False, tiktok_tags: list[str] = None,
              focus_terms: list[str] = None):
    """Orchestrateur principal du scout."""
    ct.reset_session()
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_dir = RAW_DIR / date_str
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  SCOUT KDP — {date_str}")
    print(f"  Crédits Scrapingdog restants estimés : {get_remaining_estimate()}")
    if tiktok_tags:
        print(f"  Input TikTok manuel : {', '.join(tiktok_tags)}")
    else:
        print("  Input TikTok : non fourni (scout avec 4 sources auto)")
    if focus_terms:
        print(f"  🎯 Focus domaine : {', '.join(focus_terms)}")
    print(f"{'='*60}\n")

    sources_ok = []
    sources_ko = []

    # ── MODE DRY-RUN ─────────────────────────────────────────────────────────
    if dry_run or ct.is_dry_run():
        print("[DRY-RUN] Test avec 1 crédit autocomplete...")
        try:
            suggestions = amazon_autocomplete.fetch_autocomplete("ikigai")
            print(f"[DRY-RUN] ✓ Clé API valide. Suggestions reçues : {suggestions[:3]}")
            print(f"[DRY-RUN] 1 crédit consommé. Crédits restants : {get_remaining_estimate()}")
            print("\n→ Lance le scout complet en demandant à Cowork 'lance le scout'")
        except BudgetExceededError as e:
            print(f"[DRY-RUN] 🛑 {e}")
        except Exception as e:
            print(f"[DRY-RUN] ✗ ERREUR API : {e}")
            print("Vérifie ta clé Scrapingdog dans le fichier .env")
        return

    # ── ÉTAPE A : Sources gratuites ───────────────────────────────────────────
    print("ÉTAPE A — Collecte des sources gratuites...")

    try:
        trends_data = trends_fr.run(output_dir)
        sources_ok.append("Google Trends FR")
    except Exception as e:
        print(f"[trends_fr] ✗ Erreur : {e}")
        trends_data = {}
        sources_ko.append(f"Google Trends FR ({e})")

    try:
        reddit_data = reddit_fr.run(output_dir)
        sources_ok.append("Reddit FR (RSS dégradé)")
    except Exception as e:
        print(f"[reddit_fr] ✗ Erreur : {e}")
        reddit_data = {}
        sources_ko.append(f"Reddit FR ({e})")

    try:
        news_data = news_fr.run(output_dir)
        sources_ok.append("Google News FR")
    except Exception as e:
        print(f"[news_fr] ✗ Erreur : {e}")
        news_data = {}
        sources_ko.append(f"Google News FR ({e})")

    # TikTok manuel
    tiktok_data = {}
    if tiktok_tags:
        tiktok_data = {tag: 20 for tag in tiktok_tags}  # score fixe pour les tags manuels
        sources_ok.append(f"TikTok manuel ({len(tiktok_tags)} tags)")
    else:
        print("[TikTok] Input non fourni — ignoré")

    # Fusion et filtrage des sources dynamiques
    raw_keywords = _merge_keywords(trends_data, reddit_data, news_data, tiktok_data)
    filtered_keywords = _filter_keywords(raw_keywords)

    # ── Seeds KDP curatés : la seule source pour l'autocomplete ──────────────
    # Les signaux dynamiques (Reddit/Trends/News) NE VONT PAS dans l'autocomplete.
    # Ils servent uniquement à booster le score de demande des seeds pertinents.
    # Raison : les mots Reddit/News sont souvent des termes uniques non-livres
    # ("rapporteur", "licence", "charles") qui génèrent des suggestions Amazon inutiles.
    seeds_dict = {seed: 10 for seed in KDP_SEEDS}

    # ── Expansion focus (--focus) ─────────────────────────────────────────────
    # Si des termes focus ont été fournis, on appelle l'autocomplete dessus
    # pour découvrir le champ lexical réel (ce que les gens cherchent sur Amazon).
    # Ces suggestions deviennent des seeds prioritaires (score 25 > 10 des seeds standards).
    focus_seeds = []
    if focus_terms:
        focus_seeds = _expand_focus_terms(focus_terms, output_dir)
        for fs in focus_seeds:
            seeds_dict[fs] = seeds_dict.get(fs, 0) + 25  # priorité maximale

    # Boost : si un seed KDP recroupe un signal dynamique, son score monte
    boosted_seeds = dict(seeds_dict)
    for kw_dyn, score_dyn in filtered_keywords.items():
        for seed in list(seeds_dict.keys()):
            if kw_dyn.lower() in seed.lower() or seed.lower() in kw_dyn.lower():
                boosted_seeds[seed] = boosted_seeds.get(seed, 10) + min(score_dyn, 15)

    # Tri par score boosted → focus en tête, puis seeds boostés par l'actualité
    candidates = sorted(boosted_seeds.items(), key=lambda x: x[1], reverse=True)

    focus_info = f" | 🎯 {len(focus_seeds)} seeds focus ({len(focus_terms)} terme(s))" if focus_terms else ""
    print(f"\n→ {len(KDP_SEEDS)} seeds KDP (autocomplete){focus_info} | {len(filtered_keywords)} signaux dynamiques (scoring boost uniquement)\n")

    # ── ÉTAPE B : Autocomplete Amazon ────────────────────────────────────────
    print("ÉTAPE B — Expansion via Amazon Autocomplete (KDP seeds uniquement)...")
    # Autocomplete UNIQUEMENT sur les seeds KDP curatés — jamais sur les mots Reddit/News
    candidate_kws = [kw for kw, _ in candidates]

    # Estimation crédits autocomplete via Scrapingdog
    nb_seeds = len(candidate_kws)
    est_l1 = nb_seeds * 2          # seed + "livre [seed]"
    est_l2 = nb_seeds * 4          # max 4 expansions niveau 2 par seed
    est_autocomplete = est_l1 + est_l2
    est_total = est_autocomplete
    print(f"\n💰 ESTIMATION CRÉDITS :")
    print(f"   Autocomplete niveau 1 ({nb_seeds} seeds × 2) : ~{est_l1} crédits")
    print(f"   Autocomplete niveau 2 (expansion) : ~{est_l2} crédits max")
    print(f"   TOTAL estimé : ~{est_total} crédits / {ct.MAX_CREDITS_PER_RUN} autorisés")
    print(f"   Crédits restants sur compte : ~{get_remaining_estimate()}")
    print(f"   ⚠️  Note : le plafond actuel est {ct.MAX_CREDITS_PER_RUN} crédits.")
    print(f"   Si insuffisant, augmente MAX_CREDITS_PER_RUN dans 00-config/credits-config.md\n")

    try:
        autocomplete_results = amazon_autocomplete.run(candidate_kws, output_dir, expand_level2=True)
        sources_ok.append("Amazon Autocomplete (via Scrapingdog)")

        # Aplatir les suggestions avec leurs scores (niveau 1 direct, livre, niveau 2)
        from amazon_autocomplete import flatten_suggestions
        flat_suggestions = flatten_suggestions(autocomplete_results)

        # Fusionner avec les seeds multi-mots déjà candidats
        niche_phrases = dict(flat_suggestions)
        for seed, score in candidates:
            if len(seed.split()) >= 2:
                niche_phrases[seed] = niche_phrases.get(seed, 0) + score

        # Filtrer les génériques, exclusions et mots uniques
        niche_phrases_filtered = {
            k: v for k, v in niche_phrases.items()
            if len(k.split()) >= 2
            and k.lower() not in GENERIC_WORDS
            and not any(ex in k.lower() for ex in EXCLUSIONS_HARD)
        }
        expanded_candidates = sorted(niche_phrases_filtered.items(), key=lambda x: x[1], reverse=True)[:60]

        total_sugg = sum(
            len(d.get("direct", [])) + len(d.get("livre", [])) + len(d.get("level2", []))
            for d in autocomplete_results.values()
        )
        print(f"→ {total_sugg} suggestions Amazon (niveaux 1+2) → {len(niche_phrases_filtered)} niches uniques\n")
    except BudgetExceededError as e:
        print(f"[autocomplete] 🛑 Plafond atteint : {e}")
        expanded_candidates = [(kw, sc) for kw, sc in candidates if len(kw.split()) >= 2]
        sources_ko.append(f"Amazon Autocomplete partiel ({e})")

    # ── ÉTAPE C : Filtres systématiques ──────────────────────────────────────
    print("ÉTAPE C — Filtres systématiques...")

    # Exclusions étendues pour les finalistes (en plus des EXCLUSIONS_HARD)
    EXCLUSIONS_FINALISTES_PATTERNS = [
        # TOS KDP — combinaisons problématiques
        ("sexualité", "enfant"), ("sexuel", "mineur"), ("sexualité", "ado"),
        # Politique contemporaine
        "présidentielle", "élection 2027", "présidentiel",
        # Produits physiques / non-livres
        "tee shirt", "t-shirt", "bijoux", "plinthes", "accessoire", "matériel",
        "panneau", "exterieur balcon", "argentin", "graines", "chaussures",
        "alarme", "anti agression", "dvd", "cd ",
        # Jeux / non-livres
        "jeu de plis", "jeu de l'anneau", "jeu de cartes",
        # Logiciels / licences logicielles
        "licence windows", "office 2024", "microsoft office", "licence a vie",
        # Ultra-niche religieuse institutionnelle
        "pontifical", "biblique pontifical", "theologique internationale",
        # Format audiovisuel (pas un livre)
        "audiovisuel accessoire", "audiovisuel materiel", "production audiovisuelle",
        # Auteurs spécifiques sans niche claire
        "charles robin", "bell hooks",
        # Termes trop génériques pour être une niche
        "livre public", "livre propos",
    ]

    def _is_excluded_finaliste(kw: str) -> bool:
        kw_lower = kw.lower()
        for excl in EXCLUSIONS_FINALISTES_PATTERNS:
            if isinstance(excl, tuple):
                # Exclusion combinée : les deux termes doivent être présents
                if all(term in kw_lower for term in excl):
                    return True
            else:
                if excl in kw_lower:
                    return True
        return False

    finalists_raw = [kw for kw, _ in expanded_candidates if not _is_excluded_finaliste(kw)]
    finalists = finalists_raw[:20]
    print(f"→ {len(finalists)} niches finalistes pour analyse approfondie :")
    for i, f in enumerate(finalists, 1):
        print(f"   {i:2}. {f}")
    print()

    # ── ÉTAPE D : Enrichissement via autocomplete (0 crédit) ─────────────────
    # Scrapingdog Amazon Search non disponible sur le plan actuel.
    # Le scoring s'appuie sur les signaux autocomplete + Trends + Reddit + News.
    # La validation BSR est déléguée à la Phase 2 (navigation manuelle Baptiste).
    print("ÉTAPE D — Enrichissement signal autocomplete (0 crédit, BSR à valider en Phase 2)...")

    # Calcul du nombre de suggestions par finaliste (signal de volume de recherche)
    # autocomplete_results[kw] = {"direct": [...], "livre": [...], "level2": [...]}
    autocomplete_signal = {}
    for kw in finalists:
        seed_data = autocomplete_results.get(kw, {}) if 'autocomplete_results' in dir() else {}
        if isinstance(seed_data, dict):
            all_sugg = (seed_data.get("direct", []) + seed_data.get("livre", [])
                        + seed_data.get("level2", []))
        else:
            all_sugg = list(seed_data) if seed_data else []
        autocomplete_signal[kw] = len(all_sugg)
        if all_sugg:
            preview = all_sugg[:3]
            print(f"   '{kw}' → {len(all_sugg)} suggestions : {preview}")
        else:
            print(f"   '{kw}' → aucune suggestion directe (signal basé sur score croisé)")

    sources_ok.append("Amazon Autocomplete (signal volume)")
    search_results = {}  # vide, BSR à valider manuellement en Phase 2
    sources_ko.append("Amazon Search BSR (non disponible — à valider manuellement en Phase 2)")
    print()

    # ── ÉTAPE E : Scoring ────────────────────────────────────────────────────
    print("ÉTAPE E — Scoring des niches...\n")
    scored_niches = []
    keyword_dict = dict(expanded_candidates)

    for kw in finalists:
        kw_score = keyword_dict.get(kw, 1)
        # Bonus si l'autocomplete a retourné des suggestions (signal de volume Amazon)
        nb_suggestions = autocomplete_signal.get(kw, 0)
        kw_score_adjusted = kw_score + (nb_suggestions * 2)
        search_data = {"organic": [], "sponsored": [], "bsr_stats": {}}
        score = _score_niche(kw, kw_score_adjusted, search_data)
        score["sources_signal"] = ", ".join(sources_ok)
        score["nb_autocomplete_suggestions"] = nb_suggestions
        score["bsr_note"] = "À valider manuellement sur Amazon.fr (Phase 2)"
        score["sponsored_list"] = []
        scored_niches.append(score)

    scored_niches.sort(key=lambda x: x["global_score"], reverse=True)

    # ── Rapport Excel ─────────────────────────────────────────────────────────
    print("Génération du rapport Excel...")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"scout-{date_str}.xlsx"

    meta = {
        "date": date_str,
        "sources_ok": sources_ok,
        "sources_ko": sources_ko,
        "tiktok_input": tiktok_tags or [],
        "candidates_before_filter": len(raw_keywords),
        "candidates_after_filter": len(finalists),
        "credits_this_run": get_session_credits(),
        "credits_remaining_estimate": get_remaining_estimate(),
    }

    build_excel_report(scored_niches, meta, report_path)

    # ── Résumé final ─────────────────────────────────────────────────────────
    top3 = scored_niches[:3]
    total_sponsored = sum(len(n.get("sponsored_list", [])) for n in scored_niches)

    print(f"\n{'='*60}")
    print(f"  SCOUT TERMINÉ — {date_str}")
    print(f"  Niches analysées : {len(scored_niches)}")
    print(f"  Sponsorisés écartés au total : {total_sponsored}")
    print(f"  Crédits consommés ce run : {get_session_credits()}")
    print(f"  Crédits restants estimés : {get_remaining_estimate()}")
    print(f"  Sources OK : {', '.join(sources_ok)}")
    if sources_ko:
        print(f"  ⚠️ Sources KO : {', '.join(sources_ko)}")
    print(f"\n  TOP 3 niches :")
    for i, n in enumerate(top3, 1):
        print(f"    {i}. {n['keyword']} — Score {n['global_score']}/10 — {n['verdict']}")
    print(f"\n  Rapport : {report_path}")
    print(f"{'='*60}\n")

    return scored_niches


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scout KDP")
    parser.add_argument("--dry-run", action="store_true", help="Test 1 crédit uniquement")
    parser.add_argument("--tiktok", type=str, default="", help="Tags TikTok manuels séparés par des virgules")
    parser.add_argument(
        "--focus", type=str, default="",
        help=(
            "Termes focus séparés par des virgules. Ex: \"nutrition sportive,sport santé\". "
            "Le scout appelle l'autocomplete Amazon sur ces termes pour découvrir le champ "
            "lexical réel, puis injecte les suggestions comme seeds prioritaires."
        )
    )
    args = parser.parse_args()

    tiktok_tags = [t.strip() for t in args.tiktok.split(",") if t.strip()] if args.tiktok else None
    focus_terms = [t.strip() for t in args.focus.split(",") if t.strip()] if args.focus else None
    run_scout(dry_run=args.dry_run, tiktok_tags=tiktok_tags, focus_terms=focus_terms)
