# LLM System Trading

AI-driven multi-account trading system. Python orchestrator bridges **MetaTrader 5** to **LLMs** (LangChain) for market analysis and automated execution, monitored via a real-time **Next.js** dashboard.

## Quick Start

```bash
# 1. Copy environment files
cp .env.example .env
cp backend/.env.example backend/.env       # fill in ENCRYPTION_KEY + LLM API key
cp frontend/.env.local.example frontend/.env.local

# 2. Build and start all services (with hot-reload)
docker compose up --build

# 3. Open in browser
#    Dashboard  → http://localhost:3000
#    API docs   → http://localhost:8000/docs
#    QuestDB UI → http://localhost:9000
```

## Services

| Service | URL | Description |
|---------|-----|-------------|
| **Dashboard** (Next.js) | http://localhost:3000 | Real-time equity, trades, analytics |
| **REST API** (FastAPI) | http://localhost:8000/docs | Swagger UI, all endpoints |
| **WebSocket** | ws://localhost:8000/ws/dashboard/{id} | Live equity + trade events |
| **QuestDB UI** | http://localhost:9000 | Time-series data explorer |
| **PostgreSQL** | localhost:5432 | DB: `trading` / User: `trading` |

## Hot-Reload

Both application services reload automatically when you save a file:

| Service | Trigger | Mechanism |
|---------|---------|-----------|
| Backend | Save any `.py` file in `backend/` | `uvicorn --reload` |
| Frontend | Save any `.ts/.tsx/.css` in `frontend/` | Next.js HMR + `WATCHPACK_POLLING` |

> No need to restart Docker. Changes are live within ~1–2 seconds.

## Environment Files

| File | Read by | Key vars |
|------|---------|---------|
| `.env` | Docker Compose | `POSTGRES_PASSWORD` |
| `backend/.env` | FastAPI (pydantic-settings) | `ENCRYPTION_KEY`, `LLM_PROVIDER`, API keys |
| `frontend/.env.local` | Next.js | `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL` |

Generate `ENCRYPTION_KEY` (required before first run):
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Useful Commands

```bash
# Start only databases (run backend/frontend locally outside Docker)
docker compose up postgres questdb

# View logs
docker compose logs -f backend
docker compose logs -f frontend

# Rebuild after adding Python packages
docker compose up --build backend

# Run backend tests
docker compose exec backend uv run pytest -v

# MT5 integration — Windows host only (not in Docker)
cd backend && uv sync --extra mt5
```

## Project Structure

```
├── backend/            FastAPI + Python orchestrator
│   ├── mt5/            Bridge (sole MetaTrader5 importer) + executor
│   ├── ai/             LangChain pipeline + chart vision analysis
│   ├── db/             PostgreSQL (SQLAlchemy) + QuestDB client
│   ├── api/routes/     REST endpoints + WebSocket
│   ├── services/       Kill switch, analytics
│   └── core/           Config (pydantic-settings), Fernet encryption
├── frontend/           Next.js 16 dashboard
├── plantuml/           System data flow diagrams
├── docker-compose.yml  All 4 services with hot-reload
├── CLAUDE.md           AI assistant context + dev guide
└── ARCHITECTURE.md     Module rules + data flow
```

## Architecture Highlights

- **Kill Switch** — hard gate in `services/kill_switch.py`; blocks all order execution when active
- **LLM as Advisor** — AI produces signals; Python validates risk before execution
- **Hybrid Analysis** — combines structured indicators (RSI, MA, OHLCV) with optional chart vision
- **Encrypted Credentials** — broker passwords Fernet-encrypted at rest; key only in `.env`
- **Non-blocking MT5** — synchronous MT5 calls run in `asyncio.run_in_executor`
- **Timeframes** — optimized for M15–Daily (not HFT); LLM latency is acceptable

See [ARCHITECTURE.md](ARCHITECTURE.md) for full module boundaries and design rules.
See [plantuml/](plantuml/) for system data flow diagrams.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 16 · TypeScript · Tailwind CSS 4 |
| Backend | FastAPI · Python 3.12 · uv |
| AI | LangChain · OpenAI GPT-4o / Gemini 1.5 Pro / Claude Sonnet |
| Broker | MetaTrader5 Python (Windows) |
| Databases | PostgreSQL 16 · QuestDB |
| Infra | Docker Compose |
