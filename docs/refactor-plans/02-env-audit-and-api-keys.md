# Plan 2: Env Audit + DB-Backed API Key Verification

**Branch:** `refactor/env-api-keys`
**Depends on:** Plan 1 (dead code cleanup merged first).
**Risk:** medium — touches credential handling and live-trading LLM calls.

## Context already verified during planning

The "save user-provided keys in Postgres" system **already exists and is
already wired into live trading**, not just the settings UI:

- `LLMProviderConfig` (`db/models.py:257`) stores one Fernet-encrypted key
  per provider (`openai`, `gemini`, `anthropic`, `openrouter`, `ollama`).
- `TaskLLMAssignment` maps a task name (e.g. `market_analysis`, `vision`,
  `execution_decision`, `news_analysis`, `maintenance_technical`,
  `maintenance_sentiment`, `maintenance_decision`, `post_trade_analysis`)
  to a provider + model.
- `_get_task_llm(task, db)` looks up the assignment, loads the matching
  `LLMProviderConfig` row, decrypts the key, and builds the LLM — this is
  called from every real call site: `services/ai_trading/_signal.py`,
  `services/news_analyzer.py`, `services/position_maintenance.py`,
  `services/research_loop.py`, `services/trade_analyzer.py`.
- If no `TaskLLMAssignment` row exists for a task, `_get_task_llm` returns
  `None` and the caller falls back to `ai/orchestrator.py:_build_llm()`
  with no `api_key`, which then falls back to `settings.<provider>_api_key`
  (the `.env` value). **This fallback chain is correct and intentional —
  do not remove it** (per grilling decision: `.env` stays as a bootstrap
  default for a fresh deploy with an empty DB).

## Found during planning — fix these

1. **Duplicated `_get_task_llm`.** The exact same function body exists in
   two places:
   - `services/ai_trading/_helpers.py:74` (canonical — re-exported via
     `services/ai_trading/__init__.py` and imported by
     `news_analyzer.py`, `research_loop.py`, `trade_analyzer.py`)
   - `services/position_maintenance.py:154` (independent copy)

   **Task:** delete the copy in `position_maintenance.py`, import the
   canonical one from `services.ai_trading` instead. Verify no behavior
   change (same DB queries, same decrypt call).

2. **`jwt_secret` is dead.** Declared in `core/config.py`, present in
   `.env.example` as `JWT_SECRET`, but has zero references anywhere else
   in the backend (verified via repo-wide grep). Either:
   - remove it from `config.py` and `.env.example` entirely, or
   - if there's a near-term plan to add dashboard auth that will use it,
     leave a comment noting it's reserved and why.

   **Do not silently delete without checking with whoever owns the
   near-term roadmap** — unlike the other dead-code removals, a secret key
   placeholder being unused today doesn't rule out an imminent auth
   feature depending on it.

## Full env audit (do this exhaustively, not just spot-checks)

1. List every variable in `backend/.env.example`.
2. For each, `grep -rn "settings\.<field_name>"` across `backend/` (outside
   `core/config.py`) to confirm it's actually read somewhere.
3. For each `Settings` field in `core/config.py`, confirm it appears in
   `.env.example` with a comment explaining its purpose and valid values
   (several already do — match that style for any missing ones).
4. Anything with zero usages outside `config.py`: flag it explicitly in
   the PR description (don't just delete silently) so it's reviewable.
5. Confirm `frontend` has no stray env vars of its own beyond what
   `next.config.ts`/`NEXT_PUBLIC_*` actually reads — same
   grep-for-usage check.

## Verify DB-backed key path end-to-end

1. Confirm all 5 providers (`openai`, `gemini`, `anthropic`, `openrouter`,
   `ollama`) round-trip through `api/routes/settings.py`'s save/test/list
   endpoints (spot-checked during planning — all 5 branches exist in the
   connection-test and model-fetch helpers).
2. Confirm `TaskLLMAssignment.provider` has no DB constraint that silently
   excludes `openrouter`/`ollama` (check the Alembic migration that created
   the column, not just the SQLAlchemy model).
3. Manually exercise the settings UI: save a key for a provider, assign a
   task to it, and confirm (via logs — see `core/logging.py` conventions)
   that the next real signal-generation run for that task actually uses
   the DB key and not the `.env` fallback. This is the one part of this
   plan that needs a live/manual check, not just a lint pass.

## Acceptance criteria

- `services/position_maintenance.py` no longer defines its own
  `_get_task_llm` — imports the shared one.
- `.env.example` audit is complete and documented in the PR description:
  every var confirmed used, or explicitly flagged as dead with a decision
  recorded (removed vs. kept-as-reserved).
- Manual verification of at least one provider's DB-key path reaching a
  live LLM call, documented in the PR description (what was tested, what
  was observed in logs).
- `uv run pytest -v` passes.
