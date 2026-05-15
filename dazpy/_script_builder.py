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
