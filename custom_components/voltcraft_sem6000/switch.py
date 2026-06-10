from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VoltcraftDataUpdateCoordinator
from .protocol import SwitchModes

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VoltcraftDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MainSwitchEntity(coordinator)])


class MainSwitchEntity(CoordinatorEntity[VoltcraftDataUpdateCoordinator], SwitchEntity):
    _attr_device_class = SwitchDeviceClass.OUTLET

    def __init__(self, coordinator: VoltcraftDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.mac
        self._attr_name = "Power switch"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        """State comes exclusively from notify_state — never from direct BLE reads."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.is_on

    @property
    def available(self) -> bool:
        return self.coordinator.session.is_connected and self.coordinator.data is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_switch_command(SwitchModes.ON.build_payload())

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_switch_command(SwitchModes.OFF.build_payload())
