from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VoltcraftDataUpdateCoordinator

# Reset PIN payload: 0F 0C 17 00 02 00 00 00 00 00 00 00 00 [CHECKSUM] FF FF
_RESET_PIN_PAYLOAD = bytes([
    0x0F, 0x0C, 0x17, 0x00, 0x02,
    0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00,
    0x18,
    0xFF, 0xFF,
])


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
            ResetPinButtonEntity(coordinator),
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


class ResetPinButtonEntity(_LedButtonBase):
    def __init__(self, coordinator: VoltcraftDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.mac}_reset_pin"
        self._attr_name = "Reset PIN to 0000"

    async def async_press(self) -> None:
        session = self.coordinator.session
        if not session.is_connected or not session.is_authenticated:
            return
        await session.async_write_command(_RESET_PIN_PAYLOAD)
        # After reset, update stored PIN and live session
        entry = self.coordinator.config_entry
        new_data = {**entry.data, "pin": "0000"}
        self.hass.config_entries.async_update_entry(entry, data=new_data)
        session._pin = "0000"
