from fastapi import FastAPI

from shared.a2a_sdk.auth import AuthProvider
from shared.a2a_sdk.server import A2AServer
from shared.a2a_sdk.task_manager import build_task_manager

from .agent_card import build_agent_card
from .config import settings
from .handlers import rag_search_handler

app = FastAPI(
    title="rag-agent",
    description="A2A agent: wyszukiwanie w bazie wiedzy (RAG) i odpowiedzi z cytatami.",
    version="1.0.0",
)

task_manager = build_task_manager()
auth = AuthProvider.from_env()
agent_card = build_agent_card()

a2a = A2AServer(agent_id=settings.agent_id, agent_card=agent_card, task_manager=task_manager, auth=auth)
a2a.skill("rag.search")(rag_search_handler)

app.include_router(a2a.router)
