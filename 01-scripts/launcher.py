"""launcher.py — petit lanceur interactif d'IA-Niches (canaux gratuits).
Lancé par le raccourci bureau (IA-Niches.bat). En attendant l'orchestrateur
complet (Plan 2), il expose les deux canaux déjà validés en live :
suggestions Amazon (autocomplete) et classement des ventes (BSR)."""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

from amazon_autocomplete import fetch_suggestions
from amazon_product import fetch_bsr

BANNER = """
  IA-Niches  —  explorateur de niches KDP
  ------------------------------------------------
  Canaux gratuits validés : autocomplete + BSR
"""


def _menu() -> str:
    print("\n  1) Suggestions Amazon pour un mot-clé")
    print("  2) Classement des ventes (BSR) d'un ASIN")
    print("  q) Quitter")
    return input("\n  Choix > ").strip().lower()


def _do_suggest() -> None:
    kw = input("  Mot-clé > ").strip()
    if not kw:
        return
    sugg = fetch_suggestions(kw)
    if sugg:
        print(f"\n  {len(sugg)} suggestions pour « {kw} » :")
        for s in sugg:
            print(f"    - {s}")
    else:
        print("  Aucune suggestion (mot-clé vide ou endpoint temporairement bloqué).")


def _do_bsr() -> None:
    asin = input("  ASIN (10 caractères, ex. 2266283340) > ").strip()
    if not asin:
        return
    info = fetch_bsr(asin)
    if info:
        print(f"\n  BSR {info.asin} : N°{info.rank_livres} en Livres")
        for sub in info.subcategories:
            print(f"    N°{sub['rank']} en {sub['category']}")
    else:
        print("  Classement introuvable (fiche bloquée ou sans BSR — réessaie).")


def main() -> None:
    print(BANNER)
    while True:
        choice = _menu()
        if choice in ("q", "quit", "quitter"):
            print("  A bientot !")
            break
        if choice == "1":
            _do_suggest()
        elif choice == "2":
            _do_bsr()
        elif choice:
            print("  Choix non reconnu.")


if __name__ == "__main__":
    main()
