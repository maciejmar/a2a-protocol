"""
Wspólne modele danych protokołu A2A (Agent-to-Agent).

Zakres zgodny koncepcyjnie z A2A 0.3 (Message, Task, Artifact, AgentCard) —
patrz PRD sekcja 9. To jest lokalny, minimalny model danych, nie pełna
implementacja referencyjna A2A.
"""
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


# ── Message ───────────────────────────────────────────────────────────────────

class Part(BaseModel):
    type: Literal["text", "json", "file"] = "text"
    text: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class Message(BaseModel):
    message_id: str = Field(default_factory=lambda: new_id("msg"))
    role: Literal["user", "agent", "system"] = "user"
    parts: List[Part] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def text(self) -> str:
        """Konkatenacja wszystkich części typu text — wygodny dostęp dla handlerów skilli."""
        return "\n".join(p.text for p in self.parts if p.type == "text" and p.text)


# ── Task ──────────────────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.EXPIRED,
}


class Artifact(BaseModel):
    artifact_id: str = Field(default_factory=lambda: new_id("art"))
    task_id: str
    type: str = "application/json"
    name: str
    content: Any = None
    created_at: str = Field(default_factory=_now)


class Task(BaseModel):
    task_id: str = Field(default_factory=lambda: new_id("task"))
    context_id: Optional[str] = None
    status: TaskStatus = TaskStatus.SUBMITTED
    skill: str
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    input: Dict[str, Any] = Field(default_factory=dict)
    output: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    artifacts: List[Artifact] = Field(default_factory=list)
    status_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Agent Card ────────────────────────────────────────────────────────────────

class AgentCapabilities(BaseModel):
    streaming: bool = True
    artifacts: bool = True
    taskCancellation: bool = True


class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    inputModes: List[str] = Field(default_factory=lambda: ["application/json"])
    outputModes: List[str] = Field(default_factory=lambda: ["application/json", "text/plain"])


class SecurityScheme(BaseModel):
    type: Literal["apiKey"] = "apiKey"
    in_: Literal["header"] = Field(default="header", alias="in")
    name: str = "X-Agent-Token"

    class Config:
        populate_by_name = True


class AgentCard(BaseModel):
    name: str
    description: str
    url: str
    version: str = "1.0.0"
    protocolVersion: str = "0.3.0"
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    defaultInputModes: List[str] = Field(default_factory=lambda: ["text/plain", "application/json"])
    defaultOutputModes: List[str] = Field(default_factory=lambda: ["text/plain", "application/json"])
    skills: List[AgentSkill] = Field(default_factory=list)
    securitySchemes: Dict[str, SecurityScheme] = Field(default_factory=dict)


# ── JSON-RPC envelope ─────────────────────────────────────────────────────────

class JSONRPCRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: Optional[str] = None
    method: str
    params: Dict[str, Any] = Field(default_factory=dict)


class JSONRPCErrorObj(BaseModel):
    code: int
    message: str
    data: Optional[Dict[str, Any]] = None


class JSONRPCResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[JSONRPCErrorObj] = None
