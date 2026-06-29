"""PRD sekcja 19: 'SSE zwraca eventy statusu'."""
import json

import httpx


def test_sse_stream_emits_status_events_until_completed(live_agents, auth_headers):
    payload = {
        "jsonrpc": "2.0",
        "id": "req-sse",
        "method": "message/send",
        "params": {
            "skill": "rag.search",
            "message": {"role": "user", "parts": [{"type": "text", "text": "sse test"}]},
            "metadata": {"tenant_id": "bgk"},
        },
    }
    send_resp = httpx.post(
        f"{live_agents['rag_url']}/a2a/jsonrpc", json=payload, headers=auth_headers("orchestrator-agent"), timeout=5
    )
    task_id = send_resp.json()["result"]["task_id"]

    events = []
    with httpx.stream(
        "GET",
        f"{live_agents['rag_url']}/a2a/tasks/{task_id}/stream",
        headers=auth_headers("orchestrator-agent"),
        timeout=10,
    ) as resp:
        assert resp.status_code == 200
        event_name = None
        for line in resp.iter_lines():
            if not line:
                continue
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:"):].strip())
                events.append((event_name, data))
                if data.get("status") == "completed":
                    break

    event_names = [name for name, _ in events]
    assert any(name.startswith("task.") for name in event_names)
    assert events[-1][1]["status"] == "completed"


def test_sse_stream_requires_auth(live_agents):
    resp = httpx.get(f"{live_agents['rag_url']}/a2a/tasks/whatever/stream", timeout=5)
    assert resp.status_code == 401
