"""
Cykl życia taska A2A — PRD sekcja 9.3 i 13.

Dwa backendy:
  InMemoryTaskManager — domyślny, zero zależności, wystarczający do testów i dev.
  PostgresTaskManager — produkcyjny, trwały, zgodny ze schematem z PRD sekcji 13.

Streaming SSE (publish_event/subscribe) działa tylko w pamięci danego procesu —
to wystarcza dla MVP: klient śledzi task w czasie, gdy jest on jeszcze "working"
na tym samym kontenerze, który go przyjął.
"""
import abc
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .errors import A2AError
from .schemas import Artifact, Task, TaskStatus, TERMINAL_STATUSES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskManager(abc.ABC):
    def __init__(self) -> None:
        self._event_queues: Dict[str, List["asyncio.Queue"]] = {}

    @abc.abstractmethod
    async def create_task(
        self,
        skill: str,
        input: Dict[str, Any],
        metadata: Dict[str, Any],
        context_id: Optional[str] = None,
    ) -> Task: ...

    @abc.abstractmethod
    async def get_task(self, task_id: str) -> Task: ...

    @abc.abstractmethod
    async def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        status_message: Optional[str] = None,
        output: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
    ) -> Task: ...

    @abc.abstractmethod
    async def add_artifact(self, task_id: str, artifact: Artifact) -> Task: ...

    async def cancel_task(self, task_id: str) -> Task:
        task = await self.get_task(task_id)
        if task.status in TERMINAL_STATUSES:
            raise A2AError(
                "TASK_CANCELLED",
                f"Task {task_id} jest już w statusie końcowym {task.status.value}",
            )
        return await self.update_status(
            task_id, TaskStatus.CANCELLED, status_message="Cancelled by caller"
        )

    # ── SSE pub/sub ────────────────────────────────────────────────────────────

    def subscribe(self, task_id: str) -> "asyncio.Queue":
        queue: "asyncio.Queue" = asyncio.Queue()
        self._event_queues.setdefault(task_id, []).append(queue)
        return queue

    def unsubscribe(self, task_id: str, queue: "asyncio.Queue") -> None:
        subs = self._event_queues.get(task_id, [])
        if queue in subs:
            subs.remove(queue)

    async def publish_event(self, task_id: str, event: str, data: Dict[str, Any]) -> None:
        for queue in list(self._event_queues.get(task_id, [])):
            await queue.put((event, data))


class InMemoryTaskManager(TaskManager):
    def __init__(self) -> None:
        super().__init__()
        self._tasks: Dict[str, Task] = {}

    async def create_task(self, skill, input, metadata, context_id=None) -> Task:
        task = Task(skill=skill, input=input, metadata=metadata, context_id=context_id)
        self._tasks[task.task_id] = task
        return task

    async def get_task(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise A2AError("TASK_NOT_FOUND", f"Task {task_id} nie istnieje")
        return task

    async def update_status(self, task_id, status, status_message=None, output=None, error=None) -> Task:
        task = await self.get_task(task_id)
        task.status = status
        task.updated_at = _now()
        if status_message is not None:
            task.status_message = status_message
        if output is not None:
            task.output = output
        if error is not None:
            task.error = error
        await self.publish_event(
            task_id,
            f"task.{status.value}",
            {"task_id": task_id, "status": status.value, "message": status_message},
        )
        return task

    async def add_artifact(self, task_id, artifact: Artifact) -> Task:
        task = await self.get_task(task_id)
        task.artifacts.append(artifact)
        task.updated_at = _now()
        await self.publish_event(
            task_id,
            "artifact.created",
            {"task_id": task_id, "artifact_id": artifact.artifact_id, "name": artifact.name},
        )
        return task


class PostgresTaskManager(TaskManager):
    """Trwały task manager — tabele a2a_tasks / a2a_artifacts (PRD sekcja 13)."""

    def __init__(self, dsn: str):
        super().__init__()
        self._dsn = dsn
        self._ensure_schema()

    def _connect(self):
        import psycopg2

        return psycopg2.connect(self._dsn)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS a2a_tasks (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        task_id TEXT UNIQUE NOT NULL,
                        context_id TEXT,
                        skill TEXT NOT NULL,
                        status TEXT NOT NULL,
                        status_message TEXT,
                        input_json JSONB NOT NULL,
                        output_json JSONB,
                        error_json JSONB,
                        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS a2a_artifacts (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        artifact_id TEXT UNIQUE NOT NULL,
                        task_id TEXT NOT NULL REFERENCES a2a_tasks(task_id),
                        mime_type TEXT NOT NULL,
                        name TEXT NOT NULL,
                        content_json JSONB,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    );
                    """
                )
            conn.commit()

    def _row_to_task(self, row, artifacts: List[Artifact]) -> Task:
        (task_id, context_id, skill, status, status_message,
         input_json, output_json, error_json, metadata_json,
         created_at, updated_at) = row
        return Task(
            task_id=task_id,
            context_id=context_id,
            skill=skill,
            status=TaskStatus(status),
            status_message=status_message,
            input=input_json or {},
            output=output_json,
            error=error_json,
            metadata=metadata_json or {},
            artifacts=artifacts,
            created_at=created_at.isoformat(),
            updated_at=updated_at.isoformat(),
        )

    def _fetch_artifacts(self, cur, task_id: str) -> List[Artifact]:
        cur.execute(
            "SELECT artifact_id, task_id, mime_type, name, content_json, created_at "
            "FROM a2a_artifacts WHERE task_id = %s ORDER BY created_at",
            (task_id,),
        )
        return [
            Artifact(
                artifact_id=r[0], task_id=r[1], type=r[2], name=r[3],
                content=r[4], created_at=r[5].isoformat(),
            )
            for r in cur.fetchall()
        ]

    async def create_task(self, skill, input, metadata, context_id=None) -> Task:
        return await asyncio.to_thread(self._create_task_sync, skill, input, metadata, context_id)

    def _create_task_sync(self, skill, input, metadata, context_id) -> Task:
        import psycopg2.extras

        task = Task(skill=skill, input=input, metadata=metadata, context_id=context_id)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO a2a_tasks
                        (task_id, context_id, skill, status, input_json, metadata_json, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        task.task_id, task.context_id, task.skill, task.status.value,
                        psycopg2.extras.Json(task.input), psycopg2.extras.Json(task.metadata),
                        task.created_at, task.updated_at,
                    ),
                )
            conn.commit()
        return task

    async def get_task(self, task_id: str) -> Task:
        return await asyncio.to_thread(self._get_task_sync, task_id)

    def _get_task_sync(self, task_id: str) -> Task:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT task_id, context_id, skill, status, status_message, input_json, "
                    "output_json, error_json, metadata_json, created_at, updated_at "
                    "FROM a2a_tasks WHERE task_id = %s",
                    (task_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise A2AError("TASK_NOT_FOUND", f"Task {task_id} nie istnieje")
                artifacts = self._fetch_artifacts(cur, task_id)
        return self._row_to_task(row, artifacts)

    async def update_status(self, task_id, status, status_message=None, output=None, error=None) -> Task:
        await asyncio.to_thread(self._update_status_sync, task_id, status, status_message, output, error)
        task = await self.get_task(task_id)
        await self.publish_event(
            task_id,
            f"task.{status.value}",
            {"task_id": task_id, "status": status.value, "message": status_message},
        )
        return task

    def _update_status_sync(self, task_id, status, status_message, output, error) -> None:
        import psycopg2.extras

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM a2a_tasks WHERE task_id = %s", (task_id,))
                if cur.fetchone() is None:
                    raise A2AError("TASK_NOT_FOUND", f"Task {task_id} nie istnieje")
                cur.execute(
                    """
                    UPDATE a2a_tasks
                    SET status = %s,
                        status_message = COALESCE(%s, status_message),
                        output_json = COALESCE(%s, output_json),
                        error_json = COALESCE(%s, error_json),
                        updated_at = now()
                    WHERE task_id = %s
                    """,
                    (
                        status.value, status_message,
                        psycopg2.extras.Json(output) if output is not None else None,
                        psycopg2.extras.Json(error) if error is not None else None,
                        task_id,
                    ),
                )
            conn.commit()

    async def add_artifact(self, task_id, artifact: Artifact) -> Task:
        await asyncio.to_thread(self._add_artifact_sync, task_id, artifact)
        task = await self.get_task(task_id)
        await self.publish_event(
            task_id,
            "artifact.created",
            {"task_id": task_id, "artifact_id": artifact.artifact_id, "name": artifact.name},
        )
        return task

    def _add_artifact_sync(self, task_id, artifact: Artifact) -> None:
        import psycopg2.extras

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM a2a_tasks WHERE task_id = %s", (task_id,))
                if cur.fetchone() is None:
                    raise A2AError("TASK_NOT_FOUND", f"Task {task_id} nie istnieje")
                cur.execute(
                    """
                    INSERT INTO a2a_artifacts (artifact_id, task_id, mime_type, name, content_json, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        artifact.artifact_id, task_id, artifact.type, artifact.name,
                        psycopg2.extras.Json(artifact.content), artifact.created_at,
                    ),
                )
            conn.commit()


def build_task_manager() -> TaskManager:
    """Wybiera backend na podstawie ENV TASK_BACKEND (memory|postgres), domyślnie memory."""
    import os

    backend = os.getenv("TASK_BACKEND", "memory").lower()
    if backend == "postgres":
        dsn = os.environ["DATABASE_URL"]
        return PostgresTaskManager(dsn)
    return InMemoryTaskManager()
