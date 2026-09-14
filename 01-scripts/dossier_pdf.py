"""dossier_pdf.py — le Dossier de niche v2, commun non-fiction et low-content.

Le one-pager (`positioning_pdf`) s'arrête au verdict. Ce qui manque à un auteur qui va
publier tient en trois choses, et elles étaient DÉJÀ toutes payées :

  1. CONTRE QUI il publie — `top_books` porte titres, prix, avis et BSR depuis le chunk B,
     et n'apparaissait nulle part.
  2. QUOI écrire dans les 7 champs de mots-clés backend KDP.
  3. DANS QUELLES CATÉGORIES ranger le livre — déduit des BSR déjà collectés, coût 0 $.

Un invariant traverse tout le module, et il compte plus ici qu'à l'écran : une donnée
absente s'écrit « non mesuré », jamais zéro. Sur un document imprimé que l'auteur relira
dans trois semaines, il n'y a plus d'interface pour poser la question — un zéro muet y
devient définitif.

Deux formes de niche entrent (`ScoredNiche`, `LowContentScored`) et une seule sort :
`_lire()` les ramène à un dict commun. Écrire deux générateurs ferait diverger le document
selon l'onglet, exactement comme deux chemins de lancement ont divergé (§2.6).

Contrainte technique : fpdf2 en police core Helvetica n'accepte que du latin-1.
L'assainisseur de `positioning_pdf` est RÉUTILISÉ, pas recopié — deux assainisseurs
finiraient par ne plus traiter les mêmes caractères.
"""
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from positioning_pdf import _safe, _verdict_color

_BLUE = (30, 64, 175)
_DARK = (30, 41, 59)
_MUTED = (100, 116, 139)
_LIGHT = (241, 245, 249)
_AMBER_BG = (254, 243, 199)
_AMBER_TX = (146, 64, 14)

MAX_CONCURRENTS = 8
MAX_ANGLES = 3
# 50 caracteres : la limite DURE d'un champ de mots-cles KDP. Ce n'est pas une convention
# d'affichage, c'est la contrainte de saisie que l'auteur va rencontrer.
KDP_MAX_CAR = 50


def _nb(v) -> str:
    """Un nombre, ou « non mesuré ». JAMAIS zéro par défaut : zéro est le MEILLEUR
    classement BSR possible, et un prix à zéro ferait croire à un rayon bradé."""
    if v is None:
        return "non mesuré"
    if isinstance(v, float):
        return f"{v:.2f}".replace(".", ",")
    return f"{v:,}".replace(",", " ")


def _pct(v) -> str:
    return "non mesuré" if v is None else f"{round(v * 100)} %"


def _eur(v, suffixe: str = "") -> str:
    """Un montant, ou « non mesuré » SANS unité : « non mesuré EUR par vente » posait une
    unité sur une absence de mesure, et se relisait comme un montant manquant de chiffre."""
    return "non mesuré" if v is None else f"{_nb(v)} EUR{suffixe}"


def _lire(s) -> dict:
    """Ramène `ScoredNiche` et `LowContentScored` à une forme commune.

    Deux générateurs de PDF feraient diverger le document selon l'onglet — c'est le même
    piège que les deux chemins de lancement, qui ont fini par ne plus faire la même chose
    sans que personne le voie."""
    n = getattr(s, "niche", None)
    est_lc = not isinstance(n, str)
    return {
        "est_lc": est_lc,
        "titre": (n.niche if est_lc else n) or "",
        "requete": (n.requete_amazon if est_lc else s.requete_amazon) or "",
        "categorie": (n.categorie if est_lc else s.categorie) or "",
        "global": s.global_score,
        "axes": ([("Demande", s.demande), ("Pénétration", s.penetration),
                  ("Rentabilité", s.rentabilite), ("Faisabilité", s.faisabilite)]
                 if est_lc else
                 [("Demande", s.demande), ("Pénétration", s.penetration),
                  ("Compatibilité", s.compatibilite)]),
        "bsr_best": s.bsr_best,
        "bsr_moy": s.bsr_top_avg if est_lc else s.bsr_top5_avg,
        "n_cibles": s.n_concurrents_cibles,
        "n_sponsored": s.n_sponsored,
        "mesuree": s.concurrence_mesuree,
        "top_books": list(s.top_books or []),
        "verdict": s.verdict,
        # Propres au low-content ; None ailleurs, et la section est alors omise plutôt que
        # rendue vide — une section vide se lit comme une mesure a zero.
        "part_indie": getattr(s, "part_indie", None) if est_lc else None,
        "prix_median": getattr(s, "prix_median", None) if est_lc else None,
        "redevance": getattr(s, "redevance_estimee", None) if est_lc else None,
        "pages": getattr(s, "pages_median", None) if est_lc else None,
        "variantes": getattr(s, "n_variantes_quasi_identiques", None) if est_lc else None,
        "format_cle": (n.format_cle if est_lc else ""),
    }


def _bandeau(pdf: FPDF, titre: str, sous_titre: str, d: dict) -> None:
    pdf.set_fill_color(*_BLUE)
    pdf.rect(0, 0, pdf.w, 24, "F")
    pdf.set_xy(10, 6)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(pdf.w - 60, 8, _safe(titre[:70]), new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(10, 15)
    pdf.cell(pdf.w - 60, 5, _safe(sous_titre), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    v = d["verdict"]
    if v is not None:
        pdf.set_fill_color(*_verdict_color(v.verdict))
        pdf.set_xy(pdf.w - 55, 6)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(45, 12, _safe(f"{v.verdict}  {v.confiance}/10"), align="C", fill=True,
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*_DARK)
    pdf.set_y(30)


def _titre_section(pdf: FPDF, texte: str) -> None:
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*_BLUE)
    pdf.cell(0, 7, _safe(texte), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*_DARK)


def _encadre(pdf: FPDF, texte: str) -> None:
    """Encadré d'avertissement. Réservé aux ABSENCES DE MESURE : c'est la seule chose qui
    doit arrêter l'œil sur un document qu'on parcourt."""
    pdf.set_fill_color(*_AMBER_BG)
    pdf.set_text_color(*_AMBER_TX)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.multi_cell(0, 4.5, _safe(texte), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*_DARK)
    pdf.ln(1)


def _page_marche(pdf: FPDF, d: dict) -> None:
    """Page 1 — le marché : les chiffres, puis CONTRE QUI on publie."""
    _bandeau(pdf, d["titre"],
             f"Requete : « {d['requete']} »  ·  {d['categorie']}", d)

    if not d["mesuree"]:
        _encadre(pdf, "Concurrence NON MESUREE : la recherche Amazon n'a pas repondu pour "
                      "cette niche. Les compteurs de concurrents et de sponsorises valent "
                      "zero faute de mesure, pas parce que le rayon est vide. Le score "
                      "n'est pas exploitable en l'etat - relancez l'analyse.")

    _titre_section(pdf, "Chiffres cles")
    pdf.set_font("Helvetica", "", 9)
    lignes = [f"Score global : {d['global']}/10"]
    lignes += [f"{k} : {v}/10" for k, v in d["axes"]]
    lignes.append(f"BSR meilleur : {_nb(d['bsr_best'])}  ·  moyenne du top : {_nb(d['bsr_moy'])}")
    lignes.append(f"Concurrents ciblant la requete : {_nb(d['n_cibles'])}  ·  "
                  f"sponsorises ecartes des calculs : {_nb(d['n_sponsored'])}")
    if d["est_lc"]:
        lignes.append(f"Part indie (publies via KDP) : {_pct(d['part_indie'])}  ·  "
                      f"variantes quasi identiques : {_nb(d['variantes'])} "
                      f"(eleve = mauvais)")
        lignes.append(f"Prix median : {_eur(d['prix_median'])}  ·  pagination : "
                      f"{_nb(d['pages'])}  ·  redevance estimee au prix median du rayon : "
                      f"{_eur(d['redevance'], ' par vente')}")
    for l in lignes:
        pdf.multi_cell(0, 5, _safe(l), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    _titre_section(pdf, "Contre qui vous publiez (top organique)")
    livres = d["top_books"][:MAX_CONCURRENTS]
    if not livres:
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(0, 5, _safe(
            "Aucun concurrent connu : la recherche Amazon n'a rien rendu pour cette "
            "niche. Ce n'est pas un rayon vide, c'est une donnee non mesuree."),
            new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        return

    W = pdf.w - 20
    col = (W - 70, 22, 18, 30)          # titre, prix, avis, BSR
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(*_LIGHT)
    for largeur, entete in zip(col, ("Titre", "Prix", "Avis", "BSR")):
        pdf.cell(largeur, 6, _safe(entete), border=0, fill=True,
                 align="L" if entete == "Titre" else "R", new_x=XPos.RIGHT,
                 new_y=YPos.TOP)
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 8)
    for b in livres:
        # Titre TRONQUE, jamais replie sur plusieurs lignes : un titre KDP bourre de
        # mots-cles fait 300 caracteres et devorerait la page a lui seul.
        titre = (b.title or b.asin or "")[:62]
        pdf.cell(col[0], 5.5, _safe(titre), new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(col[1], 5.5, _safe(_nb(b.price)), align="R", new_x=XPos.RIGHT,
                 new_y=YPos.TOP)
        pdf.cell(col[2], 5.5, _safe(_nb(b.reviews_count)), align="R", new_x=XPos.RIGHT,
                 new_y=YPos.TOP)
        pdf.cell(col[3], 5.5, _safe(_nb(b.bsr)), align="R", new_x=XPos.LMARGIN,
                 new_y=YPos.NEXT)


def _page_angle(pdf: FPDF, d: dict) -> None:
    """Page 2 — ce qu'on ecrit. Sans verdict, la page dit qu'il n'a pas ete demande : le
    document reste utile et n'invente rien."""
    pdf.add_page()
    _titre_section(pdf, "Angle recommande")
    v = d["verdict"]
    if v is None or not v.angles:
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(0, 5, _safe(
            "Verdict non demande pour cette niche. L'analyse editoriale se demande a la "
            "piece depuis le tableau : elle est facturee separement, et n'est donc pas "
            "generee d'office. Les mesures de la page precedente restent valables."),
            new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        return

    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 5, _safe(f"Facteur decisif : {v.facteur_decisif}"),
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    for i, a in enumerate(v.angles[:MAX_ANGLES]):
        # La redevance de l'angle est une PHRASE du modele : aucun prix, aucune pagination ni
        # aucun bareme d'impression n'y entre cote code. Imprimee nue, elle se lisait comme le
        # montant calcule de la page 1. Le qualificatif va dans la valeur, pas dans le libelle :
        # la cellule du libelle fait 34 mm, un libelle long chevaucherait le texte.
        redevance = (a.redevance_estimee or "").strip()
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 10.5)
        pdf.multi_cell(0, 5.5, _safe(("" if i else "→ ") + (a.titre or "")),
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(0, 5, _safe(a.sous_titre or ""), new_x=XPos.LMARGIN,
                       new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 8.5)
        for label, valeur in (("Pourquoi", a.pourquoi), ("Risque", a.risque),
                              ("Prix suggere", a.prix_suggere),
                              ("Couverture", a.direction_couverture),
                              # Propres au low-content : l'INTERIEUR est le produit, un
                              # angle sans spec ne se fabrique pas. Vides ailleurs, et
                              # alors omis -- une ligne vide se lirait comme une lacune.
                              ("Interieur", a.spec_interieur),
                              ("Redevance", f"estimation de l'IA, non calculee : {redevance}"
                                            if redevance else ""),
                              ("Source reglementaire", a.source_reglementaire)):
            if not (valeur or "").strip():
                continue
            pdf.set_font("Helvetica", "B", 8.5)
            pdf.cell(34, 4.8, _safe(label), new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.set_font("Helvetica", "", 8.5)
            pdf.multi_cell(0, 4.8, _safe(valeur), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    _titre_section(pdf, "Critique strategique")
    pdf.set_font("Helvetica", "", 8.5)
    for label, valeur in (("Saturation", v.saturation),
                          ("Faux concurrent", v.faux_concurrent),
                          ("Differenciation", v.differenciation)):
        if not (valeur or "").strip():
            continue
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.cell(34, 4.8, _safe(label), new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.multi_cell(0, 4.8, _safe(valeur), new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _page_publication(pdf: FPDF, mots_cles, categories) -> None:
    """Page 3 — comment on le publie : les 7 champs KDP, et ou ranger le livre."""
    pdf.add_page()
    _titre_section(pdf, "Mots-cles backend KDP (7 emplacements)")
    pdf.set_font("Helvetica", "", 8.5)

    if mots_cles is None:
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(0, 5, _safe(
            "Mots-cles non demandes. Ils se generent a la piece depuis le tableau : "
            "l'IA propose, les regles KDP sont appliquees cote code, et l'autocomplete "
            "confirme gratuitement ce qui est reellement cherche."),
            new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    else:
        if mots_cles.sonde_indisponible:
            # Sans ce drapeau, des mots-cles NON confirmes se liraient comme confirmes.
            _encadre(pdf, "Sonde autocomplete indisponible : AUCUN de ces mots-cles n'a "
                          "pu etre confirme aupres d'Amazon. Ce sont des paris, pas des "
                          "volumes verifies.")
        confirmes = set(mots_cles.confirmes_par_amazon or [])
        for i, m in enumerate(mots_cles.emplacements[:7], 1):
            marque = "confirme" if m in confirmes else "non confirme"
            pdf.multi_cell(0, 5, _safe(f"{i}. {m}   [{len(m)}/{KDP_MAX_CAR} car. - "
                                       f"{marque}]"),
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if mots_cles.a_verifier:
            pdf.ln(1)
            pdf.set_font("Helvetica", "I", 8)
            pdf.multi_cell(0, 4.5, _safe("A verifier a la main : "
                                         + ", ".join(mots_cles.a_verifier[:12])),
                           new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if mots_cles.rejetes:
            pdf.ln(1)
            pdf.set_font("Helvetica", "B", 8.5)
            pdf.cell(0, 5, _safe("Ecartes, avec leur motif :"), new_x=XPos.LMARGIN,
                     new_y=YPos.NEXT)
            pdf.set_font("Helvetica", "", 8)
            for r in mots_cles.rejetes[:10]:
                # Le MOTIF, jamais le seul rejet : « ecarte » n'apprend rien et l'auteur
                # reproposerait la meme expression au run suivant.
                pdf.multi_cell(0, 4.5,
                               _safe(f"- {r.get('mot', '?')} : {r.get('motif', '?')}"),
                               new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    _titre_section(pdf, "Categories Amazon suggerees")
    pdf.set_font("Helvetica", "", 8.5)
    if not categories:
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(0, 5, _safe(
            "Aucune sous-categorie lisible dans les classements du top : donnee non "
            "mesuree, et non « aucune categorie pertinente »."),
            new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    else:
        for c in categories[:6]:
            # On CONSTATE, on ne recommande pas : ces categories sont celles de livres
            # DEJA installes, pas forcement celles ou une place est libre.
            pdf.multi_cell(0, 5, _safe(
                f"- {c.get('category', '?')} : {c.get('n_livres', 0)} livre(s) du top y "
                f"sont ranges, meilleur rang {_nb(c.get('meilleur_rang'))}"),
                new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(*_MUTED)
    pdf.multi_cell(0, 4, _safe(
        "IA-Niches - analyse indicative, a valider par vos propres verifications. Les "
        "categories constatees ne sont pas une recommandation : elles decrivent ou sont "
        "ranges les livres deja installes."), new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def build_dossier_pdf(niche, out_path, mots_cles=None, categories=None) -> Path:
    """Dossier de niche en trois pages. Accepte `ScoredNiche` ou `LowContentScored`.

    `mots_cles` et `categories` sont OPTIONNELS : le dossier se génère sans eux et dit
    qu'ils n'ont pas été demandés, plutôt que de laisser des sections vides — une section
    vide se lit comme une mesure à zéro."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    d = _lire(niche)

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    _page_marche(pdf, d)
    _page_angle(pdf, d)
    _page_publication(pdf, mots_cles, categories)
    pdf.output(str(out_path))
    return out_path
