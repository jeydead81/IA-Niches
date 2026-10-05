"""La date d'écriture d'une fiche se déduit de son `expires`... et du TTL de son ÉPOQUE.

La purge ciblée (`--purger-fiches-sans-pages --ecrites-avant <date>`) date une fiche par
`expires − TTL`. Le TTL des fiches est passé de 15 à 30 jours le 2026-10-05 (décision de Baptiste).
Une ligne écrite AVANT porte `now + 15 j` : lue avec 30 j, sa date tombait 15 jours trop tôt, donc
une fiche écrite jusqu'à 15 jours APRÈS la date butoir pouvait être purgée — le sens imprudent.

Les deux époques sont séparables sans ambiguïté : une ligne écrite avant le changement expire au
plus tard 15 jours après lui ; une ligne écrite après expire au plus tôt 30 jours après lui.
"""
import datetime as dt

import pytest

from build_lowcontent_validation_set import _date_ecriture
from cache import BOOK_TTL_S, Cache
from models import EnrichedBook

JOUR = 24 * 3600
LOC = 2250


def _t(annee, mois, jour) -> float:
    return dt.datetime(annee, mois, jour, 12, tzinfo=dt.timezone.utc).timestamp()


def _ecrire(tmp_path, quand: float, ttl_s: float, asin="A1"):
    c = Cache(tmp_path / "c.db", now=lambda: quand)
    c.set_book(asin, LOC, EnrichedBook(asin=asin, title="T"), ttl_s)
    return c, c._book_key(asin, LOC)


def test_une_fiche_ecrite_avant_le_changement_garde_sa_vraie_date(tmp_path):
    ecrite = _t(2026, 9, 20)
    c, cle = _ecrire(tmp_path, ecrite, 15 * JOUR)
    assert _date_ecriture(c, cle) == pytest.approx(ecrite)


def test_une_fiche_ecrite_apres_le_changement_garde_sa_vraie_date(tmp_path):
    ecrite = _t(2026, 10, 10)
    c, cle = _ecrire(tmp_path, ecrite, BOOK_TTL_S)
    assert BOOK_TTL_S == 30 * JOUR
    assert _date_ecriture(c, cle) == pytest.approx(ecrite)


def test_la_veille_et_le_lendemain_du_changement(tmp_path):
    for jour, ttl in ((4, 15 * JOUR), (5, 15 * JOUR), (6, BOOK_TTL_S)):
        c, cle = _ecrire(tmp_path, _t(2026, 10, jour), ttl, asin=f"A{jour}")
        assert _date_ecriture(c, cle) == pytest.approx(_t(2026, 10, jour)), jour


def test_une_epoque_ancienne_ne_vise_pas_une_fiche_plus_recente_que_la_date_butoir(tmp_path):
    """LE scénario du défaut : butoir au 2026-09-25, fiche écrite le 2026-09-30 (après), TTL 15 j.
    Lue avec 30 j elle datait du 2026-09-15 et aurait été purgée."""
    butoir = _t(2026, 9, 25)
    c, cle = _ecrire(tmp_path, _t(2026, 9, 30), 15 * JOUR)
    assert _date_ecriture(c, cle) >= butoir


def test_une_ligne_illisible_reste_non_visee(tmp_path):
    c = Cache(tmp_path / "c.db")
    assert _date_ecriture(c, "book:absente") is None
