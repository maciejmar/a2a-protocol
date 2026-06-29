# A2A — Przewodnik dla zespołu

## Czym jest A2A i kiedy go używasz

A2A (Agent-to-Agent) to warstwa komunikacji **między agentami**. Używasz jej, gdy
Twój agent ma zlecić zadanie innemu agentowi (np. `developer-agent -> test-agent`,
`orchestrator-agent -> rag-agent`).

**Nie używaj A2A**, gdy wołasz narzędzie/serwis (RAG, parser dokumentów, Confluence,
baza danych) — to idzie przez MCP albo zwykłe REST/SDK tego serwisu, tak jak dotychczas.

```
agent -> agent        => A2A   (ten projekt)
agent -> narzędzie     => MCP   (bez zmian, jak dotychczas)
```

Twój agent przez A2A **nigdy** nie ujawnia innym agentom swoich promptów, pamięci
ani tego, jakich narzędzi/MCP używa wewnętrznie. Ujawnia tylko: kim jest, jakie ma
skille, jak przyjąć task i jak zwrócić wynik.

---

## Dwie role: agent wywoływany i agent wywołujący

Twoja aplikacja może być jednym albo drugim (często obydwoma naraz):

- **Agent wywoływany** — wystawia skille, które inni mogą zlecić (`A2AServer`).
- **Agent wywołujący** — zleca zadania innym agentom (`A2AClient`).

Przykład w tym repo: `rag-agent` jest tylko wywoływany (ma skill `rag.search`).
`orchestrator-agent` jest tylko wywołującym wobec `rag-agent`, ale jednocześnie sam
jest wywoływany (ma własny skill `orchestrator.ask_rag`, który ktoś inny może zlecić).

---

## Krok 1 — Wystaw swoje skille innym agentom (A2AServer)

Skopiuj `agents/rag-agent` jako szablon. Cztery pliki:

**`app/config.py`** — wszystko z ENV, nic na hardkodzie:

```python
import os
from dataclasses import dataclass, field

@dataclass
class MyAgentConfig:
    agent_id: str = field(default_factory=lambda: os.getenv("AGENT_ID", "moj-agent"))
    public_base_url: str = field(default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "http://moj-agent:8000"))

settings = MyAgentConfig()
```

**`app/agent_card.py`** — czym jesteś i co umiesz (to jedyne, co inni agenci widzą):

```python
from shared.a2a_sdk.schemas import AgentCapabilities, AgentCard, AgentSkill, SecurityScheme
from .config import settings

def build_agent_card() -> AgentCard:
    return AgentCard(
        name="moj-agent",
        description="Krótki opis tego, co ten agent robi.",
        url=f"{settings.public_base_url}/a2a/jsonrpc",
        capabilities=AgentCapabilities(streaming=True, artifacts=True, taskCancellation=True),
        skills=[
            AgentSkill(
                id="moj_agent.do_something",
                name="Krótka nazwa skilla",
                description="Co ten skill dokładnie robi i co zwraca.",
            )
        ],
        securitySchemes={"serviceToken": SecurityScheme(name="X-Agent-Token")},
    )
```

**`app/handlers.py`** — logika skilla. Tu, jeśli trzeba, wołaj MCP/inne serwisy —
**nigdy** innego agenta inaczej niż przez `A2AClient`:

```python
from shared.a2a_sdk.schemas import Message

async def do_something_handler(message: Message, metadata: dict) -> dict:
    query = message.text
    # ... Twoja logika, ewentualnie wywołanie MCP/serwisu ...
    return {"answer": "wynik", "details": {}}
```

Zwrócony `dict` zostaje automatycznie zapisany jako artifact `result.json`, a task
przechodzi w status `completed`.

**`app/main.py`** — sklejenie wszystkiego:

```python
from fastapi import FastAPI
from shared.a2a_sdk.auth import AuthProvider
from shared.a2a_sdk.server import A2AServer
from shared.a2a_sdk.task_manager import build_task_manager
from .agent_card import build_agent_card
from .config import settings
from .handlers import do_something_handler

app = FastAPI(title="moj-agent")

a2a = A2AServer(
    agent_id=settings.agent_id,
    agent_card=build_agent_card(),
    task_manager=build_task_manager(),
    auth=AuthProvider.from_env(),
)
a2a.skill("moj_agent.do_something")(do_something_handler)

app.include_router(a2a.router)
```

Skopiuj też `Dockerfile` i `requirements.txt` z `agents/rag-agent` (zmień tylko ścieżki).

---

## Krok 2 — Zarejestruj agenta

1. **`config/agents.yaml`** — dopisz wpis:

```yaml
agents:
  moj-agent:
    enabled: true
    internal_url: "http://moj-agent:8000"
    public_base_path: "/agents/moj-agent"
    card_url: "http://moj-agent:8000/.well-known/agent-card.json"
```

2. **`docker-compose.yml`** — skopiuj blok `rag-agent`, zmień nazwę/port:

```yaml
  moj-agent:
    build:
      context: .
      dockerfile: agents/moj-agent/Dockerfile
      secrets: [pip_conf]
    environment:
      AGENT_ID: moj-agent
      PUBLIC_BASE_URL: https://portal-ai.local/agents/moj-agent
      A2A_TOKEN: ${A2A_TOKEN:-change_me}
      A2A_ALLOWED_CALLERS: "*"
      TASK_BACKEND: postgres
      DATABASE_URL: postgresql://portal_ai:${POSTGRES_PASSWORD}@postgres:5432/portal_ai
    ports: ["8044:8000"]
    networks: [a2a-net]
    depends_on: { postgres: { condition: service_healthy } }
```

3. **`nginx/conf.d/portal-ai.conf`** — skopiuj blok `/agents/rag-agent/`, zmień nazwę
   i port (na ten z `ports:` powyżej), wklej do wspólnego nginx i przeładuj:

```bash
docker exec portal-ai-nginx nginx -s reload
```

4. `docker compose up -d --build moj-agent`. Od teraz `agent-registry` go widzi, a
   każdy inny agent może go odnaleźć i wywołać.

---

## Krok 3 — Wywołaj innego agenta ze swojego kodu (A2AClient)

Tak robi to `orchestrator-agent` w `agents/orchestrator-agent/app/workflows.py`:

```python
from shared.a2a_sdk.client import A2AClient

client = A2AClient(
    registry_url="http://agent-registry:8000",   # zawsze ten sam URL w sieci docker
    agent_id="moj-agent",                          # Twoja tożsamość jako caller
    token_provider=lambda: settings.a2a_token,     # ten sam A2A_TOKEN co cały zespół
    tenant_id="bgk",
    app_id="portal-ai",
)

async def call_rag_agent(question: str) -> dict:
    # 1. send_message sam pobiera Agent Card rag-agenta i sprawdza, czy skill istnieje
    sent = await client.send_message(
        target_agent="rag-agent",
        skill="rag.search",
        text=question,
        metadata={"tenant_id": "bgk"},
    )
    # 2. czekaj na wynik (polling tasks/get co 1s, timeout konfigurowalny)
    task = await client.wait_for_task(
        target_agent="rag-agent", task_id=sent.task_id, timeout_seconds=120,
    )
    if task["status"] != "completed":
        raise RuntimeError(f"rag-agent nie dokończył: {task['status']} {task.get('error')}")
    return task["output"]   # to jest dict, który handler rag-agenta zwrócił
```

Jeśli chcesz śledzić postęp w czasie rzeczywistym zamiast pollować:

```python
async for event, data in client.stream_task("rag-agent", sent.task_id):
    print(event, data)   # task.working, artifact.created, task.completed, heartbeat...
```

`A2AClient` sam: pobiera i cache'uje Agent Card, sprawdza czy skill istnieje (inaczej
dostajesz `SKILL_NOT_FOUND` zamiast wysłać request na ślepo), dorzuca nagłówki
`X-Agent-Id/X-Agent-Token/X-Tenant-Id/X-Request-Id`, robi retry z backoffem na
błędach sieciowych/5xx, i mapuje błędy JSON-RPC z drugiej strony na `A2AError`.

---

## Krok 4 — Kto może wołać Twojego agenta (autoryzacja)

Każdy request musi mieć nagłówki `X-Agent-Id`, `X-Agent-Token`, `X-Tenant-Id`,
`X-Request-Id`. Model MVP to **jeden wspólny sekret** w całym środowisku:

| ENV agenta | Co robi |
|---|---|
| `A2A_TOKEN` | Sekret, który MUSI nieść `X-Agent-Token` każdego, kto Cię woła. |
| `A2A_ALLOWED_CALLERS` | Lista po przecinku `X-Agent-Id`, które wpuszczasz. `*` = każdy z poprawnym tokenem. |
| `A2A_SKILL_SCOPES` | Opcjonalny JSON `{"orchestrator-agent": ["moj_agent.do_something"]}` — ograniczenie kto-do-jakiego-skilla. |

Złe `X-Agent-Token` → `401 UNAUTHORIZED_AGENT`. Caller poza allowlistą → `401`.
Caller bez prawa do skilla → `403 FORBIDDEN_SKILL`. Nieznany skill → `400 SKILL_NOT_FOUND`.

---

## Krok 5 — Sprawdź to ręcznie (curl)

```bash
# Agent Card — co umie Twój agent
curl http://localhost:8044/.well-known/agent-card.json

# Zleć skill
curl -X POST http://localhost:8044/a2a/jsonrpc \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: orchestrator-agent" -H "X-Agent-Token: change_me" -H "X-Tenant-Id: bgk" \
  -d '{
    "jsonrpc":"2.0","id":"req_001","method":"message/send",
    "params":{
      "skill":"moj_agent.do_something",
      "message":{"role":"user","parts":[{"type":"text","text":"test"}]},
      "metadata":{"tenant_id":"bgk"}
    }
  }'
# -> {"result":{"task_id":"task_...","status":"submitted"}}

# Sprawdź wynik
curl http://localhost:8044/a2a/tasks/task_... \
  -H "X-Agent-Id: orchestrator-agent" -H "X-Agent-Token: change_me" -H "X-Tenant-Id: bgk"

# Anuluj
curl -X POST http://localhost:8044/a2a/tasks/task_.../cancel \
  -H "X-Agent-Id: orchestrator-agent" -H "X-Agent-Token: change_me" -H "X-Tenant-Id: bgk"

# Stream statusu (SSE)
curl -N http://localhost:8044/a2a/tasks/task_.../stream \
  -H "X-Agent-Id: orchestrator-agent" -H "X-Agent-Token: change_me" -H "X-Tenant-Id: bgk"
```

Pełny przykład dwóch gotowych agentów rozmawiających ze sobą: zobacz `README.md`
(sekcja "Pełna delegacja: orchestrator-agent -> rag-agent") albo `tests/test_a2a_send_task.py`.

---

## Cykl życia taska — czego się trzymać

```
submitted -> working -> completed
                      -> failed
                      -> cancelled
```

- Status **nigdy nie wraca** z `completed`/`failed`/`cancelled` do innego stanu.
- Wynik Twojego handlera trafia do `task.output` ORAZ jako artifact `result.json`.
- Jeśli handler podniesie wyjątek — task dostaje `failed` z `error`, server się nie wywala.
- Anulowanie zadziała tylko, gdy task jeszcze nie jest w statusie końcowym (inaczej `409 TASK_CANCELLED`).

---

## Najczęstsze błędy

**„Mój agent nie odpowiada na A2A, mam tylko REST."**
A2A to dodatkowa warstwa nad Twoim agentem, nie zamiast niego. Dodaj `A2AServer` i
`include_router` w `main.py` tak jak w kroku 1 — Twój dotychczasowy REST może zostać bez zmian.

**„Chcę zawołać RAG/parser/Confluence z mojego skilla."**
To MCP albo zwykłe REST tego serwisu (jak `rag-agent` woła `rag-module`), nie A2A.
Nie twórz dla nich Agent Card.

**„`send_message` wywala `SKILL_NOT_FOUND` mimo że dodałem handler."**
Skill musi być zarejestrowany ORAZ wymieniony w `agent_card.py` — `A2AClient`
sprawdza dostępne skille z Agent Card przed wysłaniem requestu.

**„Dostaję 401 mimo dobrego tokena."**
Sprawdź `A2A_ALLOWED_CALLERS` agenta, którego wołasz — Twój `X-Agent-Id` (czyli
`agent_id` Twojego `A2AClient`) musi być na liście albo lista musi być `*`.

**„Jak dodać nowego agenta od zera?"** — patrz `README.md`, sekcja "Dodanie nowego agenta".
