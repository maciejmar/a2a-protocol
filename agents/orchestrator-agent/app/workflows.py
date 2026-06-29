"""
Workflow orkiestratora: delegacja pytania do rag-agent przez A2A (PRD sekcja 18).

orchestrator-agent
  -> A2A -> rag-agent
      -> MCP/tool -> istniejący serwis RAG
      <- wynik do rag-agent
  <- A2A artifact do orchestrator-agent
"""
from shared.a2a_sdk.client import A2AClient
from shared.a2a_sdk.schemas import Message

from .config import settings

client = A2AClient(
    registry_url=settings.agent_registry_url,
    agent_id=settings.agent_id,
    token_provider=lambda: settings.a2a_token,
    tenant_id=settings.tenant_id,
    app_id=settings.app_id,
)


async def ask_rag_workflow(message: Message, metadata: dict) -> dict:
    query = message.text.strip()
    tenant_id = metadata.get("tenant_id") or settings.tenant_id

    send_result = await client.send_message(
        target_agent="rag-agent",
        skill="rag.search",
        text=query,
        metadata={"tenant_id": tenant_id, "app_id": settings.app_id},
    )
    task = await client.wait_for_task(target_agent="rag-agent", task_id=send_result.task_id, timeout_seconds=120)

    if task["status"] != "completed":
        return {
            "delegated_agent": "rag-agent",
            "delegated_task_id": send_result.task_id,
            "status": task["status"],
            "error": task.get("error"),
        }

    return {
        "delegated_agent": "rag-agent",
        "delegated_task_id": send_result.task_id,
        "status": task["status"],
        "result": task.get("output"),
    }
