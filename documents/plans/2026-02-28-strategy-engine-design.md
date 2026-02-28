# Strategy Engine Design
Date: 2026-02-28 | Status: Approved

## Problem

AITradingService.analyze_and_trade() works but nothing calls it automatically.
No formal Strategy model exists. System stops trading when frontend is closed.

## Goals

1. Autonomous trading: schedule-driven, frontend-independent
2. Formal Strategy model: named, typed, configurable, stored in DB
3. Account binding: many-to-many
4. Strategy management UI: wizard to create, configure, bind strategies
5. Code-based best practice: BaseStrategy abstract class in backend/strategies/

## Decisions

- Scheduler: APScheduler AsyncIOScheduler (interval + cron, runtime add/remove)
- Code strategies: files in backend/strategies/ loaded via importlib (no dynamic eval)
- DB: normalized strategies + account_strategies junction table

---

## Architecture

New files:
  backend/strategies/base_strategy.py
  backend/strategies/eurusd_m15_scalp.py
  backend/services/scheduler.py
  backend/api/routes/strategies.py

Changed files:
  backend/db/models.py          (add Strategy, AccountStrategy, Trade.strategy_id)
  backend/main.py               (start scheduler in lifespan)
  backend/services/ai_trading.py (accept strategy_overrides param)
  frontend/src/app/strategies/  (list, new, [id] pages)

Flow:
  FastAPI lifespan -> scheduler.start() -> load active bindings from DB
    -> for each binding x symbol -> APScheduler job
         interval trigger   -> IntervalTrigger(minutes=N)
         candle_close       -> CronTrigger mapped from timeframe
              -> AITradingService.analyze_and_trade(
                     account_id, symbol, timeframe, strategy_overrides)

---

## DB Models

strategies table columns:
  id, name (UNIQUE), description, strategy_type (config|prompt|code)
  trigger_type (interval|candle_close), interval_minutes
  symbols (JSON), timeframe
  lot_size, sl_pips, tp_pips (nullable = account default), news_filter (bool)
  custom_prompt (text, prompt-type only)
  module_path, class_name (code-type only)
  is_active, created_at

account_strategies table columns:
  id, account_id FK, strategy_id FK
  is_active (per-binding toggle; starts/stops job at runtime)
  created_at
  UNIQUE(account_id, strategy_id)

trades table change:
  Add strategy_id (nullable FK -> strategies.id)

---

## Scheduler (services/scheduler.py)

Candle-close cron map:
  M15 -> minute=0,15,30,45
  M30 -> minute=0,30
  H1  -> hour=*, minute=0
  H4  -> hour=0,4,8,12,16,20 minute=0
  D1  -> hour=0, minute=0

Job ID: strat_{binding.id}_{symbol}
Runtime add/remove: on binding activate/pause/delete

---

## BaseStrategy Pattern (best practice for code-based strategies)

File: backend/strategies/base_strategy.py

  class BaseStrategy(ABC):
      symbols: list[str] = []
      timeframe: str = "M15"
      trigger_type: str = "candle_close"
      interval_minutes: int = 15

      @abstractmethod
      def system_prompt(self) -> str: ...

      def lot_size(self) -> float | None: return None
      def sl_pips(self) -> float | None: return None
      def tp_pips(self) -> float | None: return None
      def news_filter(self) -> bool: return True
      def should_trade(self, signal) -> bool: return signal.action != "HOLD"

Example (backend/strategies/eurusd_m15_scalp.py):

  class EURUSDScalp(BaseStrategy):
      symbols = ["EURUSD", "GBPUSD"]
      timeframe = "M15"
      trigger_type = "candle_close"

      def system_prompt(self) -> str:
          return "Scalping specialist on M15. London open focus. RSI+EMA confluence."

      def lot_size(self): return 0.05
      def sl_pips(self): return 15

Workflow to add new code strategy:
  1. Create backend/strategies/your_strategy.py inheriting BaseStrategy
  2. Implement system_prompt() and optional overrides
  3. UI wizard: type=Code, module=strategies.your_strategy, class=YourClass
  4. Restart backend once
  5. Bind to account -> scheduler starts job

---

## API Routes (prefix /api/v1/strategies)

  GET    /strategies
  POST   /strategies
  GET    /strategies/{id}
  PATCH  /strategies/{id}
  DELETE /strategies/{id}
  POST   /strategies/{id}/bind
  DELETE /strategies/{id}/bind/{account_id}
  PATCH  /strategies/{id}/bind/{account_id}
  GET    /strategies/{id}/runs

---

## Frontend

/strategies          list page: card grid with name, type badge, timeframe, bound accounts, last run, toggle
/strategies/new      wizard: Step1 basics, Step2 market+schedule, Step3 type-config, Step4 bind accounts
/strategies/{id}     detail tabs: Config | Accounts | Recent runs

---

## AITradingService changes

  analyze_and_trade(account_id, symbol, timeframe, db,
                    strategy_id=None, strategy_overrides=None)

  StrategyOverrides Pydantic model: lot_size, sl_pips, tp_pips, news_filter, custom_prompt
  All nullable. Scheduler builds from Strategy row before calling.

---

## Out of Scope
- Backtesting
- Strategy performance comparison
- Browser code upload
- Per-strategy LLM provider
