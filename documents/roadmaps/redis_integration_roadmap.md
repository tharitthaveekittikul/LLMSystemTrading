# Redis Integration Roadmap

## Why add Redis to the LLM System Trading project?

Currently, the project uses a solid stack with PostgreSQL for relational data and QuestDB for time-series data. However, as a trading system bridging MT5, LLMs, and real-time WebSockets, adding Redis solves several specific architectural challenges as the system scales:

1. **WebSocket Real-time Pub/Sub**: Currently, the dashboard updates via `ws://localhost:8000/ws/dashboard/{id}`. If you deploy multiple FastAPI workers (e.g., using `gunicorn` with multiple `uvicorn` workers) to handle increased LLM load, WebSocket connections will be split across separate memory spaces. Redis Pub/Sub provides a unified message broker to ensure all clients receive MT5/AI events regardless of which worker they are connected to.
2. **Distributed Locks for Trade Execution**: The `mt5/executor.py` might face race conditions if multiple signals trigger concurrently for the same account. Redis locks (e.g., Redlock) ensure that only one thread/worker can process a trade for a specific account at a single time, preventing conflicting duplicate orders.
3. **LLM Rate Limiting & Cost Tracking**: Tracking tokens used across LangChain calls per minute/hour is crucial to avoid API rate limit errors (from OpenAI/Anthropic/Gemini) and to control costs. Redis provides an extremely fast in-memory store for distributed rate-limiting algorithms like Token Bucket.
4. **Reliable Background Task Queues**: The architecture currently writes to QuestDB using `asyncio.create_task` (fire-and-forget). While fast, if the server restarts, pending tasks in memory are lost. Using a Redis-backed queue like `arq` or `Celery` allows for guaranteed execution, automatic retries for failed LLM calls, and separating heavy AI processing from the main FastAPI event loop.

---

## Technical Roadmap

### Phase 1: Infrastructure & Core Setup

- [ ] **Docker Compose**: Add the `redis:7-alpine` service to `docker-compose.yml`.
- [ ] **Configuration**: Add `REDIS_URL` to `.env` and `core/config.py` using `pydantic-settings`.
- [ ] **Redis Client**: Create `db/redis.py` to initialize an async connection pool using `redis.asyncio` (from the `redis` python package).

### Phase 2: Distributed Locking & Safety

- [ ] **Locking Mechanism**: Implement a distributed lock decorator or context manager in `services/`.
- [ ] **Executor Integration**: Wrap critical sections in `mt5/executor.py` (like `order_send`) with Redis locks to prevent duplicate simultaneous executions.
- [ ] **Kill Switch Enforcement**: Cache the `kill_switch` state in Redis for ultra-fast, cross-worker reads instead of querying PostgreSQL on every tick.

### Phase 3: WebSocket Pub/Sub

- [ ] **Event Publisher**: Modify event generators (like trade opened/closed, AI signals in `mt5` or `ai`) to publish JSON payloads to specific Redis channels (e.g., `trade_events:{account_id}`).
- [ ] **WebSocket Subscriber**: Update `api/routes/ws.py`. When a Next.js client connects, spawn an asyncio task that subscribes to the relevant Redis channel and forwards messages to the client.

### Phase 4: LLM Rate Limiting & Analytics

- [ ] **API Limits**: Implement a Redis-based rate limiter in `ai/orchestrator.py` to pause or throttle external LLM calls when nearing provider limits.
- [ ] **Cost Tracking**: Use Redis counters with TTL to keep a live, rolling window of token usage and estimated costs per hour.
- [ ] **Session Caching**: Cache recent technical indicator calculations temporarily to avoid recalculating the exact same state if multiple identical requests occur back-to-back.

### Phase 5: Asynchronous Task Queues (Optional Evolution)

- [ ] **Task Manager**: Integrate a lightweight async queue like `arq` (Async Redis Queue) for Python.
- [ ] **Offload LLMs**: Move LangChain orchestrator execution (`ai/orchestrator.py`) into asynchronous `arq` workers to completely free up the FastAPI web server from long-running network calls.
- [ ] **Reliable Logging**: Migrate fire-and-forget PostgreSQL/QuestDB inserts to background tasks with proper retry policies.
