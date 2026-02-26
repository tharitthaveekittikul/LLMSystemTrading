# LLM System Trading — Claude Context

AI-driven multi-account trading system. Python orchestrator bridges MetaTrader 5 to LLMs via LangChain, served through FastAPI backend + Next.js dashboard.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 16, TypeScript, Tailwind CSS 4 |
| Backend API | FastAPI, Python 3.12, **uv** package manager |
| AI Orchestration | LangChain, multi-provider (OpenAI / Gemini / Claude) |
| Broker Bridge | MetaTrader5 Python library (Windows host only) |
| Relational DB | PostgreSQL 16 |
| Time-Series DB | QuestDB |
| Infra | Docker Compose |

## Project Structure

```
LLMSystemTrading/
├── CLAUDE.md
├── ARCHITECTURE.md
├── docker-compose.yml
├── .gitignore
├── docker/
│   └── postgres/init.sql
├── backend/                    # FastAPI + Python orchestrator
│   ├── main.py                 # FastAPI app entry point
│   ├── core/                   # Config, security, encryption
│   ├── api/                    # HTTP routes + WebSocket
│   │   └── routes/
│   ├── mt5/                    # MT5 bridge & order executor
│   ├── ai/                     # LangChain orchestrator, vision
│   ├── db/                     # SQLAlchemy models, QuestDB client
│   ├── services/               # Kill switch, analytics, account manager
│   ├── tests/
│   └── pyproject.toml
└── frontend/                   # Next.js 16 dashboard
    └── app/
```

## Dev Commands

```bash
# Start databases only (recommended for local dev)
docker compose up -d postgres questdb

# Backend — run from /backend
uv sync                                          # install deps
uv run uvicorn main:app --reload --port 8000     # dev server
uv run pytest -v                                 # tests

# MT5 extra (Windows only, required for live trading)
uv sync --extra mt5

# Database migrations (after schema changes)
uv run alembic upgrade head

# Frontend — run from /frontend
npm run dev                                      # port 3000

# Full stack via Docker
docker compose --profile full up --build
docker compose logs -f backend
```

## Environment Setup

Copy `backend/.env.example` → `backend/.env`. Required vars:
- `DATABASE_URL` — PostgreSQL connection string
- `QUESTDB_HOST` — QuestDB hostname
- `ENCRYPTION_KEY` — Fernet key (generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)
- At least one LLM key: `OPENAI_API_KEY` / `GEMINI_API_KEY` / `ANTHROPIC_API_KEY`

## Key Conventions

**Module Boundaries (strict):**
- All MT5 Python library imports → `mt5/bridge.py` only
- All LLM API calls → `ai/orchestrator.py` only
- FastAPI routes are thin (validation + response shape only); logic lives in `services/`

**Data Flow:**
- Relational data (accounts, trades, AI journal) → PostgreSQL via SQLAlchemy
- Time-series data (ticks, OHLCV, equity snapshots) → QuestDB
- Real-time push (equity, P&L, signals) → WebSocket at `/ws/dashboard/{account_id}`

**Safety:**
- Kill switch (`services/kill_switch.py`) MUST be checked before every order
- Broker credentials are Fernet-encrypted in DB; decryption key only in `.env`
- MT5 is synchronous — always run in `asyncio.run_in_executor` to avoid blocking FastAPI

**Coding Style:**
- Python: type hints everywhere, Pydantic v2 models, `async/await` throughout
- No hardcoded credentials or connection strings anywhere in source code
- Target timeframes: M15–Daily (not HFT); latency from LLM is acceptable

## Architecture

See `ARCHITECTURE.md` for module boundaries, data flow diagram, and design rules.
