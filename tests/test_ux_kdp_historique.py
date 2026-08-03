"""tests/test_ux_kdp_historique.py — les deux fonctions ne valent que si l'utilisateur les voit.

Même motif que test_ux_glossaire.py : on lit le HTML servi tel quel et on vérifie la
présence des textes et des appels attendus, pas le rendu visuel.

L'enjeu n'est pas cosmétique : un endpoint sans bouton est une fonction que personne
n'utilisera jamais, et un backend d'historique sans affichage est une base SQLite que
personne n'ira lire à la main."""
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text("utf-8")


def test_le_bouton_mots_cles_kdp_existe_et_appelle_l_endpoint():
    assert "Mots-clés KDP" in HTML
    assert "/api/kdp-keywords" in HTML


def test_chaque_emplacement_est_copiable_un_par_un():
    """L'auteur colle les 7 expressions dans 7 champs distincts de KDP. Un bloc unique
    l'obligerait à découper à la main — et à se tromper."""
    assert "clipboard" in HTML.lower(), "un bouton copier par emplacement est attendu"
    assert "/50" in HTML, "la longueur consommée sur les 50 caractères doit être visible"


def test_le_statut_confirme_par_amazon_est_lisible():
    """LE point de vente du module : on ne devine pas le volume, on vérifie qu'Amazon
    complète l'expression. Sans pastille, cette vérification reste invisible."""
    assert "confirmé par Amazon" in HTML.lower() or "Confirmé par Amazon" in HTML
    assert "à vérifier" in HTML.lower()


def test_les_rejets_sortent_avec_leur_motif():
    """CLAUDE.md §10 : un mot-clé écarté en silence est une décision invisible."""
    assert "motif" in HTML.lower()
    assert "écarté" in HTML.lower()


def test_une_sonde_indisponible_est_annoncee_et_non_masquee():
    """Une panne d'autocomplete doit se lire comme une panne, jamais comme « aucun de tes
    mots-clés n'est cherché » — le contresens serait total et l'auteur jetterait de bons
    mots-clés."""
    assert "sonde_indisponible" in HTML
    for extrait in ("n'a pas répondu", "n'ont pas pu être vérifi"):
        assert extrait.lower() in HTML.lower(), f"message de panne manquant : {extrait}"


def test_l_historique_est_affiche_et_son_absence_n_est_pas_une_erreur():
    """Une niche vue une seule fois n'a pas d'évolution : il faut le DIRE (« premier
    passage »), pas afficher une erreur ni un delta à zéro qui se lirait « stable »."""
    assert "/api/history" in HTML
    assert "premier passage" in HTML.lower()


def test_l_evolution_est_lue_en_francais_pas_en_delta_brut():
    """C'est le champ `lecture` de DeltaNiche qui fait agir l'auteur, pas `variations` :
    « +0,23 » ne déclenche aucune décision, « la niche s'est densifiée » si. Le nombre de
    jours est déjà porté par `lecture` — le répéter dans l'en-tête ferait lire deux fois
    la même information (constaté au navigateur)."""
    assert "delta.lecture" in HTML
    assert "delta.variations" not in HTML, "le delta brut ne doit pas remonter à l'écran"
    assert "n_passages" in HTML


def test_une_niche_non_mesuree_est_signalee_dans_l_interface():
    """L'UI recalcule son badge depuis `global_score` seul : sans garde, une niche dont la
    SERP a échoué s'afficherait « Intéressant » comme une autre. C'est la faute cardinale
    du produit — une absence de mesure présentée comme un verdict de marché."""
    assert "concurrence_mesuree" in HTML
    for extrait in ("non mesurée", "relancer"):
        assert extrait.lower() in HTML.lower(), f"mention manquante : {extrait}"


# ── Écran de connexion ──────────────────────────────────────────────────────────────

def test_l_interface_a_un_ecran_de_connexion():
    """Sans écran de connexion, l'application est inutilisable depuis que tous les
    endpoints exigent une session : l'utilisateur ne verrait que des erreurs."""
    for chemin in ("/api/auth/moi", "/api/auth/connexion", "/api/auth/inscription",
                   "/api/auth/deconnexion"):
        assert chemin in HTML, f"appel manquant : {chemin}"


def test_le_mot_de_passe_est_masque_et_la_longueur_minimale_annoncee():
    """Annoncer la règle AVANT la saisie évite un refus incompréhensible au moment de
    valider. Le seuil doit suivre le serveur : il est passé de 10 à 12 après la revue de
    sécurité, et une interface qui annonce encore 10 fait échouer une inscription valide
    aux yeux de l'utilisateur."""
    from auth import LONGUEUR_MIN_MOT_DE_PASSE
    assert 'type="password"' in HTML
    assert f"{LONGUEUR_MIN_MOT_DE_PASSE} caractères" in HTML


def test_l_interface_dit_que_le_premier_compte_reprend_les_donnees_locales():
    """La reprise est silencieuse côté serveur ; ne pas la dire laisserait Baptiste croire
    que son historique a été perdu."""
    assert "donnees_locales_reprises" in HTML or "donnees_locales" in HTML


def test_l_utilisateur_connecte_est_visible_et_peut_se_deconnecter():
    """Sur un poste partagé, ne pas voir sous quel compte on travaille fait publier des
    analyses au mauvais endroit."""
    assert "Se déconnecter" in HTML or "Déconnexion" in HTML


def test_la_reprise_des_donnees_locales_est_une_case_a_cocher():
    """Le serveur n'adopte plus les données « local » automatiquement : la revue de sécurité
    a montré qu'un premier inscrit quelconque raflait sinon l'historique de Baptiste. Il faut
    donc que l'interface propose ce consentement, sinon la reprise devient inaccessible."""
    assert 'type="checkbox"' in HTML
    assert "reprendre_donnees_locales" in HTML


# ── Fourchette de prix et paramètres du scout ───────────────────────────────────────

def test_la_fourchette_de_prix_est_affichee():
    """Elle est déjà payée dans la SERP : ne pas l'afficher, c'est jeter une donnée
    achetée."""
    assert "n_prix_connus" in HTML
    for champ in ("prix_min", "prix_max", "prix_median"):
        assert champ in HTML, f"champ manquant : {champ}"


def test_un_prix_inconnu_se_dit_et_ne_devient_pas_zero():
    """Même invariant que partout : « inconnu » n'est pas « gratuit »."""
    assert "Prix du rayon" in HTML
    assert "donnée\n      absente" in HTML or "donnée absente" in HTML.replace("\n      ", " ")


def test_le_nombre_d_idees_n_est_plus_reglable():
    """L'ideator est UN SEUL appel LLM quel que soit le nombre d'idées : l'offrir au réglage
    laissait croire que c'était un levier de coût, alors que le poste qui pèse est le nombre
    de niches ANALYSÉES. Le champ « idées » disparaît, et la requête ne l'envoie plus."""
    assert 'id="ideas"' not in HTML
    assert "ideas:$('#ideas').value" not in HTML


def test_le_nombre_de_niches_analysees_va_jusqu_a_20():
    assert 'id="search"' in HTML and 'max="20"' in HTML


# ── Compositeur de trio fiction ─────────────────────────────────────────────────────

def test_le_compositeur_de_trio_existe_et_est_facultatif():
    """Le mode « propose-moi des trios » reste le chemin nominal : composer soi-même est un
    choix qu'on va chercher, replié, pas une étape imposée."""
    assert "Composer moi-même le trio" in HTML
    assert 'id="fic-tropes"' in HTML and 'id="fic-decor"' in HTML and 'id="fic-libre"' in HTML


def test_les_menus_du_trio_viennent_de_la_taxonomie():
    """Jamais une liste dupliquée en dur côté JS : elle se périmerait à la première taxo v2,
    et le serveur refuserait alors des clés que l'interface propose encore."""
    assert "/api/fiction/taxonomie/" in HTML
    for trope_en_dur in ("enquetrice_amatrice", "village_breton", "mafia"):
        assert f'value="{trope_en_dur}"' not in HTML, (
            f"{trope_en_dur} est écrit en dur dans le HTML")


def test_les_menus_se_rechargent_au_changement_de_sous_genre():
    """Les tropes diffèrent d'un sous-genre à l'autre : garder les anciens ferait composer
    un trio impossible, refusé ensuite par le serveur sans que l'auteur comprenne."""
    assert "sgSelect.addEventListener('change'" in HTML


def test_les_contraintes_partent_bien_dans_la_requete():
    """Elles voyagent désormais dans le corps JSON de `POST /api/jobs` et non dans l'URL :
    l'interface est passée sur le chemin asynchrone, qui survit à la fermeture de l'onglet."""
    for champ in ("params.tropes", "params.decor", "params.libre"):
        assert champ in HTML, f"contrainte non transmise : {champ}"


# ── Lecture des suggestions Amazon ──────────────────────────────────────────────────

def test_le_terme_dominant_est_affiche():
    """Le score note la QUANTITÉ de demande ; il ne peut pas dire qu'un rayon est tenu par
    un nom. Sans affichage, cette lecture resterait une donnée morte de plus."""
    assert "terme_dominant" in HTML and "part_dominante" in HTML
    assert "tient" in HTML.lower()


def test_l_intention_informationnelle_est_affichee():
    assert "intention_informationnelle" in HTML
    assert "marqueurs_informationnels" in HTML
    assert "pas forcément un livre" in HTML or "pas forcement un livre" in HTML


# ── Aide contextuelle ───────────────────────────────────────────────────────────────

def test_le_bouton_d_aide_existe():
    """Une pastille « ? » fixe en bas à droite : elle doit rester atteignable une fois la
    page défilée sur un tableau de résultats, car c'est au moment de LIRE les chiffres
    qu'on en a besoin — pas au moment de lancer."""
    assert 'id="aide-btn"' in HTML
    assert "position:fixed" in HTML


def test_il_y_a_un_tutoriel_par_onglet():
    """Un texte unique obligerait le lecteur à trier ce qui le concerne : les deux moteurs
    ne se lisent pas de la même façon."""
    assert "Non-fiction : trouver un sujet" in HTML
    assert "Fiction : mesurer un trio" in HTML


def test_le_tutoriel_suit_l_onglet_actif():
    """Il lit l'état RÉEL du DOM (la classe posée par switchTab) plutôt qu'une variable
    maintenue en parallèle, qui finirait par diverger du bouton affiché."""
    assert "ongletActif" in HTML
    assert "tab-fic" in HTML


def test_les_tutoriels_portent_les_pieges_de_lecture():
    """C'est la partie la plus utile : la faute la plus grave que ce produit puisse
    commettre est de faire lire une absence de mesure comme un verdict de marché."""
    assert "Pièges de lecture" in HTML
    assert "seul chiffre inversé" in HTML          # saturation du trio
    assert "n'est PAS une mauvaise niche" in HTML  # non mesurée


def test_l_aide_se_ferme_au_clavier_et_au_clic():
    """Une fenêtre qui ne se ferme qu'au bouton piège l'utilisateur qui clique à côté."""
    assert "Escape" in HTML
    assert 'id="aide-fermer"' in HTML


# ── Plus aucun montant affiché ──────────────────────────────────────────────────────

def test_aucun_cout_en_dollars_n_est_affiche():
    """La facturation se fera en jetons ou par abonnement : montrer des dollars d'API à
    l'utilisateur serait périmé le jour où le modèle change, et n'a jamais rien voulu dire
    pour lui. Le backend continue de tout mesurer — seul l'AFFICHAGE disparaît."""
    for mort in ("fmtUsd", "formatCost", "TAUX_USD_EUR", "Coût de ce run", "0,003 $"):
        assert mort not in HTML, f"résidu de coût : {mort}"


def test_la_fourchette_de_prix_des_livres_reste():
    """À ne pas confondre avec le coût de l'outil : c'est une donnée de MARCHÉ, demandée
    explicitement, et elle ne coûte rien de plus puisqu'elle arrive déjà avec la recherche."""
    assert "fmtEur" in HTML and "Prix du rayon" in HTML


def test_le_compteur_d_analyses_du_mois_reste():
    """C'est lui que le plafond mensuel consomme, et le seul repère avant un blocage."""
    assert "/api/usage" in HTML and "Ce mois-ci" in HTML


# ── Chemin asynchrone ───────────────────────────────────────────────────────────────

def test_l_interface_lance_les_runs_par_le_chemin_asynchrone():
    """`/api/scout` et `/api/fiction` en flux direct meurent avec la requête HTTP : fermer
    l'onglet perdait le résultat d'une analyse fiction de 15 minutes. `POST /api/jobs`
    détache le run, vérifie le plafond AVANT de dépenser et rend une 429 lisible."""
    assert "lancerTravail" in HTML
    assert "'/api/jobs'" in HTML
    assert "/stream" in HTML
    assert "new EventSource('/api/scout" not in HTML
    assert "new EventSource('/api/fiction?" not in HTML


def test_un_run_interrompu_est_repris_au_rechargement():
    """Sans reprise, la promesse « vous pouvez fermer cette page » resterait fausse : le
    travail continuerait côté serveur mais l'utilisateur n'aurait aucun moyen d'y revenir."""
    assert "reprendreTravail" in HTML
    assert "localStorage" in HTML
    assert "Analyse toujours en cours" in HTML


def test_le_plafond_atteint_se_dit_et_ne_passe_pas_pour_une_panne():
    """429 n'est pas une erreur technique : c'est une limite volontaire, et rien n'a été
    dépensé. Le dire évite que l'utilisateur relance en boucle."""
    assert "limite d'analyses pour ce mois-ci" in HTML
    assert "Rien n'a été lancé" in HTML
