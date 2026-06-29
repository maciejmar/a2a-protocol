"""
PRD sekcja 19: 'Task przechodzi przez statusy submitted -> working -> completed',
'tasks/get zwraca poprawny status', 'Anulowanie taska działa', 'Timeout jest obsłużony'
(tu: TASK_NOT_FOUND dla nieistniejącego taska).
"""
import time

import httpx


def _send(live_agents, auth_headers, text: str) -> str:
    payload = {
        "jsonrpc": "2.0",
        "id": "req-lifecycle",
        "method": "message/send",
        "params": {
            "skill": "rag.search",
            "message": {"role": "user", "parts": [{"type": "text", "text": text}]},
            "metadata": {"tenant_id": "bgk"},
        },
    }
    resp = httpx.post(
        f"{live_agents['rag_url']}/a2a/jsonrpc", json=payload, headers=auth_headers("orchestrator-agent"), timeout=5
    )
    return resp.json()["result"]["task_id"]


def test_task_transitions_submitted_working_completed(live_agents, auth_headers):
    task_id = _send(live_agents, auth_headers, "lifecycle test")
    statuses_seen = set()

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        resp = httpx.get(
            f"{live_agents['rag_url']}/a2a/tasks/{task_id}", headers=auth_headers("orchestrator-agent"), timeout=5
        )
        status = resp.json()["status"]
        statuses_seen.add(status)
        if status == "completed":
            break
        time.sleep(0.15)

    assert "working" in statuses_seen
    assert "completed" in statuses_seen


def test_task_not_found_returns_404(live_agents, auth_headers):
    resp = httpx.get(
        f"{live_agents['rag_url']}/a2a/tasks/task_does_not_exist", headers=auth_headers("orchestrator-agent"), timeout=5
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "TASK_NOT_FOUND"


def test_cancel_task(live_agents, auth_headers):
    # Handler rag.search "śpi" ~1.5s w trybie stub, więc anulowanie zaraz po wysłaniu
    # trafia w status "working".
    task_id = _send(live_agents, auth_headers, "cancel me")

    cancel_resp = httpx.post(
        f"{live_agents['rag_url']}/a2a/tasks/{task_id}/cancel", headers=auth_headers("orchestrator-agent"), timeout=5
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    get_resp = httpx.get(
        f"{live_agents['rag_url']}/a2a/tasks/{task_id}", headers=auth_headers("orchestrator-agent"), timeout=5
    )
    assert get_resp.json()["status"] == "cancelled"

    second_cancel = httpx.post(
        f"{live_agents['rag_url']}/a2a/tasks/{task_id}/cancel", headers=auth_headers("orchestrator-agent"), timeout=5
    )
    assert second_cancel.status_code == 409
