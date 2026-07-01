# Plan 4a: Backend File Splitting

**Branch:** `refactor/split-backend`
**Depends on:** Plans 1, 2, 3 merged first.
**Risk:** medium-high — structural change, do one file per commit and run
the done-gate after each.
**Threshold:** any `.py` file over ~400 lines (excluding tests/migrations).
**Pattern to follow:** the existing `services/ai_trading/` package — a
directory with an `__init__.py` that re-exports the public surface, and
private `_topic.py` submodules underneath. Do not invent a different shape.

## Files in scope (line counts as of this planning pass)

| File | Lines | Suggested split |
|------|-------|------------------|
| `ai/orchestrator.py` | 1144 | see below |
| `api/routes/backtest.py` | 1059 | see below |
| `api/routes/accounts.py` | 1058 | see below |
| `services/position_maintenance.py` | 728 | by pipeline stage |
| `services/scheduler.py` | 689 | by job type |
| `api/routes/settings.py` | 653 | by settings domain |
| `api/routes/llm_analytics.py` | 628 | by report type |
| `services/abstract_runner.py` | 596 | by lifecycle stage |
| `api/routes/strategies.py` | 562 | by CRUD vs. execution |
| `services/backtest_engine.py` | 553 | by engine phase |

Re-run the line-count check before starting (`wc -l` on each) — Plans 1-3
will have already shrunk some of these; re-prioritize by actual size at
execution time rather than trusting this snapshot.

## `ai/orchestrator.py` → package (verified function-level breakdown)

Convert to `ai/orchestrator/` package:

- `_llm.py`: `_build_llm`, `_provider_from_llm`, `_model_name_from_llm`,
  `_extract_tokens`, `log_llm_usage`, `_call_llm_for_role` (lines 116-333
  in the current file — LLM construction + usage logging plumbing).
- `_parsing.py`: `_normalize_raw` (334-474 — response parsing/normalization).
- `_roles.py`: `_run_market_analysis`, `_run_chart_vision`,
  `_run_execution_decision`, `_run_maintenance_technical`,
  `_run_maintenance_sentiment`, `_run_maintenance_decision` (475-689 —
  per-role prompt execution).
- `_service.py`: `analyze_news_impact`, `analyze_market`,
  `review_position`, `run_agent_pipeline` (690-end — the public entry
  points everything else in the codebase actually imports).
- `__init__.py`: re-export exactly what's imported elsewhere today (check
  every `from ai.orchestrator import ...` / `from ai import orchestrator`
  site first — use the code-review-graph `query_graph_tool` with
  `callers_of` on `ai.orchestrator` to get the exact list before moving
  anything, so the re-export barrel is complete and nothing breaks).

## `api/routes/accounts.py` → sub-routers (verified endpoint breakdown)

- CRUD (`list_accounts`, `create_account`, `get_account`, `update_account`,
  `deactivate_account`) → `accounts/_crud.py`
- MT5 live info (`get_mt5_account_info`, `list_symbols`) → `accounts/_mt5_info.py`
- Analysis (`analyze_account`) → `accounts/_analyze.py`
- Stats/history (`get_account_stats`, `get_account_history`,
  `get_equity_history`) → `accounts/_stats.py`
- Sync operations (`sync_orders`, `sync_account_history`, `sync_account`,
  `sync_all_accounts`) — this is the largest chunk (~500 lines) →
  `accounts/_sync.py`
- Research loop (`get_research_progress`, `trigger_research_loop`,
  `toggle_exclude_research_trade`) → `accounts/_research.py`
- Each submodule defines its own `APIRouter()`; `accounts/__init__.py`
  combines them with `router.include_router(...)` and exposes the final
  `router` under the same import path `api.routes.accounts` that
  `main.py` already expects — **check `main.py`'s registration line
  before renaming anything** so the mount point doesn't move.

## `api/routes/backtest.py` → sub-routers

- Run CRUD + data (`submit_run`, `list_runs`, `get_run`, `get_trades`,
  `delete_run`, `upload_csv`) → `backtest/_runs.py`
- Analytics (`get_equity_curve`, `get_drawdown`, `get_candles`,
  `get_monthly_pnl`, `get_analytics_summary`, `get_analytics_groups`,
  `get_analytics_heatmap`, `get_analytics_combinations`) — largest chunk
  (~600 lines) → `backtest/_analytics.py`
- Optimization (`submit_optimization`, `list_optimizations`,
  `get_optimization`, `cancel_optimization`, `resume_optimization`,
  `get_optimization_results`) → `backtest/_optimize.py`
- Same `__init__.py` composition approach as `accounts/`.

## Remaining files (`position_maintenance.py`, `scheduler.py`,
`settings.py`, `llm_analytics.py`, `abstract_runner.py`,
`strategies.py`, `backtest_engine.py`)

Apply the same process manually at execution time (this plan doc doesn't
pre-read every one of these to keep the doc within budget):

1. List top-level function/class definitions (`grep -n "^def \|^async def \|^class "`).
2. Group by responsibility (the file's own section-comment banners, where
   present, are a strong hint — several files in this repo already use
   `# ── Section ──` banners internally, which is a preview of where the
   split boundaries should go).
3. Before moving code, run `query_graph_tool` (callers_of) for every
   function being moved, to get the exact list of import sites to update.
4. One file split per commit. Run the done-gate after each.

## Acceptance criteria

- No file outside `tests/`, `alembic/versions/`, and generated code exceeds
  ~400 lines.
- `main.py`'s router registrations still point at valid import paths
  (verify by starting the app: `uv run uvicorn main:app --reload --port 8000`
  and hitting each affected route once).
- `uv run pytest -v` passes after every single file split, not just at
  the end.
- `uv run ruff check .` passes (import ordering, no unused imports
  introduced by the split).
