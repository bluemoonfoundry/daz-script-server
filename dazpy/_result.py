from dataclasses import dataclass, field


@dataclass
class ExecutionResult:
    value: object
    output: list[str] = field(default_factory=list)
    request_id: str = ""
    success: bool = True
    error: str = ""
    duration_ms: float = 0.0
