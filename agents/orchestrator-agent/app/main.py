from fastapi import FastAPI

from .a2a_routes import a2a

app = FastAPI(
    title="orchestrator-agent",
    description="A2A agent: orkiestruje delegację tasków do innych agentów (rag-agent, ...).",
    version="1.0.0",
)

app.include_router(a2a.router)
