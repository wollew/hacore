"""Coordinator for VELUX KLF 200 devices."""

from __future__ import annotations

from asyncio import Lock
from collections.abc import Callable
from datetime import timedelta

from pyvlx import Node, PyVLX, PyVLXException

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, LOGGER

NODES_REFRESH_INTERVAL = timedelta(minutes=5)

type NodeAddedCallback = Callable[[list[Node]], None]


class VeluxRuntimeData(DataUpdateCoordinator[dict[int, Node]]):
    """Runtime data for a Velux config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        pyvlx: PyVLX,
    ) -> None:
        """Initialize runtime data."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=NODES_REFRESH_INTERVAL,
        )

        self.config_entry_id = config_entry.entry_id
        self.pyvlx = pyvlx
        self._new_node_callbacks: list[NodeAddedCallback] = []
        self._refresh_lock = Lock()
        self._known_nodes = self._current_nodes_by_id()

    @property
    def nodes(self) -> list[Node]:
        """Return the current node list."""
        return list(self.pyvlx.nodes)

    @property
    def scenes(self) -> list:
        """Return the current scene list."""
        return list(self.pyvlx.scenes)

    @callback
    def register_new_node_callback(
        self, callback_func: NodeAddedCallback
    ) -> Callable[[], None]:
        """Register a callback for newly discovered nodes."""
        self._new_node_callbacks.append(callback_func)

        @callback
        def unregister() -> None:
            if callback_func in self._new_node_callbacks:
                self._new_node_callbacks.remove(callback_func)

        return unregister

    async def _async_update_data(self) -> dict[int, Node]:
        """Refresh nodes and notify platforms about changes."""
        async with self._refresh_lock:
            try:
                await self.pyvlx.load_nodes()
            except (OSError, PyVLXException) as err:
                LOGGER.warning("Unable to refresh Velux nodes: %s", err)
                return self._known_nodes

            current_nodes = self._current_nodes_by_id()
            if current_nodes.keys() == self._known_nodes.keys():
                self._known_nodes = current_nodes
                return current_nodes

            removed_node_ids = self._known_nodes.keys() - current_nodes.keys()
            self._async_remove_stale_devices(removed_node_ids)

            if new_node_ids := current_nodes.keys() - self._known_nodes.keys():
                new_nodes = [current_nodes[node_id] for node_id in new_node_ids]
                for callback_func in list(self._new_node_callbacks):
                    callback_func(new_nodes)

            self._known_nodes = current_nodes
            return current_nodes

    @callback
    def _async_remove_stale_devices(self, removed_node_ids: set[int]) -> None:
        """Remove stale devices from the device registry."""
        device_registry = dr.async_get(self.hass)
        for node_id in removed_node_ids:
            if (node := self._known_nodes.get(node_id)) is None:
                continue

            if device := device_registry.async_get_device(
                identifiers={(DOMAIN, self._node_identifier(node))}
            ):
                device_registry.async_update_device(
                    device_id=device.id,
                    remove_config_entry_id=self.config_entry_id,
                )

    def _current_nodes_by_id(self) -> dict[int, Node]:
        """Return the current nodes keyed by node ID."""
        return {node.node_id: node for node in self.pyvlx.nodes}

    def _node_identifier(self, node: Node) -> str:
        """Return the device identifier used by Velux entities."""
        return node.serial_number or f"{self.config_entry_id}_{node.node_id}"


type VeluxConfigEntry = ConfigEntry[VeluxRuntimeData]
