"""tutoriel_pdf.py — dossier de passation d'IA-Niches, à destination du développeur
chargé de déployer l'outil.

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
    ("IDEATOR_MODEL / VERDICT_MODEL", "Défaut claude-sonnet-5."),
    ("FICTION_IDEATOR_MODEL / FICTION_CLASSIFIER_MODEL",
     "Défaut claude-sonnet-5. NE PAS rétrograder le classifieur : Haiku 4.5 mesuré à "
     "42 % d'accord contre 80 % requis."),
    ("REDDIT_CLIENT_ID / _SECRET / _USER_AGENT", "Optionnel, sources de veille."),
]

ENDPOINTS = [
    ("GET  /", "L'interface web (page unique)."),
    ("GET  /api/scout", "Scout non-fiction en SSE. Meurt si le client se déconnecte."),
    ("GET  /api/fiction", "Scout fiction en SSE. Idem."),
    ("GET  /api/fiction/sous-genres", "Peuple le sélecteur depuis la taxonomie."),
    ("POST /api/jobs", "202 + id immédiat. Travail détaché : survit à la déconnexion. "
                       "À PRIVILÉGIER pour la fiction (10-15 min)."),
    ("GET  /api/jobs/{id}", "Statut, progression, résultat, coût."),
    ("GET  /api/jobs/{id}/stream", "Progression en SSE, reconnectable."),
    ("GET  /api/jobs", "Liste par utilisateur."),
    ("GET  /api/usage", "Consommation du mois glissant."),
    ("POST /api/verdict", "Analyse éditoriale d'UNE niche, à la demande (0,028 $)."),
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
    ("Utiliser les travaux asynchrones, pas les endpoints SSE",
     "La latence DataForSEO est très variable : SERP mesurées à 85 s, 222 s et 251 s "
     "sur un même run. Les endpoints SSE perdent le travail si le client ferme "
     "l'onglet. POST /api/jobs survit."),
    ("La file ASIN se paie une fois par run, pas par niche",
     "Environ 250 s quel que soit le nombre d'ASIN. fiction_master groupe déjà toutes "
     "les SERP avant un unique batch : ne pas revenir à un batch par niche (10 niches "
     "passeraient de 5 à 42 minutes)."),
    ("Les magasins SQLite sont locaux",
     "jobs.db et usage.db sont des fichiers. Pour plusieurs instances, les remplacer "
     "par une base partagée. Le schéma porte déjà un user_id (défaut 'local') : "
     "brancher l'authentification est un remplissage de colonne, pas une migration."),
    ("Le cache est mutualisé entre utilisateurs",
     "Clés par ASIN et par mot-clé, TTL 7 jours. C'est l'économie principale à "
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

    _titre(pdf, "6. Les six verdicts")
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


if __name__ == "__main__":
    import sys
    cible = sys.argv[1] if len(sys.argv) > 1 else "IA-Niches - Dossier de passation.pdf"
    print(f"Dossier genere : {build_tutoriel_pdf(cible)}")
