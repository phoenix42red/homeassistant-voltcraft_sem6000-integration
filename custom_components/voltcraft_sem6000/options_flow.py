"""
Options Flow for Voltcraft SEM6000.

Allows changing the device PIN from HA Settings → Integration → Configure.
On success: sends the change-PIN command, waits for ACK, saves new PIN to config entry.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CONF_OLD_PIN = "old_pin"
CONF_NEW_PIN = "new_pin"


def _encode_pin(pin: str) -> bytes:
    pin = str(pin).zfill(4)
    return bytes(int(d) for d in pin)


def _build_change_pin_payload(old_pin: str, new_pin: str) -> bytes:
    """
    Change PIN command:
    0F 0C 17 00 01 [NEW_PIN 4 bytes] [OLD_PIN 4 bytes] 00 00 00 00 [CHECKSUM] FF FF
    """
    old_bytes = _encode_pin(old_pin)
    new_bytes = _encode_pin(new_pin)

    # Verified against HCI log: 0F 0C 17 00 01 [new 4] [old 4] [checksum] FF FF
    payload = bytearray([
        0x0F, 0x0C, 0x17, 0x00, 0x01,
        *new_bytes,
        *old_bytes,
    ])

    checksum = (sum(payload[2:]) + 1) % 256
    payload.append(checksum)
    payload += b"\xFF\xFF"
    return bytes(payload)


class VoltcraftOptionsFlow(OptionsFlow):
    """Handle PIN change via Options Flow."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry
        self._errors: dict[str, str] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._errors = {}

        if user_input is not None:
            old_pin = user_input[CONF_OLD_PIN]
            new_pin = user_input[CONF_NEW_PIN]

            if not old_pin.isdigit():
                self._errors[CONF_OLD_PIN] = "invalid_pin"
            elif not new_pin.isdigit():
                self._errors[CONF_NEW_PIN] = "invalid_pin"
            else:
                result = await self._send_change_pin(old_pin, new_pin)

                if result == "success":
                    # Save new PIN to config entry data
                    new_data = {**self._config_entry.data, "pin": new_pin}
                    self.hass.config_entries.async_update_entry(
                        self._config_entry, data=new_data
                    )
                    # Update the live session
                    from .coordinator import VoltcraftDataUpdateCoordinator
                    coordinator: VoltcraftDataUpdateCoordinator = self.hass.data[DOMAIN][
                        self._config_entry.entry_id
                    ]
                    coordinator.session._pin = new_pin
                    return self.async_create_entry(title="", data={})

                elif result == "wrong_pin":
                    self._errors[CONF_OLD_PIN] = "wrong_pin"
                else:
                    self._errors["base"] = "pin_change_timeout"

        current_pin = self._config_entry.data.get("pin", "0000")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_OLD_PIN, default=current_pin): vol.All(
                        vol.Coerce(str), vol.Length(min=4, max=4)
                    ),
                    vol.Required(CONF_NEW_PIN): vol.All(
                        vol.Coerce(str), vol.Length(min=4, max=4)
                    ),
                }
            ),
            errors=self._errors,
        )

    async def _send_change_pin(self, old_pin: str, new_pin: str) -> str:
        """Send change-PIN command, wait for ACK. Returns 'success', 'wrong_pin', or 'timeout'."""
        from .coordinator import VoltcraftDataUpdateCoordinator

        coordinator: VoltcraftDataUpdateCoordinator = self.hass.data[DOMAIN][
            self._config_entry.entry_id
        ]
        session = coordinator.session

        if not session.is_connected:
            return "timeout"

        payload = _build_change_pin_payload(old_pin, new_pin)

        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        session._pending_change_pin_future = future

        try:
            await session.async_write_command(payload)
            return await asyncio.wait_for(future, timeout=5.0)
        except asyncio.TimeoutError:
            _LOGGER.warning("Change PIN timeout")
            return "timeout"
        finally:
            session._pending_change_pin_future = None
