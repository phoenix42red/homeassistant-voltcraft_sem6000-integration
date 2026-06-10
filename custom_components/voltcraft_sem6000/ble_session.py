"""
BLESessionManager: owns the BLE connection lifecycle.

Responsibilities:
  - connect / reconnect (via bleak-retry-connector)
  - PIN auth (idempotent: skipped when already authenticated)
  - start_notify / stop_notify
  - deliver parsed notify payloads to registered callbacks
  - reconnect safety: back-off, max retries, disconnect detection

NOT responsible for:
  - HA coordinator logic
  - polling (that's the coordinator's job)
  - entity state (read from notify_state only)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from bleak import BleakClient, BleakGATTCharacteristic
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import COMMAND_UUID, NOTIFY_UUID
from .protocol import (
    Command,
    MeasureNotifyPayload,
    NotifyPayload,
    ParsedNotifyPayload,
    SwitchNotifyPayload,
)

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY_BASE = 2.0   # seconds
RECONNECT_DELAY_MAX = 30.0   # seconds
RECONNECT_MAX_ATTEMPTS = 10  # 0 = unlimited


@dataclass
class NotifyState:
    """The single source of truth for device state, populated exclusively by notify handler."""

    is_on: bool | None = None
    power: float | None = None
    voltage: float | None = None
    current: float | None = None
    frequency: int | None = None
    power_factor: float | None = None
    consumed_energy: float | None = None

    def update_from_measure(self, payload: MeasureNotifyPayload, skip_is_on: bool = False) -> None:
        power = payload.power / 1000.0
        voltage = float(payload.voltage)
        current = payload.current / 1000.0
        apparent = voltage * current

        if not skip_is_on:
            self.is_on = payload.is_on
        self.power = power
        self.voltage = voltage
        self.current = current
        self.frequency = payload.frequency
        self.power_factor = min(power / apparent, 1.0) if apparent > 0 else None
        self.consumed_energy = payload.consumed_energy / 1000.0


# Callback type: called whenever notify state changes
NotifyCallback = Callable[[], None]


class BLESessionManager:
    """Manages a single BLE session with reconnect and idempotent auth."""

    def __init__(
        self,
        hass: HomeAssistant,
        mac: str,
        entry_id: str,
        pin: str | None,
    ) -> None:
        self._hass = hass
        self._mac = mac
        self._entry_id = entry_id
        self._pin = pin

        self._client: BleakClient | None = None
        self._authenticated = False
        self._notify_active = False

        self.notify_state = NotifyState()
        self._callbacks: list[NotifyCallback] = []

        self._reconnect_task: asyncio.Task | None = None
        self._shutdown = False
        self._switch_pending_state: bool | None = None  # desired is_on while waiting for SwitchACK

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_callback(self, cb: NotifyCallback) -> None:
        """Register a callback to be called on any notify state change."""
        self._callbacks.append(cb)

    def unregister_callback(self, cb: NotifyCallback) -> None:
        self._callbacks.discard(cb) if hasattr(self._callbacks, "discard") else None
        if cb in self._callbacks:
            self._callbacks.remove(cb)

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    async def async_start(self) -> None:
        """Initial connect + auth. Called once from __init__.py."""
        self._shutdown = False
        await self._connect_and_setup()

    async def async_stop(self) -> None:
        """Clean shutdown."""
        self._shutdown = True

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        await self._disconnect_client()

    async def async_write_command(self, data: bytes | bytearray, switch_state: bool | None = None) -> None:
        """Write a GATT command. Raises BleakError if not connected."""
        if not self.is_connected:
            raise BleakError("Not connected")
        if switch_state is not None:
            self._switch_pending_state = switch_state
        await self._client.write_gatt_char(COMMAND_UUID, data, response=False)

    # ------------------------------------------------------------------
    # Internal: connect + setup
    # ------------------------------------------------------------------

    async def _connect_and_setup(self) -> None:
        """Establish connection, start notify, authenticate."""
        ble_device = bluetooth.async_ble_device_from_address(
            self._hass, self._mac, connectable=True
        )
        if not ble_device:
            _LOGGER.warning("BLE device %s not found during connect", self._mac)
            self._schedule_reconnect()
            return

        try:
            _LOGGER.debug("Connecting to %s", self._mac)
            self._client = await establish_connection(
                BleakClient,
                ble_device,
                self._entry_id,
                disconnected_callback=self._on_disconnected,
            )
        except (BleakError, Exception) as err:
            _LOGGER.warning("Connect failed: %s", err)
            self._client = None
            self._schedule_reconnect()
            return

        await self._setup_session()

    async def _setup_session(self) -> None:
        """Start notify and authenticate on an already-connected client."""
        assert self._client is not None

        # Start notifications
        if not self._notify_active:
            try:
                await self._client.start_notify(NOTIFY_UUID, self._handle_notify)
                self._notify_active = True
                _LOGGER.debug("Notifications started for %s", self._mac)
            except BleakError as err:
                _LOGGER.warning("start_notify failed: %s", err)
                self._schedule_reconnect()
                return

        # Auth: idempotent — skipped if already authenticated
        if not self._authenticated:
            await self._authenticate()
        else:
            _LOGGER.debug("Already authenticated — skipping auth after reconnect")

    # ------------------------------------------------------------------
    # Internal: authentication
    # ------------------------------------------------------------------

    def _encode_pin(self, pin: str) -> bytes:
        pin = str(pin).zfill(4)
        return bytes(int(d) for d in pin)

    async def _authenticate(self) -> None:
        if not self._pin:
            _LOGGER.debug("No PIN configured — skipping auth")
            # Without PIN we consider auth "done"
            self._authenticated = True
            return

        pin_bytes = self._encode_pin(self._pin)
        payload = bytearray([
            0x0F, 0x0C, 0x17, 0x00, 0x00,
            *pin_bytes,
            0x00, 0x00, 0x00, 0x00,
            0x18 + sum(pin_bytes),
            0xFF, 0xFF,
        ])

        loop = asyncio.get_running_loop()
        auth_future: asyncio.Future[bool] = loop.create_future()

        # Temporarily wire a one-shot auth result handler
        self._pending_auth_future = auth_future

        try:
            await self._client.write_gatt_char(COMMAND_UUID, bytes(payload), response=False)
            result = await asyncio.wait_for(auth_future, timeout=5.0)
            if result:
                _LOGGER.debug("AUTH SUCCESS for %s", self._mac)
                self._authenticated = True
            else:
                _LOGGER.warning("AUTH FAILED (wrong PIN?) for %s", self._mac)
                self._authenticated = False
        except asyncio.TimeoutError:
            _LOGGER.warning("AUTH TIMEOUT for %s", self._mac)
            self._authenticated = False
        finally:
            self._pending_auth_future = None

    # ------------------------------------------------------------------
    # Internal: notify handler (single source of truth)
    # ------------------------------------------------------------------

    _pending_auth_future: asyncio.Future[bool] | None = None

    async def _handle_notify(
        self,
        sender: BleakGATTCharacteristic,
        data: bytearray,
    ) -> None:
        # --- Auth response ---
        if data.startswith(b"\x0F\x06\x17"):
            status = data[4]
            success = status == 0x00
            if not success:
                _LOGGER.warning("Auth response: FAILED (status=0x%02X)", status)
            if self._pending_auth_future and not self._pending_auth_future.done():
                self._pending_auth_future.set_result(success)
            return

        # --- Parsed payload ---
        payload: ParsedNotifyPayload | None = NotifyPayload.from_payload(data)

        if isinstance(payload, MeasureNotifyPayload):
            if self._switch_pending_state is not None:
                # Override is_on with our desired state until MEASURE confirms it
                self.notify_state.update_from_measure(payload, skip_is_on=True)
                self.notify_state.is_on = self._switch_pending_state
                # Clear pending once MEASURE confirms the plug has switched
                if payload.is_on == self._switch_pending_state:
                    self._switch_pending_state = None
            else:
                self.notify_state.update_from_measure(payload, skip_is_on=False)
            self._fire_callbacks()

        elif isinstance(payload, SwitchNotifyPayload):
            # SwitchNotify is only an ACK — plug does not encode new state in response.
            # Keep _switch_pending_state set so MEASURE-Notify continues to skip is_on
            # until MEASURE confirms the new state matches what we sent.
            pass

        else:
            _LOGGER.debug("Unknown notify payload: %s", data.hex())

    def _fire_callbacks(self) -> None:
        for cb in self._callbacks:
            try:
                cb()
            except Exception:
                _LOGGER.exception("Error in notify callback")

    # ------------------------------------------------------------------
    # Internal: disconnect handling + reconnect
    # ------------------------------------------------------------------

    def _on_disconnected(self, client: BleakClient) -> None:
        """Called by Bleak on unexpected disconnect."""
        _LOGGER.warning("BLE disconnected from %s", self._mac)
        self._notify_active = False
        # NOTE: do NOT reset self._authenticated here.
        # The device keeps auth state across short disconnects.
        # _authenticate() is idempotent anyway.
        self._schedule_reconnect()

    def _schedule_reconnect(self, attempt: int = 0) -> None:
        if self._shutdown:
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return  # Already scheduled

        self._reconnect_task = self._hass.loop.create_task(
            self._reconnect_loop(attempt)
        )

    async def _reconnect_loop(self, start_attempt: int = 0) -> None:
        attempt = start_attempt
        delay = RECONNECT_DELAY_BASE

        while not self._shutdown:
            if RECONNECT_MAX_ATTEMPTS and attempt >= RECONNECT_MAX_ATTEMPTS:
                _LOGGER.error(
                    "Max reconnect attempts (%d) reached for %s",
                    RECONNECT_MAX_ATTEMPTS,
                    self._mac,
                )
                return

            _LOGGER.info(
                "Reconnect attempt %d/%s for %s in %.1fs",
                attempt + 1,
                RECONNECT_MAX_ATTEMPTS or "∞",
                self._mac,
                delay,
            )

            await asyncio.sleep(delay)

            if self._shutdown:
                return

            await self._connect_and_setup()

            if self.is_connected:
                _LOGGER.info("Reconnected to %s after %d attempt(s)", self._mac, attempt + 1)
                return

            attempt += 1
            delay = min(delay * 2, RECONNECT_DELAY_MAX)

    async def _disconnect_client(self) -> None:
        if self._client is None:
            return
        try:
            if self._notify_active:
                await self._client.stop_notify(NOTIFY_UUID)
        except BleakError:
            pass
        try:
            await self._client.disconnect()
        except BleakError:
            pass
        self._client = None
        self._notify_active = False
        self._authenticated = False
