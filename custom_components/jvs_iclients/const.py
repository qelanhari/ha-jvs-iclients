"""Constantes de l'intégration JVS iclients."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "jvs_iclients"

CONF_PROVIDER = "provider"
CONF_BASE_URL = "base_url"
CONF_API_ID = "api_id"
CONF_CONTRACT_ID = "contract_id"
CONF_CONTRACT_NUMBER = "contract_number"

PROVIDER_CUSTOM = "custom"

# Préréglages : url du portail et Api-Id connu (utilisé si la détection automatique échoue).
PROVIDERS: dict[str, dict[str, str]] = {
    "eaudupic": {
        "name": "Eau du Pic (Grand Pic Saint-Loup)",
        CONF_BASE_URL: "https://eaudupic.client.ccgpsl.fr",
        CONF_API_ID: "d2e3b03552d0e10cfa2a5e1e9e3dc73b@iclients-35664-picsaintloup",
    },
}

# Heures locales des relances quotidiennes (les relevés arrivent avec 1 à 2 jours de retard).
POLL_HOURS: tuple[int, ...] = (8, 16)
# Délai avant nouvel essai après un refus d'authentification ou une erreur du portail.
AUTH_RETRY_DELAY = timedelta(hours=1)
# Fenêtre réimportée à chaque rafraîchissement (les relevés arrivent avec 1 à 2 jours de retard).
REFRESH_WINDOW_DAYS = 7
# Historique récupéré au premier import.
INITIAL_HISTORY_DAYS = 730
