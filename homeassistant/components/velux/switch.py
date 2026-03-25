"""Support for Velux switches."""

from __future__ import annotations

from typing import Any

from pyvlx import Node, OnOffSwitch

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VeluxConfigEntry
from .entity import VeluxEntity, wrap_pyvlx_call_exceptions

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: VeluxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switch(es) for Velux platform."""
    runtime_data = config_entry.runtime_data

    def _async_add_nodes(nodes: list[Node]) -> None:
        entities = [
            VeluxOnOffSwitch(node, config_entry.entry_id)
            for node in nodes
            if isinstance(node, OnOffSwitch)
        ]
        if entities:
            async_add_entities(entities)

    config_entry.async_on_unload(
        runtime_data.register_new_node_callback(_async_add_nodes)
    )
    _async_add_nodes(runtime_data.nodes)


class VeluxOnOffSwitch(VeluxEntity, SwitchEntity):
    """Representation of a Velux on/off switch."""

    _attr_name = None

    node: OnOffSwitch

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self.node.is_on()

    @wrap_pyvlx_call_exceptions
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.node.set_on()

    @wrap_pyvlx_call_exceptions
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.node.set_off()
