"""Wczytywanie i odpytywanie lokalnego rejestru agentów (config/agents.yaml)."""
import os
from typing import Dict, Optional

import httpx

from shared.a2a_sdk.registry import AgentEntry, load_agents_yaml

AGENTS_CONFIG = os.getenv("AGENTS_CONFIG", "/config/agents.yaml")


class RegistryStore:
    def __init__(self, config_path: str):
        self._config_path = config_path
        self._agents: Dict[str, AgentEntry] = {}
        self.reload()

    def reload(self) -> None:
        self._agents = load_agents_yaml(self._config_path)

    def list_agents(self) -> Dict[str, AgentEntry]:
        return dict(self._agents)

    def get(self, agent_id: str) -> Optional[AgentEntry]:
        entry = self._agents.get(agent_id)
        return entry if entry and entry.enabled else None

    def fetch_card(self, agent_id: str) -> Optional[dict]:
        entry = self.get(agent_id)
        if entry is None:
            return None
        resp = httpx.get(entry.card_url, timeout=10)
        resp.raise_for_status()
        return resp.json()


store = RegistryStore(AGENTS_CONFIG)
