"""OptimizationService — parameter sweep for backtesting strategies.

Runs BacktestEngine calls concurrently using ProcessPoolExecutor for true
CPU parallelism (bypasses Python GIL), bounded by opt.max_workers.

On Windows, ProcessPoolExecutor uses the 'spawn' start method, so each worker
process re-initialises Python from scratch. The _worker_initializer copies the
parent's sys.path so backend imports resolve correctly in subprocesses.

Usage:
    svc = OptimizationService()
    await svc.run(opt_run_id)
"""
from __future__ import annotations

import asyncio
import importlib
import io
import itertools
import json
import logging
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, UTC
from types import SimpleNamespace
from typing import Any

from db.models import OptimizationRun, Strategy
from db.postgres import AsyncSessionLocal
from services.backtest_data import BacktestDataService, BacktestDataError
from services.backtest_engine import BacktestEngine
from services.backtest_metrics import compute_metrics

logger = logging.getLogger(__name__)

# Metrics where lower is better (all others: higher is better)
_LOWER_IS_BETTER = {"max_drawdown_pct"}


# ── Module-level workers — must be top-level functions to be picklable ────────

def _worker_initializer(sys_path: list[str]) -> None:
    """Called once per worker process at startup.

    Copies the parent's sys.path so backend modules are importable in the
    spawned subprocess (critical on Windows where 'spawn' creates a clean env).
    """
    import sys as _sys
    for p in sys_path:
        if p not in _sys.path:
            _sys.path.insert(0, p)


def _worker_run_combo(worker_args: dict) -> dict:
    """Execute one backtest combination in a worker subprocess.

    Receives only picklable primitives (no SQLAlchemy models, no closures).
    Returns {"params": ..., "metrics": ...} or raises on failure.
    """
    import asyncio
    import importlib
    from types import SimpleNamespace
    from services.backtest_engine import BacktestEngine
    from services.backtest_metrics import compute_metrics

    mod = importlib.import_module(worker_args["module_path"])
    cls = getattr(mod, worker_args["class_name"])
    instance = cls()

    # Reconstruct strategy DB config from primitive dict (no SQLAlchemy in subprocess)
    if hasattr(instance, "apply_db_config"):
        instance.apply_db_config(SimpleNamespace(**worker_args["strategy_fields"]))

    # Apply the parameter combination for this sweep slot
    for k, v in worker_args["params"].items():
        setattr(instance, k, v)

    engine = BacktestEngine()
    result = asyncio.run(engine.run(
        candles=worker_args["candles"],
        strategy=instance,
        config=worker_args["config"],
        progress_cb=None,
        context_candles=worker_args.get("context_candles"),
    ))

    closed = [t for t in result["trades"] if t.get("profit") is not None]
    metrics = compute_metrics(closed, worker_args["initial_balance"])
    return {"params": worker_args["params"], "metrics": metrics}


# ── Service ───────────────────────────────────────────────────────────────────

class OptimizationService:

    async def run(self, opt_run_id: int) -> None:
        """Execute the full sweep for a given OptimizationRun row."""
        async with AsyncSessionLocal() as db:
            opt = await db.get(OptimizationRun, opt_run_id)
            if not opt:
                logger.error("OptimizationRun %d not found", opt_run_id)
                return

            opt.status = "running"
            opt.started_at = datetime.now(UTC)
            await db.commit()

            try:
                strategy_db = await db.get(Strategy, opt.strategy_id)
                if not strategy_db:
                    raise ValueError(f"Strategy {opt.strategy_id} not found")

                # ── Load OHLCV data once (shared across all combinations) ──────
                candles, context_candles = await self._load_data(opt, strategy_db)

                # ── Generate cartesian product of param_grid ──────────────────
                param_grid: dict[str, list[Any]] = json.loads(opt.param_grid or "{}")
                if not param_grid:
                    raise ValueError("param_grid is empty — nothing to optimize")

                param_names = list(param_grid.keys())
                param_values = [param_grid[k] for k in param_names]
                combinations = list(itertools.product(*param_values))
                total = len(combinations)

                opt.total_combinations = total
                await db.commit()
                logger.info(
                    "Optimization %d: %d combinations | strategy=%s symbol=%s workers=%d",
                    opt_run_id, total, strategy_db.name, opt.symbol, opt.max_workers,
                )

                # ── Build picklable worker args (no SQLAlchemy objects) ───────
                strategy_fields = self._extract_strategy_fields(strategy_db)
                opt_config = {
                    "symbol": opt.symbol,
                    "timeframe": opt.timeframe,
                    "initial_balance": opt.initial_balance,
                    "spread_pips": opt.spread_pips,
                    "execution_mode": opt.execution_mode,
                    "volume": opt.volume,
                    "risk_pct": opt.risk_pct or 0.0,
                    "max_llm_calls": 0,          # rule-only for optimization (no LLM cost)
                    "commission_per_lot": opt.commission_per_lot,
                    "tp_partial_close_ratio": opt.tp_partial_close_ratio,
                }

                worker_args_list = [
                    {
                        "module_path": strategy_db.module_path,
                        "class_name": strategy_db.class_name,
                        "strategy_fields": strategy_fields,
                        "params": dict(zip(param_names, combo)),
                        "candles": candles,
                        "context_candles": context_candles,
                        "config": opt_config,
                        "initial_balance": opt.initial_balance,
                    }
                    for combo in combinations
                ]

                # ── Rank key (defined early; used for both completed and cancelled) ─
                metric = opt.optimize_metric
                reverse = metric not in _LOWER_IS_BETTER

                def _sort_key(r: dict) -> float:
                    v = r["metrics"].get(metric)
                    if v is None:
                        return float("inf") if not reverse else float("-inf")
                    return float(v)

                # ── Run combinations in process pool ──────────────────────────
                # ProcessPoolExecutor gives true CPU parallelism (one OS process per
                # worker), bypassing the GIL that limits ThreadPoolExecutor for
                # CPU-bound Python work like the backtest candle loop.
                results: list[dict] = []
                completed_count = 0
                should_cancel = False
                loop = asyncio.get_running_loop()

                with ProcessPoolExecutor(
                    max_workers=opt.max_workers,
                    initializer=_worker_initializer,
                    initargs=(sys.path,),
                ) as executor:
                    futures = [
                        loop.run_in_executor(executor, _worker_run_combo, args)
                        for args in worker_args_list
                    ]

                    for fut in asyncio.as_completed(futures):
                        try:
                            result = await fut
                            results.append(result)
                        except Exception as exc:
                            logger.warning(
                                "Optimization %d combo failed: %s",
                                opt_run_id, exc,
                            )

                        completed_count += 1
                        pct = int(completed_count * 100 / total)
                        logger.debug(
                            "Optimization %d combo %d/%d done",
                            opt_run_id, completed_count, total,
                        )

                        async with AsyncSessionLocal() as progress_db:
                            o = await progress_db.get(OptimizationRun, opt_run_id)
                            if o:
                                o.completed_combinations = completed_count
                                o.progress_pct = pct
                                await progress_db.commit()
                                if o.status == "cancelling":
                                    should_cancel = True

                        if should_cancel:
                            logger.info(
                                "Optimization %d: cancellation requested, stopping after %d/%d combos",
                                opt_run_id, completed_count, total,
                            )
                            # Cancel queued (not-yet-started) futures and don't wait for
                            # running workers — the with-block __exit__ will still drain
                            # the max_workers currently-running processes quickly.
                            executor.shutdown(wait=False, cancel_futures=True)
                            break

                # ── Save results (partial on cancel, full on completion) ───────
                results.sort(key=_sort_key, reverse=reverse)
                opt.results = json.dumps(results)
                opt.best_params = json.dumps(results[0]["params"]) if results else "{}"
                opt.completed_at = datetime.now(UTC)

                if should_cancel:
                    opt.status = "cancelled"
                    opt.progress_pct = pct if total > 0 else 0
                    await db.commit()
                    logger.info(
                        "Optimization %d cancelled — %d partial results saved (%d/%d combos run)",
                        opt_run_id, len(results), completed_count, total,
                    )
                else:
                    opt.status = "completed"
                    opt.progress_pct = 100
                    opt.completed_combinations = total
                    await db.commit()
                    logger.info(
                        "Optimization %d completed — %d/%d results, best=%s",
                        opt_run_id, len(results), total, opt.best_params,
                    )

            except Exception as exc:
                logger.error("Optimization %d failed: %s", opt_run_id, exc, exc_info=True)
                opt.status = "failed"
                opt.error_message = str(exc)[:500]
                await db.commit()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _extract_strategy_fields(self, strategy_db: Strategy) -> dict:
        """Serialize SQLAlchemy model fields to a plain dict for subprocess pickling.

        Only includes the fields that apply_db_config() reads — keeps payload small.
        """
        return {
            "primary_tf": strategy_db.primary_tf,
            "context_tfs": strategy_db.context_tfs,
            "symbols": strategy_db.symbols,
            "skip_hours_timezone": strategy_db.skip_hours_timezone,
            "skip_hours": strategy_db.skip_hours,
            "skip_weekdays": strategy_db.skip_weekdays,
            "strategy_params": strategy_db.strategy_params,
        }

    async def _load_data(
        self,
        opt: OptimizationRun,
        strategy_db: Strategy,
    ) -> tuple[list[dict], dict[str, list[dict]] | None]:
        """Load primary + context candles from CSV or raise BacktestDataError."""
        data_svc = BacktestDataService()

        if not opt.csv_upload_id and not opt.csv_uploads:
            raise BacktestDataError(
                "No CSV provided for optimization. Upload a CSV file when creating the run."
            )

        csv_uploads: dict[str, str] = json.loads(opt.csv_uploads or "{}")
        primary_upload = opt.csv_upload_id or csv_uploads.get(opt.timeframe)
        if not primary_upload:
            raise BacktestDataError(
                f"No primary-TF CSV found for timeframe {opt.timeframe}."
            )

        with open(primary_upload, "r") as f:
            candles = await data_svc.load_from_csv(io.StringIO(f.read()))

        # Context candles (MTF strategies)
        context_candles: dict[str, list[dict]] | None = None
        context_tfs: list[str] = json.loads(strategy_db.context_tfs or "[]")
        if csv_uploads and context_tfs:
            context_candles = {}
            for tf in context_tfs:
                upload_path = csv_uploads.get(tf)
                if upload_path:
                    with open(upload_path, "r") as f:
                        context_candles[tf] = await data_svc.load_from_csv(io.StringIO(f.read()))

        return candles, context_candles
