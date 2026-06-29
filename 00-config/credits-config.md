# Configuration crédits Scrapingdog

## Plafonds et comportements

MAX_CREDITS_PER_RUN = 400
MAX_RETRIES_PER_REQUEST = 1
RETRY_DELAY_SECONDS = 5
DRY_RUN_FIRST_LAUNCH = False

## Notes

- MAX_CREDITS_PER_RUN : nombre maximum de crédits Scrapingdog autorisés par run de scout.
  Le script s'arrête net si ce plafond est atteint et génère un rapport partiel.
  Modifier cette valeur si tu veux autoriser plus de crédits par run (ex : 100 pour une analyse plus large).

- MAX_RETRIES_PER_REQUEST : nombre de tentatives en cas d'échec d'une requête.
  Ne pas dépasser 1 pour éviter les boucles coûteuses.

- RETRY_DELAY_SECONDS : délai en secondes entre deux tentatives.
  Ne pas descendre en dessous de 5.

- DRY_RUN_FIRST_LAUNCH : si True, le premier run fait 1 seule requête de test
  avant de demander confirmation pour le scout complet.
  Passer à False une fois que tu as confirmé que la clé API fonctionne.

## Plan tarifaire de référence

- Free tier Scrapingdog : 1 000 crédits offerts
- 1 requête autocomplete Amazon = 1 crédit
- 1 requête search Amazon = 1 crédit
- Requête Google via Scrapingdog = 5 crédits (À ÉVITER — on utilise Google Trends gratuit)
- Rechargement : voir https://scrapingdog.com/pricing
