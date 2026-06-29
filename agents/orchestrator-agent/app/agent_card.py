from shared.a2a_sdk.schemas import AgentCapabilities, AgentCard, AgentSkill, SecurityScheme

from .config import settings


def build_agent_card() -> AgentCard:
    return AgentCard(
        name="orchestrator-agent",
        description="Orchestrates multi-agent workflows by delegating tasks to specialised A2A agents.",
        url=f"{settings.public_base_url}/a2a/jsonrpc",
        capabilities=AgentCapabilities(streaming=True, artifacts=True, taskCancellation=True),
        skills=[
            AgentSkill(
                id="orchestrator.ask_rag",
                name="Ask knowledge base (delegates to rag-agent)",
                description="Delegates a question to rag-agent over A2A and returns the grounded answer.",
                inputModes=["application/json"],
                outputModes=["application/json", "text/plain"],
            )
        ],
        securitySchemes={"serviceToken": SecurityScheme(name="X-Agent-Token")},
    )
