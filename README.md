# Portal-AI A2A

Prototyp protokołu **A2A (Agent-to-Agent)** dla zamkniętego środowiska Portal-AI
(serwer `10.112.32.19`, brak Internetu w runtime, wszystko w Dockerze, wspólny nginx).

A2A służy **wyłącznie** do komunikacji agent-agent (np. `orchestrator-agent -> rag-agent`).
Komunikacja agent-narzędzie (RAG, parser dokumentów, Confluence, ...) idzie przez **MCP** —
ten projekt nie zastępuje MCP, tylko dodaje brakującą warstwę agent-agent obok niego.

## Struktura

```
shared/a2a_sdk/        # wspólny SDK (schemas, server, client, task_manager, ...)
services/agent-registry/  # lokalny discovery agentów (config/agents.yaml)
agents/orchestrator-agent/  # przykładowy agent delegujący zadania
agents/rag-agent/          # przykładowy agent ze skillem rag.search
config/agents.yaml      # rejestr agentów (kto, gdzie, jaki internal_url)
nginx/conf.d/portal-ai.conf  # snippet do wklejenia do WSPÓLNEGO nginx
tests/                  # testy integracyjne (uruchamiają realne procesy agentów)
```

## Jak to działa

Każdy agent wystawia ten sam interfejs:

```
GET  /.well-known/agent-card.json   — kim jestem, jakie mam skille
POST /a2a/jsonrpc                   — message/send, tasks/get, tasks/cancel
GET  /a2a/tasks/{task_id}
GET  /a2a/tasks/{task_id}/stream    — SSE
POST /a2a/tasks/{task_id}/cancel
GET  /health
```

Agent Card **nigdy** nie ujawnia promptów, pamięci ani narzędzi agenta — tylko nazwę,
opis, capabilities i skille.

`orchestrator-agent` w tym prototypie ma jeden skill (`orchestrator.ask_rag`), który
pokazuje pełny scenariusz z PRD: dostaje pytanie, woła `rag-agent` po A2A, czeka na
wynik i zwraca go jako swój własny artifact. `rag-agent` ma skill `rag.search`, który
woła **istniejący serwis RAG** (np. `rag-module`/`rag-gateway`) jako narzędzie —
to jest granica MCP, nie A2A.

## Pierwsze uruchomienie na serwerze

### 1. Przygotuj `.env`

```bash
cd a2a-protocol
cp .env.example .env
```

Minimalnie ustaw/sprawdź:
- `A2A_TOKEN` — wspólny sekret (zmień z `change_me`)
- Porty `AGENT_REGISTRY_PORT` / `ORCHESTRATOR_PORT` / `RAG_AGENT_PORT` (domyślnie
  `8041`/`8042`/`8043`) — sprawdź, że są wolne: `ss -tulpn | grep -E '8041|8042|8043'`
- `RAG_BACKEND_URL` można na razie zostawić puste — `rag-agent` wtedy odpowiada
  deterministycznym stubem (do pierwszego testu wystarczy, nie potrzebujesz
  uruchomionego `rag-module`)

### 2. Sprawdź wymagane pliki na hoście (build + CA trust)

```bash
ls -la /etc/pip.conf
ls -la /etc/pki/tls/certs/ca-bundle.crt
```

Jeśli budowałeś już `rag-module` na tym serwerze, powinny tam być.

### 3. Postaw kontenery

```bash
docker compose up -d --build
docker compose ps
```

Wszystkie 4 serwisy (`postgres`, `agent-registry`, `orchestrator-agent`, `rag-agent`)
powinny być `healthy`/`running`. W razie problemu: `docker compose logs -f <serwis>`.

### 4. Health check

```bash
curl http://localhost:8041/health   # agent-registry
curl http://localhost:8042/health   # orchestrator-agent
curl http://localhost:8043/health   # rag-agent
```

### 5. Zobacz A2A w akcji (bez nginx, na portach hosta)

```bash
# Agent Card
curl http://localhost:8043/.well-known/agent-card.json | jq

# Wyślij task
curl -s -X POST http://localhost:8043/a2a/jsonrpc \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: orchestrator-agent" -H "X-Agent-Token: <TWÓJ_A2A_TOKEN>" -H "X-Tenant-Id: bgk" \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{
    "skill":"rag.search",
    "message":{"role":"user","parts":[{"type":"text","text":"Test A2A na serwerze"}]},
    "metadata":{"tenant_id":"bgk"}
  }}' | jq

# Sprawdź status (zobaczysz przejście submitted -> working -> completed,
# stub celowo "myśli" ~1.5s)
curl -s http://localhost:8043/a2a/tasks/<TASK_ID> \
  -H "X-Agent-Id: orchestrator-agent" -H "X-Agent-Token: <TWÓJ_A2A_TOKEN>" -H "X-Tenant-Id: bgk" | jq
```

Pełną listę gotowych przykładów (cancel, SSE, delegacja orchestrator -> rag-agent)
znajdziesz w sekcji [Przykładowe curle](#przykładowe-curle) poniżej.

### 6. Podłącz pod wspólny nginx

Ten projekt **nie** stawia własnego nginx — wkleja się do istniejącego, wspólnego
reverse proxy (`portal-ai-nginx`), tak jak inne moduły (np. `rag-module`).

```bash
# 1. Skopiuj zawartość nginx/conf.d/portal-ai.conf do /root/nginx/conf/default.conf
# 2. Przeładuj:
docker exec portal-ai-nginx nginx -s reload
```

Po tym agenci są dostępni jako kolejny serwis pod wspólnym adresem, obok
pozostałych modułów (np. `rag-module`):

```
https://portal-ai.local/agents/orchestrator-agent/.well-known/agent-card.json
https://portal-ai.local/agents/rag-agent/.well-known/agent-card.json
```

Zweryfikuj dokładnie tymi samymi curlami co w kroku 5, tylko zamieniając
`http://localhost:<port>` na `https://portal-ai.local/agents/<agent>` — jeśli
odpowiedzi się zgadzają, A2A działa już przez wspólny nginx tak samo jak każdy
inny serwis w Portal-AI.

## Przykładowe curle

### Agent Card

```bash
curl http://localhost:8043/.well-known/agent-card.json
```

### message/send — wywołanie skilla rag.search

```bash
curl -X POST http://localhost:8043/a2a/jsonrpc \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: orchestrator-agent" \
  -H "X-Agent-Token: change_me" \
  -H "X-Tenant-Id: bgk" \
  -H "X-Request-Id: $(uuidgen)" \
  -d '{
    "jsonrpc": "2.0",
    "id": "req_001",
    "method": "message/send",
    "params": {
      "skill": "rag.search",
      "message": {
        "role": "user",
        "parts": [{"type": "text", "text": "Test komunikacji A2A"}]
      },
      "metadata": {
        "tenant_id": "bgk",
        "app_id": "portal-ai",
        "caller_agent": "orchestrator-agent"
      }
    }
  }'
```

Odpowiedź: `{"jsonrpc":"2.0","id":"req_001","result":{"task_id":"task_...","status":"submitted"}}`

### tasks/get — sprawdzenie statusu i wyniku

```bash
curl -X POST http://localhost:8043/a2a/jsonrpc \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: orchestrator-agent" \
  -H "X-Agent-Token: change_me" \
  -H "X-Tenant-Id: bgk" \
  -d '{"jsonrpc":"2.0","id":"req_002","method":"tasks/get","params":{"task_id":"task_..."}}'
```

Albo REST-owo: `curl http://localhost:8043/a2a/tasks/task_... -H "X-Agent-Id: orchestrator-agent" -H "X-Agent-Token: change_me" -H "X-Tenant-Id: bgk"`

### Anulowanie taska

```bash
curl -X POST http://localhost:8043/a2a/tasks/task_.../cancel \
  -H "X-Agent-Id: orchestrator-agent" -H "X-Agent-Token: change_me" -H "X-Tenant-Id: bgk"
```

### SSE stream

```bash
curl -N http://localhost:8043/a2a/tasks/task_.../stream \
  -H "X-Agent-Id: orchestrator-agent" -H "X-Agent-Token: change_me" -H "X-Tenant-Id: bgk"
```

### Pełna delegacja: orchestrator-agent -> rag-agent

```bash
curl -X POST http://localhost:8042/a2a/jsonrpc \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: external-caller" \
  -H "X-Agent-Token: change_me" \
  -H "X-Tenant-Id: bgk" \
  -d '{
    "jsonrpc": "2.0",
    "id": "req_003",
    "method": "message/send",
    "params": {
      "skill": "orchestrator.ask_rag",
      "message": {"role": "user", "parts": [{"type": "text", "text": "Znajdź zasady SSO"}]},
      "metadata": {"tenant_id": "bgk"}
    }
  }'
```

`tasks/get` na tym tasku zwróci wynik z `output.delegated_agent = "rag-agent"` i
zagnieżdżonym wynikiem z rag-agenta.

## Bezpieczeństwo (MVP)

Każdy request musi nieść nagłówki `X-Agent-Id`, `X-Agent-Token`, `X-Tenant-Id`,
`X-Request-Id`. Model MVP to **jeden wspólny sekret** (`A2A_TOKEN`) — każdy agent
porównuje nagłówek `X-Agent-Token` ze swoją wartością `A2A_TOKEN` i opcjonalnie
ogranicza, którzy `X-Agent-Id` mogą do niego dzwonić (`A2A_ALLOWED_CALLERS`) i do
jakich skilli (`A2A_SKILL_SCOPES`, JSON `{"agent_id": ["skill.id", ...]}`).

Docelowo (poza MVP — patrz PRD sekcja 15): JWT service-to-service, scope per skill,
mTLS, Vault na sekrety, rotacja tokenów, podpisywanie Agent Card.

## Dodanie nowego agenta

1. Skopiuj katalog `agents/rag-agent` jako szablon.
2. Zmień `agent_card.py` (nazwa, opis, skille) i `handlers.py` (logika skilli — tu
   wołaj MCP/inne serwisy, **nigdy** innego agenta przez nic innego niż A2A SDK).
3. Dopisz wpis w `config/agents.yaml`.
4. Dopisz service w `docker-compose.yml` (skopiuj blok `rag-agent`, zmień port).
5. Dopisz `location /agents/<nowy-agent>/` w `nginx/conf.d/portal-ai.conf` i przeładuj nginx.
6. `docker compose up -d --build`.

Od tej chwili każdy inny agent może go odnaleźć przez `agent-registry` i wywołać
przez `A2AClient`.

## Testy

Testy integracyjne uruchamiają prawdziwe procesy `agent-registry`, `orchestrator-agent`
i `rag-agent` (TASK_BACKEND=memory, bez Postgresa, bez prawdziwego backendu RAG —
`rag-agent` odpowiada wtedy deterministycznym stubem).

```bash
pip install -r tests/requirements.txt
python -m pytest tests/ -v
```

## Co jest poza zakresem MVP

Pełny OAuth2, mTLS, push notifications, federacja między środowiskami, workflow
engine, `document-agent`/`notary-agent` (placeholdery z PRD — dodaj je tym samym
przepisem co `rag-agent`), metryki Prometheus (`a2a_requests_total` itd. — logi
audytowe w `shared/a2a_sdk/logging.py` już mają wszystkie potrzebne pola, podłącz
exporter gdy będzie potrzebny).
