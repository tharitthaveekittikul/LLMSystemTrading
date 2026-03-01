from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, event
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
    direction: Mapped[str] = mapped_column(String(4))  # BUY | SELL
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
    strategy_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("strategies.id"), nullable=True)

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
    signal: Mapped[str] = mapped_column(String(10))       # BUY | SELL | HOLD
    confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text)
    indicators_snapshot: Mapped[str] = mapped_column(Text)  # JSON string
    llm_provider: Mapped[str] = mapped_column(String(50))
    model_name: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    strategy_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("strategies.id"), nullable=True)
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
    kwargs.setdefault("trigger_type", "candle_close")
    kwargs.setdefault("symbols", "[]")
    kwargs.setdefault("timeframe", "M15")
    kwargs.setdefault("news_filter", True)
    kwargs.setdefault("is_active", True)
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
