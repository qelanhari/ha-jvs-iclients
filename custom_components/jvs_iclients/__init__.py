"""Intégration Portail abonnés eau JVS-Mairistem (iclients)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import Contract, JvsIclientsClient
from .const import CONF_API_ID, CONF_BASE_URL, CONF_CONTRACT_ID, CONF_CONTRACT_NUMBER
from .coordinator import JvsCoordinator

PLATFORMS = [Platform.SENSOR]

type JvsConfigEntry = ConfigEntry[JvsCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: JvsConfigEntry) -> bool:
    """Crée le client et le coordinateur, puis les plateformes."""
    client = JvsIclientsClient(
        async_create_clientsession(hass),
        entry.data[CONF_BASE_URL],
        entry.data[CONF_API_ID],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    contract = Contract(
        id=entry.data[CONF_CONTRACT_ID],
        number=entry.data[CONF_CONTRACT_NUMBER],
        active=True,
        principal=True,
    )
    coordinator = JvsCoordinator(hass, entry, client, contract, entry.data[CONF_BASE_URL])
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: JvsConfigEntry) -> bool:
    """Décharge les plateformes."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
