"""OptimizationService — parameter sweep for backtesting strategies.

Runs multiple BacktestEngine calls (one per param combination) sequentially,
collects metrics, ranks by the chosen metric, and persists the result grid.

Usage:
    svc = OptimizationService()
    await svc.run(opt_run_id)
"""
from __future__ import annotations

import importlib
import io
import itertools
import json
import logging
from datetime import datetime, UTC
from typing import Any

from db.models import OptimizationRun, Strategy
from db.postgres import AsyncSessionLocal
from services.backtest_data import BacktestDataService, BacktestDataError
from services.backtest_engine import BacktestEngine
from services.backtest_metrics import compute_metrics

logger = logging.getLogger(__name__)

# Metrics where lower is better (all others: higher is better)
_LOWER_IS_BETTER = {"max_drawdown_pct"}


class OptimizationService:

    async def run(self, opt_run_id: int) -> None:
        """Execute the full sweep for a given OptimizationRun row."""
        async with AsyncSessionLocal() as db:
            opt = await db.get(OptimizationRun, opt_run_id)
            if not opt:
                logger.error("OptimizationRun %d not found", opt_run_id)
                return

            opt.status = "running"
            await db.commit()

            try:
                strategy_db = await db.get(Strategy, opt.strategy_id)
                if not strategy_db:
                    raise ValueError(f"Strategy {opt.strategy_id} not found")

                # ── Load OHLCV data once (shared across all combinations) ──────
                candles, context_candles = await self._load_data(opt, strategy_db)

                # ── Generate cartesian product of param_grid ─────────────────
                param_grid: dict[str, list[Any]] = json.loads(opt.param_grid or "{}")
                if not param_grid:
                    raise ValueError("param_grid is empty — nothing to optimize")

                param_names = list(param_grid.keys())
                param_values = [param_grid[k] for k in param_names]
                combinations = list(itertools.product(*param_values))

                opt.total_combinations = len(combinations)
                await db.commit()
                logger.info(
                    "Optimization %d: %d combinations for strategy=%s symbol=%s",
                    opt_run_id, len(combinations), strategy_db.name, opt.symbol,
                )

                # ── Run each combination sequentially ─────────────────────────
                results: list[dict] = []
                for i, combo in enumerate(combinations):
                    params = dict(zip(param_names, combo))
                    try:
                        result = await self._run_single(
                            candles, context_candles, strategy_db, opt, params
                        )
                        results.append(result)
                        logger.debug("Optimization %d combo %d/%d done: %s", opt_run_id, i + 1, len(combinations), params)
                    except Exception as exc:
                        logger.warning(
                            "Optimization %d combo %d failed (params=%s): %s",
                            opt_run_id, i + 1, params, exc,
                        )

                    opt.completed_combinations = i + 1
                    opt.progress_pct = int((i + 1) * 100 / len(combinations))
                    await db.commit()

                # ── Rank by optimize_metric ───────────────────────────────────
                metric = opt.optimize_metric
                reverse = metric not in _LOWER_IS_BETTER

                def _sort_key(r: dict) -> float:
                    v = r["metrics"].get(metric)
                    if v is None:
                        return float("inf") if not reverse else float("-inf")
                    return float(v)

                results.sort(key=_sort_key, reverse=reverse)

                opt.results = json.dumps(results)
                opt.best_params = json.dumps(results[0]["params"]) if results else "{}"
                opt.status = "completed"
                opt.progress_pct = 100
                await db.commit()
                logger.info(
                    "Optimization %d completed — %d results, best=%s",
                    opt_run_id, len(results), opt.best_params,
                )

            except Exception as exc:
                logger.error("Optimization %d failed: %s", opt_run_id, exc, exc_info=True)
                opt.status = "failed"
                opt.error_message = str(exc)[:500]
                await db.commit()

    # ── Private helpers ───────────────────────────────────────────────────────

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
        import json as _json
        context_tfs: list[str] = _json.loads(strategy_db.context_tfs or "[]")
        if csv_uploads and context_tfs:
            context_candles = {}
            for tf in context_tfs:
                upload_path = csv_uploads.get(tf)
                if upload_path:
                    with open(upload_path, "r") as f:
                        context_candles[tf] = await data_svc.load_from_csv(io.StringIO(f.read()))

        return candles, context_candles

    async def _run_single(
        self,
        candles: list[dict],
        context_candles: dict[str, list[dict]] | None,
        strategy_db: Strategy,
        opt: OptimizationRun,
        params: dict[str, Any],
    ) -> dict:
        """Instantiate strategy with `params`, run engine, return {params, metrics}."""
        # Instantiate a fresh strategy for each combination
        mod = importlib.import_module(strategy_db.module_path)
        cls = getattr(mod, strategy_db.class_name)
        instance = cls()

        # Apply base DB config (primary_tf, context_tfs, symbols, etc.)
        if hasattr(instance, "apply_db_config"):
            instance.apply_db_config(strategy_db)

        # Override with sweep params
        for k, v in params.items():
            setattr(instance, k, v)

        config = {
            "symbol": opt.symbol,
            "timeframe": opt.timeframe,
            "initial_balance": opt.initial_balance,
            "spread_pips": opt.spread_pips,
            "execution_mode": opt.execution_mode,
            "volume": opt.volume,
            "risk_pct": 0.0,
            "max_llm_calls": 0,   # rule-only for optimization (no LLM cost)
            "commission_per_lot": opt.commission_per_lot,
            "tp_partial_close_ratio": opt.tp_partial_close_ratio,
        }

        engine = BacktestEngine()
        result = await engine.run(
            candles=candles,
            strategy=instance,
            config=config,
            progress_cb=None,
            context_candles=context_candles,
        )

        closed = [t for t in result["trades"] if t.get("profit") is not None]
        metrics = compute_metrics(closed, opt.initial_balance)

        return {"params": params, "metrics": metrics}
