from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .ble_session import BLESessionManager
from .const import DOMAIN
from .coordinator import VoltcraftDataUpdateCoordinator

PLATFORMS = ["sensor", "switch", "button"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    mac_address: str = entry.data[CONF_MAC]
    pin: str | None = entry.data.get("pin")
    device_name: str | None = None

    # Grab device name from BLE discovery if available (best-effort)
    ble_device = bluetooth.async_ble_device_from_address(
        hass, mac_address, connectable=True
    )
    if ble_device:
        device_name = ble_device.name

    # Create session manager (does NOT connect yet)
    session = BLESessionManager(
        hass=hass,
        mac=mac_address,
        entry_id=entry.entry_id,
        pin=pin,
    )

    # Create coordinator (wires notify callback)
    coordinator = VoltcraftDataUpdateCoordinator(
        hass=hass,
        session=session,
        mac=mac_address,
        device_name=device_name,
    )

    # Start BLE session (connect + notify + auth)
    # Raises ConfigEntryNotReady if initial connect fails
    try:
        await session.async_start()
    except Exception as err:
        raise ConfigEntryNotReady(f"BLE session start failed: {err}") from err

    # First HA data refresh (sends MEASURE, waits for notify response)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: VoltcraftDataUpdateCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.session.async_stop()

    return unload_ok
