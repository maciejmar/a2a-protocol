"""PRD sekcja 19: 'GET /.well-known/agent-card.json działa dla każdego agenta'."""
import httpx


def test_rag_agent_card(live_agents):
    resp = httpx.get(f"{live_agents['rag_url']}/.well-known/agent-card.json", timeout=5)
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "rag-agent"
    assert card["protocolVersion"] == "0.3.0"
    assert {s["id"] for s in card["skills"]} == {"rag.search"}
    assert card["capabilities"]["streaming"] is True
    assert card["securitySchemes"]["serviceToken"]["name"] == "X-Agent-Token"


def test_orchestrator_agent_card(live_agents):
    resp = httpx.get(f"{live_agents['orchestrator_url']}/.well-known/agent-card.json", timeout=5)
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "orchestrator-agent"
    assert "orchestrator.ask_rag" in {s["id"] for s in card["skills"]}


def test_agent_card_does_not_leak_secrets(live_agents):
    resp = httpx.get(f"{live_agents['rag_url']}/.well-known/agent-card.json", timeout=5)
    card_text = resp.text
    assert "test-secret-token" not in card_text


def test_agent_registry_lists_agents(live_agents):
    resp = httpx.get(f"{live_agents['registry_url']}/registry/agents", timeout=5)
    assert resp.status_code == 200
    agents = resp.json()
    assert set(agents.keys()) == {"orchestrator-agent", "rag-agent"}


def test_agent_registry_proxies_card(live_agents):
    resp = httpx.get(f"{live_agents['registry_url']}/registry/agents/rag-agent/card", timeout=5)
    assert resp.status_code == 200
    assert resp.json()["name"] == "rag-agent"


def test_agent_registry_unknown_agent_404(live_agents):
    resp = httpx.get(f"{live_agents['registry_url']}/registry/agents/no-such-agent", timeout=5)
    assert resp.status_code == 404
