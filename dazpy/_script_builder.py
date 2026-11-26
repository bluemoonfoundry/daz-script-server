import json
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._node import NodeIdentifier


class ScriptBuilder:
    @staticmethod
    def escape_string(value: str) -> str:
        return json.dumps(value)

    @staticmethod
    def iife(body: str) -> str:
        return f"(function(){{\n{body}\n}})()"

    @staticmethod
    def js_num(value: object) -> str:
        """A finite number as a DazScript literal.

        Use this for every number interpolated into a script. ``str(nan)`` is
        ``nan``, which DazScript reads as an undefined identifier, and
        ``NaN``/``Infinity`` would write garbage into the scene, so non-finite
        values raise ``ValueError`` before any request is sent.
        """
        number = float(value)  # type: ignore[arg-type]
        if not math.isfinite(number):
            raise ValueError(f"expected a finite number, got {value!r}")
        return repr(number)

    @staticmethod
    def serialize_arg(value: object) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return ScriptBuilder.js_num(value)
        # allow_nan=False: NaN/Infinity inside a list or dict raise ValueError.
        return json.dumps(value, allow_nan=False)

    @staticmethod
    def find_node_expr(identifier: "NodeIdentifier") -> str:
        if identifier.kind == "label":
            return f"Scene.findNodeByLabel({json.dumps(identifier.value)})"
        if identifier.kind == "element_id":
            return f"Scene.findNodeByElementID({ScriptBuilder.element_id(identifier)})"
        return f"Scene.findNode({json.dumps(identifier.value)})"

    @staticmethod
    def element_id(identifier: "NodeIdentifier") -> int:
        """The integer elementID of an ``element_id`` identifier (validated)."""
        try:
            return int(str(identifier.value))
        except ValueError:
            raise ValueError(
                f"element_id identifier must be an integer, got {identifier.value!r}"
            ) from None

    @staticmethod
    def skeleton_match(identifier: "NodeIdentifier", item: str = "_skels[_i]") -> str:
        """JS condition that is true when skeleton *item* is the one *identifier* names."""
        if identifier.kind == "label":
            return f"{item}.getLabel() === {json.dumps(identifier.value)}"
        if identifier.kind == "element_id":
            return f"{item}.elementID === {ScriptBuilder.element_id(identifier)}"
        return f"{item}.getName() === {json.dumps(identifier.value)}"

    @staticmethod
    def node_body(identifier: "NodeIdentifier", body: str) -> str:
        expr = ScriptBuilder.find_node_expr(identifier)
        return ScriptBuilder.iife(
            f"var _node = {expr};\n"
            f"if (!_node) return null;\n"
            f"{body}"
        )

    @staticmethod
    def node_body_from_locator(locator: str, body: str) -> str:
        """Like node_body but uses a pre-built JS locator expression for _node."""
        return ScriptBuilder.iife(
            f"var _node = {locator};\n"
            f"if (!_node) return null;\n"
            f"{body}"
        )

    @staticmethod
    def skeleton_lookup(identifier: "NodeIdentifier") -> str:
        """Return a JS snippet that finds a skeleton and binds it to ``_skel``.

        The snippet does not wrap itself in an IIFE — embed it at the top of
        a larger script body and follow it with ``if (!_skel) return null;``.
        """
        match = ScriptBuilder.skeleton_match(identifier)
        return (
            f"var _skel=null,_skels=Scene.getSkeletonList();"
            f"for(var _i=0;_i<_skels.length;_i++){{"
            f"if({match}){{_skel=_skels[_i];break;}}}}"
        )
