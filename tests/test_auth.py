"""PRD sekcja 19: błędny token -> 401/403, nieznany skill -> błąd JSON-RPC."""
import httpx


def _payload(skill: str = "rag.search", text: str = "test"):
    return {
        "jsonrpc": "2.0",
        "id": "req-auth",
        "method": "message/send",
        "params": {
            "skill": skill,
            "message": {"role": "user", "parts": [{"type": "text", "text": text}]},
            "metadata": {"tenant_id": "bgk"},
        },
    }


def test_missing_agent_id_rejected(live_agents):
    resp = httpx.post(
        f"{live_agents['rag_url']}/a2a/jsonrpc",
        json=_payload(),
        headers={"X-Agent-Token": live_agents["token"]},
        timeout=5,
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "UNAUTHORIZED_AGENT"


def test_invalid_token_rejected(live_agents):
    resp = httpx.post(
        f"{live_agents['rag_url']}/a2a/jsonrpc",
        json=_payload(),
        headers={"X-Agent-Id": "orchestrator-agent", "X-Agent-Token": "wrong-token"},
        timeout=5,
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "UNAUTHORIZED_AGENT"


def test_unknown_skill_returns_jsonrpc_error(live_agents, auth_headers):
    resp = httpx.post(
        f"{live_agents['rag_url']}/a2a/jsonrpc",
        json=_payload(skill="rag.unknown"),
        headers=auth_headers("orchestrator-agent"),
        timeout=5,
    )
    body = resp.json()
    assert resp.status_code == 400
    assert body["error"]["message"] == "SKILL_NOT_FOUND"
    assert body["error"]["data"]["skill"] == "rag.unknown"


def test_valid_request_accepted(live_agents, auth_headers):
    resp = httpx.post(
        f"{live_agents['rag_url']}/a2a/jsonrpc",
        json=_payload(),
        headers=auth_headers("orchestrator-agent"),
        timeout=5,
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["status"] == "submitted"


def test_get_task_without_headers_rejected(live_agents):
    resp = httpx.get(f"{live_agents['rag_url']}/a2a/tasks/whatever", timeout=5)
    assert resp.status_code == 401
