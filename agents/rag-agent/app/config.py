import os
from dataclasses import dataclass, field


@dataclass
class RagAgentConfig:
    agent_id: str = field(default_factory=lambda: os.getenv("AGENT_ID", "rag-agent"))
    public_base_url: str = field(default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "http://rag-agent:8000"))

    # Istniejący serwis RAG (rag-module/rag-gateway) traktowany jako narzędzie wołane
    # PRZEZ tego agenta (rola MCP/tool), NIE jako kolejny agent A2A.
    # Puste = handler zwraca odpowiedź-stub (przydatne w testach bez zależności zewnętrznych).
    rag_backend_url: str = field(default_factory=lambda: os.getenv("RAG_BACKEND_URL", ""))
    rag_tenant_id: str = field(default_factory=lambda: os.getenv("RAG_TENANT_ID", "portal-ai"))
    rag_app_id: str = field(default_factory=lambda: os.getenv("RAG_APP_ID", "a2a-rag-agent"))
    rag_knowledge_base_id: str = field(default_factory=lambda: os.getenv("RAG_KNOWLEDGE_BASE_ID", "default"))


settings = RagAgentConfig()
