-- ============================================================
-- One-time cleanup of test / dev data from PostgreSQL.
-- Run against your local DB when needed:
--   psql $DATABASE_URL -f backend/tests/cleanup_test_data.sql
--
-- Sections are ordered to respect FK constraints.
-- Uncomment blocks you actually want to delete.
-- ============================================================

-- ── 1. Test artifacts left by automated tests ────────────────
-- Strategy created by test_strategy_routes (if cleanup failed)
DELETE FROM strategies WHERE name = 'Test M15';

-- Accounts created by test_account_stats / test_equity_history
-- (CASCADE automatically removes related trades, ai_journal,
--  account_strategies, pipeline_runs, pipeline_steps, llm_calls)
DELETE FROM accounts WHERE broker = 'TestBroker';

-- Kill-switch log rows written by test_kill_switch_routes
-- (all rows are safe to delete — they are just audit records)
-- TRUNCATE kill_switch_log;

-- ── 2. Dev / manual-testing data ─────────────────────────────
-- LLM call logs written by real pipeline runs during development
-- (gpt-4o, gemini-2.5-flash, etc.)
-- TRUNCATE llm_calls;

-- Pipeline run traces from development
-- (CASCADE removes pipeline_steps automatically)
-- TRUNCATE pipeline_runs CASCADE;

-- AI journal entries from development
-- TRUNCATE ai_journal;

-- Backtest runs from development
-- (CASCADE removes backtest_trades automatically)
-- TRUNCATE backtest_runs CASCADE;
