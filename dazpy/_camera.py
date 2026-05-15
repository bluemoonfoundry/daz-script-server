from __future__ import annotations

from ._node import DazNode, NodeIdentifier
from ._script_builder import ScriptBuilder


class DazCamera(DazNode):
    @property
    def focal_length(self) -> float | None:
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
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.getFieldOfView();"
        )
        return self._client.execute(script).value

    @property
    def depth_of_field(self) -> bool | None:
        return self.get_property("Depth of Field")

    @depth_of_field.setter
    def depth_of_field(self, value: bool) -> None:
        self.set_property("Depth of Field", value)

    @property
    def frame_width(self) -> float | None:
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.frameWidth;"
        )
        return self._client.execute(script).value

    @property
    def focal_distance(self) -> float | None:
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
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.nearClippingPlane;"
        )
        return self._client.execute(script).value

    @property
    def far_clipping_plane(self) -> float | None:
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.farClippingPlane;"
        )
        return self._client.execute(script).value

    def aim_at(self, x: float, y: float, z: float) -> None:
        script = ScriptBuilder.node_body(
            self._identifier,
            f"_node.aimAt(new DzVec3({float(x)}, {float(y)}, {float(z)}));"
        )
        self._client.execute(script)

    def focal_point(self) -> dict | None:
        script = ScriptBuilder.node_body(
            self._identifier,
            "var fp = _node.getFocalPoint(); return {x: fp.x, y: fp.y, z: fp.z};"
        )
        return self._client.execute(script).value

    def is_view_camera(self) -> bool | None:
        script = ScriptBuilder.node_body(
            self._identifier,
            "return _node.isViewCamera();"
        )
        return self._client.execute(script).value
