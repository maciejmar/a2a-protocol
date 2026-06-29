"""
A2A Client SDK — PRD sekcja 12.

Użycie:

    client = A2AClient(registry_url="http://agent-registry:8000",
                        agent_id="orchestrator-agent", token_provider="change_me")

    task = await client.send_message(target_agent="rag-agent", skill="rag.search",
                                      text="...", metadata={"tenant_id": "bgk"})
    result = await client.wait_for_task(target_agent="rag-agent", task_id=task.task_id,
                                         timeout_seconds=120)
"""
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Dict, Optional, Tuple, Union

import httpx

from .errors import A2AError
from .registry import RegistryClient
from .schemas import AgentCard, TERMINAL_STATUSES, new_id

TokenProvider = Union[str, Callable[[], str]]


@dataclass
class SendResult:
    task_id: str
    status: str
    target_agent: str


class A2AClient:
    def __init__(
        self,
        registry_url: str,
        agent_id: str,
        token_provider: TokenProvider,
        tenant_id: str = "",
        app_id: str = "",
        timeout: float = 30.0,
        retries: int = 2,
    ):
        self.registry = RegistryClient(registry_url)
        self.agent_id = agent_id
        self.tenant_id = tenant_id
        self.app_id = app_id
        self.timeout = timeout
        self.retries = retries
        self._token_provider: Callable[[], str] = (
            token_provider if callable(token_provider) else (lambda: token_provider)
        )
        self._card_cache: Dict[str, AgentCard] = {}
        self._url_cache: Dict[str, str] = {}

    def _headers(self, request_id: Optional[str] = None) -> dict:
        return {
            "X-Agent-Id": self.agent_id,
            "X-Agent-Token": self._token_provider(),
            "X-Tenant-Id": self.tenant_id,
            "X-Request-Id": request_id or new_id("req"),
            "Content-Type": "application/json",
        }

    # ── Discovery ──────────────────────────────────────────────────────────────

    async def get_agent_card(self, target_agent: str, force_refresh: bool = False) -> AgentCard:
        if not force_refresh and target_agent in self._card_cache:
            return self._card_cache[target_agent]
        card_data = await self.registry.get_agent_card(target_agent)
        card = AgentCard(**card_data)
        self._card_cache[target_agent] = card
        return card

    async def _agent_base_url(self, target_agent: str) -> str:
        if target_agent not in self._url_cache:
            entry = await self.registry.get_agent(target_agent)
            self._url_cache[target_agent] = entry["internal_url"].rstrip("/")
        return self._url_cache[target_agent]

    @staticmethod
    def _validate_skill(card: AgentCard, skill: str) -> None:
        skill_ids = {s.id for s in card.skills}
        if skill not in skill_ids:
            raise A2AError(
                "SKILL_NOT_FOUND",
                f"Agent {card.name!r} nie udostępnia skilla {skill!r}",
                data={"skill": skill, "available": sorted(skill_ids)},
            )

    # ── message/send ───────────────────────────────────────────────────────────

    async def send_message(
        self,
        target_agent: str,
        skill: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        context_id: Optional[str] = None,
    ) -> SendResult:
        card = await self.get_agent_card(target_agent)
        self._validate_skill(card, skill)
        base_url = await self._agent_base_url(target_agent)

        merged_metadata = {"caller_agent": self.agent_id, "tenant_id": self.tenant_id, "app_id": self.app_id}
        merged_metadata.update(metadata or {})

        payload = {
            "jsonrpc": "2.0",
            "id": new_id("req"),
            "method": "message/send",
            "params": {
                "skill": skill,
                "message": {"role": "user", "parts": [{"type": "text", "text": text}]},
                "metadata": merged_metadata,
                "context_id": context_id,
            },
        }

        data = await self._post_jsonrpc(base_url, payload, target_agent)
        result = data["result"]
        return SendResult(task_id=result["task_id"], status=result["status"], target_agent=target_agent)

    async def _post_jsonrpc(self, base_url: str, payload: dict, target_agent: str) -> dict:
        request_id = payload["id"]
        last_exc: Optional[Exception] = None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.retries + 1):
                try:
                    resp = await client.post(
                        f"{base_url}/a2a/jsonrpc", json=payload, headers=self._headers(request_id)
                    )
                except httpx.RequestError as exc:
                    last_exc = exc
                    await asyncio.sleep(min(2 ** attempt, 5))
                    continue

                if resp.status_code >= 500:
                    last_exc = RuntimeError(f"HTTP {resp.status_code} from {target_agent}")
                    await asyncio.sleep(min(2 ** attempt, 5))
                    continue

                data = resp.json()
                if data.get("error"):
                    err = data["error"]
                    raise A2AError(
                        err.get("message", "INTERNAL_ERROR"),
                        (err.get("data") or {}).get("detail"),
                        data=err.get("data"),
                    )
                return data

        raise A2AError("AGENT_UNAVAILABLE", f"Nie udało się połączyć z {target_agent}: {last_exc}")

    # ── tasks/get (polling) ────────────────────────────────────────────────────

    async def wait_for_task(
        self,
        target_agent: str,
        task_id: str,
        timeout_seconds: float = 120.0,
        poll_interval: float = 1.0,
    ) -> dict:
        base_url = await self._agent_base_url(target_agent)
        deadline = time.monotonic() + timeout_seconds

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while True:
                resp = await client.get(f"{base_url}/a2a/tasks/{task_id}", headers=self._headers())
                if resp.status_code == 404:
                    raise A2AError("TASK_NOT_FOUND", f"Task {task_id} nie istnieje na {target_agent}")
                resp.raise_for_status()
                task = resp.json()
                if task["status"] in {s.value for s in TERMINAL_STATUSES}:
                    return task
                if time.monotonic() > deadline:
                    raise A2AError(
                        "TASK_TIMEOUT", f"Task {task_id} na {target_agent} nie zakończył się w {timeout_seconds}s"
                    )
                await asyncio.sleep(poll_interval)

    async def get_task(self, target_agent: str, task_id: str) -> dict:
        base_url = await self._agent_base_url(target_agent)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{base_url}/a2a/tasks/{task_id}", headers=self._headers())
            if resp.status_code == 404:
                raise A2AError("TASK_NOT_FOUND", f"Task {task_id} nie istnieje na {target_agent}")
            resp.raise_for_status()
            return resp.json()

    async def cancel_task(self, target_agent: str, task_id: str) -> dict:
        base_url = await self._agent_base_url(target_agent)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{base_url}/a2a/tasks/{task_id}/cancel", headers=self._headers())
            if resp.status_code == 404:
                raise A2AError("TASK_NOT_FOUND", f"Task {task_id} nie istnieje na {target_agent}")
            resp.raise_for_status()
            return resp.json()

    # ── SSE stream ─────────────────────────────────────────────────────────────

    async def stream_task(self, target_agent: str, task_id: str) -> AsyncIterator[Tuple[str, dict]]:
        base_url = await self._agent_base_url(target_agent)
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "GET", f"{base_url}/a2a/tasks/{task_id}/stream", headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                event_name = "message"
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("event:"):
                        event_name = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        data = json.loads(line[len("data:"):].strip())
                        yield event_name, data
