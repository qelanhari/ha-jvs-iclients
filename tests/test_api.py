"""Tests du client aiohttp du portail."""

from __future__ import annotations

from datetime import date, datetime

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.jvs_iclients.api import (
    PARIS,
    JvsApiIdNotFound,
    JvsAuthError,
    JvsIclientsClient,
    JvsPortalError,
    discover_api_id,
    parse_reading,
)

from .conftest import (
    API_ID,
    BASE_URL,
    CONTRACT_DETAIL_PAYLOAD,
    CONTRACTS_PAYLOAD,
    TELEINDEX_PAYLOAD,
    make_jwt,
    reading_item,
)

SIGNIN = f"{BASE_URL}/api/v1/iclients/signin"
CONTRACTS = f"{BASE_URL}/api/v1/iclients/contrat"
TELEINDEX = f"{BASE_URL}/api/v1/iclients/teleindex2/5288/20261016/20261023"


def client(hass: HomeAssistant) -> JvsIclientsClient:
    return JvsIclientsClient(async_get_clientsession(hass), BASE_URL, API_ID, "u", "p")


async def logged_in(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> JvsIclientsClient:
    mock_signin(aioclient_mock)
    c = client(hass)
    await c.authenticate()
    return c


def mock_signin(aioclient_mock: AiohttpClientMocker, exp: int = 2_000_000_000) -> None:
    # Le portail répond 201 Created au login.
    aioclient_mock.post(
        SIGNIN, status=201, json={"data": {}}, headers={"authorization": make_jwt(exp)}
    )


class TestDiscoverApiId:
    async def test_discover_api_id_reads_bundle(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        aioclient_mock.get(f"{BASE_URL}/", text='<script src="/assets/index-abc.js"></script>')
        aioclient_mock.get(f"{BASE_URL}/assets/index-abc.js", text='x,"Api-Id":"id@site",y')
        assert await discover_api_id(async_get_clientsession(hass), BASE_URL) == "id@site"

    async def test_discover_api_id_without_bundle_raises(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        aioclient_mock.get(f"{BASE_URL}/", text="<html></html>")
        with pytest.raises(JvsApiIdNotFound):
            await discover_api_id(async_get_clientsession(hass), BASE_URL)

    async def test_discover_api_id_without_api_id_raises(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        aioclient_mock.get(f"{BASE_URL}/", text='<script src="/assets/index-abc.js"></script>')
        aioclient_mock.get(f"{BASE_URL}/assets/index-abc.js", text="nothing here")
        with pytest.raises(JvsApiIdNotFound):
            await discover_api_id(async_get_clientsession(hass), BASE_URL)

    async def test_discover_api_id_network_error_raises(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        aioclient_mock.get(f"{BASE_URL}/", exc=aiohttp.ClientConnectionError("down"))
        with pytest.raises(JvsPortalError):
            await discover_api_id(async_get_clientsession(hass), BASE_URL)


class TestAuthenticate:
    async def test_authenticate_posts_jsonapi_body(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        mock_signin(aioclient_mock)
        await client(hass).authenticate()
        body = aioclient_mock.mock_calls[0][2]["data"]
        assert body == {
            "type": "POICL_Signin",
            "id": "",
            "attributes": {"login": "u", "password": "p", "remember": False},
        }

    async def test_authenticate_rejected_raises_auth_error(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        aioclient_mock.post(SIGNIN, status=401, text="Not authorized !")
        with pytest.raises(JvsAuthError):
            await client(hass).authenticate()

    async def test_authenticate_without_header_raises_auth_error(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        aioclient_mock.post(SIGNIN, json={"errors": []})
        with pytest.raises(JvsAuthError):
            await client(hass).authenticate()

    async def test_authenticate_server_error_raises_portal_error(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        aioclient_mock.post(SIGNIN, status=500, text="oops")
        with pytest.raises(JvsPortalError):
            await client(hass).authenticate()

    async def test_authenticate_network_error_raises_portal_error(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        aioclient_mock.post(SIGNIN, exc=aiohttp.ClientConnectionError("down"))
        with pytest.raises(JvsPortalError):
            await client(hass).authenticate()


class TestContracts:
    async def test_contracts_logs_in_and_sends_headers(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        c = await logged_in(hass, aioclient_mock)
        aioclient_mock.get(CONTRACTS, json=CONTRACTS_PAYLOAD)
        contracts = await c.contracts()
        headers = aioclient_mock.mock_calls[1][3]
        assert headers["Api-Id"] == API_ID
        assert headers["Origin"] == BASE_URL
        assert headers["Referer"] == f"{BASE_URL}/accueil"
        assert headers["Authorization"].startswith('Jwt id="')
        assert [(c.id, c.number, c.active, c.principal) for c in contracts] == [
            ("5288", "340400867", True, True)
        ]

    async def test_get_unauthorized_raises_auth_error(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        c = await logged_in(hass, aioclient_mock)
        aioclient_mock.get(CONTRACTS, status=401, text="Not authorized !")
        with pytest.raises(JvsAuthError):
            await c.contracts()

    async def test_get_server_error_raises_portal_error(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        c = await logged_in(hass, aioclient_mock)
        aioclient_mock.get(CONTRACTS, status=503, text="maintenance")
        with pytest.raises(JvsPortalError):
            await c.contracts()

    async def test_get_network_error_raises_portal_error(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        c = await logged_in(hass, aioclient_mock)
        aioclient_mock.get(CONTRACTS, exc=aiohttp.ClientConnectionError("down"))
        with pytest.raises(JvsPortalError):
            await c.contracts()


class TestMeter:
    async def test_meter_parses_included_compteur(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        c = await logged_in(hass, aioclient_mock)
        aioclient_mock.get(f"{CONTRACTS}/5288", json=CONTRACT_DETAIL_PAYLOAD)
        meter = await c.meter("5288")
        assert meter is not None
        assert (meter.serial, meter.brand, meter.diameter, meter.model) == (
            "SERIAL0001",
            "DIEHL",
            "15",
            "GPVW",
        )

    async def test_meter_missing_returns_none(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        c = await logged_in(hass, aioclient_mock)
        aioclient_mock.get(f"{CONTRACTS}/5288", json={"data": {}, "included": []})
        assert await c.meter("5288") is None


class TestReadings:
    async def test_readings_builds_url_and_params(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        c = await logged_in(hass, aioclient_mock)
        aioclient_mock.get(TELEINDEX, json=TELEINDEX_PAYLOAD)
        await c.readings("5288", date(2026, 10, 16), date(2026, 10, 23))
        url = aioclient_mock.mock_calls[1][1]
        assert url.path == "/api/v1/iclients/teleindex2/5288/20261016/20261023"
        assert dict(url.query) == {"option[sort]": "asc", "option[algorithm]": "chronological"}

    async def test_readings_skips_completion_and_sorts(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        c = await logged_in(hass, aioclient_mock)
        aioclient_mock.get(TELEINDEX, json=TELEINDEX_PAYLOAD)
        readings = await c.readings("5288", date(2026, 10, 16), date(2026, 10, 23))
        assert [r.index_liters for r in readings] == [106945, 107284]

    async def test_readings_without_login_raises_auth_error(
        self, hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
    ) -> None:
        aioclient_mock.get(TELEINDEX, status=401, text="Not authorized !")
        with pytest.raises(JvsAuthError):
            await client(hass).readings("5288", date(2026, 10, 16), date(2026, 10, 23))
        assert aioclient_mock.mock_calls[0][3]["Authorization"] == "JWT"


class TestParseReading:
    def test_parse_reading_sets_paris_timezone(self) -> None:
        reading = parse_reading(reading_item("20", 106945, 350))
        assert reading is not None
        assert reading.at == datetime(2026, 10, 20, 1, 0, tzinfo=PARIS)

    def test_parse_reading_index_m3(self) -> None:
        reading = parse_reading(reading_item("20", 106945, 350))
        assert reading is not None
        assert reading.index_m3 == 106.945

    def test_parse_reading_missing_index_returns_none(self) -> None:
        item = reading_item("20", 1, None)
        del item["attributes"]["ni"]
        assert parse_reading(item) is None

    def test_parse_reading_keeps_estimated_flag(self) -> None:
        reading = parse_reading(reading_item("20", 1, 5, estimated=True))
        assert reading is not None
        assert reading.estimated is True
