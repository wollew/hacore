"""Tests for Velux integration initialization and retry behavior.

These tests verify that setup retries (ConfigEntryNotReady) are triggered
when scene or node loading fails.

They also verify that unloading the integration properly disconnects.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pyvlx.exception import PyVLXException

from homeassistant.components.velux.const import DOMAIN
from homeassistant.components.velux.coordinator import NODES_REFRESH_INTERVAL
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component

from tests.common import (
    AsyncMock,
    ConfigEntry,
    MockConfigEntry,
    async_fire_time_changed,
)


async def test_setup_retry_on_nodes_failure(
    mock_config_entry: ConfigEntry, hass: HomeAssistant, mock_pyvlx: AsyncMock
) -> None:
    """Test that a failure loading nodes triggers setup retry.

    The integration loads scenes first, then nodes. If loading raises PyVLXException,
    (which could have a multitude of reasons, unfortunately there are no specialized
    exceptions that give a reason), the ConfigEntry should enter SETUP_RETRY.
    """

    mock_pyvlx.load_nodes.side_effect = PyVLXException("nodes boom")
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    mock_pyvlx.load_scenes.assert_awaited_once()
    mock_pyvlx.load_nodes.assert_awaited_once()


async def test_setup_retry_on_oserror_during_scenes(
    mock_config_entry: ConfigEntry, hass: HomeAssistant, mock_pyvlx: AsyncMock
) -> None:
    """Test that OSError during scene loading triggers setup retry.

    OSError typically indicates network/connection issues when the gateway
    refuses connections or is unreachable.
    """

    mock_pyvlx.load_scenes.side_effect = OSError("Connection refused")
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    mock_pyvlx.load_scenes.assert_awaited_once()
    mock_pyvlx.load_nodes.assert_not_called()


async def test_setup_auth_error(
    mock_config_entry: ConfigEntry, hass: HomeAssistant, mock_pyvlx: AsyncMock
) -> None:
    """Test that PyVLXException with auth message raises ConfigEntryAuthFailed and starts reauth flow."""

    mock_pyvlx.load_scenes.side_effect = PyVLXException(
        "Login to KLF 200 failed, check credentials"
    )
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # ConfigEntryAuthFailed results in SETUP_ERROR state
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["step_id"] == "reauth_confirm"

    mock_pyvlx.load_scenes.assert_awaited_once()
    mock_pyvlx.load_nodes.assert_not_called()


@pytest.fixture
def platform() -> Platform:
    """Fixture to specify platform to test."""
    return Platform.COVER


@pytest.mark.usefixtures("setup_integration")
async def test_unload_calls_disconnect(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_pyvlx
) -> None:
    """Test that unloading the config entry disconnects from the gateway."""

    # Unload the entry
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Verify disconnect was called
    mock_pyvlx.disconnect.assert_awaited_once()


@pytest.mark.usefixtures("setup_integration")
async def test_unload_does_not_disconnect_if_platform_unload_fails(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_pyvlx
) -> None:
    """Test that disconnect is not called if platform unload fails."""

    # Mock platform unload to fail
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        return_value=False,
    ):
        result = await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Verify unload failed
    assert result is False

    # Verify disconnect was NOT called since platform unload failed
    mock_pyvlx.disconnect.assert_not_awaited()


@pytest.mark.usefixtures("setup_integration")
async def test_reboot_gateway_service_raises_on_exception(
    hass: HomeAssistant, mock_pyvlx: AsyncMock
) -> None:
    """Test that reboot_gateway service raises HomeAssistantError on exception."""

    mock_pyvlx.reboot_gateway.side_effect = OSError("Connection failed")
    with pytest.raises(HomeAssistantError, match="Failed to reboot gateway"):
        await hass.services.async_call(
            "velux",
            "reboot_gateway",
            blocking=True,
        )

    mock_pyvlx.reboot_gateway.side_effect = PyVLXException("Reboot failed")
    with pytest.raises(HomeAssistantError, match="Failed to reboot gateway"):
        await hass.services.async_call(
            "velux",
            "reboot_gateway",
            blocking=True,
        )


async def test_reboot_gateway_service_raises_validation_error(
    hass: HomeAssistant,
) -> None:
    """Test that reboot_gateway service raises ServiceValidationError when no gateway is loaded."""
    # Set up the velux integration's async_setup to register the service
    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError, match="No loaded Velux gateway found"):
        await hass.services.async_call(
            "velux",
            "reboot_gateway",
            blocking=True,
        )


@pytest.mark.parametrize("mock_pyvlx", ["mock_window"], indirect=True)
async def test_dynamic_devices_add_and_remove_nodes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_pyvlx: AsyncMock,
    mock_window: AsyncMock,
    mock_window_added: AsyncMock,
    device_registry: dr.DeviceRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test dynamic addition and removal of Velux node-backed devices."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.velux.PLATFORMS",
        [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.COVER],
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert (
        len(
            dr.async_entries_for_config_entry(
                device_registry, mock_config_entry.entry_id
            )
        )
        == 2
    )
    assert hass.states.get("cover.test_window") is not None
    assert hass.states.get("button.test_window_identify") is not None

    mock_pyvlx.nodes.append(mock_window_added)

    freezer.tick(NODES_REFRESH_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert (
        len(
            dr.async_entries_for_config_entry(
                device_registry, mock_config_entry.entry_id
            )
        )
        == 3
    )
    assert hass.states.get("cover.new_window") is not None
    assert hass.states.get("button.new_window_identify") is not None

    mock_pyvlx.nodes.remove(mock_window)

    freezer.tick(NODES_REFRESH_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert (
        len(
            dr.async_entries_for_config_entry(
                device_registry, mock_config_entry.entry_id
            )
        )
        == 2
    )
    assert (
        device_registry.async_get_device(
            identifiers={(DOMAIN, mock_window.serial_number)}
        )
        is None
    )
    assert hass.states.get("cover.test_window") is None
    assert hass.states.get("button.test_window_identify") is None


@pytest.mark.parametrize("mock_pyvlx", ["mock_window"], indirect=True)
async def test_dynamic_devices_add_dual_roller_shutter_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_pyvlx: AsyncMock,
    mock_dual_roller_shutter: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test dynamically adding a dual roller shutter creates all cover entities."""
    mock_config_entry.add_to_hass(hass)

    with patch("homeassistant.components.velux.PLATFORMS", [Platform.COVER]):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)

    mock_pyvlx.nodes.append(mock_dual_roller_shutter)

    freezer.tick(NODES_REFRESH_INTERVAL + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get("cover.test_dual_roller_shutter") is not None
    assert hass.states.get("cover.test_dual_roller_shutter_upper_shutter") is not None
    assert hass.states.get("cover.test_dual_roller_shutter_lower_shutter") is not None
