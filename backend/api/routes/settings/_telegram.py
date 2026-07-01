"""Telegram alerting configuration: view, save, enable/disable, test."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.settings._llm_providers import TestProviderResponse, _mask_key
from core.config import settings
from core.security import decrypt, encrypt
from db.models import TelegramSettings as TelegramSettingsModel
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class TelegramSettingsResponse(BaseModel):
    is_configured: bool
    is_enabled: bool
    chat_id: str
    token_hint: str | None


class TelegramSettingsUpdate(BaseModel):
    bot_token: str
    chat_id: str


class TelegramPatch(BaseModel):
    is_enabled: bool | None = None


def _telegram_row_to_response(row: TelegramSettingsModel) -> TelegramSettingsResponse:
    return TelegramSettingsResponse(
        is_configured=bool(row.bot_token_encrypted),
        is_enabled=row.is_enabled,
        chat_id=row.chat_id,
        token_hint=row.bot_token_hint,
    )


async def _get_or_create_telegram_row(db: AsyncSession) -> TelegramSettingsModel:
    row = (await db.execute(
        select(TelegramSettingsModel).where(TelegramSettingsModel.id == 1)
    )).scalar_one_or_none()
    if not row:
        row = TelegramSettingsModel(id=1)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


@router.get("/telegram", response_model=TelegramSettingsResponse)
async def get_telegram_settings(db: AsyncSession = Depends(get_db)) -> TelegramSettingsResponse:
    """Return Telegram alerting status. Never returns the raw bot token."""
    row = await _get_or_create_telegram_row(db)
    return _telegram_row_to_response(row)


@router.put("/telegram", response_model=TelegramSettingsResponse)
async def save_telegram_settings(
    body: TelegramSettingsUpdate,
    db: AsyncSession = Depends(get_db),
) -> TelegramSettingsResponse:
    """Save Telegram bot token (encrypted) and chat ID, then activate in-memory."""
    if not body.bot_token.strip():
        raise HTTPException(status_code=422, detail="bot_token must not be empty")
    if not body.chat_id.strip():
        raise HTTPException(status_code=422, detail="chat_id must not be empty")

    raw_token = body.bot_token.strip()
    row = await _get_or_create_telegram_row(db)
    row.bot_token_encrypted = encrypt(raw_token)
    row.bot_token_hint = _mask_key(raw_token)
    row.chat_id = body.chat_id.strip()
    row.is_enabled = True

    await db.commit()
    await db.refresh(row)

    # Apply to in-memory config so alerting works immediately
    settings.telegram_bot_token = raw_token
    settings.telegram_chat_id = row.chat_id
    logger.info("Telegram settings saved | chat_id=%s", row.chat_id)
    return _telegram_row_to_response(row)


@router.patch("/telegram", response_model=TelegramSettingsResponse)
async def patch_telegram_settings(
    body: TelegramPatch,
    db: AsyncSession = Depends(get_db),
) -> TelegramSettingsResponse:
    """Toggle Telegram alerting on/off without clearing credentials."""
    row = await _get_or_create_telegram_row(db)
    if body.is_enabled is not None:
        row.is_enabled = body.is_enabled
        # Reflect toggle in in-memory settings
        if body.is_enabled and row.bot_token_encrypted:
            settings.telegram_bot_token = decrypt(row.bot_token_encrypted)
            settings.telegram_chat_id = row.chat_id
        elif not body.is_enabled:
            settings.telegram_bot_token = ""
            settings.telegram_chat_id = ""

    await db.commit()
    await db.refresh(row)
    logger.info("Telegram settings patched | is_enabled=%s", row.is_enabled)
    return _telegram_row_to_response(row)


@router.post("/telegram/test", response_model=TestProviderResponse)
async def test_telegram(
    body: TelegramSettingsUpdate,
    db: AsyncSession = Depends(get_db),
) -> TestProviderResponse:
    """Send a test Telegram message using the provided (or stored) credentials."""
    import httpx as _httpx  # noqa: PLC0415

    bot_token = body.bot_token.strip()
    chat_id = body.chat_id.strip()

    # Fall back to stored credentials if inputs are blank
    if not bot_token or not chat_id:
        row = await _get_or_create_telegram_row(db)
        if not row.bot_token_encrypted or not row.chat_id:
            return TestProviderResponse(success=False, message="No Telegram credentials configured")
        bot_token = decrypt(row.bot_token_encrypted)
        chat_id = row.chat_id

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": "*Test alert* from LLM Trading System ✅", "parse_mode": "Markdown"}
    try:
        async with _httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        return TestProviderResponse(success=True, message="Test message sent successfully")
    except _httpx.HTTPStatusError as exc:
        return TestProviderResponse(success=False, message=f"Telegram API error: {exc.response.text}")
    except Exception as exc:
        return TestProviderResponse(success=False, message=str(exc))
