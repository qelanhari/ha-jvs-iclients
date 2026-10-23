"""Flux de configuration : choix du portail, identifiants, contrat, réauthentification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import (
    Contract,
    JvsApiIdNotFound,
    JvsAuthError,
    JvsIclientsClient,
    JvsPortalError,
    discover_api_id,
)
from .const import (
    CONF_API_ID,
    CONF_BASE_URL,
    CONF_CONTRACT_ID,
    CONF_CONTRACT_NUMBER,
    CONF_PROVIDER,
    DOMAIN,
    PROVIDER_CUSTOM,
    PROVIDERS,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PROVIDER, default=next(iter(PROVIDERS))): SelectSelector(
            SelectSelectorConfig(
                options=[*PROVIDERS, PROVIDER_CUSTOM],
                mode=SelectSelectorMode.DROPDOWN,
                translation_key=CONF_PROVIDER,
            )
        ),
        vol.Optional(CONF_BASE_URL): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)
STEP_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class InvalidUrl(ValueError):
    """URL de portail invalide."""


def normalize_url(raw: str | None) -> str:
    """Valide et normalise l'URL d'un portail personnalisé."""
    url = (raw or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise InvalidUrl(raw or "")
    return f"{parsed.scheme}://{parsed.netloc}"


async def resolve_portal(
    hass: HomeAssistant, provider: str, raw_url: str | None
) -> tuple[str, str]:
    """Renvoie (base_url, api_id) : préréglage ou URL libre, Api-Id détecté dans le bundle."""
    session = async_create_clientsession(hass)
    if provider == PROVIDER_CUSTOM:
        base_url = normalize_url(raw_url)
        return base_url, await discover_api_id(session, base_url)
    preset = PROVIDERS[provider]
    try:
        return preset[CONF_BASE_URL], await discover_api_id(session, preset[CONF_BASE_URL])
    except JvsApiIdNotFound:
        return preset[CONF_BASE_URL], preset[CONF_API_ID]


async def validate_credentials(
    hass: HomeAssistant, base_url: str, api_id: str, username: str, password: str
) -> list[Contract]:
    """Tente le login et renvoie les contrats actifs."""
    client = JvsIclientsClient(
        async_create_clientsession(hass), base_url, api_id, username, password
    )
    await client.authenticate()
    return [c for c in await client.contracts() if c.active]


def _error_key(err: Exception) -> str:
    if isinstance(err, InvalidUrl):
        return "invalid_url"
    if isinstance(err, JvsAuthError):
        return "invalid_auth"
    if isinstance(err, JvsApiIdNotFound):
        return "api_id_not_found"
    return "cannot_connect"


class JvsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Flux de configuration de l'intégration."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._contracts: list[Contract] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Portail + identifiants."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                return await self._async_handle_user(user_input)
            except (InvalidUrl, JvsPortalError) as err:
                errors["base"] = _error_key(err)
        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    async def _async_handle_user(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        base_url, api_id = await resolve_portal(
            self.hass, user_input[CONF_PROVIDER], user_input.get(CONF_BASE_URL)
        )
        username, password = user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
        contracts = await validate_credentials(self.hass, base_url, api_id, username, password)
        if not contracts:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_SCHEMA, errors={"base": "no_contract"}
            )
        self._data = {
            CONF_PROVIDER: user_input[CONF_PROVIDER],
            CONF_BASE_URL: base_url,
            CONF_API_ID: api_id,
            CONF_USERNAME: username,
            CONF_PASSWORD: password,
        }
        self._contracts = contracts
        if len(contracts) == 1:
            return await self._async_create(contracts[0])
        return await self.async_step_contract()

    async def async_step_contract(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choix du contrat quand le compte en a plusieurs."""
        if user_input is not None:
            contract = next(c for c in self._contracts if c.id == user_input[CONF_CONTRACT_ID])
            return await self._async_create(contract)
        options = {
            c.id: f"{c.number}{' (principal)' if c.principal else ''}" for c in self._contracts
        }
        schema = vol.Schema({vol.Required(CONF_CONTRACT_ID): vol.In(options)})
        return self.async_show_form(step_id="contract", data_schema=schema)

    async def _async_create(self, contract: Contract) -> ConfigFlowResult:
        host = urlparse(self._data[CONF_BASE_URL]).netloc
        await self.async_set_unique_id(f"{host}:{self._data[CONF_USERNAME]}:{contract.id}")
        self._abort_if_unique_id_configured()
        provider = self._data[CONF_PROVIDER]
        label = PROVIDERS[provider]["name"] if provider in PROVIDERS else host
        return self.async_create_entry(
            title=f"{label} – contrat {contract.number}",
            data={
                **self._data,
                CONF_CONTRACT_ID: contract.id,
                CONF_CONTRACT_NUMBER: contract.number,
            },
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Déclenché quand le portail refuse les identifiants."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Nouveau mot de passe."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await validate_credentials(
                    self.hass,
                    entry.data[CONF_BASE_URL],
                    entry.data[CONF_API_ID],
                    entry.data[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except JvsPortalError as err:
                errors["base"] = _error_key(err)
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={CONF_USERNAME: entry.data[CONF_USERNAME]},
        )
