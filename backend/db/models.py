from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.postgres import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    broker: Mapped[str] = mapped_column(String(100))
    login: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    password_encrypted: Mapped[str] = mapped_column(String(500))  # Fernet-encrypted
    server: Mapped[str] = mapped_column(String(200))
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # Trading config per account
    allowed_symbols: Mapped[str] = mapped_column(Text, default="")  # JSON list
    max_lot_size: Mapped[float] = mapped_column(Float, default=0.1)
    risk_pct: Mapped[float] = mapped_column(Float, default=0.01)  # fraction of balance per trade (1% default)
    auto_trade_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    paper_trade_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mt5_path: Mapped[str] = mapped_column(String(500), default="")
    account_type: Mapped[str] = mapped_column(String(20), default="USD")  # USD | USC

    trades: Mapped[list["Trade"]] = relationship("Trade", back_populates="account")
    journal_entries: Mapped[list["AIJournal"]] = relationship("AIJournal", back_populates="account")
    strategy_bindings: Mapped[list["AccountStrategy"]] = relationship(
        "AccountStrategy", back_populates="account", cascade="all, delete-orphan"
    )


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    ticket: Mapped[int] = mapped_column(Integer, index=True)  # MT5 order ticket
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    direction: Mapped[str] = mapped_column(String(4))  # BUY | SELL (underlying direction)
    volume: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="ai")  # ai | manual
    is_paper_trade: Mapped[bool] = mapped_column(Boolean, default=False)
    maintenance_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    order_type:   Mapped[str] = mapped_column(String(6),  default="market")   # market | limit | stop
    order_status: Mapped[str] = mapped_column(String(9),  default="filled")   # pending | filled | cancelled | expired
    strategy_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("strategies.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        UniqueConstraint("account_id", "ticket", name="uq_trade_account_ticket"),
    )

    strategy: Mapped["Strategy | None"] = relationship("Strategy", back_populates="trades", foreign_keys="Trade.strategy_id")

    account: Mapped["Account"] = relationship("Account", back_populates="trades")
    journal: Mapped["AIJournal | None"] = relationship(
        "AIJournal", back_populates="trade", uselist=False
    )


class AIJournal(Base):
    __tablename__ = "ai_journal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    trade_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("trades.id"), unique=True, nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10))
    signal: Mapped[str] = mapped_column(String(15))       # BUY | SELL | BUY_LIMIT | SELL_LIMIT | HOLD
    confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text)
    indicators_snapshot: Mapped[str] = mapped_column(Text)  # JSON string
    llm_provider: Mapped[str] = mapped_column(String(50))
    model_name: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    strategy_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("strategies.id", ondelete="SET NULL"), nullable=True)
    strategy: Mapped["Strategy | None"] = relationship("Strategy", back_populates="journal_entries_strategy", foreign_keys="AIJournal.strategy_id")

    account: Mapped["Account"] = relationship("Account", back_populates="journal_entries")
    trade: Mapped["Trade | None"] = relationship("Trade", back_populates="journal")


class KillSwitchLog(Base):
    __tablename__ = "kill_switch_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(20))        # activated | deactivated
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(20))  # system | user
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    strategy_type: Mapped[str] = mapped_column(String(20), default="config")   # config|prompt|code
    execution_mode: Mapped[str] = mapped_column(String(30), default="llm_only")
    # llm_only|rule_then_llm|rule_only|hybrid_validator|multi_agent
    primary_tf: Mapped[str] = mapped_column(String(10), default="M15")
    context_tfs: Mapped[str] = mapped_column(Text, default="[]")   # JSON list of TF strings
    trigger_type: Mapped[str] = mapped_column(String(20), default="candle_close")  # interval|candle_close
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    symbols: Mapped[str] = mapped_column(Text, default="[]")           # JSON list
    timeframe: Mapped[str] = mapped_column(String(10), default="M15")
    lot_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    sl_pips: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp_pips: Mapped[float | None] = mapped_column(Float, nullable=True)
    news_filter: Mapped[bool] = mapped_column(Boolean, default=True)
    custom_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    module_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    class_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    maintenance_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    account_bindings: Mapped[list["AccountStrategy"]] = relationship(
        "AccountStrategy", back_populates="strategy", cascade="all, delete-orphan"
    )
    trades: Mapped[list["Trade"]] = relationship("Trade", back_populates="strategy")
    journal_entries_strategy: Mapped[list["AIJournal"]] = relationship("AIJournal", back_populates="strategy")


@event.listens_for(Strategy, "init")
def _strategy_init_defaults(_target: Strategy, _args: tuple, kwargs: dict) -> None:
    """Apply Python-level defaults for Strategy attributes not passed to __init__."""
    kwargs.setdefault("strategy_type", "config")
    kwargs.setdefault("execution_mode", "llm_only")
    kwargs.setdefault("primary_tf", "M15")
    kwargs.setdefault("context_tfs", "[]")
    kwargs.setdefault("trigger_type", "candle_close")
    kwargs.setdefault("symbols", "[]")
    kwargs.setdefault("timeframe", "M15")
    kwargs.setdefault("news_filter", True)
    kwargs.setdefault("is_active", True)
    kwargs.setdefault("maintenance_enabled", True)
    kwargs.setdefault("created_at", datetime.now(UTC))


class AccountStrategy(Base):
    __tablename__ = "account_strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (UniqueConstraint("account_id", "strategy_id", name="uq_account_strategy"),)

    account: Mapped["Account"] = relationship("Account", back_populates="strategy_bindings")
    strategy: Mapped["Strategy"] = relationship("Strategy", back_populates="account_bindings")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10))
    task_type: Mapped[str] = mapped_column(String(20), default="signal")
    # "signal" | "maintenance"
    status: Mapped[str] = mapped_column(String(20), default="running")
    # running | completed | hold | skipped | failed
    final_action: Mapped[str | None] = mapped_column(String(15), nullable=True)
    total_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    journal_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("ai_journal.id"), nullable=True
    )
    trade_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("trades.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

    steps: Mapped[list["PipelineStep"]] = relationship(
        "PipelineStep", back_populates="run", cascade="all, delete-orphan",
        order_by="PipelineStep.seq",
    )


class PipelineStep(Base):
    __tablename__ = "pipeline_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    step_name: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(10))  # ok | skip | error
    input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    run: Mapped["PipelineRun"] = relationship("PipelineRun", back_populates="steps")


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_step_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("pipeline_steps.id", ondelete="SET NULL"), nullable=True, index=True
    )
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 8), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class LLMProviderConfig(Base):
    __tablename__ = "llm_provider_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    # 'openai' | 'gemini' | 'anthropic'
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    key_hint: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class TaskLLMAssignment(Base):
    __tablename__ = "task_llm_assignments"

    task: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 'market_analysis' | 'vision' | 'execution_decision'
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(Integer, ForeignKey("strategies.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10))
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    initial_balance: Mapped[float] = mapped_column(Float, default=10000.0)
    spread_pips: Mapped[float] = mapped_column(Float, default=1.5)
    execution_mode: Mapped[str] = mapped_column(String(20), default="close_price")
    primary_tf: Mapped[str] = mapped_column(String(10), default="M15")
    context_tfs: Mapped[str] = mapped_column(Text, default="[]")   # JSON list
    max_llm_calls: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    expectancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    recovery_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    sortino_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_win: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_consec_wins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_consec_losses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

    trades: Mapped[list["BacktestTrade"]] = relationship(
        "BacktestTrade", back_populates="run", cascade="all, delete-orphan"
    )
    strategy: Mapped["Strategy"] = relationship("Strategy")


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("backtest_runs.id", ondelete="CASCADE"), index=True
    )
    symbol: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(4))
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    equity_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    pattern_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pattern_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string

    run: Mapped["BacktestRun"] = relationship("BacktestRun", back_populates="trades")


class HMMModelRegistry(Base):
    __tablename__ = "hmm_model_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    candle_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_states: Mapped[int] = mapped_column(Integer, default=4)
    model_path: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", name="uq_hmm_symbol_timeframe"),
    )
