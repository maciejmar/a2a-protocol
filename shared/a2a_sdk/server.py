"""
A2A Server SDK — wspólny FastAPI router dla każdego agenta (PRD sekcja 11).

Użycie:

    a2a = A2AServer(agent_id="rag-agent", agent_card=agent_card,
                     task_manager=task_manager, auth=auth_provider)

    @a2a.skill("rag.search")
    async def rag_search_handler(message, metadata):
        ...
        return {"answer": "...", "citations": []}

    app.include_router(a2a.router)

Endpointy wystawiane przez router:
    GET  /.well-known/agent-card.json
    POST /a2a/jsonrpc                       (message/send, tasks/get, tasks/cancel)
    GET  /a2a/tasks/{task_id}
    GET  /a2a/tasks/{task_id}/stream        (SSE)
    POST /a2a/tasks/{task_id}/cancel
    GET  /health

Handler skilla dostaje (message: Message, metadata: dict) i zwraca dict z wynikiem.
Zwrócony dict jest automatycznie zapisywany jako artifact "result.json" oraz jako
task.output, po czym task przechodzi w status completed.
"""
import asyncio
import json
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .artifact_store import json_artifact
from .auth import AuthContext, AuthProvider
from .errors import A2AError
from .logging import audit_log
from .schemas import (
    AgentCard,
    JSONRPCErrorObj,
    JSONRPCResponse,
    Message,
    Task,
    TaskStatus,
    TERMINAL_STATUSES,
)
from .task_manager import TaskManager

SkillHandler = Callable[[Message, Dict[str, Any]], Awaitable[Dict[str, Any]]]


class A2AServer:
    def __init__(self, agent_id: str, agent_card: AgentCard, task_manager: TaskManager, auth: AuthProvider):
        self.agent_id = agent_id
        self.agent_card = agent_card
        self.task_manager = task_manager
        self.auth = auth
        self._skills: Dict[str, SkillHandler] = {}
        self._running: Dict[str, "asyncio.Task"] = {}
        self.router = APIRouter()
        self._register_routes()

    def skill(self, skill_id: str):
        """Dekorator rejestrujący handler dla danego skilla (musi istnieć w agent_card.skills)."""

        def decorator(fn: SkillHandler) -> SkillHandler:
            self._skills[skill_id] = fn
            return fn

        return decorator

    # ── Routing ────────────────────────────────────────────────────────────────

    def _register_routes(self) -> None:
        router = self.router

        @router.get("/.well-known/agent-card.json")
        async def get_agent_card() -> dict:
            return self.agent_card.model_dump(by_alias=True)

        @router.get("/health")
        async def health() -> dict:
            return {"status": "ok", "agent": self.agent_id}

        @router.post("/a2a/jsonrpc")
        async def jsonrpc_endpoint(request: Request):
            return await self._dispatch(request)

        @router.get("/a2a/tasks/{task_id}")
        async def get_task_endpoint(task_id: str, request: Request):
            try:
                self.auth.verify(request)
                task = await self.task_manager.get_task(task_id)
                return self._task_result(task)
            except A2AError as exc:
                return self._error_response(exc)

        @router.post("/a2a/tasks/{task_id}/cancel")
        async def cancel_task_endpoint(task_id: str, request: Request):
            try:
                ctx = self.auth.verify(request)
                task = await self._cancel(task_id, ctx)
                return self._task_result(task)
            except A2AError as exc:
                return self._error_response(exc)

        @router.get("/a2a/tasks/{task_id}/stream")
        async def stream_task_endpoint(task_id: str, request: Request):
            try:
                self.auth.verify(request)
                task = await self.task_manager.get_task(task_id)
            except A2AError as exc:
                return self._error_response(exc)
            return StreamingResponse(self._event_generator(task), media_type="text/event-stream")

    async def _dispatch(self, request: Request):
        body = await request.json()
        req_id = body.get("id") if isinstance(body, dict) else None
        method = body.get("method") if isinstance(body, dict) else None
        params = body.get("params") or {} if isinstance(body, dict) else {}

        try:
            if method == "message/send":
                result = await self._handle_send(request, params)
            elif method == "tasks/get":
                result = await self._handle_get(request, params)
            elif method in ("tasks/cancel",):
                result = await self._handle_cancel(request, params)
            elif method == "tasks/resubscribe":
                result = await self._handle_get(request, params)
            else:
                raise A2AError("INVALID_MESSAGE", f"Nieznana metoda JSON-RPC: {method!r}")
            return JSONRPCResponse(id=req_id, result=result).model_dump()
        except A2AError as exc:
            payload = JSONRPCResponse(id=req_id, error=JSONRPCErrorObj(**exc.to_jsonrpc_error()))
            return JSONResponse(status_code=exc.http_status, content=payload.model_dump())

    # ── Metody JSON-RPC ────────────────────────────────────────────────────────

    async def _handle_send(self, request: Request, params: dict) -> dict:
        skill = params.get("skill")
        if not skill:
            raise A2AError("INVALID_MESSAGE", "Brak pola 'skill' w params")

        ctx = self.auth.verify(request, skill=skill)

        if skill not in self._skills:
            raise A2AError("SKILL_NOT_FOUND", f"Nieznany skill {skill!r}", data={"skill": skill})

        message_data = params.get("message")
        if not message_data:
            raise A2AError("INVALID_MESSAGE", "Brak pola 'message' w params")
        message = Message(**message_data)

        metadata = dict(params.get("metadata") or {})
        metadata.setdefault("caller_agent", ctx.agent_id)
        metadata.setdefault("tenant_id", ctx.tenant_id)
        metadata["target_agent"] = self.agent_id

        task = await self.task_manager.create_task(
            skill=skill,
            input={"message": message.model_dump(), "metadata": metadata},
            metadata=metadata,
            context_id=params.get("context_id"),
        )

        audit_log(
            request_id=ctx.request_id, task_id=task.task_id, tenant_id=ctx.tenant_id,
            caller_agent=ctx.agent_id, target_agent=self.agent_id, skill=skill,
            status=task.status.value, event="task_created",
        )

        asyncio_task = asyncio.create_task(self._run_skill(task.task_id, skill, message, metadata, ctx))
        self._running[task.task_id] = asyncio_task

        return {"task_id": task.task_id, "status": task.status.value}

    async def _handle_get(self, request: Request, params: dict) -> dict:
        self.auth.verify(request)
        task_id = params.get("task_id")
        if not task_id:
            raise A2AError("INVALID_MESSAGE", "Brak pola 'task_id' w params")
        task = await self.task_manager.get_task(task_id)
        return self._task_result(task)

    async def _handle_cancel(self, request: Request, params: dict) -> dict:
        ctx = self.auth.verify(request)
        task_id = params.get("task_id")
        if not task_id:
            raise A2AError("INVALID_MESSAGE", "Brak pola 'task_id' w params")
        task = await self._cancel(task_id, ctx)
        return self._task_result(task)

    async def _cancel(self, task_id: str, ctx: AuthContext) -> Task:
        task = await self.task_manager.cancel_task(task_id)
        running = self._running.pop(task_id, None)
        if running is not None and not running.done():
            running.cancel()
        audit_log(
            request_id=ctx.request_id, task_id=task_id, tenant_id=ctx.tenant_id,
            caller_agent=ctx.agent_id, target_agent=self.agent_id,
            status=task.status.value, event="task_cancelled",
        )
        return task

    # ── Wykonanie skilla w tle ─────────────────────────────────────────────────

    async def _run_skill(self, task_id: str, skill: str, message: Message, metadata: dict, ctx: AuthContext) -> None:
        handler = self._skills[skill]
        try:
            await self.task_manager.update_status(
                task_id, TaskStatus.WORKING, status_message=f"Wykonywanie skilla {skill}"
            )
            result = await handler(message, metadata)
            artifact = json_artifact(task_id, "result.json", result)
            await self.task_manager.add_artifact(task_id, artifact)
            await self.task_manager.update_status(task_id, TaskStatus.COMPLETED, output=result)
            audit_log(
                request_id=ctx.request_id, task_id=task_id, tenant_id=ctx.tenant_id,
                caller_agent=ctx.agent_id, target_agent=self.agent_id, skill=skill,
                status="completed", event="task_completed",
            )
        except asyncio.CancelledError:
            await self.task_manager.update_status(task_id, TaskStatus.CANCELLED, status_message="Cancelled")
            raise
        except A2AError as exc:
            await self.task_manager.update_status(
                task_id, TaskStatus.FAILED, status_message=exc.message, error=exc.to_jsonrpc_error()
            )
            audit_log(
                request_id=ctx.request_id, task_id=task_id, tenant_id=ctx.tenant_id,
                caller_agent=ctx.agent_id, target_agent=self.agent_id, skill=skill,
                status="failed", error_code=exc.code, event="task_failed",
            )
        except Exception as exc:  # noqa: BLE001 - błąd handlera nie może zabić serwera
            error = {"code": -32603, "message": "INTERNAL_ERROR", "data": {"detail": str(exc)}}
            await self.task_manager.update_status(
                task_id, TaskStatus.FAILED, status_message=str(exc), error=error
            )
            audit_log(
                request_id=ctx.request_id, task_id=task_id, tenant_id=ctx.tenant_id,
                caller_agent=ctx.agent_id, target_agent=self.agent_id, skill=skill,
                status="failed", error_code="INTERNAL_ERROR", event="task_failed",
            )
        finally:
            self._running.pop(task_id, None)

    # ── Pomocnicze ─────────────────────────────────────────────────────────────

    @staticmethod
    def _error_response(exc: A2AError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content={"detail": exc.code, "message": exc.message, "data": exc.data})

    @staticmethod
    def _task_result(task: Task) -> dict:
        return {
            "task_id": task.task_id,
            "context_id": task.context_id,
            "status": task.status.value,
            "status_message": task.status_message,
            "skill": task.skill,
            "output": task.output,
            "error": task.error,
            "artifacts": [a.model_dump() for a in task.artifacts],
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }

    @staticmethod
    def _sse_event(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"

    async def _event_generator(self, task: Task):
        yield self._sse_event(f"task.{task.status.value}", self._task_result(task))
        if task.status in TERMINAL_STATUSES:
            return

        queue = self.task_manager.subscribe(task.task_id)
        try:
            while True:
                try:
                    event, data = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield self._sse_event("heartbeat", {"task_id": task.task_id})
                    continue
                yield self._sse_event(event, data)
                if data.get("status") in {s.value for s in TERMINAL_STATUSES}:
                    break
        finally:
            self.task_manager.unsubscribe(task.task_id, queue)
