import os
from dataclasses import dataclass, field


@dataclass
class OrchestratorConfig:
    agent_id: str = field(default_factory=lambda: os.getenv("AGENT_ID", "orchestrator-agent"))
    public_base_url: str = field(default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "http://orchestrator-agent:8000"))
    agent_registry_url: str = field(default_factory=lambda: os.getenv("AGENT_REGISTRY_URL", "http://agent-registry:8000"))
    # Sekret, którym ten agent przedstawia się INNYM agentom, gdy sam jest callerem A2A.
    a2a_token: str = field(default_factory=lambda: os.getenv("A2A_TOKEN", ""))
    tenant_id: str = field(default_factory=lambda: os.getenv("TENANT_ID", "portal-ai"))
    app_id: str = field(default_factory=lambda: os.getenv("APP_ID", "portal-ai"))


settings = OrchestratorConfig()
