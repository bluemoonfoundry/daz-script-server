from __future__ import annotations

from ._node import DazNode, NodeIdentifier
from ._script_builder import ScriptBuilder


class DazCamera(DazNode):
    """Proxy for a ``DzCamera`` node.

    Extends :class:`~dazpy.DazNode` with optical and image-sensor properties.
    """

    @property
    def focal_length(self) -> float | None:
        """Focal length in millimetres (read/write)."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.focalLength;"
        )
        return self._client.execute(script).value

    @focal_length.setter
    def focal_length(self, value: float) -> None:
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.focalLength = {float(value)};"
        )
        self._client.execute(script)

    @property
    def fov(self) -> float | None:
        """Field of view in degrees (read-only; derived from focal length)."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.getFieldOfView();"
        )
        return self._client.execute(script).value

    @property
    def depth_of_field(self) -> bool | None:
        """Whether depth-of-field simulation is enabled (read/write)."""
        return self.get_property("Depth of Field")

    @depth_of_field.setter
    def depth_of_field(self, value: bool) -> None:
        self.set_property("Depth of Field", value)

    @property
    def frame_width(self) -> float | None:
        """Sensor / film-gate width in millimetres (read-only)."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.frameWidth;"
        )
        return self._client.execute(script).value

    @property
    def focal_distance(self) -> float | None:
        """Distance to the focus plane (read/write)."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.focalDistance;"
        )
        return self._client.execute(script).value

    @focal_distance.setter
    def focal_distance(self, value: float) -> None:
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.focalDistance = {float(value)};"
        )
        self._client.execute(script)

    @property
    def aspect_width(self) -> float | None:
        """Render aspect ratio width component (read/write)."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.aspectWidth;"
        )
        return self._client.execute(script).value

    @aspect_width.setter
    def aspect_width(self, value: float) -> None:
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.aspectWidth = {float(value)};"
        )
        self._client.execute(script)

    @property
    def aspect_height(self) -> float | None:
        """Render aspect ratio height component (read/write)."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.aspectHeight;"
        )
        return self._client.execute(script).value

    @aspect_height.setter
    def aspect_height(self, value: float) -> None:
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.aspectHeight = {float(value)};"
        )
        self._client.execute(script)

    @property
    def pixels_width(self) -> int | None:
        """Render image width in pixels (read/write)."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.pixelsWidth;"
        )
        return self._client.execute(script).value

    @pixels_width.setter
    def pixels_width(self, value: int) -> None:
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.pixelsWidth = {int(value)};"
        )
        self._client.execute(script)

    @property
    def pixels_height(self) -> int | None:
        """Render image height in pixels (read/write)."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.pixelsHeight;"
        )
        return self._client.execute(script).value

    @pixels_height.setter
    def pixels_height(self, value: int) -> None:
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.pixelsHeight = {int(value)};"
        )
        self._client.execute(script)

    @property
    def near_clipping_plane(self) -> float | None:
        """Near clipping plane distance (read-only)."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.nearClippingPlane;"
        )
        return self._client.execute(script).value

    @property
    def far_clipping_plane(self) -> float | None:
        """Far clipping plane distance (read-only)."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.farClippingPlane;"
        )
        return self._client.execute(script).value

    def aim_at(self, x: float, y: float, z: float) -> None:
        """Point the camera at a world-space coordinate.

        Args:
            x: Target X coordinate.
            y: Target Y coordinate.
            z: Target Z coordinate.
        """
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.aimAt(new DzVec3({float(x)}, {float(y)}, {float(z)}));"
        )
        self._client.execute(script)

    def focal_point(self) -> dict | None:
        """Return the world-space focal point as ``{"x", "y", "z"}``."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "var fp = _node.getFocalPoint(); return {x: fp.x, y: fp.y, z: fp.z};"
        )
        return self._client.execute(script).value

    def is_view_camera(self) -> bool | None:
        """Return ``True`` if this is the active viewport camera."""
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.isViewCamera();"
        )
        return self._client.execute(script).value
