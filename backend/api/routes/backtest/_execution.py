"""Backtest execution engine: background job runner and strategy loader.

Runs as a FastAPI BackgroundTask kicked off by _runs.py:submit_run — not an
HTTP-facing module itself.
"""
import importlib
import io
import json
import logging

from sqlalchemy import select

from api.routes.backtest._schemas import BacktestRunRequest
from api.routes.ws import broadcast_all
from db.models import Account, BacktestRun, BacktestTrade, Strategy
from db.postgres import AsyncSessionLocal
from services.backtest_data import BacktestDataError, BacktestDataService
from services.backtest_engine import BacktestEngine
from services.backtest_metrics import compute_metrics

logger = logging.getLogger(__name__)

_TIMEFRAME_INT_MAP: dict[str, int] = {
    "M1": 1, "M2": 2, "M3": 3, "M4": 4, "M5": 5,
    "M6": 6, "M10": 10, "M12": 12, "M15": 15, "M20": 20,
    "M30": 30, "H1": 16385, "H2": 16386, "H3": 16387,
    "H4": 16388, "H6": 16390, "H8": 16392, "H12": 16396,
    "D1": 16408, "W1": 32769, "MN1": 49153,
}


def _timeframe_to_int(tf: str) -> int:
    return _TIMEFRAME_INT_MAP.get(tf.upper(), 15)


async def _run_backtest_job(
    run_id: int,
    req: BacktestRunRequest,
    strategy_db: Strategy,
    timeframe: str,
    context_tfs: list[str],
) -> None:
    """Background task: load OHLCV data, run engine, persist results."""
    async with AsyncSessionLocal() as db:
        run = await db.get(BacktestRun, run_id)
        if not run:
            return

        run.status = "running"
        await db.commit()
        await broadcast_all("backtest_progress", {"run_id": run_id, "progress_pct": 0})

        try:
            # ── Load OHLCV data ────────────────────────────────────────────────
            data_svc = BacktestDataService()

            if req.csv_upload_id or req.csv_uploads:
                # ── CSV path (primary TF) ──────────────────────────────────────
                primary_upload = req.csv_upload_id or (
                    req.csv_uploads.get(timeframe) if req.csv_uploads else None
                )
                if not primary_upload:
                    raise BacktestDataError(
                        "No primary-TF CSV provided. Upload a CSV for the primary timeframe."
                    )
                with open(primary_upload, "r") as f:
                    candles = await data_svc.load_from_csv(io.StringIO(f.read()))

                # ── Persist CSV for chart replay ────────────────────────────────
                import pathlib
                import shutil
                _candle_store = pathlib.Path("uploads/candles")
                _candle_store.mkdir(parents=True, exist_ok=True)
                _dest = _candle_store / f"{run_id}.csv"
                try:
                    shutil.copy2(str(primary_upload), str(_dest))
                    run.data_file_path = str(_dest.resolve())
                    await db.commit()
                except Exception as _e:
                    logger.warning("Could not persist candle CSV for run %d: %s", run_id, _e)

                # ── Context TF CSVs (optional) ─────────────────────────────────
                context_candles: dict[str, list[dict]] = {}
                if req.csv_uploads:
                    for ctx_tf, upload_path in req.csv_uploads.items():
                        if ctx_tf == timeframe:
                            continue  # already loaded as primary
                        with open(upload_path, "r") as f:
                            ctx_c = await data_svc.load_from_csv(io.StringIO(f.read()))
                        context_candles[ctx_tf] = ctx_c
                        logger.info(
                            "Loaded context TF %s: %d candles", ctx_tf, len(ctx_c)
                        )
            else:
                from mt5.bridge import MT5_AVAILABLE, AccountCredentials, MT5Bridge
                if not MT5_AVAILABLE:
                    raise BacktestDataError(
                        "MT5 is not available. Please upload a CSV file instead."
                    )
                account = (await db.execute(
                    select(Account).where(Account.is_active == True).limit(1)  # noqa: E712
                )).scalars().first()
                if not account:
                    raise BacktestDataError("No active MT5 account found")
                from core.security import decrypt
                creds = AccountCredentials(
                    login=account.login,
                    password=decrypt(account.password_encrypted),
                    server=account.server,
                    path=account.mt5_path or "",
                )
                # Primary TF
                tf_int = _timeframe_to_int(timeframe)
                async with MT5Bridge(creds) as bridge:
                    candles = await data_svc.load_from_mt5(
                        bridge, req.symbol, tf_int, req.start_date, req.end_date
                    )
                # Context TFs from MT5 (auto-loaded when available)
                context_candles = {}
                async with MT5Bridge(creds) as bridge:
                    for ctx_tf in context_tfs:
                        try:
                            ctx_c = await data_svc.load_from_mt5(
                                bridge, req.symbol, _timeframe_to_int(ctx_tf),
                                req.start_date, req.end_date,
                            )
                            context_candles[ctx_tf] = ctx_c
                            logger.info("Loaded MT5 context TF %s: %d candles", ctx_tf, len(ctx_c))
                        except Exception as exc:
                            logger.warning("Could not load context TF %s: %s", ctx_tf, exc)

            # ── Load strategy instance ─────────────────────────────────────────
            strategy_instance = _load_strategy(strategy_db)

            # ── Run engine ────────────────────────────────────────────────────
            engine = BacktestEngine()
            config = {
                "symbol": req.symbol,
                "timeframe": timeframe,
                "initial_balance": req.initial_balance,
                "spread_pips": req.spread_pips,
                "execution_mode": req.execution_mode,
                "volume": req.volume,
                "risk_pct": req.risk_pct,
                "max_llm_calls": req.max_llm_calls,
                "commission_per_lot": req.commission_per_lot,
                "tp_partial_close_ratio": req.tp_partial_close_ratio,
                "skip_llm": req.skip_llm,
            }

            async def _progress(pct: int) -> None:
                async with AsyncSessionLocal() as progress_db:
                    r = await progress_db.get(BacktestRun, run_id)
                    if r:
                        r.progress_pct = pct
                        await progress_db.commit()
                await broadcast_all("backtest_progress", {"run_id": run_id, "progress_pct": pct})

            result = await engine.run(
                candles, strategy_instance, config,
                progress_cb=_progress,
                context_candles=context_candles or None,
            )
            run.avg_spread = result.get("avg_spread")

            # ── Persist trades ────────────────────────────────────────────────
            for td in result["trades"]:
                bt = BacktestTrade(
                    run_id=run_id,
                    symbol=td["symbol"],
                    direction=td["direction"],
                    entry_time=td["entry_time"],
                    exit_time=td.get("exit_time"),
                    entry_price=td["entry_price"],
                    exit_price=td.get("exit_price"),
                    stop_loss=td["stop_loss"],
                    take_profit=td["take_profit"],
                    volume=td["volume"],
                    profit=td.get("profit"),
                    exit_reason=td.get("exit_reason"),
                    equity_after=td.get("equity_after"),
                    pattern_name=td.get("pattern_name"),
                    pattern_metadata=json.dumps(td.get("pattern_metadata")) if td.get("pattern_metadata") else None,
                    source=td.get("source"),
                )
                db.add(bt)
            await db.flush()

            # ── Compute + persist metrics ──────────────────────────────────────
            closed = [t for t in result["trades"] if t.get("profit") is not None]
            metrics = compute_metrics(closed, req.initial_balance)

            run.status = "completed"
            run.progress_pct = 100
            run.total_trades = metrics["total_trades"]
            run.win_rate = metrics["win_rate"]
            run.profit_factor = metrics["profit_factor"]
            run.expectancy = metrics["expectancy"]
            run.max_drawdown_pct = metrics["max_drawdown_pct"]
            run.recovery_factor = metrics["recovery_factor"]
            run.sharpe_ratio = metrics["sharpe_ratio"]
            run.sortino_ratio = metrics["sortino_ratio"]
            run.total_return_pct = metrics["total_return_pct"]
            run.avg_win = metrics["avg_win"]
            run.avg_loss = metrics["avg_loss"]
            run.max_consec_wins = metrics["max_consec_wins"]
            run.max_consec_losses = metrics["max_consec_losses"]
            await db.commit()

            await broadcast_all("backtest_complete", {
                "run_id": run_id,
                "total_trades": metrics["total_trades"],
                "win_rate": metrics["win_rate"],
                "profit_factor": metrics["profit_factor"],
            })
            logger.info("Backtest run %d completed | %d trades", run_id, metrics["total_trades"])

        except Exception as exc:
            logger.error("Backtest run %d failed: %s", run_id, exc, exc_info=True)
            run.status = "failed"
            run.error_message = str(exc)[:500]
            await db.commit()
            await broadcast_all("backtest_failed", {"run_id": run_id, "error": str(exc)[:200]})


# ── Helpers ────────────────────────────────────────────────────────────────────

_CODE_MODES = {"rule_only", "rule_then_llm", "hybrid_validator", "multi_agent"}


def _load_strategy(strategy_db: Strategy):
    """Instantiate a strategy from the DB record."""
    if (
        (strategy_db.strategy_type == "code" or strategy_db.execution_mode in _CODE_MODES)
        and strategy_db.module_path
        and strategy_db.class_name
    ):
        mod = importlib.import_module(strategy_db.module_path)
        cls = getattr(mod, strategy_db.class_name)
        instance = cls()
        instance.strategy_type = "code"
        # Hydrate primary_tf, context_tfs, symbols from DB
        if hasattr(instance, "apply_db_config"):
            instance.apply_db_config(strategy_db)
        return instance

    class _ConfigStrategy:
        strategy_type = strategy_db.strategy_type
        _prompt = strategy_db.custom_prompt

        def generate_signal(self, market_data: dict) -> dict | None:
            return None  # triggers LLM path (sampled by engine)

        def system_prompt(self) -> str | None:
            return self._prompt

    return _ConfigStrategy()
