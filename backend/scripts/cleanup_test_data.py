"""Cleanup script — remove dev/test data from the database.

Deletes:
  - llm_calls rows where model name is a known test/dev model
  - pipeline_runs that have no journal_id and no trade_id (orphaned test runs)
    (pipeline_steps cascade-delete automatically via FK ondelete=CASCADE)

Usage (from backend/ directory):
    uv run python scripts/cleanup_test_data.py

Safe to re-run (idempotent).
"""
import asyncio
import logging
import sys
from pathlib import Path

# Ensure the backend/ directory is on sys.path so db/core/etc. are importable
# when the script is run as: uv run python scripts/cleanup_test_data.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select, func
from db.postgres import AsyncSessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Model names known to be from dev/test use only — extend as needed
TEST_MODELS = {
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-3.5-turbo",
    "gemini-2.5-flash",
    "gemini-pro",
    "gemini-1.5-flash",
    "claude-3-opus-20240229",
}


async def main() -> None:
    from db.models import LLMCall, PipelineRun

    async with AsyncSessionLocal() as db:
        # ── Count before ──────────────────────────────────────────────────────
        llm_count = (await db.execute(
            select(func.count()).select_from(LLMCall)
            .where(LLMCall.model.in_(TEST_MODELS))
        )).scalar_one()

        pipeline_count = (await db.execute(
            select(func.count()).select_from(PipelineRun)
            .where(PipelineRun.journal_id.is_(None))
            .where(PipelineRun.trade_id.is_(None))
        )).scalar_one()

        logger.info("Before cleanup:")
        logger.info("  llm_calls with test model names:          %d", llm_count)
        logger.info("  orphaned pipeline_runs (no journal/trade): %d", pipeline_count)

        if llm_count == 0 and pipeline_count == 0:
            logger.info("Nothing to clean up.")
            return

        # ── Delete llm_calls with test model names ────────────────────────────
        if llm_count > 0:
            await db.execute(
                delete(LLMCall).where(LLMCall.model.in_(TEST_MODELS))
            )
            logger.info("Deleted %d llm_calls rows", llm_count)

        # ── Delete orphaned pipeline_runs (pipeline_steps cascade) ────────────
        if pipeline_count > 0:
            await db.execute(
                delete(PipelineRun)
                .where(PipelineRun.journal_id.is_(None))
                .where(PipelineRun.trade_id.is_(None))
            )
            logger.info("Deleted %d orphaned pipeline_runs (steps cascade)", pipeline_count)

        await db.commit()
        logger.info("Cleanup complete.")


if __name__ == "__main__":
    asyncio.run(main())
