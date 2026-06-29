"""Agent Registry — lokalny discovery agentów w zamkniętym środowisku (PRD sekcja 8)."""
import httpx
from fastapi import FastAPI, HTTPException

from .registry import store

app = FastAPI(
    title="Agent Registry",
    description="Lokalny rejestr agentów A2A — discovery bez Internetu.",
    version="1.0.0",
)


@app.get("/registry/agents")
def list_agents() -> dict:
    return {
        agent_id: {
            "enabled": entry.enabled,
            "internal_url": entry.internal_url,
            "public_base_path": entry.public_base_path,
            "card_url": entry.card_url,
        }
        for agent_id, entry in store.list_agents().items()
    }


@app.get("/registry/agents/{agent_id}")
def get_agent(agent_id: str) -> dict:
    entry = store.get(agent_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="AGENT_NOT_FOUND")
    return {
        "agent_id": entry.agent_id,
        "enabled": entry.enabled,
        "internal_url": entry.internal_url,
        "public_base_path": entry.public_base_path,
        "card_url": entry.card_url,
    }


@app.get("/registry/agents/{agent_id}/card")
def get_agent_card(agent_id: str) -> dict:
    if store.get(agent_id) is None:
        raise HTTPException(status_code=404, detail="AGENT_NOT_FOUND")
    try:
        card = store.fetch_card(agent_id)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"AGENT_UNAVAILABLE: {exc}")
    return card


@app.post("/registry/reload")
def reload_registry() -> dict:
    """Przeładowuje agents.yaml bez restartu kontenera — przydatne po dodaniu agenta."""
    store.reload()
    return {"status": "reloaded", "agents": list(store.list_agents().keys())}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "agent-registry"}
