from shared.a2a_sdk.auth import AuthProvider
from shared.a2a_sdk.server import A2AServer
from shared.a2a_sdk.task_manager import build_task_manager

from .agent_card import build_agent_card
from .config import settings
from .workflows import ask_rag_workflow

task_manager = build_task_manager()
auth = AuthProvider.from_env()
agent_card = build_agent_card()

a2a = A2AServer(agent_id=settings.agent_id, agent_card=agent_card, task_manager=task_manager, auth=auth)
a2a.skill("orchestrator.ask_rag")(ask_rag_workflow)
