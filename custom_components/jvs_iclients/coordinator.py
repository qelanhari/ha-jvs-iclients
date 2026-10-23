"""Coordinateur : récupère les relevés et les importe comme statistiques externes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlparse

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import slugify

from .api import Contract, JvsAuthError, JvsIclientsClient, JvsPortalError, Meter, Reading
from .const import DOMAIN, INITIAL_HISTORY_DAYS, REFRESH_WINDOW_DAYS, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass
class JvsData:
    """Données exposées aux entités."""

    latest: Reading | None
    meter: Meter | None


def build_statistic_id(base_url: str, contract_id: str) -> str:
    """Identifiant de statistique externe, unique par portail et contrat."""
    host = slugify(urlparse(base_url).netloc)
    return f"{DOMAIN}:{host}_{slugify(contract_id)}_water_index"


class JvsCoordinator(DataUpdateCoordinator[JvsData]):
    """Interroge le portail deux fois par jour et alimente les statistiques."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: JvsIclientsClient,
        contract: Contract,
        base_url: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {contract.number}",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.contract = contract
        self.base_url = base_url
        self.statistic_id = build_statistic_id(base_url, contract.id)

    async def _async_update_data(self) -> JvsData:
        previous = self.data or JvsData(latest=None, meter=None)
        baseline = await self._async_baseline()
        start = date.today() - timedelta(
            days=INITIAL_HISTORY_DAYS if baseline is None else REFRESH_WINDOW_DAYS
        )
        try:
            readings = await self.client.readings(self.contract.id, start, date.today())
            meter = previous.meter or await self.client.meter(self.contract.id)
        except JvsAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except JvsPortalError as err:
            raise UpdateFailed(str(err)) from err
        if readings:
            self._import_statistics(readings, baseline)
        return JvsData(latest=readings[-1] if readings else previous.latest, meter=meter)

    async def _async_baseline(self) -> float | None:
        """Offset ``state - sum`` déjà utilisé par la série HA ; ``None`` si elle est vide.

        La somme démarre à 0 au premier relevé (sinon le premier jour afficherait tout
        l'index en consommation) et l'offset reste constant entre les rafraîchissements.
        """
        last = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, self.statistic_id, True, {"state", "sum"}
        )
        for row in last.get(self.statistic_id, []):
            if row.get("state") is not None and row.get("sum") is not None:
                return float(row["state"]) - float(row["sum"])
        return None

    def _import_statistics(self, readings: list[Reading], baseline: float | None) -> None:
        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"Index eau contrat {self.contract.number}",
            source=DOMAIN,
            statistic_id=self.statistic_id,
            unit_class="volume",
            unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        )
        offset = readings[0].index_m3 if baseline is None else baseline
        stats = [
            StatisticData(
                start=r.at.replace(minute=0, second=0, microsecond=0),
                state=r.index_m3,
                sum=round(r.index_m3 - offset, 3),
            )
            for r in readings
        ]
        async_add_external_statistics(self.hass, metadata, stats)
        _LOGGER.debug("%d relevés importés dans %s", len(stats), self.statistic_id)
