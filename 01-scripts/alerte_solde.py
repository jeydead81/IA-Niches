"""alerte_solde.py — prévenir l'exploitant quand le compte du fournisseur de données se vide.

Le contrôle de solde avant lancement (`server._verifier_solde`) refuse un run quand le compte ne
couvre pas ses recherches : le CLIENT lit « service momentanément indisponible », l'exploitant ne lit
rien. Le compte DataForSEO se recharge à la main (le dépôt n'a, et ne doit avoir, aucun moyen de
payer) : sans alerte, la première nouvelle d'un compte vide est un abonné qui ne peut plus rien
lancer — et DataForSEO est l'unique fournisseur de ce produit.

Cinq règles, dans l'ordre de ce qu'elles coûteraient si on les cassait :

1. **Un solde illisible n'est pas un solde bas** (règle 3 du dépôt) : aucune alerte sur `None`.
2. **Une alerte par jour au plus.** Un compte qui reste bas ne doit pas remplir une boîte à chaque
   run. La marque vit dans le cache partagé (`df-cache.db`) pour survivre à un redémarrage — sur un
   hébergeur chaque mise en ligne en est un. Une RECHARGE (solde revenu au-dessus du seuil) efface la
   marque : le prochain creux est signalé tout de suite, pas après un délai posé pour la crise d'avant.
3. **Sans destinataire rien ne part, et on le DIT** (journal) : ne pas laisser croire que l'alerte est
   câblée. Aucune marque n'est alors posée, pour que définir `ALERTE_SOLDE_EMAIL` plus tard déclenche
   l'alerte au contrôle suivant.
4. **Un envoi qui échoue sera retenté** au contrôle suivant (aucune marque).
5. **Le message ne porte que le solde et le seuil** : ni identifiant, ni clé, ni donnée d'un client.

Fonction pure côté décision : le cache, l'envoi et le journal sont injectés (§2.10).
"""
import os

SEUIL_DEFAUT_USD = 5.0
INTERVALLE_S = 24 * 3600
_CLE = "alerte:solde"


def seuil_usd() -> float:
    """Le seuil en dollars (`ALERTE_SOLDE_USD`, défaut 5). Une valeur illisible, nulle ou négative
    retombe sur le défaut : un seuil absurde ne doit ni désactiver l'alerte ni la déclencher en
    permanence."""
    try:
        v = float((os.getenv("ALERTE_SOLDE_USD") or "").strip())
    except ValueError:
        return SEUIL_DEFAUT_USD
    return v if v > 0 else SEUIL_DEFAUT_USD


def destinataire() -> str | None:
    """L'adresse qui reçoit l'alerte (`ALERTE_SOLDE_EMAIL`), ou None."""
    return (os.getenv("ALERTE_SOLDE_EMAIL") or "").strip() or None


def _montant(v: float) -> str:
    return f"{v:.2f}".replace(".", ",") + " $"


def _message(solde: float, seuil: float) -> tuple[str, str]:
    sujet = f"IA-Niches : solde DataForSEO bas ({_montant(solde)})"
    corps = "\n".join([
        f"Le solde du compte DataForSEO est de {_montant(solde)}, sous le seuil d'alerte de "
        f"{_montant(seuil)}.",
        "",
        "Quand il ne couvre plus les recherches d'une analyse, le service refuse de la lancer et "
        "répond aux clients « momentanément indisponible » (rien n'est décompté). Rechargez le "
        "compte sur app.dataforseo.com.",
        "",
        "Ce message n'est envoyé qu'une fois par 24 heures, et de nouveau après une recharge si le "
        "solde retombe sous le seuil.",
        "",
        "IA-Niches"])
    return sujet, corps


def verifier_et_alerter(solde, cache, envoyer, journal) -> str:
    """Décide et, au besoin, envoie. Rend l'issue :

    `illisible` (solde None) · `ok` (au-dessus du seuil) · `deja_alerte` (marque du jour) ·
    `sans_destinataire` · `envoye` · `echec_envoi`. Ne lève jamais : une alerte qui casse ne doit pas
    faire échouer ce qui l'appelle (la fin d'un run, le contrôle avant lancement)."""
    if solde is None:
        return "illisible"
    seuil = seuil_usd()
    try:
        if solde >= seuil:
            if cache.get(_CLE) is not None:
                cache.set(_CLE, {"efface": True}, 1)         # recharge : le prochain creux réalerte
            return "ok"
        if cache.get(_CLE) is not None:
            return "deja_alerte"
        dest = destinataire()
        if dest is None:
            journal.error("solde du fournisseur BAS (%s, seuil %s) et aucun destinataire : définir "
                          "ALERTE_SOLDE_EMAIL pour être prévenu par e-mail.",
                          _montant(solde), _montant(seuil))
            return "sans_destinataire"
        sujet, corps = _message(solde, seuil)
        try:
            ok = bool(envoyer(dest, sujet, corps))
        except Exception as e:  # noqa: BLE001 — voir docstring
            journal.error("alerte de solde non envoyée (%s)", type(e).__name__)
            return "echec_envoi"
        if not ok:
            journal.error("alerte de solde non envoyée : le serveur de courriel a refusé")
            return "echec_envoi"
        cache.set(_CLE, {"solde": solde}, INTERVALLE_S)
        return "envoye"
    except Exception as e:  # noqa: BLE001 — voir docstring
        journal.error("contrôle d'alerte de solde impossible (%s)", type(e).__name__)
        return "echec_envoi"
