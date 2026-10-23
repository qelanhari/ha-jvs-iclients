"""Tests du flux de configuration."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_mock import MockerFixture

from custom_components.jvs_iclients import config_flow
from custom_components.jvs_iclients.api import (
    Contract,
    JvsApiIdNotFound,
    JvsAuthError,
    JvsPortalError,
)
from custom_components.jvs_iclients.const import (
    CONF_API_ID,
    CONF_BASE_URL,
    CONF_CONTRACT_ID,
    CONF_CONTRACT_NUMBER,
    CONF_PROVIDER,
    DOMAIN,
)

from .conftest import API_ID, BASE_URL

USER_INPUT = {CONF_PROVIDER: "eaudupic", CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}
MAIN = Contract(id="5288", number="340400867", active=True, principal=True)
SECOND = Contract(id="9999", number="340400999", active=True, principal=False)


@pytest.fixture
def portal(mocker: MockerFixture) -> None:
    mocker.patch.object(config_flow, "resolve_portal", return_value=(BASE_URL, API_ID))


@pytest.fixture
def credentials(mocker: MockerFixture) -> None:
    mocker.patch.object(config_flow, "validate_credentials", return_value=[MAIN])


async def start_user_flow(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    return result["flow_id"]


@pytest.mark.usefixtures("portal", "credentials")
async def test_user_flow_single_contract_creates_entry(hass: HomeAssistant) -> None:
    flow_id = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Eau du Pic (Grand Pic Saint-Loup) – contrat 340400867"
    assert result["data"] == {
        **USER_INPUT,
        CONF_BASE_URL: BASE_URL,
        CONF_API_ID: API_ID,
        CONF_CONTRACT_ID: "5288",
        CONF_CONTRACT_NUMBER: "340400867",
    }


@pytest.mark.usefixtures("portal")
async def test_user_flow_multiple_contracts_asks_which(
    hass: HomeAssistant, mocker: MockerFixture
) -> None:
    mocker.patch.object(config_flow, "validate_credentials", return_value=[MAIN, SECOND])
    flow_id = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "contract"
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_CONTRACT_ID: "9999"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CONTRACT_NUMBER] == "340400999"


@pytest.mark.usefixtures("portal")
async def test_user_flow_no_active_contract_shows_error(
    hass: HomeAssistant, mocker: MockerFixture
) -> None:
    mocker.patch.object(config_flow, "validate_credentials", return_value=[])
    flow_id = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_contract"}


@pytest.mark.usefixtures("portal")
@pytest.mark.parametrize(
    ("exc", "error"),
    [
        (JvsAuthError("no"), "invalid_auth"),
        (JvsApiIdNotFound("no"), "api_id_not_found"),
        (JvsPortalError("no"), "cannot_connect"),
    ],
)
async def test_user_flow_portal_errors(
    hass: HomeAssistant, mocker: MockerFixture, exc: Exception, error: str
) -> None:
    mocker.patch.object(config_flow, "validate_credentials", side_effect=exc)
    flow_id = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["errors"] == {"base": error}


async def test_user_flow_custom_invalid_url(hass: HomeAssistant) -> None:
    flow_id = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {**USER_INPUT, CONF_PROVIDER: "custom", CONF_BASE_URL: "not a url"}
    )
    assert result["errors"] == {"base": "invalid_url"}


@pytest.mark.usefixtures("portal", "credentials")
async def test_user_flow_duplicate_aborts(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    flow_id = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_password(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mocker: MockerFixture
) -> None:
    mock_config_entry.add_to_hass(hass)
    validate = mocker.patch.object(config_flow, "validate_credentials", return_value=[MAIN])
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-secret"}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == "new-secret"
    assert validate.call_args.args[4] == "new-secret"


async def test_reauth_wrong_password_shows_error(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mocker: MockerFixture
) -> None:
    mock_config_entry.add_to_hass(hass)
    mocker.patch.object(config_flow, "validate_credentials", side_effect=JvsAuthError("no"))
    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "bad"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


class TestHelpers:
    @pytest.mark.parametrize("raw", ["", "ftp://x", "example.com", None])
    def test_normalize_url_rejects_invalid(self, raw: str | None) -> None:
        with pytest.raises(config_flow.InvalidUrl):
            config_flow.normalize_url(raw)

    def test_normalize_url_strips_path_and_slash(self) -> None:
        assert config_flow.normalize_url(" https://x.fr/accueil/ ") == "https://x.fr"

    async def test_resolve_portal_preset_falls_back_to_known_api_id(
        self, hass: HomeAssistant, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(config_flow, "discover_api_id", side_effect=JvsApiIdNotFound("x"))
        assert await config_flow.resolve_portal(hass, "eaudupic", None) == (BASE_URL, API_ID)

    async def test_resolve_portal_preset_prefers_discovered_api_id(
        self, hass: HomeAssistant, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(config_flow, "discover_api_id", return_value="fresh@id")
        assert await config_flow.resolve_portal(hass, "eaudupic", None) == (BASE_URL, "fresh@id")

    async def test_resolve_portal_custom_requires_discovery(
        self, hass: HomeAssistant, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(config_flow, "discover_api_id", side_effect=JvsApiIdNotFound("x"))
        with pytest.raises(JvsApiIdNotFound):
            await config_flow.resolve_portal(hass, "custom", "https://other.fr/")

    async def test_validate_credentials_returns_active_contracts(
        self, hass: HomeAssistant, mocker: MockerFixture
    ) -> None:
        client = mocker.patch.object(config_flow, "JvsIclientsClient").return_value
        client.authenticate = AsyncMock()
        client.contracts = AsyncMock(
            return_value=[MAIN, Contract("1", "n", active=False, principal=False)]
        )
        assert await config_flow.validate_credentials(hass, BASE_URL, API_ID, "u", "p") == [MAIN]
        client.authenticate.assert_awaited_once()
