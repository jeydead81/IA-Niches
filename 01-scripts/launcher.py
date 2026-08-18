"""launcher.py — petit lanceur interactif d'IA-Niches. GRATUIT, et seulement gratuit.
Lancé par le raccourci bureau (IA-Niches.bat). Deux sondes validées en live :
suggestions Amazon (autocomplete) et classement des ventes (BSR scrapé).

CE MODULE NE DOIT JAMAIS APPELER UN CHEMIN PAYANT. Il est antérieur à l'interface web
et ne connaît ni compte, ni session, ni plafond : tout appel facturé lancé d'ici
échapperait à `_verifier_plafond` ET à `UsageMeter`, donc à `usage.db`. Le montant
n'est pas le sujet — une option retirée le 2026-08-18 coûtait ~0,02 €. Le sujet est
que `usage.db` porte tout le raisonnement de marge du produit : ce qu'il ne voit pas,
personne ne le voit. Pour dépenser, il y a `POST /api/jobs`, qui vérifie et impute.

`tests/test_launcher.py` est le cliquet : il échoue si un import payant revient ici."""
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
    print("\n  1) Suggestions Amazon pour un mot-clé   (gratuit)")
    print("  2) Classement des ventes (BSR) d'un ASIN  (gratuit)")
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
