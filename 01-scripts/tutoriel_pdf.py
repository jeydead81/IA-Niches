"""tutoriel_pdf.py — guide d'utilisation d'IA-Niches en PDF, pour un auteur non technique.

Écrit pour quelqu'un qui publie sur KDP mais n'a jamais entendu « ASIN » ni « trope ».
Principe repris de la revue UX : on n'appauvrit pas les données (le BSR est la valeur de
l'outil), on les EXPLIQUE. Chaque chiffre est ancré sur une échelle et suivi de ce qu'il
faut en faire.

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
         "🟢": "", "🟠": "", "🔴": "", "⚪": "", "≥": ">=", "«": '"', "»": '"'}


def _safe(s) -> str:
    s = "" if s is None else str(s)
    for k, v in _REPL.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


# --- Contenu du guide -------------------------------------------------------------
# Les textes vivent ici, pas dans le code de mise en page : les corriger ne doit pas
# demander de toucher au PDF lui-même.

GLOSSAIRE = [
    ("BSR", "Le classement des ventes d'Amazon. Plus le nombre est PETIT, plus le livre "
            "se vend. Sous 10 000 : très bon. Au-delà de 100 000 : faible."),
    ("Rayon", "L'endroit d'Amazon où le livre est classé : boutique Kindle ou livres "
              "papier. Les classements des deux ne se comparent PAS entre eux."),
    ("Trio", "La recette d'un roman : un sous-genre + un ou deux thèmes + un décor. "
             "Exemple : cosy mystery + enquêtrice amatrice + village breton."),
    ("Trope", "Un ressort d'intrigue que le lecteur attend et recherche. "
              "Exemple : « ennemis devenus amants », « mariage arrangé »."),
    ("Profondeur", "Est-ce que les livres de ce rayon SE VENDENT ? Proche de 1 : oui, "
                   "franchement. Proche de 0 : non."),
    ("Ouverture", "Reste-t-il de la PLACE ? Proche de 1 : oui. Proche de 0 : les places "
                  "sont tenues par des livres bien installés."),
    ("Saturation", "Part des livres qui promettent DÉJÀ la même chose que vous. "
                   "ATTENTION : c'est le seul chiffre où un score ÉLEVÉ est MAUVAIS. "
                   "0,7 signifie que 7 livres sur 10 racontent déjà cela."),
    ("Part séries", "Proportion de livres appartenant à une série. Élevée = un tome "
                    "unique sera désavantagé."),
    ("Sonde autocomplete", "Est-ce que les lecteurs tapent vraiment ces mots dans la "
                           "recherche Amazon ? Un zéro n'est pas alarmant : beaucoup de "
                           "rayons se parcourent au lieu de se chercher."),
]

VERDICTS = [
    ("Pépite", _GREEN, "Cela se vend, il reste de la place, et personne ne raconte encore "
                       "tout à fait cela. À creuser en priorité."),
    ("Porteur mais encombré", _AMBER, "Cela se vend et il reste de la place, mais beaucoup "
                                      "de livres promettent déjà la même chose. Gardez le "
                                      "sous-genre, changez de thème ou de décor."),
    ("Mur installé", _RED, "Cela se vend, mais les places sont tenues par des livres bien "
                           "installés. Difficile d'entrer sans un angle très différent."),
    ("Désert", _AMBER, "Il reste de la place, mais rien ne prouve que ces livres se "
                       "vendent. Risqué."),
    ("Sans intérêt", _RED, "Peu de ventes et peu de place. Passez à autre chose."),
    ("Non mesuré", _GREY, "Impossible de conclure : le rayon était vide ou tous les livres "
                          "ont été écartés. Reformulez la requête ou changez de rayon. "
                          "Ce n'est PAS un mauvais résultat, c'est une ABSENCE de résultat."),
]

ETAPES_NF = [
    "Restez sur l'onglet « Non-fiction ».",
    "Tapez un sujet dans « Graine » (exemple : sommeil, stoïcisme, jardinage). "
    "Vous pouvez aussi laisser vide : l'IA proposera des sujets d'elle-même.",
    "Laissez les deux nombres tels quels la première fois.",
    "Cliquez sur « Lancer le scout » et patientez 2 à 3 minutes.",
    "Lisez les niches de haut en bas : la meilleure est la première.",
]

ETAPES_FIC = [
    "Cliquez sur l'onglet « Fiction ».",
    "Choisissez un sous-genre dans la liste (cosy mystery, dark romance...).",
    "Choisissez le rayon : Kindle ou Papier.",
    "Cliquez sur « Lancer le scout fiction ».",
    "Comptez 10 à 15 minutes. VOUS POUVEZ FERMER LA PAGE : le travail continue tout "
    "seul et vous le retrouverez à votre retour.",
]

PIEGES = [
    ("Un score de saturation élevé est un MAUVAIS signe",
     "C'est le seul chiffre inversé par rapport aux autres. 0,8 veut dire que 8 livres "
     "sur 10 promettent déjà votre idée."),
    ("« Non mesuré » ne veut pas dire « mauvais »",
     "Cela veut dire qu'aucun livre n'a pu être analysé. Reformulez votre requête "
     "plutôt que d'abandonner la niche."),
    ("Ne comparez jamais un BSR Kindle à un BSR papier",
     "Ce sont deux classements différents. Un 2 000 en Kindle et un 2 000 en papier ne "
     "représentent pas du tout les mêmes ventes."),
    ("Une part de séries élevée change la stratégie",
     "Si 7 livres sur 10 sont des tomes de séries, prévoyez une série plutôt qu'un "
     "roman isolé, sinon vous partirez avec un handicap."),
]


class _Pdf(FPDF):
    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*_MUTED)
        self.cell(0, 5, _safe(f"IA-Niches - guide d'utilisation - page {self.page_no()}"),
                  align="C")


def _titre(pdf: _Pdf, texte: str) -> None:
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*_BLUE)
    pdf.cell(0, 8, _safe(texte), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_draw_color(*_BLUE)
    pdf.set_line_width(0.4)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(2.5)


def _para(pdf: _Pdf, texte: str, taille: int = 9.5) -> None:
    pdf.set_font("Helvetica", "", taille)
    pdf.set_text_color(*_DARK)
    pdf.multi_cell(0, 4.8, _safe(texte), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1.5)


def build_tutoriel_pdf(out_path) -> Path:
    """Génère le guide. Aucune donnée d'entrée : c'est un document statique, versionné
    avec le code pour ne jamais décrire une interface qui n'existe plus."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = _Pdf(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    W = pdf.w - 20

    # --- Couverture légère
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
               "Vous partez d'un sujet et l'outil cherche les angles porteurs.")
    _para(pdf, "FICTION : romans. Vous partez d'un sous-genre et l'outil teste des "
               "combinaisons de thèmes et de décors. C'est le mode le plus puissant : il "
               "LIT les quatrièmes de couverture des livres concurrents pour savoir ce "
               "qu'ils promettent déjà.")

    _titre(pdf, "2. Lancer une analyse non-fiction")
    pdf.set_font("Helvetica", "", 9.5)
    for i, e in enumerate(ETAPES_NF, 1):
        pdf.set_text_color(*_AMBER)
        pdf.cell(6, 4.8, _safe(f"{i}."))
        pdf.set_text_color(*_DARK)
        pdf.multi_cell(W - 6, 4.8, _safe(e), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    _titre(pdf, "3. Lancer une analyse fiction")
    pdf.set_font("Helvetica", "", 9.5)
    for i, e in enumerate(ETAPES_FIC, 1):
        pdf.set_text_color(*_AMBER)
        pdf.cell(6, 4.8, _safe(f"{i}."))
        pdf.set_text_color(*_DARK)
        pdf.multi_cell(W - 6, 4.8, _safe(e), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.add_page()
    _titre(pdf, "4. Comprendre les mots et les chiffres")
    for terme, expl in GLOSSAIRE:
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(*_BLUE)
        pdf.cell(0, 5, _safe(terme), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_DARK)
        pdf.multi_cell(W, 4.4, _safe(expl), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1.2)

    pdf.add_page()
    _titre(pdf, "5. Les six verdicts, et quoi faire")
    for nom, couleur, conseil in VERDICTS:
        pdf.set_fill_color(*couleur)
        y0 = pdf.get_y()
        pdf.rect(pdf.l_margin, y0, 2.2, 9, style="F")     # liseré coloré
        pdf.set_x(pdf.l_margin + 4)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*couleur)
        pdf.cell(0, 4.6, _safe(nom), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_x(pdf.l_margin + 4)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_DARK)
        pdf.multi_cell(W - 4, 4.4, _safe(conseil), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)

    _titre(pdf, "6. Les quatre pièges à connaître")
    for titre, expl in PIEGES:
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(*_AMBER)
        pdf.multi_cell(W, 4.6, _safe(titre), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_DARK)
        pdf.multi_cell(W, 4.4, _safe(expl), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1.5)

    _titre(pdf, "7. Durée et coût")
    _para(pdf, "Une analyse non-fiction prend 2 à 3 minutes. Une analyse fiction prend "
               "10 à 15 minutes, parce qu'Amazon met du temps à répondre. Vous pouvez "
               "fermer la page : le travail continue et vous le retrouverez à votre retour.")
    _para(pdf, "Le coût réel de chaque analyse est affiché en fin de run. Il se compte en "
               "centimes.")

    pdf.output(str(out_path))
    return out_path


if __name__ == "__main__":
    import sys
    cible = sys.argv[1] if len(sys.argv) > 1 else "IA-Niches - Guide d'utilisation.pdf"
    print(f"Guide genere : {build_tutoriel_pdf(cible)}")
