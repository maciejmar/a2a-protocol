"""
Fixture wspólna dla testów integracyjnych: uruchamia agent-registry, orchestrator-agent
i rag-agent jako prawdziwe procesy uvicorn na lokalnych portach (TASK_BACKEND=memory,
bez Postgresa i bez prawdziwego rag-module — patrz RAG_BACKEND_URL="").

Każdy serwis startuje tak jak w kontenerze Docker: cwd na katalogu agenta (tam gdzie
leży pakiet "app"), PYTHONPATH wskazujący na repo root (dla "shared") + katalog agenta.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
A2A_TOKEN = "test-secret-token"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_healthy(url: str, proc: subprocess.Popen, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    last_exc = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
            raise RuntimeError(f"Proces zakończył się przedwcześnie (exit={proc.returncode}):\n{output}")
        try:
            resp = httpx.get(url, timeout=2.0)
            if resp.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_exc = exc
        time.sleep(0.3)
    raise RuntimeError(f"Serwis {url} nie odpowiedział w {timeout}s: {last_exc}")


def _spawn_service(service_dir: Path, port: int, extra_env: dict) -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{service_dir}"
    env.update(extra_env)
    return subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ],
        cwd=str(service_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


@pytest.fixture(scope="session")
def live_agents():
    registry_port = _free_port()
    orchestrator_port = _free_port()
    rag_port = _free_port()

    agents_yaml = {
        "agents": {
            "orchestrator-agent": {
                "enabled": True,
                "internal_url": f"http://127.0.0.1:{orchestrator_port}",
                "public_base_path": "/agents/orchestrator-agent",
                "card_url": f"http://127.0.0.1:{orchestrator_port}/.well-known/agent-card.json",
            },
            "rag-agent": {
                "enabled": True,
                "internal_url": f"http://127.0.0.1:{rag_port}",
                "public_base_path": "/agents/rag-agent",
                "card_url": f"http://127.0.0.1:{rag_port}/.well-known/agent-card.json",
            },
        }
    }
    tmp_dir = Path(tempfile.mkdtemp(prefix="a2a-test-"))
    agents_yaml_path = tmp_dir / "agents.yaml"
    agents_yaml_path.write_text(yaml.safe_dump(agents_yaml), encoding="utf-8")

    procs = []
    try:
        registry_proc = _spawn_service(
            REPO_ROOT / "services" / "agent-registry", registry_port,
            {"AGENTS_CONFIG": str(agents_yaml_path)},
        )
        procs.append(registry_proc)
        _wait_healthy(f"http://127.0.0.1:{registry_port}/health", registry_proc)

        orchestrator_proc = _spawn_service(
            REPO_ROOT / "agents" / "orchestrator-agent", orchestrator_port,
            {
                "AGENT_ID": "orchestrator-agent",
                "PUBLIC_BASE_URL": f"http://127.0.0.1:{orchestrator_port}",
                "AGENT_REGISTRY_URL": f"http://127.0.0.1:{registry_port}",
                "A2A_TOKEN": A2A_TOKEN,
                "A2A_ALLOWED_CALLERS": "*",
                "TASK_BACKEND": "memory",
                "TENANT_ID": "bgk",
                "APP_ID": "portal-ai",
            },
        )
        procs.append(orchestrator_proc)
        _wait_healthy(f"http://127.0.0.1:{orchestrator_port}/health", orchestrator_proc)

        rag_proc = _spawn_service(
            REPO_ROOT / "agents" / "rag-agent", rag_port,
            {
                "AGENT_ID": "rag-agent",
                "PUBLIC_BASE_URL": f"http://127.0.0.1:{rag_port}",
                "A2A_TOKEN": A2A_TOKEN,
                "A2A_ALLOWED_CALLERS": "*",
                "TASK_BACKEND": "memory",
                "RAG_BACKEND_URL": "",
            },
        )
        procs.append(rag_proc)
        _wait_healthy(f"http://127.0.0.1:{rag_port}/health", rag_proc)

        yield {
            "registry_url": f"http://127.0.0.1:{registry_port}",
            "orchestrator_url": f"http://127.0.0.1:{orchestrator_port}",
            "rag_url": f"http://127.0.0.1:{rag_port}",
            "token": A2A_TOKEN,
        }
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.fixture
def auth_headers(live_agents):
    def _headers(agent_id: str, tenant_id: str = "bgk", request_id: str = "req-test") -> dict:
        return {
            "X-Agent-Id": agent_id,
            "X-Agent-Token": live_agents["token"],
            "X-Tenant-Id": tenant_id,
            "X-Request-Id": request_id,
            "Content-Type": "application/json",
        }

    return _headers
