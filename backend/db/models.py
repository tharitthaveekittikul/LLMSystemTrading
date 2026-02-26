from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Trading config per account
    allowed_symbols: Mapped[str] = mapped_column(Text, default="")  # JSON list
    max_lot_size: Mapped[float] = mapped_column(Float, default=0.1)

    trades: Mapped[list["Trade"]] = relationship("Trade", back_populates="account")


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
    opened_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="ai")  # ai | manual

    account: Mapped["Account"] = relationship("Account", back_populates="trades")
    journal: Mapped["AIJournal | None"] = relationship(
        "AIJournal", back_populates="trade", uselist=False
    )


class AIJournal(Base):
    __tablename__ = "ai_journal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(Integer, ForeignKey("trades.id"), unique=True)
    signal: Mapped[str] = mapped_column(String(10))       # BUY | SELL | HOLD
    confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text)
    indicators_snapshot: Mapped[str] = mapped_column(Text)  # JSON string
    llm_provider: Mapped[str] = mapped_column(String(50))
    model_name: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    trade: Mapped["Trade"] = relationship("Trade", back_populates="journal")


class KillSwitchLog(Base):
    __tablename__ = "kill_switch_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(20))        # activated | deactivated
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(20))  # system | user
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
