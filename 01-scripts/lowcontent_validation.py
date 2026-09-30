"""lowcontent_validation.py — protocole de calibration du scoring low-content (G1).

Les seuils de `data/lowcontent_criteres.json` sont des HYPOTHÈSES : `variantes_max=6`,
`part_indie_bonne=0.5`, `redevance_min_bonne=2.0` n'ont été confrontés à aucun rayon
réel. Le moteur tourne et rend des chiffres cohérents entre eux ; rien ne dit qu'ils
correspondent à ce que Baptiste sait du terrain. Ce module produit la mesure qui manque.

**Le protocole INVERSE celui du classifieur fiction, et c'est le point.** En fiction,
Baptiste CORRIGE des étiquettes que l'IA a produites (`fiction_validation.py`). Ici il
étiquette des requêtes AVANT toute analyse : son jugement est la référence, pas la
retouche d'une sortie. Si l'IA proposait les requêtes à juger, on calibrerait le scoring
sur lui-même et la corrélation serait garantie sans rien prouver.

Critère de sortie, conjoint : **Spearman ≥ 0,5 ET aucune requête « morte » en 🟢**.
Une corrélation honnête qui recommande quand même un rayon mort ferait publier dans le
vide — la faute la plus chère du produit (règle 3), et elle ne se compense pas par une
bonne moyenne d'ensemble.

Trois décisions de mesure, toutes dans le même esprit que §5.10 :
- Spearman et non Pearson : les étiquettes sont ORDINALES (morte < mauvaise < bonne),
  pas numériques. L'écart « morte → mauvaise » n'a aucune raison de valoir l'écart
  « mauvaise → bonne », et Pearson supposerait que si.
- Rangs MOYENS sur les ex aequo : avec trois étiquettes il y en aura partout, et un
  départage arbitraire mesurerait l'ordre de saisie du fichier.
- Les niches dont la concurrence n'a PAS été mesurée sortent du calcul. Leur score a été
  produit sans le moindre bonus ni malus de SERP : les corréler mesurerait l'écart entre
  un humain qui a vu le rayon et un score qui ne l'a pas vu. Elles sont comptées et
  annoncées (`n_non_mesurees`), jamais jetées en silence.

En cas d'échec, on corrige `data/lowcontent_criteres.json` — **jamais le code**. Un seuil
qui migre dans `lowcontent_scoring.py` redevient invisible et non discutable.
"""
from __future__ import annotations

from pathlib import Path
from statistics import median

from pydantic import BaseModel, Field

from lowcontent_taxonomy import load_taxonomy
from models import LowContentScored

# Ordre volontairement croissant : c'est la valeur ordinale corrélée au score.
ETIQUETTES: tuple[str, ...] = ("morte", "mauvaise", "bonne")
_ORDINAL: dict[str, int] = {e: i for i, e in enumerate(ETIQUETTES)}

SEUIL_SPEARMAN = 0.5           # porte du plan G1
MIN_PAR_FAMILLE = 3            # en deçà, la famille n'est pas calibrée, elle est frôlée

_ENTETES = ["requete", "famille", "etiquette", "note"]

# Ce qu'une relance TELLE QUELLE ne corrige pas. Le rapport du run 4 promettait « le cache ne
# repaiera que ce qui manque » : il resservait en fait les 185 fiches LUES par un parseur qui
# ne trouvait pas la pagination, et le 5e run aurait rendu le même rapport pour ~0,08 $.
_RELANCE_TELLE_QUELLE = (
    "Relancer tel quel ne corrige rien : SERP et fiches déjà rendues sont servies par le "
    "cache pendant 15 j, telles qu'elles ont été LUES ; le classement Anthropic sera repayé "
    "s'il n'a pas pu être gardé en cache.")


class SondeIndisponible(RuntimeError):
    """La sonde autocomplete est restée muette APRÈS une re-sonde gratuite, là où la porte
    serait CERTAINEMENT indécidable : toutes les requêtes, ou au moins une « morte ».

    Levée AVANT l'appel Anthropic. Continuer payait le classement, puis les SERP et les
    fiches, pour un rapport dont la conclusion était connue d'avance : « aucune morte en
    vert » ne se vérifie pas sur une morte dont la demande n'a pas été mesurée
    (`mortes_indecidables`). Une « bonne » ou une « mauvaise » muette ne bloque pas : elle
    sort du calcul et se compte (`n_demande_non_mesuree`), c'est Baptiste qui juge (§2.14)."""

    def __init__(self, requetes: list[str], mortes: list[str]):
        self.requetes = list(requetes)
        self.mortes = list(mortes)
        if mortes:
            detail = (f"{len(mortes)} requête(s) « morte » non sondée(s) : "
                      + ", ".join(f"« {m} »" for m in mortes)
                      + " — « aucune morte en vert » serait INDÉCIDABLE")
        else:
            detail = f"les {len(requetes)} requêtes sont restées non sondées"
        super().__init__(f"sonde autocomplete muette après une re-sonde : {detail}")


def requetes_non_sondees(etiquetees: list["RequeteEtiquetee"], mesures: dict,
                         cle=None) -> list["RequeteEtiquetee"]:
    """Les requêtes du classeur dont la sonde n'a rendu AUCUNE mesure (`None`, jamais 0 :
    zéro complétion est une mesure). `cle` est la règle d'appariement de l'appelant — la
    CLI passe la sienne, qui est celle de l'ideator."""
    cle = cle or (lambda r: " ".join((r or "").lower().split()))
    return [e for e in etiquetees if mesures.get(cle(e.requete)) is None]


# ── Spearman ───────────────────────────────────────────────────────────────────

def _rangs(valeurs: list[float]) -> list[float]:
    """Rangs 1..n, MOYENNÉS sur les ex aequo.

    Sans cette moyenne, `[bonne, bonne, mauvaise]` recevrait les rangs 1, 2, 3 : le
    premier « bonne » du fichier serait déclaré meilleur que le second alors que Baptiste
    les a jugés identiques. La corrélation mesurerait l'ordre des lignes."""
    ordre = sorted(range(len(valeurs)), key=lambda i: valeurs[i])
    out = [0.0] * len(valeurs)
    i = 0
    while i < len(ordre):
        j = i
        while j + 1 < len(ordre) and valeurs[ordre[j + 1]] == valeurs[ordre[i]]:
            j += 1
        moyen = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[ordre[k]] = moyen
        i = j + 1
    return out


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Corrélation de rangs. `None` quand elle est INDÉFINIE, jamais 0.0.

    Deux cas d'indéfinition, et les confondre avec « aucune corrélation » serait la même
    faute que partout ailleurs dans ce dépôt (§5.10) :
    - moins de deux points : il n'y a pas de classement ;
    - une série constante (toutes les étiquettes identiques, ou tous les scores égaux) :
      l'écart-type des rangs est nul, il n'y a rien à corréler. Rendre 0,0 se lirait
      « le scoring ne suit pas Baptiste » alors que le jeu ne permet pas de le dire."""
    if len(xs) != len(ys):
        raise ValueError(f"séries de longueurs différentes : {len(xs)} vs {len(ys)}")
    n = len(xs)
    if n < 2:
        return None
    rx, ry = _rangs(list(xs)), _rangs(list(ys))
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx)
    dy = sum((b - my) ** 2 for b in ry)
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy) ** 0.5


# ── Le gabarit que Baptiste remplit ────────────────────────────────────────────

class RequeteEtiquetee(BaseModel):
    requete: str
    famille: str = ""
    etiquette: str
    note: str = ""


def familles_taxonomie(version: str = "fr_v1") -> list[str]:
    """Source unique : les familles viennent de la taxo, jamais d'une liste en dur.
    Une famille ajoutée en v2 apparaît alors d'elle-même dans le gabarit."""
    taxo = load_taxonomy(version)
    vues: dict[str, None] = {}
    for f in taxo["formats"].values():
        vues.setdefault(f["famille"], None)
    return list(vues)


def exporter_gabarit(path: str | Path, n_par_famille: int = MIN_PAR_FAMILLE + 1,
                     version: str = "fr_v1", ecraser: bool = False) -> Path:
    """Écrit le classeur vide, pré-découpé PAR FAMILLE.

    Une page blanche produirait vingt requêtes de carnets et zéro registre : on
    calibrerait le rayon que Baptiste connaît le mieux, et on croirait avoir calibré le
    produit. Les lignes sont donc déjà attribuées, et le rapport redira lesquelles sont
    restées vides.

    **LÈVE si le fichier existe DÉJÀ et porte des étiquettes.** Le gabarit et le fichier
    de travail portent le même nom : relancer la commande après avoir étiqueté trente
    requêtes effacerait une demi-heure de travail, en silence et sans retour arrière —
    il n'y a pas de corbeille pour un xlsx écrasé. C'est la règle 10 du dépôt
    (confirmation avant d'écraser un fichier existant) appliquée à l'outil lui-même.

    Un gabarit VIERGE se régénère sans discuter : il n'y a rien à perdre. On refuse
    plutôt que de sauvegarder à côté — un `.bak` créé sans le dire est un fichier de
    plus que personne ne relira. `ecraser=True` passe outre, parce qu'un refus
    incontournable pousserait à supprimer le fichier à la main sans réfléchir."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    out = Path(path)
    if out.exists() and not ecraser:
        try:
            deja = charger_etiquettes(out)
        except Exception:                     # noqa: BLE001 — voir plus bas
            # Illisible ou d'un autre schéma : on refuse aussi. Un fichier qu'on ne sait
            # pas lire est le cas où l'écraser coûterait le plus cher, pas le moins.
            raise FileExistsError(
                f"{out} existe et n'a pas pu être relu — refus d'écraser. "
                f"Renommez-le, ou relancez avec --forcer.")
        if deja:
            exemples = ", ".join(f"« {e.requete} »" for e in deja[:3])
            raise FileExistsError(
                f"{out} contient déjà {len(deja)} requête(s) étiquetée(s) ({exemples}…) "
                f"— refus d'écraser. Lancez l'analyse avec --xlsx {out}, ou relancez "
                f"avec --forcer pour repartir d'un classeur vierge.")

    wb = Workbook()
    ws = wb.active
    ws.title = "Validation"

    ws.append(["Jeu de validation low-content — étiquetez AVANT toute analyse"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"Étiquettes autorisées : {' | '.join(ETIQUETTES)}"])
    ws.append([f"Au moins {MIN_PAR_FAMILLE} requêtes par famille — en deçà, cette famille "
               f"n'est pas calibrée."])
    ws.append(["« morte » = personne n'achète · « mauvaise » = demandé mais impénétrable "
               "ou non rentable · « bonne » = j'y publierais"])
    ws.append([])
    ws.append(list(_ENTETES))
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)

    premiere = ws.max_row + 1
    for famille in familles_taxonomie(version):
        for _ in range(n_par_famille):
            ws.append(["", famille, "", ""])

    dv = DataValidation(type="list", formula1='"' + ",".join(ETIQUETTES) + '"',
                        allow_blank=True, showDropDown=False)
    ws.add_data_validation(dv)
    dv.add(f"C{premiere}:C{ws.max_row}")

    for col, largeur in zip("ABCD", (52, 16, 14, 46)):
        ws.column_dimensions[col].width = largeur
    for ligne in ws.iter_rows(min_row=1, max_row=4, max_col=1):
        ligne[0].alignment = Alignment(wrap_text=False)

    wb.save(out)
    return out


def charger_etiquettes(path: str | Path) -> list[RequeteEtiquetee]:
    """Relit le classeur corrigé. Une ligne non remplie est IGNORÉE (c'est l'état normal
    d'un gabarit fraîchement créé) ; une étiquette inconnue LÈVE.

    L'asymétrie est voulue : une ligne vide est un travail pas encore fait, une étiquette
    « bof » est un travail fait de travers. L'avaler amputerait le jeu de validation sans
    que personne s'en aperçoive — et un jeu amputé en silence mesure faux."""
    from openpyxl import load_workbook

    ws = load_workbook(Path(path), data_only=True).active
    lignes = [[(c.value if c.value is not None else "") for c in r]
              for r in ws.iter_rows(max_col=4)]

    debut = None
    for i, l in enumerate(lignes):
        if [str(v).strip().lower() for v in l[:4]] == _ENTETES:
            debut = i + 1
            break
    if debut is None:
        raise ValueError(f"aucune ligne d'en-tête {_ENTETES} dans {path}")

    out: list[RequeteEtiquetee] = []
    for i, l in enumerate(lignes[debut:], start=debut + 1):
        requete = str(l[0]).strip()
        etiquette = str(l[2]).strip().lower()
        if not requete and not etiquette:
            continue
        if etiquette not in ETIQUETTES:
            raise ValueError(
                f"ligne {i} : étiquette « {etiquette or '(vide)'} » inconnue pour "
                f"« {requete or '(sans requête)'} » — attendu {' | '.join(ETIQUETTES)}")
        if not requete:
            raise ValueError(f"ligne {i} : étiquette « {etiquette} » sans requête")
        out.append(RequeteEtiquetee(requete=requete, famille=str(l[1]).strip(),
                                    etiquette=etiquette, note=str(l[3]).strip()))
    return out


# ── Le rapport ─────────────────────────────────────────────────────────────────

class RapportCalibration(BaseModel):
    """Ce qui s'archive dans `99-logs/`, à côté du rapport du classifieur fiction.

    `porte_franchie` porte les deux critères du plan — Spearman ≥ seuil, aucune « morte »
    en vert — et rien d'autre qui soit un JUGEMENT. S'y ajoute une seule condition, qui
    n'est pas un troisième critère mais la DÉCIDABILITÉ des deux premiers : un run dont
    l'enrichissement ASIN est tombé garde des scores calculables — la SERP fournit encore
    titres, prix, concurrents et variantes, et le BSR est rattrapé gratuitement par le
    scrape — donc un Spearman parfaitement calculable. Mais `part_indie` et
    `redevance_estimee` y valent `None` PARTOUT. La porte s'ouvrirait alors sur un run
    incapable de régler `part_indie_bonne` et `redevance_min_bonne`, deux des trois seuils
    que cette calibration existe POUR régler, en affichant un ✅ et en sortant en code 0.
    Même logique que `mortes_indecidables` : indécidable n'est pas satisfait (règle 3).

    Les `avertissements` — une famille sous-représentée, des SERP tombées, une « bonne »
    perdue avant analyse — ne la ferment PAS : ils disent sur quoi la mesure ne porte pas,
    ce qui est une information distincte de « le scoring a tort »."""
    n_requetes: int = 0
    n_calibrees: int = 0
    n_non_mesurees: int = 0
    # Sur combien de niches CALIBRABLES chacun des deux signaux propres au rayon
    # low-content a pu être lu. « part_indie médiane = 0,7 » ne se lit pas de la même
    # façon sur neuf niches et sur une : sans ces compteurs, le tableau des signaux est
    # illisible pour qui règle les seuils.
    n_part_indie_mesuree: int = 0
    n_redevance_mesuree: int = 0
    n_par_etiquette: dict[str, int] = Field(default_factory=dict)

    spearman: float | None = None
    seuil_spearman: float = SEUIL_SPEARMAN
    morts_en_vert: list[str] = Field(default_factory=list)
    # Deux COMPTEURS, sans effet sur la porte (décision de Baptiste, 2026-09-18) : au run 5,
    # « 0 morte en vert » se lisait comme une preuve de sûreté alors qu'une seule niche sur 51
    # était verte et qu'aucune bonne ne dépassait 6,31. `None` sans bonne calibrée, jamais 0.
    n_verts: int = 0
    meilleur_score_bonne: float | None = None
    # Combien de « morte » ont VRAIMENT été scorées. « Aucune morte en vert » se vérifiait
    # jusqu'au 2026-09-29 sur l'ensemble vide : neuf mortes toutes écartées ou non rendues
    # satisfaisaient le critère le plus important du plan sans qu'aucune n'ait vu un rayon.
    n_mortes_scorees: int = 0
    porte_franchie: bool = False
    # INDÉCIDABLE n'est pas ÉCHOUÉE. Vrai quand la porte est fermée faute de mesure COMPLÈTE
    # (SERP tombées, « morte » non vérifiable, rayon jamais lu) : relancer, et surtout ne PAS
    # toucher à `lowcontent_criteres.json`. Seule une porte fermée par une mesure complète dit
    # que les seuils ont tort. Défaut PESSIMISTE, comme `concurrence_mesuree=False` : un
    # rapport vierge n'a rien mesuré.
    porte_indecidable: bool = True

    # Distribution des signaux par étiquette — c'est CE tableau qui sert à régler
    # `lowcontent_criteres.json`. Sans lui on ajusterait un seuil au hasard.
    signaux: dict[str, dict[str, float | int | None]] = Field(default_factory=dict)
    familles: dict[str, int] = Field(default_factory=dict)

    # Requêtes perdues AVANT toute dépense (filtre IP, filtre saisonnier, gate gratuit).
    # Séparées par étiquette parce qu'elles ne disent pas la même chose : une « morte »
    # écartée là est le gate qui fait son travail pour zéro centime ; une « bonne »
    # écartée là est un faux négatif que l'utilisateur ne peut PAS voir, puisque la niche
    # n'apparaît nulle part. Les additionner effacerait exactement cette différence.
    ecartees_correctement: list[str] = Field(default_factory=list)
    bonnes_perdues_avant_analyse: list[str] = Field(default_factory=list)

    # Requêtes FOURNIES au moteur et absentes de sa sortie sans qu'aucun filtre ne les ait
    # écartées : omises par le modèle, tronquées, ou coupées par le plafond de coût. Aucun
    # gate ne joue en mode classement — les verser dans `ecartees_*` les faisait passer
    # pour des rejets « pour zéro centime », alors qu'elles étaient dans un prompt payé.
    non_rendues: list[dict[str, str]] = Field(default_factory=list)
    # Niches à SERP mesurée mais dont la sonde autocomplete est tombée : leur axe demande
    # repose sur un minimum inventé (`demand_score=1`), elles sortent du calcul.
    n_demande_non_mesuree: int = 0
    hors_taxonomie: list[dict[str, str]] = Field(default_factory=list)
    avertissements: list[str] = Field(default_factory=list)
    # Sur combien de niches calibrables la pagination a été lue : sans elle, « redevance
    # non mesurée » ne dit pas si la cause est le prix ou les pages.
    n_pages_mesurees: int = 0
    # Un rapport REJOUÉ hors ligne (`--rejouer`) : les seuils essayés l'ont été sur le jeu
    # même, il ne peut donc jamais franchir la porte (voir `rejouer_entrees`).
    rejeu: bool = False
    # Devis calculé AVANT toute dépense par la CLI, et dossier des captures du run.
    devis: dict | None = None
    dossier_captures: str = ""


def _est_vert(s: LowContentScored, c: dict) -> bool:
    """La priorité fait foi quand elle est renseignée ; à défaut on retombe sur le seuil.
    Se fier au seul score raterait le cas « ⚪ non mesurée » qui peut porter un score
    élevé sans jamais s'afficher en vert.

    Le seuil est celui du fichier de critères, comme dans `score_lowcontent` : une copie
    locale (l'ancienne constante SEUIL_VERT) divergeait dès qu'on touchait le fichier."""
    if s.priorite:
        return s.priorite.startswith("🟢")
    return s.global_score >= c["seuil_verdict_vivant"]


def _mediane(valeurs: list[float | None]) -> float | None:
    """Les `None` sont EXCLUS, jamais comptés zéro. Moyenner une part indie non mesurée à
    zéro fausserait exactement le seuil qu'on cherche à régler (§5.10)."""
    connus = [v for v in valeurs if v is not None]
    return median(connus) if connus else None


def _compteurs_diagnostic(lot: list[LowContentScored], c: dict) -> dict:
    """R20 — combien de niches d'une étiquette ont TOUCHÉ chaque bonus ou malus. Sans seuil
    ni effet sur la porte : « bonne 7/7 au bonus, morte 8/9 » se lit, et c'est Baptiste qui
    juge — une proportion d'alerte serait un critère inventé (§2.14).

    Mêmes comparaisons que `score_lowcontent` (>= pour part indie et récents, > pour crit3) :
    à tenir ensemble si le scoring change."""
    parts = [s.part_indie for s in lot if s.part_indie is not None]
    return {
        "n_bonus_part_indie": sum(1 for p in parts if p >= c["part_indie_bonne"]),
        "part_indie_min": min(parts) if parts else None,
        "part_indie_max": max(parts) if parts else None,
        "n_crit3": sum(1 for s in lot if s.bsr_worst is not None
                       and s.bsr_worst > c["bsr_crit3_place_a_prendre_min"]),
        "n_malus_recents": sum(1 for s in lot if s.part_moins_12_mois is not None
                               and s.part_moins_12_mois >= c["part_recents_afflux"]),
    }


def rapport_calibration(paires: list[tuple[str, LowContentScored]],
                        familles: list[str] | None = None,
                        ecartees: list[tuple[str, str]] | None = None,
                        version: str = "fr_v1",
                        non_rendues: list[tuple[str, str]] | None = None,
                        criteres: dict | None = None) -> RapportCalibration:
    """`paires` = (étiquette de Baptiste, niche scorée par le moteur), dans le même ordre
    que `familles` si elle est fournie. `ecartees` = (requête, étiquette) des requêtes
    perdues avant la moindre dépense. `criteres` ne sert qu'aux compteurs de diagnostic
    (défaut : `data/lowcontent_criteres.json`) ; il n'entre pas dans la porte."""
    from lowcontent_scoring import charger_criteres
    c = criteres or charger_criteres()
    r = RapportCalibration(n_requetes=len(paires) + len(ecartees or [])
                           + len(non_rendues or []))
    if familles is not None and len(familles) != len(paires):
        raise ValueError(f"{len(familles)} familles pour {len(paires)} paires")

    for e, _ in paires:
        if e not in ETIQUETTES:
            raise ValueError(f"étiquette « {e} » inconnue — attendu {ETIQUETTES}")
        r.n_par_etiquette[e] = r.n_par_etiquette.get(e, 0) + 1

    # Le signal terrain qui fera la taxonomie v2 : indépendant de la SERP, donc lu sur
    # TOUTES les paires, y compris celles dont la concurrence n'a pas pu être mesurée.
    for _, s in paires:
        if s.niche.format_cle == "other":
            r.hors_taxonomie.append({"requete": s.niche.requete_amazon,
                                     "libelle_observe": s.niche.other_libelle})

    r.morts_en_vert = [s.niche.requete_amazon for e, s in paires
                       if e == "morte" and _est_vert(s, c)]

    for requete, e in (ecartees or []):
        if e not in ETIQUETTES:
            raise ValueError(f"étiquette « {e} » inconnue — attendu {ETIQUETTES}")
        r.n_par_etiquette[e] = r.n_par_etiquette.get(e, 0) + 1
        (r.bonnes_perdues_avant_analyse if e == "bonne"
         else r.ecartees_correctement).append(requete)
    if r.bonnes_perdues_avant_analyse:
        r.avertissements.append(
            f"{len(r.bonnes_perdues_avant_analyse)} requête(s) jugée(s) « bonne » "
            f"perdue(s) AVANT toute analyse : "
            f"{', '.join(r.bonnes_perdues_avant_analyse)}. Faux négatif invisible — "
            f"la niche n'apparaît nulle part à l'écran. Vérifier le filtre IP et le filtre "
            f"saisonnier. N'entre PAS dans la porte du plan.")
    if r.ecartees_correctement:
        r.avertissements.append(
            f"{len(r.ecartees_correctement)} requête(s) non « bonne(s) » écartée(s) pour "
            f"zéro centime par le filtre IP ou le filtre saisonnier, avant tout appel "
            f"payant.")

    for requete, e in (non_rendues or []):
        if e not in ETIQUETTES:
            raise ValueError(f"étiquette « {e} » inconnue — attendu {ETIQUETTES}")
        r.n_par_etiquette[e] = r.n_par_etiquette.get(e, 0) + 1
        r.non_rendues.append({"requete": requete, "etiquette": e})
    mortes_non_scorees = [d["requete"] for d in r.non_rendues if d["etiquette"] == "morte"]
    if r.non_rendues:
        r.avertissements.append(
            f"{len(r.non_rendues)} requête(s) NON rendue(s) par le classement (omise par le "
            f"modèle, réponse tronquée ou plafond de coût atteint) : "
            + ", ".join(d["requete"] for d in r.non_rendues)
            + ". Ni le filtre IP, ni le filtre saisonnier, ni un gate ne les a écartées : "
              "elles n'ont simplement pas été mesurées.")
    # Les « morte » indécidables sont réunies plus bas, une fois connues les niches que la
    # SERP ou la sonde n'ont pas mesurées : l'omission n'est qu'une voie sur trois.

    serp_ok = [(e, s) for e, s in paires if s.concurrence_mesuree]
    calibrables = [(e, s) for e, s in serp_ok if s.niche.n_enfants_autocomplete is not None]
    r.n_calibrees = len(calibrables)
    r.n_non_mesurees = len(paires) - len(serp_ok)
    r.n_demande_non_mesuree = len(serp_ok) - len(calibrables)
    # Les DEUX signaux qui ne viennent que de l'enrichissement ASIN (§2.11). Les compter
    # est la seule façon de savoir si la calibration a pu voir ce qu'elle est venue
    # régler : un batch ASIN tombé laisse les scores calculables, donc le Spearman aussi,
    # et rien d'autre dans le rapport ne distinguerait ce run d'un run nominal.
    r.n_part_indie_mesuree = sum(1 for _, s in calibrables if s.part_indie is not None)
    r.n_redevance_mesuree = sum(1 for _, s in calibrables
                                if s.redevance_estimee is not None)
    r.n_pages_mesurees = sum(1 for _, s in calibrables if s.pages_median is not None)
    r.n_verts = sum(1 for _, s in calibrables if _est_vert(s, c))
    scores_bonnes = [s.global_score for e, s in calibrables if e == "bonne"]
    r.meilleur_score_bonne = max(scores_bonnes) if scores_bonnes else None
    if r.n_demande_non_mesuree:
        r.avertissements.append(
            f"{r.n_demande_non_mesuree} requête(s) écartée(s) du calcul : demande non "
            f"mesurée (sonde autocomplete tombée). Leur axe demande repose sur un minimum "
            f"inventé — les corréler mesurerait ce minimum. À relancer.")

    # « Aucune morte en vert » ne se vérifie que sur une morte réellement MESURÉE. Omise,
    # à SERP tombée (« ⚪ à relancer », jamais verte — mais son score n'a jamais vu le
    # rayon) ou à demande non mesurée (score calculé sur un minimum inventé), elle est
    # INDÉCIDABLE : la compter comme « pas en vert » ouvrirait la porte par artefact.
    ids_calibres = {id(s) for _, s in calibrables}
    mortes_indecidables = mortes_non_scorees + [
        s.niche.requete_amazon for e, s in paires
        if e == "morte" and id(s) not in ids_calibres]
    if mortes_indecidables:
        r.avertissements.append(
            f"{len(mortes_indecidables)} requête(s) « morte » NON vérifiable(s) (omise, SERP "
            f"tombée ou demande non mesurée) : " + ", ".join(mortes_indecidables)
            + ". Le critère « aucune morte en vert » est INDÉCIDABLE pour elles, pas "
              "satisfait — porte fermée. " + _RELANCE_TELLE_QUELLE)
    if r.n_non_mesurees:
        r.avertissements.append(
            f"{r.n_non_mesurees} requête(s) écartée(s) du calcul : concurrence non "
            f"mesurée (SERP tombée). Leur score n'a reçu ni bonus ni malus de "
            f"concurrence — les corréler mesurerait du bruit. À relancer.")

    r.spearman = spearman([float(_ORDINAL[e]) for e, _ in calibrables],
                          [s.global_score for _, s in calibrables])

    for etiquette in ETIQUETTES:
        lot = [s for e, s in calibrables if e == etiquette]
        if not lot:
            continue
        r.signaux[etiquette] = {
            "n": len(lot),
            "score": _mediane([s.global_score for s in lot]),
            "part_indie": _mediane([s.part_indie for s in lot]),
            "n_part_indie_mesuree": sum(1 for s in lot if s.part_indie is not None),
            "n_variantes": _mediane([float(s.n_variantes_quasi_identiques) for s in lot]),
            "n_concurrents_cibles": _mediane([float(s.n_concurrents_cibles) for s in lot]),
            "prix_median": _mediane([s.prix_median for s in lot]),
            "redevance": _mediane([s.redevance_estimee for s in lot]),
            "n_redevance_mesuree": sum(1 for s in lot if s.redevance_estimee is not None),
            "bsr_best": _mediane([float(s.bsr_best) for s in lot
                                  if s.bsr_best is not None]),
            "part_bsr_ok": sum(1 for s in lot if s.criteres_bsr_ok) / len(lot),
            # R25 — médianes des QUATRE axes. Le Spearman porte sur le score global : une
            # étiquette peut être mal ordonnée sur un axe et bien placée au total.
            "demande": _mediane([s.demande for s in lot]),
            "penetration": _mediane([s.penetration for s in lot]),
            "rentabilite": _mediane([s.rentabilite for s in lot]),
            "faisabilite": _mediane([s.faisabilite for s in lot]),
            **_compteurs_diagnostic(lot, c),
        }
    if r.signaux:
        r.avertissements.append(
            "diagnostics par étiquette (compteurs de bonus, médianes d'axes) : sans seuil et "
            "sans effet sur la porte. Ne pas régler les seuils BSR ou de demande à partir du "
            "Spearman global : il porte sur le score entier, où pénétration et rentabilité "
            "font aussi descendre « mauvaise ».")

    if familles is not None:
        for f in familles_taxonomie(version):
            r.familles[f] = 0
        for f in familles:
            r.familles[f] = r.familles.get(f, 0) + 1
        maigres = [f for f, n in r.familles.items() if n < MIN_PAR_FAMILLE]
        if maigres:
            r.avertissements.append(
                f"famille(s) sous-représentée(s) (< {MIN_PAR_FAMILLE} requêtes) : "
                f"{', '.join(f'{f} ({r.familles[f]})' for f in maigres)} — la "
                f"calibration ne porte pas sur ces rayons, elle les frôle.")

    if calibrables and not (r.n_part_indie_mesuree and r.n_redevance_mesuree):
        if not r.n_part_indie_mesuree:
            r.avertissements.append(
                f"rayon jamais lu : part indie mesurée sur {r.n_part_indie_mesuree} "
                f"niche(s), redevance sur {r.n_redevance_mesuree}, sur {len(calibrables)} "
                f"calibrable(s). L'enrichissement ASIN n'a rendu aucune fiche exploitable — "
                f"les scores restent calculables (la SERP donne titres, prix et "
                f"concurrents), mais `part_indie_bonne` et `redevance_min_bonne` ne peuvent "
                f"être réglés sur ce run. Le critère est INDÉCIDABLE, pas satisfait — porte "
                f"fermée. " + _RELANCE_TELLE_QUELLE)
        else:
            # Le run 4 : éditeur lu sur 31 niches, redevance sur 0. Les fiches ÉTAIENT là ;
            # c'est leur LECTURE qui manquait la pagination. « Aucune fiche exploitable »
            # faisait chercher une panne d'enrichissement, et « relancer » rachetait le
            # même rapport.
            r.avertissements.append(
                f"redevance jamais calculée : fiches LUES (éditeur mesuré sur "
                f"{r.n_part_indie_mesuree} niche(s), pagination sur {r.n_pages_mesurees}), "
                f"redevance sur {r.n_redevance_mesuree}, sur {len(calibrables)} "
                f"calibrable(s). Cause côté LECTURE (prix ou pagination), pas côté marché : "
                f"à diagnostiquer avant de relancer — relancer rend les mêmes fiches. "
                f"`redevance_min_bonne` ne peut être réglé sur ce run : critère INDÉCIDABLE, "
                f"porte fermée. " + _RELANCE_TELLE_QUELLE)

    # ── Deux conditions de mesure COMPLÈTE (décision de Baptiste, 2026-09-29) ──────────
    # Mesuré au pré-mortem du run 6 sur les entrées réelles du run 5 : un jeu amputé à 10
    # niches sur 46 sortait la porte FRANCHIE avec un Spearman de +0,522, contre +0,462 sur
    # le run complet. Ce sont les « mortes » qui portent le signal (+0,219 sans elles) :
    # l'échec partiel est donc le scénario qui FABRIQUE un faux vert, pas celui qui le
    # dégrade. Et « aucune morte en vert » se vérifiait sur l'ensemble vide dès que les
    # mortes étaient toutes écartées ou non rendues.
    # Les ÉCARTÉES (filtre IP, saisonnier) sortent du dénominateur : elles ne sont pas une
    # mesure ratée mais un gate du PRODUIT, gratuit et voulu, et une décision antérieure dit
    # qu'elles ne ferment pas la porte (§2.14). Une « morte » écartée, elle, reste couverte
    # par la seconde condition ci-dessous.
    n_ecartees = len(r.ecartees_correctement) + len(r.bonnes_perdues_avant_analyse)
    mesure_incomplete = r.n_calibrees < r.n_requetes - n_ecartees
    mortes_scorees = [s.niche.requete_amazon for e, s in calibrables if e == "morte"]
    r.n_mortes_scorees = len(mortes_scorees)
    if mesure_incomplete:
        r.avertissements.append(
            f"mesure INCOMPLÈTE : {r.n_calibrees} niche(s) calibrée(s) sur "
            f"{r.n_requetes - n_ecartees} requête(s) analysable(s) ({r.n_non_mesurees} "
            f"SERP tombée(s), {r.n_demande_non_mesuree} demande(s) non mesurée(s), "
            f"{len(r.non_rendues)} non rendue(s) par le classement ; {n_ecartees} "
            f"écartée(s) avant analyse, hors décompte). Un jeu amputé n'est pas un petit "
            f"jeu : les "
            f"« mortes » portent le signal, donc un run troué rend un Spearman PLUS haut "
            f"qu'un run complet (mesuré : +0,522 sur 10 niches contre +0,462 sur 46). "
            f"Porte INDÉCIDABLE : aucun seuil ne se règle là-dessus.")
    if not mortes_scorees:
        r.avertissements.append(
            "aucune « morte » SCORÉE : le critère « aucune morte en vert » porterait sur "
            "l'ensemble vide. Il est INDÉCIDABLE, pas satisfait (règle 3) — porte fermée.")

    r.porte_franchie = (r.spearman is not None
                        and r.spearman >= SEUIL_SPEARMAN
                        and not r.morts_en_vert
                        and not mortes_indecidables
                        and not mesure_incomplete
                        and bool(mortes_scorees)
                        and bool(r.n_part_indie_mesuree)
                        and bool(r.n_redevance_mesuree))
    # Le conseil « corriger les critères » ne vaut que sur une mesure COMPLÈTE. Un Spearman
    # calculé mais mauvais, alors qu'une « morte » manque, reste indécidable : régler les
    # seuils là-dessus, c'est risquer de les régler sur ce qui manquait. Le premier run réel
    # (2026-09-13, 0 niche calibrée) affichait « corriger data/lowcontent_criteres.json » —
    # un conseil qui, suivi, réglait les seuils sur rien.
    r.porte_indecidable = not r.porte_franchie and (
        r.spearman is None or bool(mortes_indecidables)
        or mesure_incomplete or not mortes_scorees
        or not (r.n_part_indie_mesuree and r.n_redevance_mesuree))
    return r


# ── Rejeu hors ligne des entrées archivées (R26) ───────────────────────────────

def entrees_vers_arguments(entree: dict) -> dict:
    """Une entrée du journal (`run_lowcontent_scout(journal_entrees=…)`) redevient les
    arguments EXACTS de `score_lowcontent`, date comprise : `part_recents` lit la date du
    jour, et un rejeu un autre jour rescorerait autre chose que le run."""
    from models import EnrichedBook, LowContentNiche, NicheValidation, SearchResult
    return dict(
        niche=LowContentNiche.model_validate(entree["niche"]),
        validation=NicheValidation.model_validate(entree["validation"]),
        search=(None if entree.get("search") is None
                else SearchResult.model_validate(entree["search"])),
        livres=[EnrichedBook.model_validate(b) for b in entree.get("livres") or []],
        bsrs=list(entree.get("bsrs") or []),
        bsr_map=dict(entree.get("bsr_map") or {}),
        subcats_map=dict(entree.get("subcats_map") or {}),
        aujourdhui=entree.get("aujourdhui"))


def _liste_entrees(entrees) -> list[dict]:
    return list(entrees.get("entrees") or []) if isinstance(entrees, dict) else list(entrees)


def rescorer_entrees(entrees, criteres: dict | None = None
                     ) -> list[tuple[dict, LowContentScored]]:
    """Rescore chaque niche archivée avec `criteres` (défaut : le fichier courant). Aucun
    fournisseur, aucun modèle, aucun réseau : c'est ce qui rend un réglage de seuil
    essayable sans repayer un run."""
    from lowcontent_scoring import score_lowcontent
    return [(e, score_lowcontent(**entrees_vers_arguments(e), criteres=criteres))
            for e in _liste_entrees(entrees) if e.get("type") == "niche"]


def rejouer_entrees(entrees, criteres: dict | None = None,
                    version: str = "fr_v1") -> RapportCalibration:
    """Le rapport de calibration recalculé sur les entrées archivées.

    **Il ne franchit JAMAIS la porte.** Un seuil réglé en regardant ce jeu-ci, puis validé
    sur ce même jeu, mesure l'ajustement, pas le terrain. La porte que le rejeu AURAIT
    ouverte est dite en avertissement ; la franchir exige un nouveau run payant."""
    if isinstance(entrees, dict):
        version = entrees.get("version") or version
    liste = _liste_entrees(entrees)
    paires, familles = [], []
    for e, s in rescorer_entrees(liste, criteres=criteres):
        if e.get("etiquette") in ETIQUETTES:
            paires.append((e["etiquette"], s))
            familles.append(e.get("famille", ""))
    ecartees = [(e["requete"], e["etiquette"]) for e in liste if e.get("type") == "ecartee"]
    non_rendues = [(e["requete"], e["etiquette"]) for e in liste
                   if e.get("type") == "non_rendue"]
    r = rapport_calibration(paires, familles=familles, ecartees=ecartees,
                            non_rendues=non_rendues, version=version, criteres=criteres)
    aurait_franchi = r.porte_franchie
    r.rejeu, r.porte_franchie, r.porte_indecidable = True, False, True
    r.avertissements.insert(0, (
        "REJEU hors ligne : la porte AURAIT été franchie avec ces critères. Réglés sur ce "
        "jeu même, ils ne s'y valident pas — un nouveau run payant est nécessaire."
        if aurait_franchi else
        "REJEU hors ligne : aucune porte ne se franchit sur le jeu qui a servi à régler "
        "les seuils."))
    return r

