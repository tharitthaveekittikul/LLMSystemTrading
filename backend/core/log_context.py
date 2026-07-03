"""Correlation IDs for structured logs — request_id/run_id/account_id/symbol.

Bind one or more fields once at an entry point (an HTTP request, a pipeline
run, a poll tick) and every log record emitted while that context is active
carries them automatically via CorrelationFilter — including third-party
loggers (mt5.bridge, httpcore) that never mention them in their own message
text. This is what lets "which poll tick caused these reconnects" become a
grep-able question instead of eyeballing timestamps.

Usage:
    tokens = bind(run_id=run.id, account_id=account_id, symbol=symbol)
    try:
        ...
    finally:
        clear(tokens)
"""
import contextvars
import logging

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_run_id: contextvars.ContextVar[int | None] = contextvars.ContextVar("run_id", default=None)
_account_id: contextvars.ContextVar[int | None] = contextvars.ContextVar("account_id", default=None)
_symbol: contextvars.ContextVar[str | None] = contextvars.ContextVar("symbol", default=None)

_VARS: dict[str, contextvars.ContextVar] = {
    "request_id": _request_id,
    "run_id": _run_id,
    "account_id": _account_id,
    "symbol": _symbol,
}


class CorrelationFilter(logging.Filter):
    """Attaches the current contextvar values to every log record that passes through."""

    def filter(self, record: logging.LogRecord) -> bool:
        for name, var in _VARS.items():
            value = var.get()
            if value is not None:
                setattr(record, name, value)
        return True


def bind(**kwargs: str | int | None) -> dict[str, contextvars.Token]:
    """Set one or more correlation fields. Returns tokens to pass to clear()."""
    tokens: dict[str, contextvars.Token] = {}
    for key, value in kwargs.items():
        if key not in _VARS:
            raise KeyError(f"Unknown correlation field: {key!r} (expected one of {list(_VARS)})")
        tokens[key] = _VARS[key].set(value)
    return tokens


def clear(tokens: dict[str, contextvars.Token]) -> None:
    """Reset fields bound by bind() back to their prior value."""
    for key, token in tokens.items():
        _VARS[key].reset(token)
