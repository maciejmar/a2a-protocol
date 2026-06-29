from shared.a2a_sdk.schemas import AgentCapabilities, AgentCard, AgentSkill, SecurityScheme

from .config import settings


def build_agent_card() -> AgentCard:
    """Agent Card generowana z konfiguracji (ENV) — żadnych hardcodowanych URL-i (PRD sekcja 7)."""
    return AgentCard(
        name="rag-agent",
        description="Reusable RAG agent for tenant-specific document search and grounded answers.",
        url=f"{settings.public_base_url}/a2a/jsonrpc",
        capabilities=AgentCapabilities(streaming=True, artifacts=True, taskCancellation=True),
        skills=[
            AgentSkill(
                id="rag.search",
                name="Search knowledge base",
                description="Search tenant-specific knowledge base and return grounded answer with citations.",
                inputModes=["application/json"],
                outputModes=["application/json", "text/plain"],
            )
        ],
        securitySchemes={"serviceToken": SecurityScheme(name="X-Agent-Token")},
    )
