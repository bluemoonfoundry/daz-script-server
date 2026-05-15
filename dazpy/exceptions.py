class DazError(Exception):
    pass


class ConnectionError(DazError):
    pass


class AuthenticationError(DazError):
    pass


class ScriptError(DazError):
    def __init__(self, message: str, script: str = "", request_id: str = ""):
        super().__init__(message)
        self.script = script
        self.request_id = request_id

    @property
    def diagnostic(self) -> str:
        lines = []
        if self.script:
            numbered = "\n".join(f"{i+1:4d}: {line}" for i, line in enumerate(self.script.splitlines()))
            lines.append(numbered)
        lines.append(str(self))
        if self.request_id:
            lines.append(f"request_id: {self.request_id}")
        return "\n".join(lines)


class ScriptSyntaxError(ScriptError):
    pass


class ScriptRuntimeError(ScriptError):
    pass


class TimeoutError(DazError):
    pass


class NodeNotFoundError(DazError):
    pass


class AsyncExecutionError(DazError):
    def __init__(self, message: str, request_id: str = ""):
        super().__init__(message)
        self.request_id = request_id
