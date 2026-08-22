"""notification.py — prévenir l'auteur quand son analyse est finie, sans la lui envoyer.

Un run dure de deux à douze minutes. L'interface le reprend au rechargement
(`reprendreTravail`), mais elle ne peut rien faire quand l'onglet est fermé — et c'est
justement ce qu'on invite l'utilisateur à faire. Le message de fin est la seule chose qui
traverse l'absence.

Quatre règles, dans l'ordre de ce qu'elles coûteraient si on les cassait :

1. **Un échec d'envoi ne fait jamais échouer un run.** Le run a coûté de l'argent réel,
   son résultat est en base et l'unité de plafond est consommée. Le marquer « en échec »
   parce qu'un serveur SMTP a refusé la connexion effacerait de l'écran un travail payé et
   réussi (§5.29). `envoyer` rend un booléen et ne lève jamais.
2. **Aucun résultat dans le corps.** L'e-mail est un canal en clair, relayé, archivé et
   indexé chez le fournisseur du destinataire. Les niches trouvées sont exactement ce que
   l'auteur a payé pour être seul à savoir : les recopier dans un e-mail les publierait
   chez un tiers. Le message dit qu'une analyse est prête et où la lire, rien d'autre.
3. **Aucun secret dans les journaux.** Le mot de passe SMTP est lu du `.env` et
   `_assainir` le retire de toute ligne journalisée : une exception de bibliothèque porte
   régulièrement la ligne d'authentification entière (règle 6). Même famille de défaut que
   `_erreur_publique` côté serveur — un secret peut fuir sans qu'aucune ligne du code
   n'ait « logué un secret ».
4. **Éteint par défaut.** Il faut `NOTIFICATIONS_EMAIL` ET un `SMTP_HOST`. Une
   configuration à moitié faite n'envoie pas « au mieux » : elle n'envoie pas. Sinon
   l'exploitant croit avoir activé les messages et personne ne les reçoit.

Aucune dépendance ajoutée : `smtplib` et `email.message` sont dans la bibliothèque
standard, comme `hashlib.scrypt` pour l'authentification.
"""
from __future__ import annotations

import os
from email.message import EmailMessage

from pydantic import BaseModel

PORT_DEFAUT = 587          # soumission avec STARTTLS

_LIBELLES = {
    "scout": "Analyse non-fiction",
    "fiction": "Analyse fiction",
    "lowcontent": "Analyse low-content",
}


class ConfigSMTP(BaseModel):
    model_config = {"frozen": True}
    hote: str
    port: int = PORT_DEFAUT
    utilisateur: str = ""
    mot_de_passe: str = ""
    expediteur: str = ""
    tls: bool = True


def _vrai(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "oui")


def config_smtp() -> ConfigSMTP | None:
    """`None` tant que les DEUX conditions ne sont pas réunies : le drapeau et l'hôte.

    Poser un hôte SMTP dans le `.env` n'est pas consentir à écrire aux utilisateurs, et
    poser le drapeau sans hôte n'est pas une configuration."""
    if not _vrai(os.getenv("NOTIFICATIONS_EMAIL")):
        return None
    hote = (os.getenv("SMTP_HOST") or "").strip()
    if not hote:
        return None
    try:
        port = int(os.getenv("SMTP_PORT") or PORT_DEFAUT)
    except ValueError:
        # Même discipline que `PORT` et `DATAFORSEO_PRIORITY` : une valeur illisible ne
        # doit pas empêcher le service de démarrer.
        port = PORT_DEFAUT
    utilisateur = (os.getenv("SMTP_USER") or "").strip()
    return ConfigSMTP(
        hote=hote, port=port, utilisateur=utilisateur,
        mot_de_passe=os.getenv("SMTP_PASSWORD") or "",
        expediteur=(os.getenv("SMTP_FROM") or utilisateur).strip(),
        tls=_vrai(os.getenv("SMTP_TLS") or "1"))


def corps_fin_de_job(type_: str, statut: str, job_id: str, base_url: str | None = None,
                     erreur: str | None = None, resultat=None,
                     cout_usd: float | None = None) -> tuple[str, str]:
    """Rend (sujet, corps). `resultat` et `cout_usd` sont acceptés et **ignorés**.

    Ils figurent dans la signature exprès : les appelants les ont sous la main au moment
    d'appeler, et un paramètre absent invite à « juste ajouter le top 3 dans le mail ».
    Le paramètre présent et documenté dit que la décision a été prise et pourquoi
    (règle 2 du module, et §5.27 pour le coût)."""
    libelle = _LIBELLES.get(type_, "Analyse")
    if statut == "echec":
        sujet = f"{libelle} — interrompue"
        lignes = [
            f"Votre {libelle.lower()} s'est interrompue avant la fin.",
            "",
            "Les sources qui ont répondu ont été conservées : ouvrez l'analyse pour "
            "voir ce qui a été mesuré et ce qui ne l'a pas été.",
        ]
        # L'erreur interne n'est JAMAIS recopiée : elle peut porter l'URL DataForSEO,
        # donc les identifiants HTTP Basic. La référence de l'analyse suffit à la
        # retrouver côté journal.
    else:
        sujet = f"{libelle} — prête"
        lignes = [f"Votre {libelle.lower()} est terminée.", ""]
    lignes.append(f"Référence : {job_id}")
    if base_url:
        lignes += ["", f"Ouvrir : {base_url.rstrip('/')}/"]
    else:
        # Rien dans le code ne connaît le nom de domaine : il n'y a pas de déploiement.
        # Annoncer un lien mort serait pire que ne pas en mettre.
        lignes += ["", "Retrouvez-la dans « Mes analyses »."]
    lignes += ["", "— IA-Niches"]
    return sujet, "\n".join(lignes)


class Notificateur:
    """Instance par appel, jamais à l'import (§5.20) : la configuration est relue à chaque
    envoi, et aucun socket n'est ouvert tant que rien n'est envoyé."""

    def __init__(self, smtp_factory=None, journal=None, config: ConfigSMTP | None = None):
        self._factory = smtp_factory
        self._journal = journal or (lambda _m: None)
        self._config = config

    def _assainir(self, texte: str) -> str:
        """Retire le mot de passe de toute ligne journalisée. Une exception de
        bibliothèque porte régulièrement la ligne d'authentification entière."""
        c = self._config
        mdp = (c.mot_de_passe if c else "") or ""
        return texte.replace(mdp, "***") if mdp else texte

    def envoyer(self, destinataire: str, sujet: str, corps: str) -> bool:
        """Rend True si le message est parti. **Ne lève jamais** — voir règle 1."""
        destinataire = (destinataire or "").strip()
        if not destinataire:
            return False
        self._config = self._config or config_smtp()
        c = self._config
        if c is None:
            return False

        factory = self._factory
        if factory is None:                       # pragma: no cover — réseau réel
            import smtplib
            factory = smtplib.SMTP

        msg = EmailMessage()
        msg["From"] = c.expediteur or c.utilisateur
        msg["To"] = destinataire
        msg["Subject"] = sujet
        # `Auto-Submitted` évite qu'un répondeur automatique du destinataire réponde à
        # l'adresse d'envoi et alimente une boucle.
        msg["Auto-Submitted"] = "auto-generated"
        msg.set_content(corps)

        try:
            with factory(c.hote, c.port, timeout=20) as s:
                if c.tls:
                    s.starttls()
                if c.utilisateur:
                    s.login(c.utilisateur, c.mot_de_passe)
                s.send_message(msg)
            return True
        except Exception as e:                    # noqa: BLE001 — voir règle 1
            self._journal(f"[notification] envoi impossible ({type(e).__name__}) : "
                          f"{self._assainir(str(e))}")
            return False


def notifier_fin_de_job(email: str | None, type_: str, statut: str, job_id: str,
                        notificateur: Notificateur | None = None,
                        journal=None, **ignores) -> bool:
    """Point d'appel unique, partagé par les DEUX exécuteurs de job.

    Le serveur exécute les jobs dans un thread, `worker.py` dans un pool selon
    `JOBS_MODE`. Ne brancher la notification que sur un des deux la rendrait dépendante
    d'une variable d'environnement — la divergence exacte qui a coûté la suppression des
    endpoints doubles (§7) — et elle serait invisible : rien à l'écran ne distingue
    « pas de message » de « message pas envoyé ».

    `**ignores` absorbe `resultat`, `cout_usd`, `erreur` : voir `corps_fin_de_job`."""
    try:
        n = notificateur or Notificateur(journal=journal)
        sujet, corps = corps_fin_de_job(
            type_=type_, statut=statut, job_id=job_id,
            base_url=(os.getenv("BASE_URL") or "").strip() or None)
        return n.envoyer(email or "", sujet, corps)
    except Exception as e:                        # noqa: BLE001 — voir règle 1
        (journal or (lambda _m: None))(
            f"[notification] ignorée ({type(e).__name__})")
        return False
