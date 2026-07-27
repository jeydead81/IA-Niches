from fiction_scoring import (SEUILS, livres_scorables, depth_score, openness_score,
                             saturation_trio, series_share, price_band)
from models import EnrichedBook, FictionNiche, TropeClassification


def _livre(asin, bsr, rayon="Boutique Kindle", gratuit=False, prix=3.99, avis=20,
           serie=False, pos=1):
    return EnrichedBook(asin=asin, title="T", bsr=bsr, bsr_rayon=rayon,
                        bsr_gratuit=gratuit, price=prix, reviews_count=avis,
                        serie_total=5 if serie else None, serie_tome=1 if serie else None,
                        serp_position=pos)


def test_scorables_ecarte_gratuits_non_romans_et_mauvais_rayon():
    """Trois exclusions mesurées au spike : un titre gratuit a un classement DISTINCT,
    un jeu n'est pas un roman, et un rang « Livres » n'est pas comparable à un rang
    « Boutique Kindle »."""
    livres = [_livre("A1", 2000), _livre("A2", 478, gratuit=True),
              _livre("A3", 1597, rayon="Livres"), _livre("A4", 5000), _livre("A5", None)]
    cl = {"A4": TropeClassification(asin="A4", taxonomy_version="fr_v1", est_roman=False)}
    ok = livres_scorables(livres, cl, rayon="kindle")
    assert [b.asin for b in ok] == ["A1"]


def test_depth_calee_sur_les_rayons_mesures():
    """thriller psy (best 1960) doit sortir nettement au-dessus de cosy village (best 62230)."""
    actif = [_livre(f"A{i}", b) for i, b in enumerate([1960, 2168, 7422, 14924, 47262])]
    faible = [_livre(f"B{i}", b) for i, b in enumerate([62230, 95309, 150766, 156045, 204800])]
    assert depth_score(actif) > 0.7
    assert depth_score(faible) < 0.4
    assert depth_score([]) == 0.0                 # rayon vide -> pas de demande prouvée


def test_saturation_trio_compte_les_livres_qui_promettent_DEJA_le_trio():
    """Le différenciateur : 3 livres sur 4 promettent déjà mafia+captivite -> saturé."""
    niche = FictionNiche(sous_genre="dark_romance", tropes=["mafia", "captivite"],
                         rayon="kindle", query="q")
    livres = [_livre(f"A{i}", 2000) for i in range(4)]
    cl = {
        "A0": TropeClassification(asin="A0", taxonomy_version="fr_v1",
                                  tropes=["mafia", "captivite"]),
        "A1": TropeClassification(asin="A1", taxonomy_version="fr_v1",
                                  tropes=["mafia", "captivite", "vengeance"]),
        "A2": TropeClassification(asin="A2", taxonomy_version="fr_v1", tropes=["mafia"]),
        "A3": TropeClassification(asin="A3", taxonomy_version="fr_v1",
                                  tropes=["mariage_arrange"]),
    }
    # A0 et A1 couvrent le trio entier ; A2 partiellement ; A3 pas du tout
    s = saturation_trio(niche, livres, cl)
    assert 0.4 < s < 0.7
    assert saturation_trio(niche, livres, {}) == 0.0      # rien de classé -> rien de prouvé


def test_openness_recompense_un_rayon_peu_dote_en_avis():
    """Peu d'avis sur les leaders = places prenables ; beaucoup = mur installé."""
    ouvert = [_livre(f"A{i}", 5000, avis=15) for i in range(5)]
    ferme = [_livre(f"B{i}", 5000, avis=3000) for i in range(5)]
    assert openness_score(ouvert) > openness_score(ferme)


def test_series_share_et_price_band():
    livres = [_livre("A1", 2000, prix=2.99, serie=True), _livre("A2", 3000, prix=4.99),
              _livre("A3", 4000, prix=3.99, serie=True)]
    assert series_share(livres) == 2 / 3
    b = price_band(livres)
    assert b[0] == 2.99 and b[-1] == 4.99


def test_les_seuils_sont_exposes_et_documentes():
    """Repères marché, pas vérités : un produit vendu devra les exposer."""
    assert SEUILS["bsr_kindle_excellent"] < SEUILS["bsr_kindle_correct"]
