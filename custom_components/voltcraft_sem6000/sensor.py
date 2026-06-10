from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VoltcraftDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VoltcraftDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            VoltcraftPowerSensor(coordinator),
            VoltcraftVoltageSensor(coordinator),
            VoltcraftCurrentSensor(coordinator),
            VoltcraftFrequencySensor(coordinator),
            VoltcraftPowerFactorSensor(coordinator),
            VoltcraftEnergySensor(coordinator),
        ]
    )


class VoltcraftSensor(CoordinatorEntity[VoltcraftDataUpdateCoordinator], SensorEntity):
    def __init__(self, coordinator: VoltcraftDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info

    @property
    def available(self) -> bool:
        return self.coordinator.session.is_connected and self.coordinator.data is not None


class VoltcraftPowerSensor(VoltcraftSensor):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: VoltcraftDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_power"
        self._attr_name = "Power"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.power if self.coordinator.data else None


class VoltcraftVoltageSensor(VoltcraftSensor):
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: VoltcraftDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_voltage"
        self._attr_name = "Voltage"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.voltage if self.coordinator.data else None


class VoltcraftCurrentSensor(VoltcraftSensor):
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: VoltcraftDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_current"
        self._attr_name = "Current"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.current if self.coordinator.data else None


class VoltcraftFrequencySensor(VoltcraftSensor):
    _attr_device_class = SensorDeviceClass.FREQUENCY
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: VoltcraftDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_frequency"
        self._attr_name = "Frequency"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.frequency if self.coordinator.data else None


class VoltcraftPowerFactorSensor(VoltcraftSensor):
    _attr_device_class = SensorDeviceClass.POWER_FACTOR
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: VoltcraftDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_power_factor"
        self._attr_name = "Power Factor"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.power_factor if self.coordinator.data else None


class VoltcraftEnergySensor(VoltcraftSensor):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: VoltcraftDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_energy"
        self._attr_name = "Total Energy"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.consumed_energy if self.coordinator.data else None
