"""
Standardowe błędy A2A — patrz PRD sekcja 22.

Każdy błąd ma stały kod JSON-RPC i nazwę używaną też jako HTTP error code
w endpointach REST (agent-card, tasks/get, stream).
"""
from typing import Any, Dict, Optional

# Nazwa błędu -> (kod JSON-RPC, domyślny HTTP status)
ERROR_CODES = {
    "AGENT_NOT_FOUND": (-32001, 404),
    "SKILL_NOT_FOUND": (-32004, 400),
    "UNAUTHORIZED_AGENT": (-32010, 401),
    "FORBIDDEN_SKILL": (-32011, 403),
    "INVALID_MESSAGE": (-32602, 400),
    "TASK_NOT_FOUND": (-32002, 404),
    "TASK_CANCELLED": (-32020, 409),
    "TASK_TIMEOUT": (-32021, 504),
    "AGENT_UNAVAILABLE": (-32030, 503),
    "INTERNAL_ERROR": (-32603, 500),
}


class A2AError(Exception):
    def __init__(self, code: str, message: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        if code not in ERROR_CODES:
            code = "INTERNAL_ERROR"
        self.code = code
        self.rpc_code, self.http_status = ERROR_CODES[code]
        self.message = message or code
        self.data = data or {}
        super().__init__(self.message)

    def to_jsonrpc_error(self) -> Dict[str, Any]:
        return {
            "code": self.rpc_code,
            "message": self.code,
            "data": {"detail": self.message, **self.data},
        }
