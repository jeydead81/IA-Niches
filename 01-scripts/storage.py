"""storage.py — source unique du répertoire où vivent les cinq bases SQLite.

Le chemin était écrit à quatre endroits : les quatre constantes de `web/server.py` et le
`df-cache.db` construit à l'identique par les trois orchestrateurs. Tant que tout tourne
sur le poste de Baptiste, cette duplication ne coûte rien — le dossier est le même pour
tout le monde. Elle devient dangereuse au moment exact où l'on héberge : il suffit d'un
seul chemin oublié pour qu'une base reparte sur le disque éphémère du conteneur pendant
que les autres suivent le volume. Et la plus discrète est la pire — `df-cache.db` perdu ne
lève rien, ne s'affiche nulle part, et fait simplement repayer à tout le monde ce qui
était déjà acheté.

**Pourquoi une LEVÉE et pas un défaut, en production.** Partout ailleurs dans ce dépôt, un
réglage oublié retombe sur une valeur prudente : `_cookie_securise` déduit du protocole,
`_plafond_analyses_mensuel` retombe sur illimité-mais-journalisé. Ici c'est impossible.
Le disque d'un conteneur est effacé à chaque déploiement, et un déploiement, sur une
plateforme moderne, c'est un `git push`. Sans volume, le service redémarre sur des bases
VIDES et se comporte exactement comme une installation neuve : plus aucun compte, plus
aucune consommation — donc le plafond mensuel repart de zéro et la base de la future
facturation est perdue —, plus aucune antériorité d'historique. Rien ne le signale : le
premier visiteur crée le « premier compte », l'amorçage joue, et tout a l'air normal.

C'est la règle 3 appliquée au stockage : un répertoire vide ne doit jamais pouvoir se
lire comme « pas encore de client ». On refuse donc de démarrer, comme
`_verifier_config_prod` refuse de démarrer sur un `BSR_SOURCE` intenable — s'en apercevoir
au premier client perdu arriverait beaucoup trop tard.

En local, rien ne change : `DATA_DIR` absent = `99-logs/`, le dossier historique.
"""
import os
from pathlib import Path

_RACINE = Path(__file__).resolve().parent.parent
DOSSIER_PAR_DEFAUT = _RACINE / "99-logs"


def _en_production() -> bool:
    """Même lecture qu'`_verifier_config_prod` côté serveur. Lue à CHAQUE appel et non
    figée à l'import : une constante d'import serait intestable et surtout impossible à
    corriger sans redémarrer (§5.20, §5.21)."""
    return (os.getenv("APP_ENV") or "").strip().lower() == "prod"


def data_dir() -> Path:
    """Le répertoire des bases, créé s'il manque.

    Créé et pas seulement calculé : un volume fraîchement monté est vide, et laisser la
    première écriture échouer ferait rater la première inscription — sur une installation
    neuve, c'est-à-dire au pire moment possible."""
    brut = (os.getenv("DATA_DIR") or "").strip()
    if not brut:
        if _en_production():
            raise RuntimeError(
                "APP_ENV=prod exige DATA_DIR — le chemin d'un volume PERSISTANT. "
                "Le disque d'un conteneur est effacé à chaque déploiement : sans volume, "
                "comptes.db, usage.db, history.db, jobs.db et df-cache.db disparaissent "
                "au prochain push. Les comptes clients, la consommation qui porte le "
                "plafond et la future facturation, l'antériorité de l'historique, et le "
                "cache mutualisé. Et rien ne le dirait : le service repartirait sur des "
                "bases vides en se comportant comme une installation neuve.")
        chemin = DOSSIER_PAR_DEFAUT
    else:
        chemin = Path(brut)
    chemin.mkdir(parents=True, exist_ok=True)
    return chemin


def base(nom: str) -> Path:
    """Chemin d'une base par son nom de fichier. Les appelants nomment ce qu'ils veulent
    ouvrir, jamais où ça se trouve."""
    return data_dir() / nom
