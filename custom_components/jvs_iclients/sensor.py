"""Capteurs : dernier index, consommation de la veille, date du relevé, compteur."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import JvsConfigEntry
from .const import DOMAIN
from .coordinator import JvsCoordinator, JvsData

type StateValue = float | int | str | datetime | None


@dataclass(frozen=True, kw_only=True)
class JvsSensorDescription(SensorEntityDescription):
    """Description d'un capteur avec sa fonction d'extraction."""

    value_fn: Callable[[JvsData], StateValue]


SENSORS: tuple[JvsSensorDescription, ...] = (
    JvsSensorDescription(
        key="water_index",
        translation_key="water_index",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        value_fn=lambda d: d.latest.index_m3 if d.latest else None,
    ),
    JvsSensorDescription(
        key="daily_consumption",
        translation_key="daily_consumption",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        value_fn=lambda d: d.latest.consumption_liters if d.latest else None,
    ),
    JvsSensorDescription(
        key="last_reading",
        translation_key="last_reading",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.latest.at if d.latest else None,
    ),
    JvsSensorDescription(
        key="meter_serial",
        translation_key="meter_serial",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.meter.serial if d.meter else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: JvsConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Crée les capteurs du contrat."""
    coordinator = entry.runtime_data
    async_add_entities(JvsSensor(coordinator, entry, description) for description in SENSORS)


class JvsSensor(CoordinatorEntity[JvsCoordinator], SensorEntity):
    """Capteur alimenté par le coordinateur."""

    entity_description: JvsSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: JvsCoordinator, entry: JvsConfigEntry, description: JvsSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        meter = coordinator.data.meter
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Compteur eau {coordinator.contract.number}",
            manufacturer=meter.brand if meter else None,
            model=f"{meter.model or ''} DN{meter.diameter or '?'}".strip() if meter else None,
            serial_number=meter.serial if meter else None,
            configuration_url=coordinator.base_url,
        )

    @property
    def native_value(self) -> StateValue:
        """Valeur courante."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Identifiant de la statistique externe et nature du relevé."""
        latest = self.coordinator.data.latest
        return {
            "statistic_id": self.coordinator.statistic_id,
            "estimated": latest.estimated if latest else None,
        }
