"""Sensors: the pet's stats, mood, battery and current screen."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import FerretEntity
from .hub import FerretHub


@dataclass(frozen=True, kw_only=True)
class FerretSensorDescription(SensorEntityDescription):
    """Describes a HomeCritters sensor (state JSON key = description key)."""

    round_value: bool = False


SENSORS: tuple[FerretSensorDescription, ...] = (
    FerretSensorDescription(
        key="hunger", translation_key="hunger", icon="mdi:food-apple",
        native_unit_of_measurement=PERCENTAGE, round_value=True,
    ),
    FerretSensorDescription(
        key="energy", translation_key="energy", icon="mdi:lightning-bolt",
        native_unit_of_measurement=PERCENTAGE, round_value=True,
    ),
    FerretSensorDescription(
        key="joy", translation_key="joy", icon="mdi:emoticon-happy",
        native_unit_of_measurement=PERCENTAGE, round_value=True,
    ),
    FerretSensorDescription(
        key="hygiene", translation_key="hygiene", icon="mdi:shower",
        native_unit_of_measurement=PERCENTAGE, round_value=True,
    ),
    FerretSensorDescription(
        key="battery", translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
    ),
    FerretSensorDescription(key="mood", translation_key="mood", icon="mdi:emoticon"),
    FerretSensorDescription(key="screen", translation_key="screen", icon="mdi:monitor"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: FerretHub = entry.runtime_data
    async_add_entities(FerretSensor(hub, d) for d in SENSORS)


class FerretSensor(FerretEntity, SensorEntity):
    entity_description: FerretSensorDescription

    def __init__(self, hub: FerretHub, description: FerretSensorDescription) -> None:
        super().__init__(hub, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        value = self._hub.data.get(self.entity_description.key)
        if value is None:
            return None
        if self.entity_description.round_value:
            return round(float(value))
        return value
