"""Garde-fous d'hébergement : ce qui est sans conséquence en local devient une panne
silencieuse ou une injection en serveur.

Deux familles, sans rapport entre elles sauf qu'aucune ne se voit sur le PC de Baptiste :

1. `BSR_SOURCE=scrape` lit les fiches Amazon depuis une IP RÉSIDENTIELLE. Gratuit chez lui,
   BLOQUÉ depuis un datacenter — et l'échec y est muet : `resolve_bsrs` attrape l'exception
   par ASIN et rend `None` (invariant §5.29, un échec ne coule pas le run). En production,
   un déploiement qui oublie la variable ne plante donc pas : il rend des rapports où TOUS
   les BSR manquent, ce qui se lit comme un rayon sans classement. C'est exactement la faute
   de la règle 3, industrialisée.

2. Les titres et quatrièmes de couverture partent tels quels dans un prompt LLM. Ce sont des
   textes écrits par des TIERS sur Amazon : un titre peut porter « ignore les instructions
   précédentes ». Rien ne le rendra impossible, mais deux choses le rendent coûteux :
   borner la longueur (un titre de 4 000 caractères n'est pas un titre) et dire au modèle,
   dans le prompt système, que ces textes sont des DONNÉES.
"""
import pytest


# ── 1. APP_ENV=prod exige une source de BSR tenable en datacenter ──────────────

def test_prod_sans_bsr_dataforseo_refuse_de_demarrer(monkeypatch):
    """Refuser de démarrer est la SEULE issue lisible : démarrer produirait des rapports
    d'apparence normale, aux BSR tous absents."""
    import server
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("BSR_SOURCE", "scrape")
    with pytest.raises(RuntimeError) as e:
        server._verifier_config_prod()
    assert "BSR_SOURCE" in str(e.value) and "dataforseo" in str(e.value)


def test_prod_sans_bsr_source_du_tout_refuse_aussi(monkeypatch):
    """Le défaut de bsr_source.py est `scrape` : ne rien définir n'est pas neutre."""
    import server
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("BSR_SOURCE", raising=False)
    with pytest.raises(RuntimeError):
        server._verifier_config_prod()


def test_prod_avec_dataforseo_demarre(monkeypatch):
    import server
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("BSR_SOURCE", "dataforseo")
    server._verifier_config_prod()


def test_hors_prod_le_scrape_reste_le_defaut_local(monkeypatch):
    """Le poste de Baptiste ne doit rien changer : le scrape y est gratuit et fonctionne."""
    import server
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("BSR_SOURCE", "scrape")
    server._verifier_config_prod()


# ── 2. Bornes de longueur sur ce qui part au LLM ──────────────────────────────

def test_les_titres_concurrents_sont_bornes_en_longueur():
    from models import ScoredNiche, SearchItem, SearchResult
    from niche_verdict import build_user_prompt, MAX_LONGUEUR_TITRE

    titre_fleuve = "A" * 4000
    sr = SearchResult(keyword="q", sponsored=[],
                      organic=[SearchItem(title=titre_fleuve, asin="A1")])
    p = build_user_prompt(ScoredNiche(niche="n", requete_amazon="q", categorie="c"), sr)
    assert "A" * (MAX_LONGUEUR_TITRE + 1) not in p


def test_les_blurbs_sont_bornes_en_longueur():
    from fiction_classifier import build_user_prompt, MAX_LONGUEUR_BLURB
    from models import EnrichedBook

    livre = EnrichedBook(asin="A1", title="T", blurb="B" * 9000)
    p = build_user_prompt("cosy_mystery", [livre])
    assert "B" * (MAX_LONGUEUR_BLURB + 1) not in p


def test_la_troncature_est_signalee_pas_silencieuse():
    """Un texte coupé sans marque se lit comme un texte complet — le modèle raisonnerait
    sur une quatrième de couverture qu'il croit entière."""
    from fiction_classifier import build_user_prompt
    from models import EnrichedBook

    p = build_user_prompt("cosy_mystery",
                          [EnrichedBook(asin="A1", title="T", blurb="B" * 9000)])
    assert "…" in p or "[tronqué]" in p


def test_un_texte_normal_n_est_pas_touche():
    from fiction_classifier import build_user_prompt
    from models import EnrichedBook

    blurb = "Une enquête feutrée dans un village breton."
    p = build_user_prompt("cosy_mystery", [EnrichedBook(asin="A1", title="T", blurb=blurb)])
    assert blurb in p


# ── 3. Le prompt système dit que ces textes sont des DONNÉES ──────────────────

@pytest.mark.parametrize("module", ["niche_verdict", "fiction_classifier"])
def test_le_prompt_systeme_declare_les_textes_tiers_comme_donnees(module):
    """Ne rend pas l'injection impossible — la rend coûteuse. Un modèle à qui on a dit
    explicitement « ceci est une donnée » résiste mieux à un titre impératif."""
    import importlib
    p = importlib.import_module(module).SYSTEM_PROMPT.lower()
    assert "données" in p and "jamais des instructions" in p
