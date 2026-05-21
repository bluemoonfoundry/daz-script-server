import json


class ScriptBuilder:
    @staticmethod
    def escape_string(value: str) -> str:
        return json.dumps(value)

    @staticmethod
    def iife(body: str) -> str:
        return f"(function(){{\n{body}\n}})()"

    @staticmethod
    def serialize_arg(value: object) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return json.dumps(value)
        return json.dumps(value)

    @staticmethod
    def find_node_expr(identifier: "NodeIdentifier") -> str:  # noqa: F821
        if identifier.kind == "label":
            return f"Scene.findNodeByLabel({json.dumps(identifier.value)})"
        return f"Scene.findNode({json.dumps(identifier.value)})"

    @staticmethod
    def node_body(identifier: "NodeIdentifier", body: str) -> str:  # noqa: F821
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
    def skeleton_lookup(identifier: "NodeIdentifier") -> str:  # noqa: F821
        """Return a JS snippet that finds a skeleton and binds it to ``_skel``.

        The snippet does not wrap itself in an IIFE — embed it at the top of
        a larger script body and follow it with ``if (!_skel) return null;``.
        """
        value = json.dumps(identifier.value)
        match = (
            f"_skels[_i].getLabel() === {value}"
            if identifier.kind == "label"
            else f"_skels[_i].getName() === {value}"
        )
        return (
            f"var _skel=null,_skels=Scene.getSkeletonList();"
            f"for(var _i=0;_i<_skels.length;_i++){{"
            f"if({match}){{_skel=_skels[_i];break;}}}}"
        )
