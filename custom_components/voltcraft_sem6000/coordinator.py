"""
VoltcraftDataUpdateCoordinator

Responsibilities (ONLY):
  - Trigger a MEASURE command every SCAN_INTERVAL
  - Call async_set_updated_data() when notify_state changes
  - Provide device_info and data snapshot to entities

NOT responsible for:
  - BLE connection / reconnect
  - PIN authentication
  - Notify parsing
  - Any direct BleakClient usage
"""

from __future__ import annotations

import logging

from bleak.exc import BleakError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import (
    CONNECTION_BLUETOOTH,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .ble_session import BLESessionManager, NotifyState
from .const import COMMAND_UUID, DEVICE_NAME, DOMAIN, SCAN_INTERVAL
from .protocol import Command

_LOGGER = logging.getLogger(__name__)


class VoltcraftDataUpdateCoordinator(DataUpdateCoordinator[NotifyState | None]):
    """Coordinator: polls MEASURE, publishes notify_state to entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: BLESessionManager,
        mac: str,
        device_name: str | None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{mac}",
            update_interval=SCAN_INTERVAL,
        )

        self._session = session
        self.mac = format_mac(mac)
        self._device_name = device_name

        # Wire notify callbacks → coordinator update
        self._session.register_callback(self._on_notify_state_changed)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self.mac)},
            identifiers={(DOMAIN, self.mac)},
            name=self._device_name or DEVICE_NAME,
        )

    @property
    def session(self) -> BLESessionManager:
        return self._session

    # ------------------------------------------------------------------
    # Commands (delegated to session)
    # ------------------------------------------------------------------

    async def async_send_switch_command(self, payload: bytes | bytearray, switch_state: bool | None = None) -> None:
        """Send a switch command via the session manager."""
        if not self._session.is_authenticated:
            _LOGGER.warning("Cannot send switch command: not authenticated")
            return
        try:
            await self._session.async_write_command(payload, switch_state=switch_state)
        except BleakError as err:
            _LOGGER.warning("Switch command failed: %s", err)

    async def async_send_led_command(self, state: bool) -> None:
        """Send an LED command via the session manager."""
        if not self._session.is_authenticated:
            _LOGGER.warning("Cannot send LED command: not authenticated")
            return
        payload = (
            bytes.fromhex("0F090F0005010000000016FFFF")
            if state
            else bytes.fromhex("0F090F0005000000000015FFFF")
        )
        try:
            await self._session.async_write_command(payload)
        except BleakError as err:
            _LOGGER.warning("LED command failed: %s", err)

    # ------------------------------------------------------------------
    # Coordinator core
    # ------------------------------------------------------------------

    def _on_notify_state_changed(self) -> None:
        """Called by BLESessionManager whenever notify state updates."""
        # Push the current notify_state snapshot to all entities
        self.async_set_updated_data(self._session.notify_state)

    async def _async_update_data(self) -> NotifyState | None:
        """
        Called every SCAN_INTERVAL by HA.

        We only trigger a MEASURE request here.
        The actual data arrives via notify → _on_notify_state_changed.
        """
        if not self._session.is_connected:
            # Not connected yet — return last known state (may be None on first run)
            _LOGGER.debug("Update skipped: BLE not connected")
            return self._session.notify_state

        if not self._session.is_authenticated:
            _LOGGER.debug("Update skipped: not authenticated")
            return self._session.notify_state

        try:
            await self._session.async_write_command(
                Command.MEASURE.build_payload()
            )
        except BleakError as err:
            raise UpdateFailed(f"MEASURE command failed: {err}") from err

        # Return the last known state; fresh data arrives via notify callback
        return self._session.notify_state
