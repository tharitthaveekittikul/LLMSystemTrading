"""LLM provider configuration and task assignment settings."""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import decrypt, encrypt
from db.models import LLMProviderConfig, TaskLLMAssignment, GlobalSettings as GlobalSettingsModel
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

_VALID_PROVIDERS = {"openai", "gemini", "anthropic", "openrouter"}
_VALID_TASKS = {
    "market_analysis", "vision", "execution_decision",
    "maintenance_technical", "maintenance_sentiment", "maintenance_decision",
}


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ProviderStatus(BaseModel):
    provider: str
    is_configured: bool
    is_active: bool
    key_hint: str | None  # e.g. "sk-...abcd" — never the real key


class SaveProviderRequest(BaseModel):
    api_key: str


class TestProviderResponse(BaseModel):
    success: bool
    message: str


class TaskAssignment(BaseModel):
    task: str
    provider: str
    model_name: str


class SaveAssignmentsRequest(BaseModel):
    assignments: list[TaskAssignment]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mask_key(raw_key: str) -> str:
    """Return a safe display hint like 'sk-...abcd' without exposing the key."""
    if len(raw_key) < 16:
        return "****"
    return f"{raw_key[:6]}...{raw_key[-4:]}"


async def _fetch_provider_models(provider: str, api_key: str) -> list[str]:
    """Fetch available model IDs from the provider's API."""
    try:
        if provider == "openai":
            import openai  # noqa: PLC0415
            client = openai.AsyncOpenAI(api_key=api_key)
            response = await client.models.list()
            return sorted(
                m.id for m in response.data
                if m.id.startswith(("gpt-", "o1", "o3", "o4"))
            )

        if provider == "gemini":
            from google import genai as google_genai  # noqa: PLC0415
            gc = google_genai.Client(api_key=api_key)
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(None, lambda: list(gc.models.list()))
            return sorted(
                m.name.removeprefix("models/") for m in raw
                if "gemini" in m.name.lower()
            )

        if provider == "anthropic":
            import anthropic  # noqa: PLC0415
            client = anthropic.AsyncAnthropic(api_key=api_key)
            response = await client.models.list()
            return [m.id for m in response.data]

        if provider == "openrouter":
            import openai  # noqa: PLC0415
            client = openai.AsyncOpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
            )
            response = await client.models.list()
            return sorted(m.id for m in response.data)

    except Exception as exc:
        logger.warning("Failed to fetch models for %s: %s", provider, exc)
    return []


async def _test_provider_connection(provider: str, api_key: str) -> tuple[bool, str]:
    """Try a real API call with the given key. Returns (success, message)."""
    try:
        if provider == "openai":
            import openai  # noqa: PLC0415
            client = openai.AsyncOpenAI(api_key=api_key)
            await client.models.list()
            return True, "Connected to OpenAI"

        if provider == "gemini":
            from google import genai as google_genai  # noqa: PLC0415
            client = google_genai.Client(api_key=api_key)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: list(client.models.list()))
            return True, "Connected to Gemini"

        if provider == "anthropic":
            import anthropic  # noqa: PLC0415
            client = anthropic.AsyncAnthropic(api_key=api_key)
            await client.models.list()
            return True, "Connected to Anthropic"

        if provider == "openrouter":
            import openai  # noqa: PLC0415
            client = openai.AsyncOpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
            )
            await client.models.list()
            return True, "Connected to OpenRouter"

        return False, f"Unknown provider: {provider}"

    except Exception as exc:
        return False, str(exc)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/llm/providers", response_model=list[ProviderStatus])
async def list_providers(db: AsyncSession = Depends(get_db)) -> list[ProviderStatus]:
    """Return status for all three providers. Never returns raw API keys."""
    rows = (await db.execute(select(LLMProviderConfig))).scalars().all()
    configs = {row.provider: row for row in rows}

    result: list[ProviderStatus] = []
    for provider in ["openai", "gemini", "anthropic", "openrouter"]:
        row = configs.get(provider)
        if row:
            result.append(ProviderStatus(
                provider=provider,
                is_configured=True,
                is_active=row.is_active,
                key_hint=row.key_hint or "****",
            ))
        else:
            result.append(ProviderStatus(
                provider=provider,
                is_configured=False,
                is_active=False,
                key_hint=None,
            ))
    return result


@router.put("/llm/providers/{provider}", response_model=ProviderStatus)
async def save_provider(
    provider: str,
    body: SaveProviderRequest,
    db: AsyncSession = Depends(get_db),
) -> ProviderStatus:
    """Save or update an API key for a provider (encrypted at rest)."""
    if provider not in _VALID_PROVIDERS:
        raise HTTPException(status_code=422, detail=f"Unknown provider: {provider!r}")
    if not body.api_key.strip():
        raise HTTPException(status_code=422, detail="api_key must not be empty")

    raw_key = body.api_key.strip()
    encrypted = encrypt(raw_key)
    hint = _mask_key(raw_key)
    result = (await db.execute(
        select(LLMProviderConfig).where(LLMProviderConfig.provider == provider)
    )).scalar_one_or_none()

    if result:
        result.encrypted_api_key = encrypted
        result.key_hint = hint
        result.is_active = True
    else:
        result = LLMProviderConfig(
            provider=provider,
            encrypted_api_key=encrypted,
            key_hint=hint,
            is_active=True,
        )
        db.add(result)

    await db.commit()
    await db.refresh(result)
    logger.info("LLM provider key saved | provider=%s", provider)
    return ProviderStatus(
        provider=provider,
        is_configured=True,
        is_active=True,
        key_hint=_mask_key(body.api_key.strip()),
    )


@router.post("/llm/providers/{provider}/test", response_model=TestProviderResponse)
async def test_provider(
    provider: str,
    body: SaveProviderRequest,
) -> TestProviderResponse:
    """Test an API key by making a real (cheap) connection check."""
    if provider not in _VALID_PROVIDERS:
        raise HTTPException(status_code=422, detail=f"Unknown provider: {provider!r}")
    if not body.api_key.strip():
        raise HTTPException(status_code=422, detail="api_key must not be empty")

    success, message = await _test_provider_connection(provider, body.api_key.strip())
    return TestProviderResponse(success=success, message=message)


@router.get("/llm/providers/{provider}/models", response_model=list[str])
async def list_provider_models(
    provider: str,
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    """Return available model IDs for a configured provider using its stored API key."""
    if provider not in _VALID_PROVIDERS:
        raise HTTPException(status_code=422, detail=f"Unknown provider: {provider!r}")

    row = (await db.execute(
        select(LLMProviderConfig).where(
            LLMProviderConfig.provider == provider,
            LLMProviderConfig.is_active.is_(True),
        )
    )).scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail=f"No active API key configured for {provider!r}")

    api_key = decrypt(row.encrypted_api_key)
    return await _fetch_provider_models(provider, api_key)


@router.get("/llm/assignments", response_model=list[TaskAssignment])
async def get_assignments(db: AsyncSession = Depends(get_db)) -> list[TaskAssignment]:
    """Return current task -> provider assignments."""
    rows = (await db.execute(select(TaskLLMAssignment))).scalars().all()
    assigned = {row.task: row for row in rows}

    result: list[TaskAssignment] = []
    for task in [
        "market_analysis", "vision", "execution_decision",
        "maintenance_technical", "maintenance_sentiment", "maintenance_decision",
    ]:
        row = assigned.get(task)
        if row:
            result.append(TaskAssignment(task=task, provider=row.provider, model_name=row.model_name))
        else:
            result.append(TaskAssignment(task=task, provider="", model_name=""))
    return result


@router.put("/llm/assignments", response_model=list[TaskAssignment])
async def save_assignments(
    body: SaveAssignmentsRequest,
    db: AsyncSession = Depends(get_db),
) -> list[TaskAssignment]:
    """Save all task -> provider assignments at once."""
    for item in body.assignments:
        if item.task not in _VALID_TASKS:
            raise HTTPException(status_code=422, detail=f"Unknown task: {item.task!r}")
        if item.provider and item.provider not in _VALID_PROVIDERS:
            raise HTTPException(status_code=422, detail=f"Unknown provider: {item.provider!r}")

    for item in body.assignments:
        if not item.provider:
            row = (await db.execute(
                select(TaskLLMAssignment).where(TaskLLMAssignment.task == item.task)
            )).scalar_one_or_none()
            if row:
                await db.delete(row)
            continue

        row = (await db.execute(
            select(TaskLLMAssignment).where(TaskLLMAssignment.task == item.task)
        )).scalar_one_or_none()
        if row:
            row.provider = item.provider
            row.model_name = item.model_name
        else:
            row = TaskLLMAssignment(task=item.task, provider=item.provider, model_name=item.model_name)
            db.add(row)

    await db.commit()
    logger.info("Task LLM assignments saved | count=%d", len(body.assignments))
    return await get_assignments(db)


# ── Global Settings ────────────────────────────────────────────────────────────

class GlobalSettings(BaseModel):
    maintenance_interval_minutes: int
    maintenance_task_enabled: bool
    llm_confidence_threshold: float
    news_enabled: bool


class GlobalSettingsPatch(BaseModel):
    maintenance_interval_minutes: int | None = None
    maintenance_task_enabled: bool | None = None
    llm_confidence_threshold: float | None = None
    news_enabled: bool | None = None


@router.get("/global", response_model=GlobalSettings)
async def get_global_settings(db: AsyncSession = Depends(get_db)) -> GlobalSettings:
    """Return current global settings, preferring DB-persisted values."""
    row = (await db.execute(
        select(GlobalSettingsModel).where(GlobalSettingsModel.id == 1)
    )).scalar_one_or_none()
    if row:
        return GlobalSettings(
            maintenance_interval_minutes=row.maintenance_interval_minutes,
            maintenance_task_enabled=row.maintenance_task_enabled,
            llm_confidence_threshold=row.llm_confidence_threshold,
            news_enabled=row.news_enabled,
        )
    # Fallback to in-memory config (first boot before migration runs)
    return GlobalSettings(
        maintenance_interval_minutes=settings.maintenance_interval_minutes,
        maintenance_task_enabled=settings.maintenance_task_enabled,
        llm_confidence_threshold=settings.llm_confidence_threshold,
        news_enabled=settings.news_enabled,
    )


@router.patch("/global", response_model=GlobalSettings)
async def patch_global_settings(
    body: GlobalSettingsPatch,
    db: AsyncSession = Depends(get_db),
) -> GlobalSettings:
    """Update global settings — persisted to DB and applied in-memory immediately."""
    row = (await db.execute(
        select(GlobalSettingsModel).where(GlobalSettingsModel.id == 1)
    )).scalar_one_or_none()
    if not row:
        row = GlobalSettingsModel(id=1)
        db.add(row)

    if body.maintenance_interval_minutes is not None:
        if body.maintenance_interval_minutes < 1:
            raise HTTPException(status_code=422, detail="maintenance_interval_minutes must be >= 1")
        row.maintenance_interval_minutes = body.maintenance_interval_minutes
        settings.maintenance_interval_minutes = body.maintenance_interval_minutes
        from services.scheduler import reschedule_maintenance_job
        reschedule_maintenance_job(body.maintenance_interval_minutes)
    if body.maintenance_task_enabled is not None:
        row.maintenance_task_enabled = body.maintenance_task_enabled
        settings.maintenance_task_enabled = body.maintenance_task_enabled
    if body.llm_confidence_threshold is not None:
        if not 0.0 <= body.llm_confidence_threshold <= 1.0:
            raise HTTPException(status_code=422, detail="llm_confidence_threshold must be 0.0-1.0")
        row.llm_confidence_threshold = body.llm_confidence_threshold
        settings.llm_confidence_threshold = body.llm_confidence_threshold
    if body.news_enabled is not None:
        row.news_enabled = body.news_enabled
        settings.news_enabled = body.news_enabled

    await db.commit()
    await db.refresh(row)
    logger.info("Global settings persisted to DB | %s", body.model_dump(exclude_none=True))
    return await get_global_settings(db)


# ── Risk Settings ──────────────────────────────────────────────────────────

class RiskSettingsResponse(BaseModel):
    drawdown_check_enabled: bool
    max_drawdown_pct: float
    position_limit_enabled: bool
    max_open_positions: int
    rate_limit_enabled: bool
    rate_limit_max_trades: int
    rate_limit_window_hours: float
    hedging_allowed: bool


class RiskSettingsPatch(BaseModel):
    drawdown_check_enabled: bool | None = None
    max_drawdown_pct: float | None = None
    position_limit_enabled: bool | None = None
    max_open_positions: int | None = None
    rate_limit_enabled: bool | None = None
    rate_limit_max_trades: int | None = None
    rate_limit_window_hours: float | None = None
    hedging_allowed: bool | None = None


def _risk_row_to_response(row) -> RiskSettingsResponse:
    return RiskSettingsResponse(
        drawdown_check_enabled=row.drawdown_check_enabled,
        max_drawdown_pct=row.max_drawdown_pct,
        position_limit_enabled=row.position_limit_enabled,
        max_open_positions=row.max_open_positions,
        rate_limit_enabled=row.rate_limit_enabled,
        rate_limit_max_trades=row.rate_limit_max_trades,
        rate_limit_window_hours=row.rate_limit_window_hours,
        hedging_allowed=row.hedging_allowed,
    )


@router.get("/risk", response_model=RiskSettingsResponse)
async def get_risk_settings(db: AsyncSession = Depends(get_db)) -> RiskSettingsResponse:
    """Return current risk rule toggles and thresholds."""
    from db.models import RiskSettings
    row = (await db.execute(select(RiskSettings).where(RiskSettings.id == 1))).scalar_one_or_none()
    if not row:
        # Should never happen after migration, but handle gracefully
        from db.models import RiskSettings as RS
        row = RS(id=1)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return _risk_row_to_response(row)


@router.patch("/risk", response_model=RiskSettingsResponse)
async def patch_risk_settings(
    body: RiskSettingsPatch,
    db: AsyncSession = Depends(get_db),
) -> RiskSettingsResponse:
    """Update risk rule configuration (persisted to DB)."""
    from db.models import RiskSettings
    row = (await db.execute(select(RiskSettings).where(RiskSettings.id == 1))).scalar_one_or_none()
    if not row:
        row = RiskSettings(id=1)
        db.add(row)

    if body.drawdown_check_enabled is not None:
        row.drawdown_check_enabled = body.drawdown_check_enabled
    if body.max_drawdown_pct is not None:
        if not 0 < body.max_drawdown_pct <= 100:
            raise HTTPException(status_code=422, detail="max_drawdown_pct must be > 0 and <= 100")
        row.max_drawdown_pct = body.max_drawdown_pct
    if body.position_limit_enabled is not None:
        row.position_limit_enabled = body.position_limit_enabled
    if body.max_open_positions is not None:
        if body.max_open_positions < 1:
            raise HTTPException(status_code=422, detail="max_open_positions must be >= 1")
        row.max_open_positions = body.max_open_positions
    if body.rate_limit_enabled is not None:
        row.rate_limit_enabled = body.rate_limit_enabled
    if body.rate_limit_max_trades is not None:
        if body.rate_limit_max_trades < 1:
            raise HTTPException(status_code=422, detail="rate_limit_max_trades must be >= 1")
        row.rate_limit_max_trades = body.rate_limit_max_trades
    if body.rate_limit_window_hours is not None:
        if body.rate_limit_window_hours <= 0:
            raise HTTPException(status_code=422, detail="rate_limit_window_hours must be > 0")
        row.rate_limit_window_hours = body.rate_limit_window_hours
    if body.hedging_allowed is not None:
        row.hedging_allowed = body.hedging_allowed

    await db.commit()
    await db.refresh(row)
    logger.info("Risk settings updated | %s", body.model_dump(exclude_none=True))
    return _risk_row_to_response(row)
