"""progression_publique.py — ce que la progression d'un travail montre à l'UTILISATEUR.

Les moteurs écrivent des messages pour qui développe : « 0/19 fiche(s) servie(s) par le cache »,
« (6 économisé(s) par dédup inter-niches) »… Ils disent COMMENT le produit est construit —
mutualisation entre comptes, déduplication —, et donc comment il gagne sa marge. Décision de
Baptiste (2026-10-03) : l'utilisateur n'a pas à le savoir.

Le filtre vit à la FRONTIÈRE client (lecture d'un travail, flux SSE), pas dans les moteurs :
- le brut reste dans `jobs.db` et dans la CLI. C'est un diagnostic : après un correctif de
  parseur, la ligne « N/M fiche(s) servie(s) par le cache » est l'alerte qui dit que des fiches
  mal lues sont resservies à tous les comptes (CLAUDE.md §5.38) ;
- il couvre aussi les travaux enregistrés AVANT son introduction ;
- une phrase qui parle du RÉSULTAT (compte refusé, niche écartée, rayon amputé) n'est jamais
  supprimée : on n'en retire que la mention du mécanisme.

Deuxième rôle, même frontière : MASQUER le fournisseur et le jargon technique (« DataForSEO »,
« SERP », « ASIN », « batch », la raison brute d'un refus du fournisseur, une URL…). L'utilisateur
n'a pas à les lire (décision de Baptiste, 2026-10-03 ; c'était la R30 du CLAUDE.md). Les lignes
que l'on sait réécrire le sont en phrase claire ; le reste passe par des remplacements de termes.
Un test lit TOUS les messages `progress(...)` des moteurs dans leur source : un message ajouté
demain ne laisse pas passer un nom de fournisseur sans que ce test casse.

PUR : aucune dépendance, aucun accès disque.
"""
import re

# Lignes qui ne parlent QUE du mécanisme : retirées entières.
_ABSENTS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"servie\(s\) par le\s+cache",
    r"repris du cache",
    r"déjà classée\(s\)",
    r"non mis(?:e)? en cache",
    r"non écrite\(s\) en\s+cache",
))

# Une parenthèse, avec UN niveau d'imbrication : « (0 économisé(s) par dédup inter-niches) ».
_PAREN = r"\((?:[^()]|\([^()]*\))*"

# Mentions du mécanisme DANS une phrase qui garde son sens : on retire la mention.
_RETRAITS = tuple((re.compile(p, re.IGNORECASE), "") for p in (
    r"\s*" + _PAREN + r"dédup" + r"(?:[^()]|\([^()]*\))*\)",
    r"\s*" + _PAREN + r"par le cache" + r"(?:[^()]|\([^()]*\))*\)",
    r",\s*cache seul",
    r",\s*rien n'a été mis en cache pour elles",
    r"\s*—\s*ni envoyés, ni facturés",
))

# Lignes entières réécrites en phrase claire. Premier motif qui correspond. `\1` rend
# l'indentation d'origine : l'interface s'en sert pour distinguer un avertissement d'une étape.
_REECRITURES = tuple((re.compile(p, re.IGNORECASE | re.DOTALL), r) for p, r in (
    (r"^(\s*)⚠ (\d+ niche\(s\) non mesurée\(s\)) : compte DataForSEO refusé.*$",
     r"\1⚠ \2 : service de données indisponible."),
    (r"^(\s*)⚠ échec SERP sur (« [^»]*») : .*? — niche écartée.*$",
     r"\1⚠ recherche impossible sur \2 : niche écartée."),
    (r"^(\s*)⚠ search échec \(.*\) — (niche scorée sans concurrence\.)$",
     r"\1⚠ recherche indisponible — \2"),
    (r"^(\s*)⚠ .*plus aucun appel au fournisseur.*$",
     r"\1⚠ Service de données indisponible : les niches restantes ne seront pas mesurées."),
    (r"^(\s*)⚠ (\d+) ASIN non envoyés : lot refusé.*$",
     r"\1⚠ \2 fiche(s) non demandée(s) : le service de données a refusé la demande."),
    (r"^(\s*)⚠ (\d+) ASIN non relus : l'envoi du lot a levé.*$",
     r"\1⚠ \2 fiche(s) non lue(s) : le service de données n'a pas répondu."),
    (r"^(\s*)⚠ \d+ relecture\(s\) de résultat illisible.*$",
     r"\1⚠ Certaines lectures ont dû être relancées automatiquement."),
    (r"^(\s*)⚠ .* — BSR non récupérés, niches scorées sans classement\.$",
     r"\1⚠ Classements de vente non récupérés : limite de l'analyse atteinte, niches notées sans classement."),
    (r"^(\s*)⚠ plafond de coût atteint : (\d+) ASIN non envoyés.*$",
     r"\1⚠ Limite de l'analyse atteinte : \2 fiche(s) non lue(s)."),
    (r"^(\s*)⚠ (\d+/\d+) livres à la réponse illisible.*$",
     r"\1⚠ \2 livres non classés : la réponse de l'IA les concernant était illisible."),
    (r"^\[(\d+)/(\d+)\] SERP ", r"[\1/\2] Recherche "),
    (r"(\d+) ASIN uniques en UN seul batch", r"\1 fiches livres en un seul lot"),
    (r"compte DataForSEO refusé", "accès au service de données refusé"),
    (r"réponse tronquée \(max_tokens\)", "réponse de l'IA coupée"),
))

# Termes techniques isolés : remplacés partout, y compris dans une erreur de travail.
_TERMES = tuple((re.compile(p, re.IGNORECASE), r) for p, r in (
    (r"https?://\S+", ""),
    (r"DataForSEO", "service de données"),
    (r"fournisseur", "service de données"),
    (r"plafond de coût atteint", "limite de l'analyse atteinte"),
    (r"\bSERP\b", "recherche"),
    (r"\bASIN non enrichis\b", "fiche(s) non lue(s)"),
    (r"\bASIN\b", "fiche(s)"),
    (r"\bbatch\b", "lot"),
    (r"\(max_tokens\)|max_tokens", ""),
    (r"\ble modèle\b", "l'IA"),
    (r"\btask_post\b", "demande"),
    (r"\bpayload\b", "réponse"),
    (r"\bpoll\b", "attente"),
))


def texte_public(texte):
    """Un texte quelconque destiné au client (erreur d'un travail…), sans fournisseur ni jargon.
    None reste None. Ne supprime jamais le texte : seuls les termes sont remplacés."""
    if not isinstance(texte, str):
        return texte
    for motif, remplacement in _TERMES:
        texte = motif.sub(remplacement, texte)
    return texte


def message_public(msg) -> str | None:
    """Le message tel que l'utilisateur peut le lire, ou None s'il n'a pas à le voir."""
    if not isinstance(msg, str):
        return None
    if any(r.search(msg) for r in _ABSENTS):
        return None
    for motif, remplacement in _RETRAITS:
        msg = motif.sub(remplacement, msg)
    for motif, remplacement in _REECRITURES:
        if motif.search(msg):
            msg = motif.sub(remplacement, msg)
            break
    return texte_public(msg)


def liste_publique(messages) -> list[str]:
    """La progression d'un travail pour un client : même ordre, sans les mentions du
    mécanisme ni le jargon. Ne modifie pas la liste reçue."""
    out = []
    for m in messages or []:
        pub = message_public(m)
        if pub is not None:
            out.append(pub)
    return out
