"""validate_classifier.py — CLI qui relit un xlsx de validation CORRIGÉ par Baptiste (M4-3)
et imprime le rapport d'accord IA/humain. C'est le SEUL chemin réel de mesure du protocole :
sans lui, `agreement_report` n'avait aucun appelant hors tests, et produire le rapport
aurait exigé de re-classifier — non déterministe, donc pas une mesure (cf. correctif A1)."""
import argparse

from fiction_validation import agreement_report, load_pairs


def _imprime_rapport(r) -> None:
    n_mesures = r.n_livres - r.n_non_classes
    print(f"Livres corrigés : {r.n_livres} (dont {r.n_non_classes} jamais classés par l'IA "
         "-> exclus du taux)")
    print(f"Accord : {r.n_accord}/{n_mesures} ({r.taux:.1%})")
    print(f"Porte des 80 % : {'FRANCHIE' if r.porte_franchie else 'NON FRANCHIE'}")

    if r.desaccords:
        print(f"\nASIN en désaccord ({len(r.desaccords)}) : {', '.join(r.desaccords)}")

    if r.cles_litigieuses:
        print("\nClés litigieuses (la taxonomie, pas le classifieur, est probablement en cause) :")
        for cle, compte in sorted(r.cles_litigieuses.items()):
            print(f"  - {cle} : IA seule={compte['ia_seule']}, humain seul={compte['humain_seul']}")

    if not r.porte_franchie:
        print("\n-> Sous la porte : corriger la TAXONOMIE (clés ambiguës ci-dessus) avant "
             "de toucher au prompt du classifieur.")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Rapport d'accord IA/humain sur un xlsx de "
                                             "validation du classifieur fiction (M4).")
    ap.add_argument("xlsx", help="chemin du xlsx CORRIGÉ par Baptiste (colonnes *_ok)")
    args = ap.parse_args(argv)

    paires = load_pairs(args.xlsx)
    _imprime_rapport(agreement_report(paires))


if __name__ == "__main__":
    main()
