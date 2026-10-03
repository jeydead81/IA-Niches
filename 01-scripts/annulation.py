"""annulation.py — arrêter une analyse en cours, sans tuer de thread.

Une analyse vit dans un thread du serveur (ou dans le worker) : on ne tue pas un thread, on lui
demande de s'arrêter, et il s'arrête à son prochain POINT DE CONTRÔLE. Ce module en est le
mécanisme, sans dépendance :

- `Annulation` est une `BaseException`, jamais une `Exception`. Les moteurs ont des
  `except Exception` « un échec ne coule jamais le run » qui l'avaleraient ; ils RELÈVENT en
  revanche les `BaseException` (Ctrl-C) après avoir imputé le pire cas pour une tâche créée puis
  non lue (scout_master, lowcontent_master, fiction_serp_provider, bsr_source). L'arrêt hérite de
  cette discipline : l'argent déjà engagé reste compté.
- Le contrôle est propre à CHAQUE FIL (`threading.local`) : arrêter une analyse ne touche pas les
  autres, et rien ne passe par les signatures des moteurs.
- `verifier()` est appelé aux endroits où s'arrêter coûte le moins : chaque message de
  progression, avant une phase payante (`CostTracker.verifier`), et à chaque cycle d'attente du
  fournisseur (là où une analyse « tourne dans le vide » passe son temps).
- Un contrôle qui LÈVE (base illisible) ne tue pas l'analyse : elle est payée, on continue.
"""
import threading
import time

_local = threading.local()


class Annulation(BaseException):
    """L'utilisateur a arrêté cette analyse. BaseException : voir le docstring du module."""


def installer(controle) -> None:
    """Installe, POUR CE FIL, la fonction qui dit « il faut s'arrêter » (True) ou non."""
    _local.controle = controle


def retirer() -> None:
    _local.controle = None


def verifier() -> None:
    """Point de contrôle : lève `Annulation` si l'analyse de ce fil a été arrêtée."""
    controle = getattr(_local, "controle", None)
    if controle is None:
        return
    try:
        stop = controle()
    except Exception:  # noqa: BLE001 — une base illisible ne doit pas arrêter une analyse payée
        return
    if stop:
        raise Annulation()


def controle_du_travail(store, job_id: str, intervalle_s: float = 0.5):
    """Le contrôle d'UN travail : lit son statut en base, au plus une fois par `intervalle_s`
    (un point de contrôle peut être appelé des dizaines de fois par seconde). L'arrêt est donc
    effectif au plus une demi-seconde après la demande, au premier point de contrôle atteint."""
    etat = {"vu": 0.0, "stop": False}

    def controle() -> bool:
        if etat["stop"]:
            return True
        maintenant = time.monotonic()
        if maintenant - etat["vu"] >= intervalle_s:
            etat["vu"] = maintenant
            etat["stop"] = bool(store.est_annule(job_id))
        return etat["stop"]
    return controle
