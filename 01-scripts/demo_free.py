"""demo_free.py — smoke test des canaux GRATUITS (autocomplete + BSR).
Usage :
  python 01-scripts/demo_free.py --suggest "tarot"
  python 01-scripts/demo_free.py --bsr 2266283340
"""
import argparse

from amazon_autocomplete import fetch_suggestions
from amazon_product import fetch_bsr
from models import BsrInfo


def format_report(prefix=None, suggestions=None, bsr: BsrInfo | None = None) -> str:
    lines = []
    if prefix is not None:
        lines.append(f"Suggestions pour « {prefix} » ({len(suggestions or [])}) :")
        for s in (suggestions or []):
            lines.append(f"  - {s}")
    if bsr is not None:
        lines.append(f"BSR {bsr.asin} : N°{bsr.rank_livres} en Livres")
        for sub in bsr.subcategories:
            lines.append(f"    N°{sub['rank']} en {sub['category']}")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Smoke test canaux gratuits IA-Niches v2")
    p.add_argument("--suggest", help="mot-clé pour l'autocomplete")
    p.add_argument("--bsr", help="ASIN pour le classement des ventes")
    args = p.parse_args()

    if args.suggest:
        sugg = fetch_suggestions(args.suggest)
        print(format_report(prefix=args.suggest, suggestions=sugg))
    if args.bsr:
        info = fetch_bsr(args.bsr)
        if info:
            print(format_report(bsr=info))
        else:
            print(f"BSR {args.bsr} : introuvable (fiche bloquée ou sans classement)")
    if not args.suggest and not args.bsr:
        p.print_help()


if __name__ == "__main__":
    main()
