"""tutoriel_pdf.py — les deux documents PDF d'IA-Niches.

- `build_tutoriel_pdf()`    : dossier de PASSATION, pour le développeur qui déploie.
- `build_guide_utilisateur_pdf()` : GUIDE, pour l'auteur qui se sert de l'outil.

Les deux partagent le même fond métier mais pas le même angle : le développeur a besoin
de savoir qu'il ne doit pas colorer la saturation comme les autres jauges ; l'auteur a
besoin de savoir qu'un chiffre élevé y est mauvais. Les textes sont donc distincts,
volontairement, et vivent dans des constantes séparées.

Dossier de passation à destination du développeur chargé de déployer l'outil.

Contient ce qu'on ne peut pas deviner en lisant le code : la grille de coûts par type de
demande (chiffres MESURÉS, pas estimés), ce qui change entre le poste local et un serveur,
et surtout les pièges métier qu'une réimplémentation naïve casse silencieusement — la
saturation inversée et « non mesuré » != « mauvais » en tête.

Le glossaire métier est volontairement conservé : un développeur qui ignore que la
saturation est le seul score où « élevé = mauvais » colorera la jauge en vert et fera
recommander exactement les pires niches.

Même motif que positioning_pdf.py : fpdf2, police core Helvetica + assainisseur latin-1
(portable, aucun fichier de police à embarquer)."""
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

_BLUE = (30, 64, 175)
_AMBER = (217, 119, 6)
_DARK = (30, 41, 59)
_MUTED = (100, 116, 139)
_LIGHT = (241, 245, 249)
_GREEN = (22, 163, 74)
_RED = (220, 38, 38)
_GREY = (148, 163, 184)

_REPL = {"€": "EUR", "œ": "oe", "Œ": "OE", "’": "'", "‘": "'", "“": '"', "”": '"',
         "–": "-", "—": "-", "…": "...", "\xa0": " ", "•": "-", "→": "->", "×": "x",
         "≥": ">=", "≠": "!=", "«": '"', "»": '"'}


def _safe(s) -> str:
    """Assainisseur latin-1. Les accents français (é è à ç ô...) passent SANS conversion —
    seuls oe, EUR, tirets longs et points de suspension sont remplacés."""
    s = "" if s is None else str(s)
    for k, v in _REPL.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


# --- Contenu ----------------------------------------------------------------------
# Les textes vivent ici, pas dans la mise en page : les corriger ne demande pas de
# toucher au code du PDF.

# Coûts MESURÉS (runs réels du 2026-07-21), pas des estimations. Les extrapolations sont
# signalées comme telles — un chiffre présenté comme mesuré alors qu'il est déduit
# fausserait la tarification construite dessus.
COUTS = [
    ("Scout non-fiction (BSR local, scrape)", "0,030 $", "0,021 $", "mesuré"),
    ("Scout non-fiction (BSR serveur, payant)", "0,084 $", "0,048 $", "calculé"),
    ("Scout fiction, 3 trios", "0,153 $", "0,113 $", "mesuré"),
    ("Scout fiction, 8 trios", "0,409 $", "0,299 $", "extrapolé"),
    ("Analyse éditoriale (1 niche, à la demande)", "0,028 $", "0,028 $", "mesuré"),
    ("Sonde autocomplete", "0 $", "0 $", "gratuit"),
    ("PDF de positionnement", "0 $", "0 $", "local"),
    ("Consultation d'un job / historique", "0 $", "0 $", "lecture"),
    ("Set de validation du classifieur (50 livres)", "0,32 $", "-", "one-shot"),
    ("Mots-cles backend KDP (1 niche)", "0,006 $", "0,006 $", "estime"),
    # Par analogie avec les deux autres verdicts : aucun run live de fiction_verdict.
    ("Analyse editoriale fiction (1 trio, a la demande)", "0,03 $", "0,03 $", "estime"),
]

ENV_VARS = [
    ("ANTHROPIC_API_KEY", "Obligatoire. Toute la partie IA."),
    ("DATAFORSEO_LOGIN / _PASSWORD", "Obligatoire. Le mot de passe est celui de l'API "
                                     "(app.dataforseo.com/api-access), PAS celui du compte."),
    ("BSR_SOURCE", "'scrape' (défaut, gratuit) ou 'dataforseo' (payant). VOIR SECTION "
                   "DÉPLOIEMENT : 'scrape' ne fonctionne pas depuis un serveur."),
    ("DATAFORSEO_PRIORITY", "2 = file rapide (défaut, 1-4 min). 1 = file standard, "
                            "moitié prix mais jusqu'à ~45 min."),
    ("PLAFOND_ANALYSES_MENSUEL", "Plafond glissant par utilisateur. Vide = illimité "
                                 "(mais l'usage reste journalisé)."),
    ("IDEATOR_MODEL / VERDICT_MODEL", "Défaut claude-sonnet-5. Un identifiant sans le "
                                      "préfixe 'claude-' est absent de la grille de "
                                      "cost_tracker et donc facturé 0,00 $ : le coût "
                                      "disparaît des rapports sans lever d'erreur."),
    ("FICTION_IDEATOR_MODEL / FICTION_CLASSIFIER_MODEL",
     "Défaut claude-sonnet-5. NE PAS rétrograder le classifieur : Haiku 4.5 mesuré à "
     "42 % d'accord contre 80 % requis."),
    ("KDP_KEYWORDS_MODEL", "Defaut claude-sonnet-5. Les 7 mots-cles backend."),
    ("DATA_DIR", "Ou vivent les cinq bases SQLite. Non defini = 99-logs/. EXIGEE des que "
                 "APP_ENV=prod : le disque d'un conteneur est efface a chaque "
                 "deploiement, et sans volume monte sur ce chemin les comptes, la "
                 "consommation, l'historique et le cache disparaissent SANS AUCUN "
                 "SIGNAL. Le serveur refuse de demarrer plutot que de le laisser faire."),
    ("APP_ENV", "'prod' active les gardes d'exposition : BSR_SOURCE=dataforseo exige, "
                "DATA_DIR exigee, et le serveur ecoute 0.0.0.0 au lieu de la boucle "
                "locale (sinon, dans un conteneur, il est injoignable en silence)."),
    ("HOST / PORT", "Lus seulement par `python web/server.py`. HOST est DEDUIT "
                    "d'APP_ENV et n'a normalement pas a etre renseigne ; les "
                    "plateformes injectent PORT."),
    ("JOBS_MODE", "'thread' (defaut) : le serveur execute les travaux lui-meme. "
                  "'worker' : il empile, et `python 01-scripts/worker.py` execute. Les "
                  "deux processus doivent voir le MEME DATA_DIR."),
    ("INSCRIPTIONS_OUVERTES", "FERME par defaut. Le plafond mensuel etant PAR "
                              "utilisateur, un compte de plus est un plafond neuf : "
                              "l'inscription libre offrait une depense illimitee a un "
                              "anonyme. Le PREMIER compte passe toujours (amorcage)."),
    ("NOTIFICATIONS_EMAIL", "Drapeau du message de fin d'analyse. ETEINT par defaut, et "
                            "il ne suffit PAS : sans SMTP_HOST rien ne part. Une "
                            "configuration a moitie faite n'envoie pas « au mieux », "
                            "elle n'envoie pas."),
    ("SMTP_HOST / _PORT / _USER / _PASSWORD / _FROM / _TLS",
     "Serveur d'envoi. Port 587 et STARTTLS par defaut. Le message ne contient JAMAIS "
     "les niches trouvees ni le moindre montant : l'e-mail est un canal en clair, "
     "relaye et archive chez le fournisseur du destinataire. Un envoi qui echoue ne "
     "fait jamais echouer un run -- il a coute de l'argent reel et son resultat est "
     "en base."),
    ("BASE_URL", "Racine publique, utilisee UNIQUEMENT pour le lien du message de fin. "
                 "Absente, le message part sans lien plutot qu'avec un lien mort."),
    ("MARKETPLACE", "'fr' par defaut (amazon.fr). 'com' est DECRIT mais pas pret et "
                    "LEVE au demarrage : les codes DataForSEO seraient justes, mais les "
                    "browse nodes, les baremes KDP en euros, les mots saisonniers, le "
                    "corpus du filtre IP et les prompts sont francais. Un run .com "
                    "rendrait des chiffres faux sans lever."),
    ("COOKIE_SECURE", "Normalement inutile : le drapeau Secure est DEDUIT du protocole "
                      "(X-Forwarded-Proto puis le schema). A ne renseigner que derriere "
                      "un proxy TLS qui n'annonce rien. Il ne peut que FORCER."),
]

ENDPOINTS = [
    ("GET  /", "L'interface web (page unique). SEUL endpoint servi sans session — sinon "
               "le formulaire de connexion serait inatteignable."),
    ("POST /api/auth/inscription", "Cree un compte (e-mail + mot de passe) et ouvre une "
                                   "session. Le PREMIER compte cree reprend les donnees "
                                   "accumulees sous user_id='local' avant l'authentification."),
    ("POST /api/auth/connexion", "Ouvre une session. Un e-mail inconnu et un mot de passe "
                                 "faux rendent le MEME message : sinon une liste d'adresses "
                                 "revele qui est client."),
    ("POST /api/auth/deconnexion", "Ferme cette session cote serveur et retire le cookie. "
                                   "Les autres sessions du meme compte restent ouvertes."),
    ("GET  /api/auth/moi", "Le compte de la session en cours."),
    ("POST /api/auth/mot-de-passe", "Change le mot de passe. Exige l'ANCIEN -- une session "
                                    "volee ne doit pas verrouiller le proprietaire hors de "
                                    "son compte -- et referme les AUTRES sessions, la "
                                    "courante exceptee."),
    ("POST /api/auth/compte/suppression", "Cloture le compte et efface ce qu'il a produit "
                                          "(travaux, consommation, historique). Exige le mot "
                                          "de passe : seule action irreversible du produit. "
                                          "Le cache mutualise n'est PAS touche."),
    ("GET  /api/fiction/sous-genres", "Peuple le sélecteur depuis la taxonomie."),
    ("GET  /api/lowcontent/formats", "Peuple le sélecteur de format low-content depuis la taxonomie, avec le drapeau « normé »."),
    ("GET  /api/fiction/taxonomie/{sous_genre}", "Tropes et decors autorises du sous-genre. Alimente les menus du compositeur de trio : la taxonomie est la source de verite UNIQUE, jamais une liste en dur cote JS."),
    ("POST /api/jobs", "202 + id immediat. SEUL chemin de lancement des deux scouts. "
                       "Le travail est detache : il survit a la fermeture de l'onglet, "
                       "verifie le plafond AVANT de depenser et impute l'usage. Les "
                       "anciens GET /api/scout et /api/fiction, qui streamaient dans la "
                       "requete HTTP, ont ete retires : deux chemins pour le meme travail "
                       "divergent des que l'un des deux n'est plus exerce."),
    ("GET  /api/jobs/{id}", "Statut, progression, résultat, coût."),
    ("GET  /api/jobs/{id}/stream", "Progression en SSE, reconnectable."),
    ("GET  /api/jobs", "Liste par utilisateur."),
    ("POST /api/jobs/{id}/annuler", "Arrête une analyse (elle bug ou tourne dans le vide). Immédiat "
                                    "côté données, coopératif côté fil d'exécution ; le coût déjà "
                                    "engagé et l'unité de plafond restent comptés."),
    ("DELETE /api/jobs/{id}", "Supprime une analyse terminée, en échec ou arrêtée. Ne touche ni à "
                              "la consommation ni à l'historique d'évolution des niches."),
    ("GET  /api/usage", "Consommation du mois glissant."),
    ("POST /api/verdict", "Analyse éditoriale d'UNE niche, à la demande (0,028 $)."),
    ("GET  /api/history", "Passages sur une niche + lecture de son évolution. Une niche "
                          "vue une seule fois rend delta:null avec un 200 — « pas encore "
                          "de recul » est une réponse, pas un échec."),
    ("POST /api/kdp-keywords", "Les 7 mots-clés backend KDP d'une niche (~0,006 $). Le LLM "
                               "propose, le code applique les règles KDP, l'autocomplete "
                               "confirme gratuitement."),
    ("POST /api/dossier", "Dossier de niche en 3 pages : marche + concurrents, angle et spec, mots-cles KDP et categories suggerees. Gratuit sauf si les mots-cles sont demandes (~0,006 $)."),
    ("POST /api/pdf", "One-pager de positionnement. Sans état, gratuit."),
]

GLOSSAIRE = [
    ("BSR", "Le classement des ventes d'Amazon. Plus le nombre est PETIT, plus le livre "
            "se vend. Sous 10 000 : très bon. Au-delà de 100 000 : faible."),
    ("Rayon", "Boutique Kindle ou livres papier. Les classements des deux ne se comparent "
              "PAS : passer par label_rayon() avant toute comparaison."),
    ("Trio", "Sous-genre + un ou deux thèmes + un décor. L'unité d'analyse en fiction."),
    ("Trope", "Un ressort d'intrigue que le lecteur recherche activement. "
              "Exemple : « ennemis devenus amants »."),
    ("Profondeur (depth)", "Est-ce que les livres de ce rayon se vendent ? 0 à 1, "
                           "1 = oui franchement."),
    ("Ouverture (openness)", "Reste-t-il de la place ? 0 à 1, 1 = oui."),
    ("Saturation du trio", "Part des livres qui promettent DÉJÀ la même chose. "
                           "ATTENTION : SEUL score où ÉLEVÉ = MAUVAIS. À colorer à "
                           "l'inverse des deux précédents."),
    ("Part séries", "Proportion de livres appartenant à une série. Élevée = un tome "
                    "unique est désavantagé."),
    ("Sonde autocomplete", "Les lecteurs tapent-ils ces mots ? Soft signal : ne doit "
                           "JAMAIS gater seul. Peut valoir None (non mesuré) : ne pas "
                           "l'afficher comme un 0."),
]

VERDICTS = [
    ("Pépite (pepite)", _GREEN, "Se vend, place disponible, sujet peu couvert."),
    ("Porteur mais encombré (porteur_encombre)", _AMBER,
     "Se vend et il reste de la place, mais le trio est déjà très couvert."),
    ("Mur installé (mur_installe)", _RED, "Se vend, mais les places sont tenues."),
    ("Désert (desert)", _AMBER, "De la place, mais rien ne prouve que ça se vend."),
    ("Sans intérêt (mort)", _RED, "Peu de ventes et peu de place."),
    ("Non mesuré (non_mesurable)", _GREY,
     "Rayon vide ou tous les livres écartés. ABSENCE de résultat, PAS un mauvais "
     "résultat : à afficher en neutre, jamais en rouge."),
    ("Mesure trop mince (mesure_mince)", _GREY,
     "Moins de SEUILS['livres_mesures_min'] livres mesurables (3, hypothèse non calibrée). "
     "Aucun chiffre, aucune conclusion de marché, aucune analyse éditoriale : même "
     "traitement que non_mesurable (neutre, hors historique, en bas du tri)."),
]

PIEGES = [
    ("La saturation est inversée",
     "Sur profondeur et ouverture, élevé = bon. Sur la saturation, élevé = MAUVAIS. "
     "Une jauge codée uniformément fera recommander les pires niches."),
    ("« non_mesurable » n'est pas « mort »",
     "Les deux affichent des zéros partout. Le premier signifie qu'aucun livre n'a pu "
     "être évalué. Les confondre fait écarter des niches jamais mesurées."),
    ("Un rayon amputé n'est pas un rayon désert",
     "FictionShelf.n_echecs > 0 signifie que des livres n'ont pas pu être enrichis. "
     "Le verdict le signale : ne pas masquer cette mention."),
    ("Les BSR Kindle et papier ne se comparent pas",
     "Deux classements distincts. Toujours passer par label_rayon() ; comparer "
     "niche.rayon ('kindle') à book.bsr_rayon ('Boutique Kindle') rend False partout "
     "et fait déclarer toute niche morte sans la moindre erreur."),
    ("Les titres gratuits ont leur propre classement",
     "Environ 25 % du top Kindle. Exclus du scoring via bsr_gratuit : ne pas les "
     "réintroduire dans un calcul maison."),
]

DEPLOIEMENT = [
    ("Le BSR gratuit ne survit pas au déploiement",
     "BSR_SOURCE=scrape lit les fiches Amazon depuis une IP résidentielle. Depuis un "
     "datacenter, Amazon bloque. En production : BSR_SOURCE=dataforseo, ce qui fait "
     "passer un scout non-fiction de 0,030 $ à 0,084 $."),
    ("Un seul chemin de lancement : POST /api/jobs",
     "La latence DataForSEO est très variable : SERP mesurées à 85 s, 222 s et 251 s "
     "sur un même run. Le travail vit dans jobs.db, pas dans la requête HTTP : fermer "
     "l'onglet ne le tue pas, et GET /api/jobs/{id}/stream (SSE) se reconnecte en "
     "rejouant toute la progression. Les anciens GET /api/scout et GET /api/fiction "
     "ont été supprimés : deux chemins pour le même travail, dont un seul exercé, "
     "divergent."),
    ("La file ASIN se paie une fois par run, pas par niche",
     "Environ 250 s quel que soit le nombre d'ASIN. fiction_master groupe déjà toutes "
     "les SERP avant un unique batch : ne pas revenir à un batch par niche (10 niches "
     "passeraient de 5 à 42 minutes)."),
    ("Sans volume persistant, TOUT est perdu à chaque déploiement",
     "Les cinq bases sont des fichiers, et le disque d'un conteneur est effacé à chaque "
     "mise en ligne. Sans volume : plus de comptes, plus de consommation (donc le "
     "plafond repart de zéro et la base de la facturation est perdue), plus "
     "d'antériorité d'historique, plus de cache mutualisé. Et RIEN ne le signalerait : "
     "le service repartirait sur des bases vides comme une installation neuve. D'où "
     "DATA_DIR, EXIGÉE dès APP_ENV=prod — le serveur refuse de démarrer sans elle."),
    ("Un redémarrage laisse des travaux en l'air, et ils sont récupérés au démarrage",
     "Un run coupé par une mise en ligne reste 'en_cours' : l'utilisateur voit une "
     "analyse éternellement en cours et son unité de plafond est consommée. Serveur et "
     "worker passent donc en échec, à leur démarrage, les travaux sans progression "
     "depuis 30 min — coût et progression CONSERVÉS. Limite connue : un run coupé moins "
     "de 30 min avant attendra le redémarrage suivant."),
    ("Les magasins SQLite sont locaux",
     "jobs.db et usage.db sont des fichiers. Pour plusieurs instances, les remplacer "
     "par une base partagée. Le schéma porte déjà un user_id (défaut 'local') : "
     "brancher l'authentification est un remplissage de colonne, pas une migration."),
    ("Le cache est mutualisé entre utilisateurs",
     "Clés par ASIN et par mot-clé, TTL 15 jours (30 pour la classification de "
     "quatrièmes de couverture). C'est l'économie principale à "
     "l'échelle : deux clients analysant le même rayon ne le paient qu'une fois."),
]


class _Pdf(FPDF):
    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*_MUTED)
        self.cell(0, 5, _safe(f"IA-Niches - dossier de passation - page {self.page_no()}"),
                  align="C")


def _titre(pdf: _Pdf, texte: str) -> None:
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 12.5)
    pdf.set_text_color(*_BLUE)
    pdf.cell(0, 7.5, _safe(texte), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_draw_color(*_BLUE)
    pdf.set_line_width(0.4)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(2.5)


def _para(pdf: _Pdf, texte: str) -> None:
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_DARK)
    pdf.multi_cell(0, 4.5, _safe(texte), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1.5)


def _paires(pdf: _Pdf, items, largeur_cle: float = 0, mono: bool = False) -> None:
    """Liste clé -> explication. `largeur_cle=0` met la clé sur sa propre ligne (utile
    quand elle est longue), sinon les deux colonnes s'alignent."""
    W = pdf.w - 20
    for cle, expl in items:
        pdf.set_font("Courier" if mono else "Helvetica", "B", 8.5)
        pdf.set_text_color(*_BLUE)
        if largeur_cle:
            pdf.cell(largeur_cle, 4.4, _safe(cle))
            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_text_color(*_DARK)
            pdf.multi_cell(W - largeur_cle, 4.4, _safe(expl),
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        else:
            pdf.multi_cell(W, 4.4, _safe(cle), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_text_color(*_DARK)
            pdf.multi_cell(W, 4.4, _safe(expl), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1.1)


def build_tutoriel_pdf(out_path) -> Path:
    """Génère le dossier. Document statique versionné avec le code, pour ne jamais
    décrire une interface ou des coûts qui n'existent plus."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = _Pdf(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    W = pdf.w - 20

    pdf.set_font("Helvetica", "B", 21)
    pdf.set_text_color(*_BLUE)
    pdf.cell(0, 11, _safe("IA-Niches"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 11.5)
    pdf.set_text_color(*_DARK)
    pdf.cell(0, 6.5, _safe("Dossier de passation - développeur"),
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    pdf.set_fill_color(*_LIGHT)
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(W, 4.6, _safe(
        "L'outil répond à une question : avant d'écrire un livre, ce sujet se vend-il sur "
        "Amazon, et reste-t-il de la place ? Une IA propose des pistes, les données Amazon "
        "les valident (ventes réelles, concurrence, prix).\n\n"
        "En fiction, il fait quelque chose qu'aucun concurrent ne fait : il LIT les "
        "quatrièmes de couverture du rayon pour mesurer ce que les livres promettent déjà. "
        "C'est la métrique « saturation du trio », et c'est la valeur du produit."),
        fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)

    _titre(pdf, "1. Coût par type de demande")
    _para(pdf, "Chiffres relevés sur des runs réels (2026-07-21). La colonne « standard » "
               "correspond à DATAFORSEO_PRIORITY=1 : moitié prix sur la donnée, mais "
               "jusqu'à ~45 min d'attente au lieu de 1-4 min.")
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(*_MUTED)
    pdf.cell(88, 5, _safe("Demande"))
    pdf.cell(24, 5, _safe("priority"))
    pdf.cell(24, 5, _safe("standard"))
    pdf.cell(0, 5, _safe("origine"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for libelle, p, s, origine in COUTS:
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*_DARK)
        pdf.cell(88, 4.6, _safe(libelle))
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.cell(24, 4.6, _safe(p))
        pdf.cell(24, 4.6, _safe(s))
        pdf.set_font("Helvetica", "", 7.5)
        pdf.set_text_color(*_MUTED)
        pdf.cell(0, 4.6, _safe(origine), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    _para(pdf, "L'analyse éditoriale n'est plus générée pendant le run : elle se demande "
               "sur la niche choisie. Les trois analyses pré-générées pesaient 78 % du "
               "coût d'un run pour des textes rarement lus.")
    _para(pdf, "Les chiffres ci-dessus sont ceux d'un PREMIER passage. Les classifications "
               "de quatrièmes de couverture sont mises en cache (clé : livre + taxonomie + "
               "modèle + empreinte du prompt, TTL 30 jours) : un run répété sur un "
               "sous-genre déjà exploré tombe à 0,139 $ pour 8 trios à 70 % de "
               "recouvrement, soit -66 %. À l'échelle, c'est l'économie principale — deux "
               "clients analysant le même rayon ne le paient qu'une fois.")
    _para(pdf, "Piste écartée après mesure : tronquer les blurbs à 600 caractères économise "
               "0,083 $ mais fait tomber l'accord du classifieur de 100 % à 60 % contre "
               "l'étalon-or. Le modèle perd les tropes révélés en seconde moitié de texte. "
               "Ne pas retenter sans remesurer.")

    _titre(pdf, "2. Variables d'environnement")
    _paires(pdf, ENV_VARS)

    pdf.add_page()
    _titre(pdf, "3. Endpoints")
    _paires(pdf, ENDPOINTS, largeur_cle=54, mono=True)

    _titre(pdf, "4. Déploiement : ce qui change par rapport au poste local")
    _paires(pdf, DEPLOIEMENT)

    pdf.add_page()
    _titre(pdf, "5. Glossaire métier (nécessaire pour construire l'interface)")
    _paires(pdf, GLOSSAIRE)

    _titre(pdf, "6. Les sept états d'une carte")
    for nom, couleur, sens in VERDICTS:
        pdf.set_fill_color(*couleur)
        pdf.rect(pdf.l_margin, pdf.get_y(), 2.2, 8.4, style="F")
        pdf.set_x(pdf.l_margin + 4)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*couleur)
        pdf.cell(0, 4.2, _safe(nom), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_x(pdf.l_margin + 4)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*_DARK)
        pdf.multi_cell(W - 4, 4.2, _safe(sens), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1.4)

    pdf.add_page()
    _titre(pdf, "7. Pièges à ne pas casser en réimplémentant")
    for titre, expl in PIEGES:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_AMBER)
        pdf.multi_cell(W, 4.4, _safe(titre), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(*_DARK)
        pdf.multi_cell(W, 4.4, _safe(expl), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1.6)

    _titre(pdf, "8. Durées observées")
    _para(pdf, "Scout non-fiction : 2 à 7 minutes selon la charge de DataForSEO. "
               "Scout fiction : 10 à 15 minutes (869 s mesuré sur 3 trios). "
               "La file ASIN représente l'essentiel de cette attente et ne dépend pas du "
               "nombre de livres demandés.")
    _para(pdf, "Conséquence pour l'interface : annoncer la durée et permettre de fermer "
               "la page. Une attente de 15 minutes sans explication passe pour une panne.")

    pdf.output(str(out_path))
    return out_path




# ── Guide UTILISATEUR ────────────────────────────────────────────────────────────
# Textes distincts de ceux du dossier développeur : même fond métier, autre angle. Le
# développeur doit savoir qu'il ne doit pas colorer la saturation comme les autres
# jauges ; l'auteur doit savoir qu'un chiffre élevé y est mauvais POUR LUI.

U_GLOSSAIRE = [
    ("BSR", "Le classement des ventes d'Amazon. Plus le nombre est PETIT, plus le livre "
            "se vend. Sous 10 000 : très bon. Au-delà de 100 000 : faible. C'est la "
            "preuve la plus solide que le sujet trouve des acheteurs."),
    ("Rayon", "L'endroit d'Amazon où le livre est classé : boutique Kindle, ou livres "
              "papier. Ne comparez jamais un classement Kindle à un classement papier, "
              "ce sont deux listes différentes."),
    ("Trio", "La recette d'un roman : un sous-genre, un ou deux thèmes, un décor. "
             "Exemple : cosy mystery + enquêtrice amatrice + village breton."),
    ("Trope", "Un ressort d'intrigue que le lecteur attend et recherche activement. "
              "Exemple : « ennemis devenus amants », « mariage arrangé »."),
    ("Profondeur", "Est-ce que les livres de ce rayon SE VENDENT ? Plus le chiffre est "
                   "proche de 1, plus la réponse est oui."),
    ("Ouverture", "Reste-t-il de la PLACE ? Proche de 1 : oui. Proche de 0 : les bonnes "
                  "positions sont tenues par des livres bien installés."),
    ("Saturation du trio", "La part des livres qui promettent DÉJÀ la même chose que "
                           "vous. ATTENTION : c'est le seul chiffre de l'outil où un "
                           "score ÉLEVÉ est une MAUVAISE nouvelle. 0,7 signifie que "
                           "7 livres sur 10 racontent déjà votre idée."),
    ("Part séries", "La proportion de livres qui font partie d'une série. Si elle est "
                    "élevée, un roman isolé partira avec un handicap : les lecteurs de "
                    "ce rayon cherchent des suites."),
    ("Sonde autocomplete", "Est-ce que les lecteurs tapent vraiment ces mots dans la "
                           "barre de recherche Amazon ? Un zéro n'est pas alarmant : "
                           "beaucoup de rayons se parcourent au lieu de se chercher."),
]

U_VERDICTS = [
    ("Pépite", _GREEN, "Ça se vend, il reste de la place, et personne ne raconte encore "
                       "tout à fait ça. À creuser en priorité."),
    ("Porteur mais encombré", _AMBER,
     "Ça se vend et il reste de la place, mais beaucoup de livres promettent déjà la même "
     "chose. Gardez le sous-genre, changez de thème ou de décor."),
    ("Mur installé", _RED, "Ça se vend, mais les places sont tenues par des livres bien "
                           "installés. Difficile d'entrer sans un angle très différent."),
    ("Désert", _AMBER, "Il reste de la place, mais rien ne prouve que ces livres se "
                       "vendent. Risqué."),
    ("Sans intérêt", _RED, "Peu de ventes et peu de place. Passez à autre chose."),
    ("Non mesuré", _GREY, "Impossible de conclure : le rayon était vide, ou tous les "
                          "livres ont été écartés. Reformulez votre requête ou changez de "
                          "rayon. Ce n'est PAS un mauvais résultat, c'est une ABSENCE de "
                          "résultat — la niche peut très bien être excellente."),
    ("Mesure trop mince", _GREY, "Trop peu de livres mesurés (moins de trois) pour conclure. "
                                 "Ce n'est pas un rayon mort : élargissez votre requête ou "
                                 "essayez le rayon Kindle."),
]

U_ETAPES_NF = [
    "Restez sur l'onglet « Non-fiction ».",
    "Tapez un sujet dans « Graine » : sommeil, stoïcisme, jardinage... Vous pouvez aussi "
    "laisser vide, l'IA proposera des sujets d'elle-même.",
    "Laissez les deux nombres tels quels la première fois.",
    "Cliquez sur « Lancer le scout » et patientez 2 à 3 minutes.",
    "Lisez les niches de haut en bas : la meilleure est la première. Sur celle qui vous "
    "intéresse, demandez l'analyse éditoriale : elle propose des titres et des angles.",
]

U_ETAPES_FIC = [
    "Cliquez sur l'onglet « Fiction ».",
    "Choisissez un sous-genre dans la liste (cosy mystery, dark romance...).",
    "Choisissez le rayon : Kindle ou Papier.",
    "Cliquez sur « Lancer le scout fiction ».",
    "Comptez 10 à 15 minutes. VOUS POUVEZ FERMER LA PAGE : le travail continue tout seul "
    "et vous le retrouverez à votre retour.",
    "Lisez d'abord le badge de conclusion, puis la saturation du trio.",
]

U_PIEGES = [
    ("Un score de saturation élevé est un MAUVAIS signe",
     "C'est le seul chiffre inversé par rapport aux autres. 0,8 veut dire que 8 livres "
     "sur 10 promettent déjà votre idée : mieux vaut changer d'angle."),
    ("« Non mesuré » ne veut pas dire « mauvais »",
     "Cela veut dire qu'aucun livre n'a pu être analysé. Reformulez votre requête plutôt "
     "que d'abandonner la niche — elle n'a jamais été évaluée."),
    ("Ne comparez jamais un BSR Kindle à un BSR papier",
     "Un 2 000 en Kindle et un 2 000 en papier ne représentent pas du tout les mêmes "
     "ventes. Restez dans un seul rayon pour comparer."),
    ("Une part de séries élevée change votre stratégie",
     "Si 7 livres sur 10 sont des tomes de séries, prévoyez une série plutôt qu'un roman "
     "isolé, sinon vous partirez avec un handicap."),
    ("L'outil dit ce qui se vend, pas ce que vous devez écrire",
     "Un excellent score sur un sujet qui ne vous inspire pas donnera un mauvais livre. "
     "Servez-vous en pour choisir entre plusieurs idées qui vous plaisent déjà."),
]


def _etapes(pdf: "_Pdf", etapes) -> None:
    """Liste numérotée : le numéro en ambre, le texte qui suit peut déborder sur
    plusieurs lignes sans casser l'alignement."""
    W = pdf.w - 20
    for i, e in enumerate(etapes, 1):
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(*_AMBER)
        pdf.cell(6, 4.8, _safe(f"{i}."))
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(*_DARK)
        pdf.multi_cell(W - 6, 4.8, _safe(e), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1.5)


def build_guide_utilisateur_pdf(out_path) -> Path:
    """Guide pour l'auteur qui SE SERT de l'outil (pas celui qui le déploie)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = _Pdf(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    W = pdf.w - 20

    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(*_BLUE)
    pdf.cell(0, 12, _safe("IA-Niches"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(*_DARK)
    pdf.cell(0, 7, _safe("Guide d'utilisation"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)
    pdf.set_fill_color(*_LIGHT)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.multi_cell(W, 5, _safe(
        "À quoi sert cet outil ? À savoir, AVANT d'écrire un livre, si le sujet que vous "
        "visez se vend sur Amazon et s'il reste de la place pour un livre de plus.\n\n"
        "L'IA propose des idées, Amazon les valide avec de vrais chiffres de ventes. "
        "Vous gardez la décision."), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    _titre(pdf, "1. Les deux modes")
    _para(pdf, "NON-FICTION : guides pratiques, développement personnel, histoire, santé. "
               "Vous partez d'un sujet, l'outil cherche les angles porteurs.")
    _para(pdf, "FICTION : romans. Vous partez d'un sous-genre et l'outil teste des "
               "combinaisons de thèmes et de décors. Il fait quelque chose d'unique : il "
               "LIT les quatrièmes de couverture de vos concurrents pour savoir ce qu'ils "
               "promettent déjà aux lecteurs.")

    _titre(pdf, "2. Lancer une analyse non-fiction")
    _etapes(pdf, U_ETAPES_NF)

    _titre(pdf, "3. Lancer une analyse fiction")
    _etapes(pdf, U_ETAPES_FIC)

    pdf.add_page()
    _titre(pdf, "4. Comprendre les mots et les chiffres")
    for terme, expl in U_GLOSSAIRE:
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(*_BLUE)
        pdf.cell(0, 5, _safe(terme), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_DARK)
        pdf.multi_cell(W, 4.4, _safe(expl), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1.2)

    pdf.add_page()
    _titre(pdf, "5. Les sept conclusions possibles, et quoi faire")
    for nom, couleur, conseil in U_VERDICTS:
        pdf.set_fill_color(*couleur)
        pdf.rect(pdf.l_margin, pdf.get_y(), 2.2, 9, style="F")
        pdf.set_x(pdf.l_margin + 4)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*couleur)
        pdf.cell(0, 4.6, _safe(nom), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_x(pdf.l_margin + 4)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_DARK)
        pdf.multi_cell(W - 4, 4.4, _safe(conseil), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)

    _titre(pdf, "6. Les cinq pièges à connaître")
    for titre, expl in U_PIEGES:
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(*_AMBER)
        pdf.multi_cell(W, 4.6, _safe(titre), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_DARK)
        pdf.multi_cell(W, 4.4, _safe(expl), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1.5)

    _titre(pdf, "7. Combien de temps, combien ça coûte")
    _para(pdf, "Une analyse non-fiction prend 2 à 3 minutes. Une analyse fiction prend "
               "10 à 15 minutes, parce qu'Amazon met du temps à répondre. Vous pouvez "
               "fermer la page : le travail continue et vous le retrouverez à votre retour.")
    _para(pdf, "Le coût réel de chaque analyse s'affiche en fin de parcours, et votre "
               "consommation du mois est rappelée en haut de la page. Cela se compte en "
               "centimes.")

    pdf.output(str(out_path))
    return out_path


if __name__ == "__main__":
    print("Dossier passation :", build_tutoriel_pdf("IA-Niches - Dossier de passation.pdf"))
    print("Guide utilisateur :", build_guide_utilisateur_pdf("IA-Niches - Guide utilisateur.pdf"))
