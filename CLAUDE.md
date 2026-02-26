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
├── README.md
├── CLAUDE.md
├── ARCHITECTURE.md
├── docker-compose.yml          # All 4 services with hot-reload
├── plantuml/                   # System data flow diagrams
│   ├── overview.puml           # Full architecture overview
│   ├── 02-trade-execution.puml
│   ├── 03-ai-pipeline.puml
│   ├── 04-websocket-events.puml
│   └── 05-manual-trading.puml
├── docker/postgres/init.sql
├── backend/                    # FastAPI + Python orchestrator
│   ├── main.py                 # FastAPI app entry point
│   ├── core/                   # Config, security, encryption
│   ├── api/routes/             # HTTP routes + WebSocket
│   ├── mt5/                    # MT5 bridge & order executor
│   ├── ai/                     # LangChain orchestrator, vision
│   ├── db/                     # SQLAlchemy models, QuestDB client
│   ├── services/               # Kill switch, analytics
│   ├── tests/
│   └── pyproject.toml
└── frontend/                   # Next.js 16 dashboard
    ├── Dockerfile
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

# Full stack via Docker (all 4 services with hot-reload)
docker compose up --build
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

**Logging:**
- Central setup: `core/logging.py` — call `setup_logging()` once from `main.py` at module level
- All modules: `logger = logging.getLogger(__name__)` — never use `print()` for application events
- Format: `%(asctime)s %(levelname)-8s %(name)s: %(message)s` (ISO timestamp)
- Levels: `DEBUG` dev detail, `INFO` normal ops, `WARNING` kill-switch/degraded, `ERROR` failures
- Log key lifecycle events: MT5 connect/disconnect, orders placed/rejected, LLM signal outcomes, WebSocket connect/disconnect
- Third-party loggers (`sqlalchemy.engine`, `uvicorn.access`, `httpx`) suppressed to WARNING in non-debug mode

**Validation:**
- Input validation at the boundary (Pydantic models on all API schemas and `OrderRequest`)
- `core/config.py` validates every setting at startup — bad config raises `ValueError` immediately
- In production (`debug=False`): app refuses to start if `ENCRYPTION_KEY` or `JWT_SECRET` are dev defaults
- LLM provider API key is validated at startup regardless of debug mode
- QuestDB table names are sanitized via regex before use (`_safe_table_name()` in `db/questdb.py`)
- All datetimes are timezone-aware (`datetime.now(UTC)`) — never use deprecated `datetime.utcnow()`

## Architecture

See `ARCHITECTURE.md` for module boundaries, data flow diagram, and design rules.
See `plantuml/overview.puml` for the full system component diagram.

## Reference Documents

Cached third-party docs live in `documents/` — fetch from source only when updating.

```
documents/
└── mt5-python/
    ├── README.md            # Index + critical constraints + all function list
    ├── connection.md        # initialize(), login(), shutdown()
    ├── account-terminal.md  # terminal_info(), account_info() + all fields
    ├── positions.md         # positions_get() + field reference + normalization
    ├── market-data.md       # symbol_select(), symbol_info_tick(), copy_rates_from_pos()
    ├── orders.md            # order_send() + all constants + fill/time types
    └── error-codes.md       # last_error() codes + trade retcodes
```

**MT5 critical constraints (from docs):**
- `initialize()` binds to calling OS thread via COM — use `ThreadPoolExecutor(max_workers=1)`
- All MT5 calls must run on the **same single thread** for the entire process lifetime
- Persistent connection: connect once → poll N times → `shutdown()` in `finally`
- `terminal_info().connected` — lightweight broker heartbeat (check before each fetch)
- Call `symbol_select(symbol, True)` before `symbol_info_tick()` for new symbols
