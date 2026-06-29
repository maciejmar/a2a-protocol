"""
Agent Registry — PRD sekcja 8.

Środowisko jest zamknięte (brak Internetu, brak discovery zewnętrznego), więc
agenci odnajdują się wzajemnie przez lokalny rejestr wczytywany z config/agents.yaml.

Ten moduł zawiera:
  - AgentEntry / load_agents_yaml — używane przez services/agent-registry (serwer rejestru)
  - RegistryClient — używany przez A2AClient do znajdowania innych agentów
"""
from dataclasses import dataclass
from typing import Dict, Optional

import httpx
import yaml

from .errors import A2AError


@dataclass
class AgentEntry:
    agent_id: str
    enabled: bool
    internal_url: str
    public_base_path: str
    card_url: str


def load_agents_yaml(path: str) -> Dict[str, AgentEntry]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    agents = raw.get("agents", {})
    return {
        agent_id: AgentEntry(
            agent_id=agent_id,
            enabled=cfg.get("enabled", True),
            internal_url=cfg["internal_url"],
            public_base_path=cfg["public_base_path"],
            card_url=cfg["card_url"],
        )
        for agent_id, cfg in agents.items()
    }


class RegistryClient:
    """Klient HTTP do serwisu agent-registry — odnajdywanie agenta po jego ID."""

    def __init__(self, registry_url: str, timeout: float = 10.0):
        self._registry_url = registry_url.rstrip("/")
        self._timeout = timeout

    async def list_agents(self) -> Dict[str, dict]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._registry_url}/registry/agents")
            resp.raise_for_status()
            return resp.json()

    async def get_agent(self, agent_id: str) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._registry_url}/registry/agents/{agent_id}")
            if resp.status_code == 404:
                raise A2AError("AGENT_NOT_FOUND", f"Agent {agent_id!r} nie jest zarejestrowany")
            resp.raise_for_status()
            return resp.json()

    async def get_agent_card(self, agent_id: str) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._registry_url}/registry/agents/{agent_id}/card")
            if resp.status_code == 404:
                raise A2AError("AGENT_NOT_FOUND", f"Agent {agent_id!r} nie jest zarejestrowany")
            if resp.status_code >= 400:
                raise A2AError("AGENT_UNAVAILABLE", f"Nie udało się pobrać Agent Card dla {agent_id!r}")
            return resp.json()
