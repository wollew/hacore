"""Support for rain sensors built into some Velux windows."""

from __future__ import annotations

from datetime import timedelta

from pyvlx import Node, Position, PyVLXException, Window

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VeluxConfigEntry
from .const import LOGGER
from .entity import VeluxEntity

PARALLEL_UPDATES = 1
SCAN_INTERVAL = timedelta(minutes=5)  # Use standard polling


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: VeluxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up rain sensor(s) for Velux platform."""
    runtime_data = config_entry.runtime_data

    def _async_add_nodes(nodes: list[Node]) -> None:
        entities = [
            VeluxRainSensor(node, config_entry.entry_id)
            for node in nodes
            if isinstance(node, Window) and node.rain_sensor
        ]
        if entities:
            async_add_entities(entities)

    config_entry.async_on_unload(
        runtime_data.register_new_node_callback(_async_add_nodes)
    )
    _async_add_nodes(runtime_data.nodes)


class VeluxRainSensor(VeluxEntity, BinarySensorEntity):
    """Representation of a Velux rain sensor."""

    node: Window
    _attr_should_poll = True  # the rain sensor / opening limitations needs polling unlike the rest of the Velux devices
    _attr_entity_registry_enabled_default = False
    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_translation_key = "rain_sensor"
    _unavailable_logged = False

    def __init__(self, node: Window, config_entry_id: str) -> None:
        """Initialize VeluxRainSensor."""
        super().__init__(node, config_entry_id)
        self._attr_unique_id = f"{self._attr_unique_id}_rain_sensor"

    async def async_update(self) -> None:
        """Fetch the latest state from the device."""
        try:
            limitation: Position = await self.node.get_limitation_min()
        except (OSError, PyVLXException) as err:
            if not self._unavailable_logged:
                LOGGER.warning(
                    "Rain sensor %s is unavailable: %s",
                    self.entity_id,
                    err,
                )
                self._unavailable_logged = True
            self._attr_available = False
            return

        # Log when entity comes back online after being unavailable
        if self._unavailable_logged:
            LOGGER.info("Rain sensor %s is back online", self.entity_id)
            self._unavailable_logged = False

        self._attr_available = True

        # Velux windows with rain sensors report an opening limitation when rain is detected.
        # So far we've seen 89, 91, 93 (most cases) or 100 (Velux GPU). It probably makes sense to
        # assume that any large enough limitation (we use >=89) means rain is detected.
        # Documentation on this is non-existent AFAIK.
        self._attr_is_on = limitation.position_percent >= 89
