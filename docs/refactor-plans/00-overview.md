# Refactor Plan Overview

Five independent workstreams, each with its own branch/PR and its own plan
doc. Execute in this order — each depends on the previous shrinking/settling
the codebase first.

| # | Plan | Branch | Depends on |
|---|------|--------|------------|
| 1 | [Dead code / unused variables](01-dead-code-cleanup.md) | `refactor/dead-code` | — |
| 2 | [Env audit + DB-backed API keys](02-env-audit-and-api-keys.md) | `refactor/env-api-keys` | 1 |
| 3 | [Magic-variable / clean-code pass](03-magic-variables-clean-code.md) | `refactor/magic-values` | 1, 2 |
| 4a | [Backend file splitting](04a-backend-file-splitting.md) | `refactor/split-backend` | 1, 2, 3 |
| 4b | [Frontend file splitting](04b-frontend-file-splitting.md) | `refactor/split-frontend` | 1, 3 |

## Shared rules across all plans

- **One branch/PR per plan.** Do not combine plans in one PR — a problem in
  a later, riskier plan (e.g. file splitting) must never block an earlier,
  safer one from merging.
- **Done-gate before merge:**
  - Backend: `uv run ruff check .` and `uv run pytest -v` both pass.
  - Frontend: `npm run lint` and `npm run build` both pass.
- **No behavior changes** in plans 1-3 and 4a/4b — these are pure refactors.
  Any bug found along the way gets filed/fixed separately, not folded in.
- Plan docs are intentionally scoped to stay well under the ~32k token
  budget each; if a plan grows during execution, split it further (e.g.
  `04a` could become `04a-1-orchestrator.md`, `04a-2-routes.md`) rather than
  letting one doc balloon.

## Context gathered before writing these plans

- Backend ruff config (`backend/pyproject.toml`): `select = ["E","F","I","N","W"]`,
  `line-length = 100`, `ignore = ["E501"]`. No `PLR` (magic value) or `ARG`
  (unused arg) rules enabled yet.
- Frontend lint: `eslint.config.mjs` using `eslint-config-next` (core-web-vitals
  + typescript). No `no-magic-numbers` rule enabled yet. No dedicated
  `typecheck`/`test` npm script — `next build` performs type-checking.
- `LLMProviderConfig` DB table (`backend/db/models.py:257`) already stores
  Fernet-encrypted, user-provided LLM API keys, one row per provider. Routes
  in `backend/api/routes/settings.py` already save/test/list them. The
  orchestrator already does `api_key or settings.<provider>_api_key` (DB
  wins, `.env` is just a fallback) — this system exists, it needs
  verification/completion, not a rebuild.
- No `User` model exists — this is a single-operator app (multiple trading
  *accounts*, not multiple human users). `JWT_SECRET` is declared in
  `core/config.py` but has zero references anywhere else in the backend —
  confirmed dead during this planning pass.
- Existing backend splitting convention: `backend/services/ai_trading/` is
  a package with private submodules (`_context.py`, `_execution.py`,
  `_helpers.py`, `_market_data.py`, `_models.py`, `_service.py`,
  `_signal.py`) behind `__init__.py`. Apply this same shape to other
  oversized modules rather than inventing a new pattern.
- Existing frontend splitting convention: feature-grouped folders under
  `frontend/src/components/<feature>/` (e.g. `components/backtest/`,
  `components/llm-analytics/`, `components/chart/`). Oversized `page.tsx`
  files should extract into matching `components/<feature>/` folders.
