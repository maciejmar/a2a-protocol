"""
Autoryzacja service-to-service przez nagłówki — PRD sekcja 15 (MVP).

Każdy request A2A musi nieść:
  X-Agent-Id, X-Agent-Token, X-Tenant-Id, X-Request-Id

Model bezpieczeństwa MVP — wspólny sekret per agent (zgodnie z docker-compose
z PRD sekcji 17, gdzie każdy agent ma swój A2A_TOKEN):
  - agent odbierający request zna jeden token (A2A_TOKEN) i porównuje go z nagłówkiem,
  - dodatkowo może ograniczyć, którzy callerzy (X-Agent-Id) mogą do niego dzwonić
    (A2A_ALLOWED_CALLERS) i do jakich skilli (A2A_SKILL_SCOPES).

Docelowo (poza MVP): JWT service-to-service, mTLS, Vault, per-peer tokeny — patrz README.
"""
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from fastapi import Request

from .errors import A2AError
from .schemas import new_id


@dataclass
class AuthContext:
    agent_id: str
    tenant_id: str
    request_id: str


class AuthProvider:
    def __init__(
        self,
        token: str,
        allowed_callers: Optional[List[str]] = None,
        skill_scopes: Optional[Dict[str, List[str]]] = None,
    ):
        self.token = token
        self.allowed_callers = allowed_callers  # None => każdy X-Agent-Id zaakceptowany (przy poprawnym tokenie)
        self.skill_scopes = skill_scopes or {}  # agent_id -> lista dozwolonych skilli; brak wpisu = bez ograniczeń

    @classmethod
    def from_env(cls) -> "AuthProvider":
        """
        ENV:
          A2A_TOKEN             — wymagany, sekret który musi nieść X-Agent-Token
          A2A_ALLOWED_CALLERS   — opcjonalny, lista po przecinku ("*" lub puste = każdy)
          A2A_SKILL_SCOPES      — opcjonalny JSON: {"orchestrator-agent": ["rag.search"]}
        """
        token = os.environ["A2A_TOKEN"]

        callers_raw = os.getenv("A2A_ALLOWED_CALLERS", "*").strip()
        allowed_callers = None if callers_raw in ("", "*") else [c.strip() for c in callers_raw.split(",") if c.strip()]

        try:
            skill_scopes = json.loads(os.getenv("A2A_SKILL_SCOPES", "{}"))
        except json.JSONDecodeError:
            skill_scopes = {}

        return cls(token=token, allowed_callers=allowed_callers, skill_scopes=skill_scopes)

    def verify(self, request: Request, skill: Optional[str] = None) -> AuthContext:
        agent_id = request.headers.get("X-Agent-Id")
        token = request.headers.get("X-Agent-Token")
        tenant_id = request.headers.get("X-Tenant-Id", "")
        request_id = request.headers.get("X-Request-Id") or new_id("req")

        if not agent_id:
            raise A2AError("UNAUTHORIZED_AGENT", "Brak nagłówka X-Agent-Id")

        if self.allowed_callers is not None and agent_id not in self.allowed_callers:
            raise A2AError("UNAUTHORIZED_AGENT", f"Agent {agent_id!r} nie jest na allowliście callerów")

        if not token or token != self.token:
            raise A2AError("UNAUTHORIZED_AGENT", "Nieprawidłowy X-Agent-Token")

        if skill is not None:
            allowed_skills = self.skill_scopes.get(agent_id)
            if allowed_skills is not None and skill not in allowed_skills:
                raise A2AError("FORBIDDEN_SKILL", f"{agent_id} nie ma uprawnień do skilla {skill!r}")

        return AuthContext(agent_id=agent_id, tenant_id=tenant_id, request_id=request_id)
