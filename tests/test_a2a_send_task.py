"""
Scenariusz z PRD sekcji 18 i 23: message/send -> task_id -> tasks/get -> artifact.
Druga część testuje pełną delegację orchestrator-agent -> A2A -> rag-agent.
"""
import time

import httpx


def _send_rag_search(live_agents, auth_headers, text: str):
    payload = {
        "jsonrpc": "2.0",
        "id": "req-send",
        "method": "message/send",
        "params": {
            "skill": "rag.search",
            "message": {"role": "user", "parts": [{"type": "text", "text": text}]},
            "metadata": {"tenant_id": "bgk", "app_id": "portal-ai", "caller_agent": "orchestrator-agent"},
        },
    }
    resp = httpx.post(
        f"{live_agents['rag_url']}/a2a/jsonrpc", json=payload, headers=auth_headers("orchestrator-agent"), timeout=5
    )
    assert resp.status_code == 200
    return resp.json()["result"]


def _poll_until_terminal(url: str, headers: dict, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    task = None
    while time.monotonic() < deadline:
        resp = httpx.get(url, headers=headers, timeout=5)
        assert resp.status_code == 200
        task = resp.json()
        if task["status"] in {"completed", "failed", "cancelled"}:
            return task
        time.sleep(0.2)
    raise AssertionError(f"Task nie zakończył się w {timeout}s, ostatni status: {task}")


def test_send_task_and_get_result(live_agents, auth_headers):
    result = _send_rag_search(live_agents, auth_headers, "Test komunikacji A2A")
    assert result["status"] == "submitted"
    task_id = result["task_id"]

    task = _poll_until_terminal(
        f"{live_agents['rag_url']}/a2a/tasks/{task_id}", auth_headers("orchestrator-agent")
    )

    assert task["status"] == "completed"
    assert len(task["artifacts"]) == 1
    assert task["artifacts"][0]["name"] == "result.json"
    assert "Test komunikacji A2A" in task["output"]["answer"]


def test_orchestrator_delegates_to_rag_agent(live_agents, auth_headers):
    """orchestrator-agent -> A2A -> rag-agent, zgodnie z architekturą z PRD sekcji 5 i 18."""
    payload = {
        "jsonrpc": "2.0",
        "id": "req-delegate",
        "method": "message/send",
        "params": {
            "skill": "orchestrator.ask_rag",
            "message": {"role": "user", "parts": [{"type": "text", "text": "Znajdź zasady SSO"}]},
            "metadata": {"tenant_id": "bgk"},
        },
    }
    resp = httpx.post(
        f"{live_agents['orchestrator_url']}/a2a/jsonrpc",
        json=payload,
        headers=auth_headers("external-caller"),
        timeout=5,
    )
    assert resp.status_code == 200
    task_id = resp.json()["result"]["task_id"]

    task = _poll_until_terminal(
        f"{live_agents['orchestrator_url']}/a2a/tasks/{task_id}",
        auth_headers("external-caller"),
        timeout=15,
    )

    assert task["status"] == "completed"
    assert task["output"]["delegated_agent"] == "rag-agent"
    assert task["output"]["status"] == "completed"
    assert "Znajdź zasady SSO" in task["output"]["result"]["answer"]
