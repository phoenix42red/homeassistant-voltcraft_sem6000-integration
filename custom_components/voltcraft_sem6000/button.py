from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
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
            LedOnButtonEntity(coordinator),
            LedOffButtonEntity(coordinator),
        ]
    )


class _LedButtonBase(
    CoordinatorEntity[VoltcraftDataUpdateCoordinator],
    ButtonEntity,
):
    def __init__(self, coordinator: VoltcraftDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info

    @property
    def available(self) -> bool:
        return self.coordinator.session.is_connected and self.coordinator.session.is_authenticated


class LedOnButtonEntity(_LedButtonBase):
    def __init__(self, coordinator: VoltcraftDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_led_on"
        self._attr_name = "LED ON"

    async def async_press(self) -> None:
        await self.coordinator.async_send_led_command(True)


class LedOffButtonEntity(_LedButtonBase):
    def __init__(self, coordinator: VoltcraftDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_led_off"
        self._attr_name = "LED OFF"

    async def async_press(self) -> None:
        await self.coordinator.async_send_led_command(False)
