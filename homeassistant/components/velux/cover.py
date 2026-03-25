"""Support for Velux covers."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pyvlx import (
    Awning,
    Blind,
    DualRollerShutter,
    GarageDoor,
    Gate,
    Node,
    OpeningDevice,
    Position,
    RollerShutter,
    Window,
)

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
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
    """Set up cover(s) for Velux platform."""
    runtime_data = config_entry.runtime_data

    def _async_add_nodes(nodes: list[Node]) -> None:
        entities: list[VeluxCover] = []
        for node in nodes:
            entities.extend(_entities_for_node(node, config_entry.entry_id))
        if entities:
            async_add_entities(entities)

    config_entry.async_on_unload(
        runtime_data.register_new_node_callback(_async_add_nodes)
    )
    _async_add_nodes(runtime_data.nodes)


def _entities_for_node(node: Node, config_entry_id: str) -> list[VeluxCover]:
    """Create cover entities for a node."""
    if isinstance(node, Blind):
        return [VeluxBlind(node, config_entry_id)]
    if isinstance(node, DualRollerShutter):
        return [
            VeluxDualRollerShutter(node, config_entry_id, VeluxDualRollerPart.DUAL),
            VeluxDualRollerShutter(node, config_entry_id, VeluxDualRollerPart.UPPER),
            VeluxDualRollerShutter(node, config_entry_id, VeluxDualRollerPart.LOWER),
        ]
    if isinstance(node, OpeningDevice):
        return [VeluxCover(node, config_entry_id)]
    return []


class VeluxCover(VeluxEntity, CoverEntity):
    """Representation of a Velux cover."""

    node: OpeningDevice

    # Features common to all covers
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.STOP
    )

    def __init__(self, node: OpeningDevice, config_entry_id: str) -> None:
        """Initialize VeluxCover."""
        super().__init__(node, config_entry_id)
        match node:
            case Window():
                self._attr_device_class = CoverDeviceClass.WINDOW
            case Awning():
                self._attr_device_class = CoverDeviceClass.AWNING
            case GarageDoor():
                self._attr_device_class = CoverDeviceClass.GARAGE
            case Gate():
                self._attr_device_class = CoverDeviceClass.GATE
            case RollerShutter():
                self._attr_device_class = CoverDeviceClass.SHUTTER

    @property
    def current_cover_position(self) -> int:
        """Return the current position of the cover."""
        return 100 - self.node.position.position_percent

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed."""
        return self.node.position.closed

    @property
    def is_opening(self) -> bool:
        """Return if the cover is opening or not."""
        return self.node.is_opening

    @property
    def is_closing(self) -> bool:
        """Return if the cover is closing or not."""
        return self.node.is_closing

    @wrap_pyvlx_call_exceptions
    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self.node.close(wait_for_completion=False)

    @wrap_pyvlx_call_exceptions
    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self.node.open(wait_for_completion=False)

    @wrap_pyvlx_call_exceptions
    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        position_percent = 100 - kwargs[ATTR_POSITION]

        await self.node.set_position(
            Position(position_percent=position_percent), wait_for_completion=False
        )

    @wrap_pyvlx_call_exceptions
    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        await self.node.stop(wait_for_completion=False)


class VeluxDualRollerPart(StrEnum):
    """Enum for the parts of a dual roller shutter."""

    UPPER = "upper"
    LOWER = "lower"
    DUAL = "dual"


class VeluxDualRollerShutter(VeluxCover):
    """Representation of a Velux dual roller shutter cover."""

    node: DualRollerShutter
    _attr_device_class = CoverDeviceClass.SHUTTER

    def __init__(
        self, node: DualRollerShutter, config_entry_id: str, part: VeluxDualRollerPart
    ) -> None:
        """Initialize VeluxDualRollerShutter."""
        super().__init__(node, config_entry_id)
        if part == VeluxDualRollerPart.DUAL:
            self._attr_name = None
        else:
            self._attr_unique_id = f"{self._attr_unique_id}_{part}"
            self._attr_translation_key = f"dual_roller_shutter_{part}"
        self.part = part

    @property
    def current_cover_position(self) -> int:
        """Return the current position of the cover."""
        if self.part == VeluxDualRollerPart.UPPER:
            return 100 - self.node.position_upper_curtain.position_percent
        if self.part == VeluxDualRollerPart.LOWER:
            return 100 - self.node.position_lower_curtain.position_percent
        return 100 - self.node.position.position_percent

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed."""
        if self.part == VeluxDualRollerPart.UPPER:
            return self.node.position_upper_curtain.closed
        if self.part == VeluxDualRollerPart.LOWER:
            return self.node.position_lower_curtain.closed
        return self.node.position.closed

    @wrap_pyvlx_call_exceptions
    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self.node.close(curtain=self.part, wait_for_completion=False)

    @wrap_pyvlx_call_exceptions
    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self.node.open(curtain=self.part, wait_for_completion=False)

    @wrap_pyvlx_call_exceptions
    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        position_percent = 100 - kwargs[ATTR_POSITION]

        await self.node.set_position(
            Position(position_percent=position_percent),
            curtain=self.part,
            wait_for_completion=False,
        )


class VeluxBlind(VeluxCover):
    """Representation of a Velux blind cover."""

    node: Blind
    _attr_device_class = CoverDeviceClass.BLIND

    def __init__(self, node: Blind, config_entry_id: str) -> None:
        """Initialize VeluxBlind."""
        super().__init__(node, config_entry_id)

        self._attr_supported_features |= (
            CoverEntityFeature.OPEN_TILT
            | CoverEntityFeature.CLOSE_TILT
            | CoverEntityFeature.SET_TILT_POSITION
            | CoverEntityFeature.STOP_TILT
        )

    @property
    def current_cover_tilt_position(self) -> int | None:
        """Return the current tilt position of the cover."""
        return 100 - self.node.orientation.position_percent

    @wrap_pyvlx_call_exceptions
    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Close cover tilt."""
        await self.node.close_orientation(wait_for_completion=False)

    @wrap_pyvlx_call_exceptions
    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Open cover tilt."""
        await self.node.open_orientation(wait_for_completion=False)

    @wrap_pyvlx_call_exceptions
    async def async_stop_cover_tilt(self, **kwargs: Any) -> None:
        """Stop cover tilt."""
        await self.node.stop_orientation(wait_for_completion=False)

    @wrap_pyvlx_call_exceptions
    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Move cover tilt to a specific position."""
        position_percent = 100 - kwargs[ATTR_TILT_POSITION]
        orientation = Position(position_percent=position_percent)
        await self.node.set_orientation(
            orientation=orientation, wait_for_completion=False
        )
