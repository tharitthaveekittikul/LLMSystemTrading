"""PipelineTracer — records every step of the AI trading pipeline.

Usage:
    async with PipelineTracer(account_id, symbol, timeframe) as tracer:
        t0 = time.monotonic()
        # ... do work ...
        await tracer.record(
            "step_name",
            output_data={"key": "value"},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
        tracer.finalize(status="completed", final_action="BUY", journal_id=5)

Uses its own DB session (independent of the caller's session) so partial
steps are durable even if the main pipeline session rolls back.
"""
import json
import logging
import time
from typing import Any

from db.models import PipelineRun, PipelineStep
from db.postgres import AsyncSessionLocal

logger = logging.getLogger(__name__)


class PipelineTracer:
    def __init__(self, account_id: int, symbol: str, timeframe: str) -> None:
        self._account_id = account_id
        self._symbol = symbol
        self._timeframe = timeframe
        self._run: PipelineRun | None = None
        self._seq = 0
        self._start_ms = 0.0
        self._final_status = "failed"
        self._final_action: str | None = None
        self._journal_id: int | None = None
        self._trade_id: int | None = None
        self._db = None
        self._session_ctx = None

    async def __aenter__(self) -> "PipelineTracer":
        self._session_ctx = AsyncSessionLocal()
        self._db = await self._session_ctx.__aenter__()
        self._start_ms = time.monotonic()
        self._run = PipelineRun(
            account_id=self._account_id,
            symbol=self._symbol,
            timeframe=self._timeframe,
            status="running",
        )
        self._db.add(self._run)
        await self._db.commit()
        await self._db.refresh(self._run)
        logger.debug(
            "PipelineTracer started | run_id=%s account_id=%s symbol=%s",
            self._run.id, self._account_id, self._symbol,
        )
        return self

    async def record(
        self,
        step_name: str,
        *,
        status: str = "ok",
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        """Persist a single pipeline step immediately."""
        if not self._run or not self._db:
            return
        self._seq += 1
        step = PipelineStep(
            run_id=self._run.id,
            seq=self._seq,
            step_name=step_name,
            status=status,
            input_json=json.dumps(input_data, default=str) if input_data is not None else None,
            output_json=json.dumps(output_data, default=str) if output_data is not None else None,
            error=error,
            duration_ms=duration_ms,
        )
        self._db.add(step)
        await self._db.commit()

    def finalize(
        self,
        *,
        status: str,
        final_action: str | None = None,
        journal_id: int | None = None,
        trade_id: int | None = None,
    ) -> None:
        """Set the final outcome — must be called before __aexit__."""
        self._final_status = status
        self._final_action = final_action
        self._journal_id = journal_id
        self._trade_id = trade_id

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._run and self._db:
            total_ms = int((time.monotonic() - self._start_ms) * 1000)
            self._run.status = "failed" if exc_type else self._final_status
            self._run.final_action = self._final_action
            self._run.total_duration_ms = total_ms
            self._run.journal_id = self._journal_id
            self._run.trade_id = self._trade_id
            await self._db.commit()

            run_id = self._run.id
            if not exc_type:
                try:
                    from api.routes.ws import broadcast
                    await broadcast(self._account_id, "pipeline_run_complete", {
                        "run_id": run_id,
                        "symbol": self._symbol,
                        "timeframe": self._timeframe,
                        "status": self._run.status,
                        "final_action": self._final_action,
                        "total_duration_ms": total_ms,
                        "step_count": self._seq,
                    })
                except Exception as exc:
                    logger.debug("WS broadcast failed (non-critical): %s", exc)

            logger.info(
                "PipelineTracer finished | run_id=%s status=%s action=%s duration_ms=%s",
                run_id, self._run.status, self._final_action, total_ms,
            )

        if self._session_ctx:
            await self._session_ctx.__aexit__(exc_type, exc_val, exc_tb)

        return False  # never suppress exceptions
