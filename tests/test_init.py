"""Tests de l'installation de l'entrée, du coordinateur et des capteurs."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_mock import MockerFixture

from custom_components.jvs_iclients import coordinator as coordinator_module
from custom_components.jvs_iclients.api import PARIS, JvsAuthError, JvsPortalError, Meter, Reading
from custom_components.jvs_iclients.const import (
    AUTH_RETRY_DELAY,
    DOMAIN,
    INITIAL_HISTORY_DAYS,
    REFRESH_WINDOW_DAYS,
)

STATISTIC_ID = "jvs_iclients:eaudupic_client_ccgpsl_fr_5288_water_index"
READINGS = [
    Reading(datetime(2026, 10, 20, 1, tzinfo=PARIS), 106945, 350, False),
    Reading(datetime(2026, 10, 21, 1, tzinfo=PARIS), 107284, 339, False),
]
METER = Meter("SERIAL0001", "DIEHL", "15", "GPVW", "2025-07-02")


@pytest.fixture
def client(mocker: MockerFixture) -> MagicMock:
    client = mocker.patch("custom_components.jvs_iclients.JvsIclientsClient").return_value
    client.authenticate = AsyncMock()
    client.readings = AsyncMock(return_value=READINGS)
    client.meter = AsyncMock(return_value=METER)
    return client


@pytest.fixture
def statistics(mocker: MockerFixture) -> tuple[MagicMock, MagicMock]:
    add = mocker.patch.object(coordinator_module, "async_add_external_statistics")
    last = mocker.patch.object(coordinator_module, "get_last_statistics", return_value={})
    return add, last


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str:
    found = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
    assert found is not None
    return found


@pytest.mark.usefixtures("client", "statistics")
async def test_setup_creates_sensors(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(entity_id(hass, mock_config_entry, "water_index")).state == "107.284"
    assert hass.states.get(entity_id(hass, mock_config_entry, "daily_consumption")).state == "339"
    assert hass.states.get(entity_id(hass, mock_config_entry, "meter_serial")).state == "SERIAL0001"
    last = hass.states.get(entity_id(hass, mock_config_entry, "last_reading"))
    assert last.state == "2026-10-20T23:00:00+00:00"


@pytest.mark.usefixtures("client", "statistics")
async def test_index_sensor_exposes_statistic_id(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)
    state = hass.states.get(entity_id(hass, mock_config_entry, "water_index"))
    assert state.attributes["statistic_id"] == STATISTIC_ID
    assert state.attributes["estimated"] is False


@pytest.mark.usefixtures("client")
async def test_first_refresh_imports_full_history(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    client: MagicMock,
    statistics: tuple[MagicMock, MagicMock],
) -> None:
    await setup_entry(hass, mock_config_entry)
    add, _ = statistics
    start, end = client.readings.call_args.args[1:]
    assert end == date.today() and (end - start).days == INITIAL_HISTORY_DAYS
    metadata, stats = add.call_args.args[1:]
    assert metadata["statistic_id"] == STATISTIC_ID
    assert metadata["source"] == DOMAIN
    assert metadata["unit_of_measurement"] == "m³"
    assert [(s["start"], s["state"], s["sum"]) for s in stats] == [
        (datetime(2026, 10, 20, 1, tzinfo=PARIS), 106.945, 0.0),
        (datetime(2026, 10, 21, 1, tzinfo=PARIS), 107.284, 0.339),
    ]


@pytest.mark.usefixtures("client")
async def test_later_refresh_uses_sliding_window(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    client: MagicMock,
    statistics: tuple[MagicMock, MagicMock],
) -> None:
    add, last = statistics
    last.return_value = {STATISTIC_ID: [{"state": 100.0, "sum": 7.716}]}
    await setup_entry(hass, mock_config_entry)
    start, end = client.readings.call_args.args[1:]
    assert (end - start).days == REFRESH_WINDOW_DAYS
    assert [s["sum"] for s in add.call_args.args[2]] == [14.661, 15.0]


@pytest.mark.usefixtures("statistics")
async def test_no_new_readings_keeps_previous_state(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, client: MagicMock
) -> None:
    await setup_entry(hass, mock_config_entry)
    client.readings.return_value = []
    await mock_config_entry.runtime_data.async_refresh()
    assert mock_config_entry.runtime_data.data.latest == READINGS[-1]
    assert client.meter.await_count == 1


@pytest.mark.usefixtures("statistics")
async def test_auth_error_retries_without_reauth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, client: MagicMock
) -> None:
    client.authenticate.side_effect = JvsAuthError("refused")
    await setup_entry(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []


@pytest.mark.usefixtures("statistics")
async def test_auth_error_after_setup_retries_in_one_hour(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, client: MagicMock
) -> None:
    await setup_entry(hass, mock_config_entry)
    client.authenticate.side_effect = JvsAuthError("refused")
    coordinator = mock_config_entry.runtime_data
    await coordinator.async_refresh()
    assert coordinator.last_update_success is False
    assert coordinator.update_interval == AUTH_RETRY_DELAY
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []


@pytest.mark.usefixtures("statistics")
async def test_every_poll_logs_in_again(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, client: MagicMock
) -> None:
    await setup_entry(hass, mock_config_entry)
    await mock_config_entry.runtime_data.async_refresh()
    assert client.authenticate.await_count == 2


@pytest.mark.usefixtures("client", "statistics")
async def test_success_schedules_next_slot(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mocker: MockerFixture
) -> None:
    now = datetime(2026, 10, 24, 9, 30, tzinfo=PARIS)
    mocker.patch.object(coordinator_module.dt_util, "now", return_value=now)
    await setup_entry(hass, mock_config_entry)
    assert mock_config_entry.runtime_data.update_interval == timedelta(hours=6, minutes=30)


@pytest.mark.usefixtures("statistics")
async def test_portal_error_retries_setup(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, client: MagicMock
) -> None:
    client.readings.side_effect = JvsPortalError("down")
    await setup_entry(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.usefixtures("client", "statistics")
async def test_unload_entry(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    await setup_entry(hass, mock_config_entry)
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


def test_build_statistic_id_is_valid_and_unique_per_host() -> None:
    first = coordinator_module.build_statistic_id("https://a.example.fr", "5288")
    second = coordinator_module.build_statistic_id("https://b.example.fr", "5288")
    assert first == "jvs_iclients:a_example_fr_5288_water_index"
    assert first != second


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 24, 7, 59), datetime(2026, 10, 24, 8, 0)),
        (datetime(2026, 10, 24, 8, 0), datetime(2026, 10, 24, 16, 0)),
        (datetime(2026, 10, 24, 12, 0), datetime(2026, 10, 24, 16, 0)),
        (datetime(2026, 10, 24, 16, 0, 0, 1), datetime(2026, 10, 25, 8, 0)),
        (datetime(2026, 10, 24, 23, 30), datetime(2026, 10, 25, 8, 0)),
    ],
)
def test_next_poll_is_08_or_16_local(now: datetime, expected: datetime) -> None:
    tz = ZoneInfo("Europe/Paris")
    assert coordinator_module.next_poll(now.replace(tzinfo=tz)) == expected.replace(tzinfo=tz)
