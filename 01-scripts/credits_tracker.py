"""
credits_tracker.py
------------------
Module commun de suivi et de plafonnement des crédits Scrapingdog.

Garde-fous implémentés :
- Garde-fou 1 : plafond MAX_CREDITS_PER_RUN (défaut 50)
- Garde-fou 2 : retry max 1, délai 5s
- Garde-fou 4 : log CSV en temps réel (99-logs/credits-log.csv)
"""

import csv
import os
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# ── Chemins ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = BASE_DIR / "99-logs" / "credits-log.csv"
CONFIG_FILE = BASE_DIR / "00-config" / "credits-config.md"

# ── Chargement .env ──────────────────────────────────────────────────────────
load_dotenv(BASE_DIR / ".env")
SCRAPINGDOG_API_KEY = os.getenv("SCRAPINGDOG_API_KEY", "")

# ── Paramètres (lus depuis credits-config.md si disponible, sinon défauts) ──
MAX_CREDITS_PER_RUN = 50
MAX_RETRIES_PER_REQUEST = 1
RETRY_DELAY_SECONDS = 5
DRY_RUN_FIRST_LAUNCH = True


def _load_config():
    """Lit MAX_CREDITS_PER_RUN et autres paramètres depuis credits-config.md."""
    global MAX_CREDITS_PER_RUN, MAX_RETRIES_PER_REQUEST, RETRY_DELAY_SECONDS, DRY_RUN_FIRST_LAUNCH
    if not CONFIG_FILE.exists():
        return
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("MAX_CREDITS_PER_RUN"):
                try:
                    MAX_CREDITS_PER_RUN = int(line.split("=")[1].strip())
                except (IndexError, ValueError):
                    pass
            elif line.startswith("MAX_RETRIES_PER_REQUEST"):
                try:
                    MAX_RETRIES_PER_REQUEST = int(line.split("=")[1].strip())
                except (IndexError, ValueError):
                    pass
            elif line.startswith("RETRY_DELAY_SECONDS"):
                try:
                    RETRY_DELAY_SECONDS = int(line.split("=")[1].strip())
                except (IndexError, ValueError):
                    pass
            elif line.startswith("DRY_RUN_FIRST_LAUNCH"):
                val = line.split("=")[1].strip().lower()
                DRY_RUN_FIRST_LAUNCH = val in ("true", "1", "yes")


_load_config()


# ── Compteur de session (en mémoire) ────────────────────────────────────────
_session_credits = 0

# Cache du total historique : lu UNE SEULE FOIS au démarrage du module.
# Évite de relire le CSV à chaque log_request() (problème de lock iCloud sur Windows).
_historical_credits_at_startup: int | None = None


def _read_historical_from_csv() -> int:
    """Lit le CSV une fois. Appelé uniquement à l'init."""
    if not LOG_FILE.exists():
        return 0
    total = 0
    try:
        with open(LOG_FILE, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    total += int(row.get("credits", 0))
                except (ValueError, TypeError):
                    pass
    except OSError:
        # iCloud ou autre verrou fichier — on retourne 0 en fallback silencieux
        return 0
    return total


def _init_historical_cache():
    """Initialise le cache historique. Appelé une seule fois à l'import."""
    global _historical_credits_at_startup
    _historical_credits_at_startup = _read_historical_from_csv()


_init_historical_cache()


def get_session_credits() -> int:
    return _session_credits


def get_historical_credits() -> int:
    """Total historique + session courante (lecture CSV mise en cache au démarrage)."""
    return (_historical_credits_at_startup or 0) + _session_credits


def get_remaining_estimate() -> int:
    """Estimation des crédits restants (plan free tier = 1000)."""
    return max(0, 1000 - get_historical_credits())


def is_dry_run() -> bool:
    """Retourne True si c'est le premier lancement (pas de log existant)."""
    return DRY_RUN_FIRST_LAUNCH and not LOG_FILE.exists()


def check_budget(credits_needed: int = 1) -> bool:
    """
    Vérifie si le budget de la session permet de faire la requête.
    Lève une exception si le plafond est atteint.
    """
    if _session_credits + credits_needed > MAX_CREDITS_PER_RUN:
        raise BudgetExceededError(
            f"Plafond atteint : {_session_credits}/{MAX_CREDITS_PER_RUN} crédits utilisés ce run. "
            f"Requête annulée ({credits_needed} crédit(s) demandé(s))."
        )
    return True


def log_request(endpoint: str, keyword: str, credits: int, success: bool):
    """
    Enregistre une requête dans le CSV de log (Garde-fou 4).
    Met à jour le compteur de session.
    Affiche dans la console.
    """
    global _session_credits
    _session_credits += credits

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_exists = LOG_FILE.exists()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    remaining = get_remaining_estimate()

    # Écriture CSV avec retry : iCloud peut verrouiller le fichier pendant la synchro.
    # On tente 3 fois avec 0.3s d'intervalle ; si ça échoue encore, on continue sans planter.
    row_data = {
        "timestamp": timestamp,
        "endpoint": endpoint,
        "keyword": keyword,
        "credits": credits,
        "success": "success" if success else "failure",
        "run_total": _session_credits,
        "account_estimate_remaining": remaining,
    }
    for attempt in range(3):
        try:
            with open(LOG_FILE, "a", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["timestamp", "endpoint", "keyword", "credits", "success",
                                "run_total", "account_estimate_remaining"],
                )
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row_data)
            break  # succès
        except OSError:
            if attempt < 2:
                time.sleep(0.3)
            # Après 3 tentatives : log console uniquement, on ne plante pas le scout

    status_icon = "✓" if success else "✗"
    print(
        f"{timestamp} | {endpoint} | \"{keyword}\" | {credits} crédit(s) | "
        f"{status_icon} | run_total: {_session_credits} | restants estimés: {remaining}"
    )


def reset_session():
    """Remet le compteur de session à zéro (utile pour les tests)."""
    global _session_credits
    _session_credits = 0


class BudgetExceededError(Exception):
    """Levée quand le plafond MAX_CREDITS_PER_RUN est atteint."""
    pass
