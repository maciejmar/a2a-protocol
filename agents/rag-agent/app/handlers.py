"""
Handler skilla rag.search.

Wywołuje istniejący serwis RAG (rag-module/rag-gateway) jako narzędzie — to jest
granica MCP/tool, nie A2A. Ten agent NIE rozmawia tu z innym agentem.
Brak RAG_BACKEND_URL → zwracana jest odpowiedź-stub (przydatne offline/w testach).
"""
import asyncio

import httpx

from shared.a2a_sdk.schemas import Message

from .config import settings


async def rag_search_handler(message: Message, metadata: dict) -> dict:
    query = message.text.strip()
    if not query:
        return {"answer": "Nie podano zapytania (pusty tekst w message.parts).", "citations": []}

    if not settings.rag_backend_url:
        # Symulacja czasu przetwarzania — pozwala obserwować status "working" i testować
        # anulowanie taska bez prawdziwego backendu RAG.
        await asyncio.sleep(1.5)
        return {
            "answer": f"[stub] RAG_BACKEND_URL nie jest skonfigurowany — echo zapytania: {query}",
            "citations": [],
        }

    payload = {
        "context": {
            "tenant_id": metadata.get("tenant_id") or settings.rag_tenant_id,
            "app_id": settings.rag_app_id,
            "knowledge_base_id": settings.rag_knowledge_base_id,
        },
        "query": query,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(settings.rag_backend_url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    return {
        "answer": data.get("answer", ""),
        "citations": [
            {"content": s.get("content"), "score": s.get("score"), "metadata": s.get("metadata", {})}
            for s in data.get("sources", [])
        ],
    }
