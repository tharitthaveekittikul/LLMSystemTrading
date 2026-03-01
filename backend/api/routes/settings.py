"""LLM provider configuration and task assignment settings."""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import decrypt, encrypt
from db.models import LLMProviderConfig, TaskLLMAssignment
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

_VALID_PROVIDERS = {"openai", "gemini", "anthropic"}
_VALID_TASKS = {"market_analysis", "vision", "execution_decision"}


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
    for provider in ["openai", "gemini", "anthropic"]:
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
    for task in ["market_analysis", "vision", "execution_decision"]:
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
