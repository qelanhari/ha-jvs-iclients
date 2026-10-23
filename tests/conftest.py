"""Fixtures : entrée de configuration et réponses du portail (anonymisées)."""

from __future__ import annotations

import base64
import json
from collections.abc import Generator
from typing import Any

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jvs_iclients.const import (
    CONF_API_ID,
    CONF_BASE_URL,
    CONF_CONTRACT_ID,
    CONF_CONTRACT_NUMBER,
    CONF_PROVIDER,
    DOMAIN,
)

pytest_plugins = "pytest_homeassistant_custom_component"

BASE_URL = "https://eaudupic.client.ccgpsl.fr"
API_ID = "d2e3b03552d0e10cfa2a5e1e9e3dc73b@iclients-35664-picsaintloup"
ENTRY_DATA = {
    CONF_PROVIDER: "eaudupic",
    CONF_BASE_URL: BASE_URL,
    CONF_API_ID: API_ID,
    CONF_USERNAME: "user@example.com",
    CONF_PASSWORD: "secret",
    CONF_CONTRACT_ID: "5288",
    CONF_CONTRACT_NUMBER: "340400867",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    recorder_mock: object, enable_custom_integrations: None
) -> Generator[None]:
    """Recorder (dépendance du manifest) puis chargement de custom_components."""
    yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, unique_id="eaudupic.client.ccgpsl.fr:user@example.com:5288"
    )


def make_jwt(exp: int = 2_000_000_000) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f'Jwt id="eyJhbGciOiJSUzI1NiJ9.{payload}.sig"'


def reading_item(day: str, ni: int, liters: int | None, estimated: bool = False) -> dict[str, Any]:
    return {
        "type": "PORLV_Teleconso2",
        "id": f"id-{day}",
        "attributes": {
            "partner": "suez",
            "numserie": "SERIAL0001",
            "typerlv": "TÉLÉRELÈVE",
            "dateni": f"2026-10-{day} 01:00:00",
            "ni": ni,
            "nie": ni,
            "l": liters,
            "m3": (liters or 0) // 1000,
            "estimated_consumption": estimated,
        },
    }


COMPLETION_ITEM = {
    "type": "PORLV_Teleconso2",
    "id": "completion_1",
    "attributes": {"typerlv": "NON DÉFINI", "dateni": "2026-10-22 01:00:00"},
}

TELEINDEX_PAYLOAD = {
    "meta": {"count": 3},
    "data": [reading_item("21", 107284, 339), reading_item("20", 106945, 350), COMPLETION_ITEM],
}

CONTRACTS_PAYLOAD = {
    "data": [
        {
            "type": "POICL_Contrat",
            "id": "5288",
            "attributes": {"numcontrat": "340400867", "actif": True, "principal": True},
        }
    ]
}

CONTRACT_DETAIL_PAYLOAD = {
    "data": {"type": "POICL_Contrat", "id": "5288", "attributes": {}},
    "included": [
        {
            "type": "POICL_Compteur",
            "id": "21213",
            "attributes": {
                "numserie": "SERIAL0001",
                "enum_marq": "DIEHL",
                "enum_diam": "15",
                "enum_tcpt": "GPVW",
                "dateinst": "2025-07-02T00:00:00+02:00",
            },
        }
    ],
}
