"""test_usage.py — UsageMeter : compteur d'usage par utilisateur + plafond (plan SaaS S3).
Le compteur est un garde-fou (protège de la queue de distribution), pas une grille tarifaire :
pas de plafond configuré -> illimité mais journalisé ; un plafond configuré est PAR utilisateur
et mensuel GLISSANT (un plafond cumulatif à vie bloquerait un client fidèle)."""
from usage import UsageMeter


def test_chaque_run_est_impute_a_un_utilisateur(tmp_path):
    m = UsageMeter(tmp_path / "u.db")
    m.enregistrer("local", "fiction", cout_usd=0.153, n_analyses=3)
    r = m.resume("local")
    assert r.n_analyses == 3 and abs(r.cout_usd - 0.153) < 1e-9


def test_le_plafond_protege_de_la_queue_de_distribution(tmp_path):
    """La marge est de 88 % à 30 analyses/mois : le coût unitaire n'est PAS le risque.
    Le risque est l'utilisateur à 500 analyses. Le plafond existe pour lui, pas pour
    facturer à l'acte."""
    m = UsageMeter(tmp_path / "u.db", plafond_analyses=30)
    m.enregistrer("local", "fiction", cout_usd=1.0, n_analyses=30)
    assert m.autorise("local", n_analyses=1) is False
    assert m.autorise("autre", n_analyses=1) is True     # plafond PAR utilisateur


def test_le_plafond_est_mensuel_et_glissant(tmp_path):
    """Un plafond cumulatif à vie bloquerait un client fidèle au bout de quelques mois."""
    clock = {"t": 0.0}
    m = UsageMeter(tmp_path / "u.db", plafond_analyses=30, now=lambda: clock["t"])
    m.enregistrer("local", "fiction", cout_usd=1.0, n_analyses=30)
    assert m.autorise("local", n_analyses=1) is False
    clock["t"] += 31 * 24 * 3600           # 31 jours plus tard : la fenêtre a tourné
    assert m.autorise("local", n_analyses=1) is True
    r = m.resume("local")
    assert r.n_analyses == 0               # l'usage d'il y a 31 jours est hors fenêtre


def test_aucun_plafond_configure_nautorise_pas_tout_a_linfini(tmp_path):
    """Défaut prudent : pas de plafond -> illimité, mais l'usage reste journalisé."""
    m = UsageMeter(tmp_path / "u.db")      # pas de plafond_analyses fourni
    m.enregistrer("local", "fiction", cout_usd=5.0, n_analyses=500)
    assert m.autorise("local", n_analyses=1) is True
    r = m.resume("local")
    assert r.n_analyses == 500             # journalisé malgré l'absence de plafond


def test_resume_utilisateur_sans_historique_est_a_zero(tmp_path):
    m = UsageMeter(tmp_path / "u.db")
    r = m.resume("jamais-vu")
    assert r.n_analyses == 0 and r.cout_usd == 0.0
