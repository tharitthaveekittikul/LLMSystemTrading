# Settings Page Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `/settings` page with theme switching, display preferences, LLM provider management, and per-task LLM assignment — all wired to a real backend.

**Architecture:** Frontend theme/display prefs live in `localStorage` via `next-themes` + Zustand persist. LLM provider API keys are stored encrypted (Fernet) in two new PostgreSQL tables (`llm_provider_configs`, `task_llm_assignments`). The orchestrator accepts a per-task LLM override loaded from DB at pipeline-run time, falling back to env-var config when no DB assignment exists.

**Tech Stack:** `next-themes` (already installed), Zustand persist middleware, FastAPI, SQLAlchemy async, Fernet encryption (already in `core/security.py`), LangChain (`ChatOpenAI` / `ChatGoogleGenerativeAI` / `ChatAnthropic`)

---

## Task 1: Add SQLAlchemy models for LLM settings

**Files:**
- Modify: `backend/db/models.py`

**Step 1: Add the two new model classes** at the bottom of `backend/db/models.py` (after `PipelineStep`):

```python
class LLMProviderConfig(Base):
    __tablename__ = "llm_provider_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    # 'openai' | 'gemini' | 'anthropic'
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
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
```

**Step 2: Verify the import list** at the top of `backend/db/models.py` already has `Text` and `Boolean` in the `sqlalchemy` import — it does, so no change needed.

**Step 3: Run backend to confirm no import errors**

```bash
cd backend && uv run python -c "from db.models import LLMProviderConfig, TaskLLMAssignment; print('OK')"
```

Expected: `OK`

**Step 4: Commit**

```bash
git add backend/db/models.py
git commit -m "feat(db): add LLMProviderConfig and TaskLLMAssignment models"
```

---

## Task 2: Alembic migration for LLM settings tables

**Files:**
- Create: `backend/alembic/versions/<hash>_add_llm_settings_tables.py` (auto-generated)

**Step 1: Generate the migration**

```bash
cd backend && uv run alembic revision --autogenerate -m "add_llm_settings_tables"
```

Expected: A new file appears in `backend/alembic/versions/` starting with a hash.

**Step 2: Review the generated migration** — open the new file and confirm `upgrade()` creates both tables. It should look like:

```python
def upgrade() -> None:
    op.create_table(
        "llm_provider_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider"),
    )
    op.create_table(
        "task_llm_assignments",
        sa.Column("task", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("task"),
    )


def downgrade() -> None:
    op.drop_table("task_llm_assignments")
    op.drop_table("llm_provider_configs")
```

**Step 3: Run the migration**

```bash
cd backend && uv run alembic upgrade head
```

Expected: `Running upgrade ... -> <hash>, add_llm_settings_tables`

**Step 4: Commit**

```bash
git add backend/alembic/versions/
git commit -m "feat(db): migration — add llm_provider_configs and task_llm_assignments tables"
```

---

## Task 3: Backend — LLM settings API routes

**Files:**
- Create: `backend/api/routes/settings.py`

**Step 1: Create `backend/api/routes/settings.py`** with this full content:

```python
"""LLM provider configuration and task assignment settings."""
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
    if len(raw_key) <= 8:
        return "****"
    return f"{raw_key[:4]}...{raw_key[-4:]}"


async def _test_provider_connection(provider: str, api_key: str) -> tuple[bool, str]:
    """Try a real API call with the given key. Returns (success, message)."""
    try:
        if provider == "openai":
            import openai  # noqa: PLC0415
            client = openai.AsyncOpenAI(api_key=api_key)
            await client.models.list()
            return True, "Connected to OpenAI"

        if provider == "gemini":
            from google import generativeai as genai  # noqa: PLC0415
            genai.configure(api_key=api_key)
            list(genai.list_models())
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
            raw_key = decrypt(row.encrypted_api_key)
            result.append(ProviderStatus(
                provider=provider,
                is_configured=True,
                is_active=row.is_active,
                key_hint=_mask_key(raw_key),
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

    encrypted = encrypt(body.api_key.strip())
    row = await db.get(LLMProviderConfig, None)  # query by unique provider
    result = (await db.execute(
        select(LLMProviderConfig).where(LLMProviderConfig.provider == provider)
    )).scalar_one_or_none()

    if result:
        result.encrypted_api_key = encrypted
        result.is_active = True
    else:
        result = LLMProviderConfig(
            provider=provider,
            encrypted_api_key=encrypted,
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
    db: AsyncSession = Depends(get_db),
) -> TestProviderResponse:
    """Test an API key by making a real (cheap) connection check."""
    if provider not in _VALID_PROVIDERS:
        raise HTTPException(status_code=422, detail=f"Unknown provider: {provider!r}")
    if not body.api_key.strip():
        raise HTTPException(status_code=422, detail="api_key must not be empty")

    success, message = await _test_provider_connection(provider, body.api_key.strip())
    return TestProviderResponse(success=success, message=message)


@router.get("/llm/assignments", response_model=list[TaskAssignment])
async def get_assignments(db: AsyncSession = Depends(get_db)) -> list[TaskAssignment]:
    """Return current task → provider assignments."""
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
    """Save all task → provider assignments at once."""
    for item in body.assignments:
        if item.task not in _VALID_TASKS:
            raise HTTPException(status_code=422, detail=f"Unknown task: {item.task!r}")
        if item.provider and item.provider not in _VALID_PROVIDERS:
            raise HTTPException(status_code=422, detail=f"Unknown provider: {item.provider!r}")

    for item in body.assignments:
        if not item.provider:
            # Clear the assignment
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
```

**Step 2: Run a quick syntax check**

```bash
cd backend && uv run python -c "from api.routes.settings import router; print('OK')"
```

Expected: `OK`

**Step 3: Commit**

```bash
git add backend/api/routes/settings.py
git commit -m "feat(api): LLM settings routes — providers + task assignments"
```

---

## Task 4: Register the settings router in main.py

**Files:**
- Modify: `backend/main.py`

**Step 1: Add the import** (after the `pipeline_routes` import line):

```python
from api.routes import settings as settings_routes
```

**Step 2: Add the router** (after the `pipeline_routes` include line):

```python
app.include_router(settings_routes.router, prefix="/api/v1/settings", tags=["settings"])
```

**Step 3: Restart the server and check Swagger**

```bash
cd backend && uv run uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000/docs` — confirm a **settings** tag appears with 5 routes.

**Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat(api): register /api/v1/settings router"
```

---

## Task 5: Update orchestrator to accept per-task LLM overrides

**Files:**
- Modify: `backend/ai/orchestrator.py`

**Context:** Currently `_DEFAULT_CHAIN` is built at module import. We need `analyze_market()` to accept an optional `llm_override` so `ai_trading.py` can pass a task-specific LLM.

**Step 1: Modify `_build_llm()`** to accept optional override params (add after the existing `_build_llm` signature):

Replace the existing `_build_llm` function:

```python
def _build_llm(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> BaseChatModel:
    """Build a LangChain chat model.

    If provider/api_key/model are given, use them directly (DB-sourced task assignment).
    Otherwise fall back to env-var settings.
    """
    resolved_provider = provider or settings.llm_provider

    if resolved_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or "gpt-4o",
            api_key=api_key or settings.openai_api_key,
            temperature=0,
        )

    if resolved_provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model or settings.gemini_model,
            google_api_key=api_key or settings.gemini_api_key,
            temperature=0,
        )

    if resolved_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model or "claude-sonnet-4-6",
            api_key=api_key or settings.anthropic_api_key,
            temperature=0,
        )

    raise ValueError(f"Unknown llm_provider: {resolved_provider!r}")
```

**Step 2: Update `_DEFAULT_CHAIN`** — keep as-is (used when no override is passed).

**Step 3: Add `llm_override` parameter to `analyze_market()`**. In the function signature, add:

```python
async def analyze_market(
    symbol: str,
    timeframe: str,
    current_price: float,
    indicators: dict[str, Any],
    ohlcv: list[dict[str, Any]],
    chart_analysis: str | None = None,
    open_positions: list[dict[str, Any]] | None = None,
    recent_signals: list[dict[str, Any]] | None = None,
    news_context: str | None = None,
    trade_history_context: str | None = None,
    system_prompt_override: str | None = None,
    llm_override: BaseChatModel | None = None,   # ← ADD THIS
) -> LLMAnalysisResult:
```

**Step 4: Update the chain selection logic** inside `analyze_market()`. Replace the existing block:

```python
    if system_prompt_override:
        llm = _build_llm()
        prompt = ChatPromptTemplate.from_messages([("system", system_prompt_override), ("human", _HUMAN)])
        chain = prompt | llm | JsonOutputParser()
    else:
        chain = _DEFAULT_CHAIN
```

With:

```python
    active_llm = llm_override or _build_llm()
    if system_prompt_override:
        prompt = ChatPromptTemplate.from_messages([("system", system_prompt_override), ("human", _HUMAN)])
        chain = prompt | active_llm | JsonOutputParser()
    elif llm_override:
        chain = _PROMPT | active_llm | JsonOutputParser()
    else:
        chain = _DEFAULT_CHAIN
```

**Step 5: Verify syntax**

```bash
cd backend && uv run python -c "from ai.orchestrator import analyze_market; print('OK')"
```

Expected: `OK`

**Step 6: Commit**

```bash
git add backend/ai/orchestrator.py
git commit -m "feat(ai): orchestrator accepts per-task llm_override parameter"
```

---

## Task 6: Load task-specific LLM from DB in ai_trading.py

**Files:**
- Modify: `backend/services/ai_trading.py`

**Context:** Before calling `analyze_market()`, load the `market_analysis` task assignment from DB and create the appropriate LLM. Falls back to `None` (env-var default) when no assignment exists.

**Step 1: Add a helper function** at the top of `ai_trading.py` (after the imports):

```python
async def _get_task_llm(task: str, db: AsyncSession):
    """Load task-specific LLM from DB. Returns None to use env-var default."""
    from sqlalchemy import select as sa_select
    from db.models import LLMProviderConfig, TaskLLMAssignment
    from core.security import decrypt as _decrypt
    from ai.orchestrator import _build_llm

    assignment = (await db.execute(
        sa_select(TaskLLMAssignment).where(TaskLLMAssignment.task == task)
    )).scalar_one_or_none()

    if not assignment or not assignment.provider:
        return None

    provider_row = (await db.execute(
        sa_select(LLMProviderConfig).where(
            LLMProviderConfig.provider == assignment.provider,
            LLMProviderConfig.is_active == True,  # noqa: E712
        )
    )).scalar_one_or_none()

    if not provider_row:
        return None

    api_key = _decrypt(provider_row.encrypted_api_key)
    return _build_llm(
        provider=assignment.provider,
        api_key=api_key,
        model=assignment.model_name or None,
    )
```

**Step 2: Update the LLM call in `_run_pipeline()`**. Find the block in `ai_trading.py` that calls `analyze_market()` (around line 358) and update it to:

```python
            t0 = time.monotonic()
            market_analysis_llm = await _get_task_llm("market_analysis", db)
            llm_result: LLMAnalysisResult = await analyze_market(
                symbol=symbol,
                timeframe=tf_upper,
                current_price=current_price or 0,
                indicators=indicators,
                ohlcv=candles,
                open_positions=open_positions,
                recent_signals=recent_signals,
                news_context=news_context_str,
                trade_history_context=trade_history_context,
                system_prompt_override=strategy_overrides.custom_prompt if strategy_overrides else None,
                llm_override=market_analysis_llm,
            )
```

**Step 3: Update the `llm_provider` recorded in `journal` and tracer** to reflect the actual provider used. Find the `journal.llm_provider=` line and update to:

```python
            llm_provider="rule_based" if rule_based else (
                market_analysis_llm.__class__.__module__.split(".")[1]
                if market_analysis_llm else settings.llm_provider
            ),
```

Actually this is complex — simpler approach: store the provider string separately. Add before the journal creation:

```python
            effective_llm_provider = settings.llm_provider
            if market_analysis_llm:
                # Derive provider name from LangChain class module
                mod = market_analysis_llm.__class__.__module__
                if "openai" in mod:
                    effective_llm_provider = "openai"
                elif "google" in mod or "gemini" in mod:
                    effective_llm_provider = "gemini"
                elif "anthropic" in mod:
                    effective_llm_provider = "anthropic"
```

Then use `effective_llm_provider` where `settings.llm_provider` is referenced in the journal/tracer within the LLM branch.

**Step 4: Verify no import errors**

```bash
cd backend && uv run python -c "from services.ai_trading import AITradingService; print('OK')"
```

Expected: `OK`

**Step 5: Commit**

```bash
git add backend/services/ai_trading.py
git commit -m "feat(ai): load task-specific LLM from DB in pipeline, fall back to env default"
```

---

## Task 7: Wire up next-themes ThemeProvider in layout.tsx

**Files:**
- Modify: `frontend/src/app/layout.tsx`
- Create: `frontend/src/components/theme-provider.tsx`

**Context:** `next-themes` v0.4.6 is already installed. `<html>` already has `suppressHydrationWarning`. We need a client-side wrapper because `next-themes` requires `"use client"`.

**Step 1: Create `frontend/src/components/theme-provider.tsx`**:

```tsx
"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      {children}
    </NextThemesProvider>
  );
}
```

**Step 2: Update `frontend/src/app/layout.tsx`** — import and wrap children:

```tsx
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/app-sidebar";
import { Toaster } from "@/components/ui/sonner";
import { ThemeProvider } from "@/components/theme-provider";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "LLM Trading System",
  description: "AI-driven multi-account trading dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <ThemeProvider>
          <SidebarProvider>
            <AppSidebar />
            {children}
          </SidebarProvider>
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
```

**Step 3: Check if Tailwind CSS dark mode is configured** — open `frontend/tailwind.config.ts` or `frontend/src/app/globals.css`. If using Tailwind v4, the `darkMode: "class"` is configured in CSS. If using Tailwind v3, ensure `tailwind.config.ts` has `darkMode: "class"`.

If `globals.css` uses `@import "tailwindcss"` (v4), add to the CSS:

```css
@variant dark (&:where(.dark, .dark *));
```

Or for Tailwind v4 with `next-themes` class strategy, check that `dark:` utilities work — they should work out of the box with Tailwind v4.

**Step 4: Start the dev server and verify** no hydration errors in browser console:

```bash
cd frontend && npm run dev
```

Open `http://localhost:3000` — no red hydration errors in console.

**Step 5: Commit**

```bash
git add frontend/src/components/theme-provider.tsx frontend/src/app/layout.tsx
git commit -m "feat(theme): add ThemeProvider to root layout via next-themes"
```

---

## Task 8: Add ThemeToggle component to AppHeader

**Files:**
- Create: `frontend/src/components/theme-toggle.tsx`
- Modify: `frontend/src/components/app-header.tsx`

**Step 1: Create `frontend/src/components/theme-toggle.tsx`**:

```tsx
"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";

const CYCLE: Record<string, string> = {
  system: "light",
  light: "dark",
  dark: "system",
};

const ICON: Record<string, React.ReactNode> = {
  system: <Monitor className="h-4 w-4" />,
  light: <Sun className="h-4 w-4" />,
  dark: <Moon className="h-4 w-4" />,
};

const LABEL: Record<string, string> = {
  system: "System theme",
  light: "Light theme",
  dark: "Dark theme",
};

export function ThemeToggle() {
  const { theme = "system", setTheme } = useTheme();

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(CYCLE[theme] ?? "system")}
      title={LABEL[theme] ?? "Toggle theme"}
    >
      {ICON[theme] ?? <Monitor className="h-4 w-4" />}
    </Button>
  );
}
```

**Step 2: Update `frontend/src/components/app-header.tsx`**:

```tsx
import { AccountSelector } from "@/components/dashboard/account-selector";
import { ConnectionStatus } from "@/components/dashboard/connection-status";
import { ThemeToggle } from "@/components/theme-toggle";

interface AppHeaderProps {
  title: string;
}

export function AppHeader({ title }: AppHeaderProps) {
  return (
    <header className="flex h-16 shrink-0 items-center gap-2 border-b px-4">
      <h1 className="font-semibold">{title}</h1>
      <div className="ml-auto flex items-center gap-3">
        <ConnectionStatus />
        <ThemeToggle />
        <AccountSelector />
      </div>
    </header>
  );
}
```

**Step 3: Open the app** and click the icon in the header — it should cycle System → Light → Dark → System with the correct icon.

**Step 4: Commit**

```bash
git add frontend/src/components/theme-toggle.tsx frontend/src/components/app-header.tsx
git commit -m "feat(ui): add ThemeToggle to AppHeader"
```

---

## Task 9: Add useSettings Zustand hook with localStorage persistence

**Files:**
- Create: `frontend/src/hooks/use-settings.ts`

**Step 1: Create `frontend/src/hooks/use-settings.ts`**:

```ts
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SettingsState {
  defaultAccountId: number | null;
  setDefaultAccountId: (id: number | null) => void;
}

export const useSettings = create<SettingsState>()(
  persist(
    (set) => ({
      defaultAccountId: null,
      setDefaultAccountId: (id) => set({ defaultAccountId: id }),
    }),
    { name: "llm-trading-settings" },
  ),
);
```

**Step 2: Wire `defaultAccountId` into the trading store initialisation** — open `frontend/src/hooks/use-trading-store.ts`, find where `activeAccountId` is initialized. If it starts as `null`, update the initial load logic in `app/page.tsx` or the WebSocket hook to read from `useSettings().defaultAccountId` on first mount. (This is a light touch — just read the value; the trading store already handles the active account.)

For now, the settings page will show the selector and save the value. The auto-select wiring is a follow-up.

**Step 3: Verify no TypeScript errors**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: Build succeeds (or only pre-existing errors, none new).

**Step 4: Commit**

```bash
git add frontend/src/hooks/use-settings.ts
git commit -m "feat(hooks): add useSettings with localStorage persistence"
```

---

## Task 10: Add settingsApi client

**Files:**
- Create: `frontend/src/lib/api/settings.ts`

**Step 1: Create `frontend/src/lib/api/settings.ts`**:

```ts
import { apiRequest } from "@/lib/api";

export interface ProviderStatus {
  provider: string;
  is_configured: boolean;
  is_active: boolean;
  key_hint: string | null;
}

export interface TaskAssignment {
  task: string;
  provider: string;
  model_name: string;
}

export const settingsApi = {
  listProviders: () =>
    apiRequest<ProviderStatus[]>("/settings/llm/providers"),

  saveProvider: (provider: string, api_key: string) =>
    apiRequest<ProviderStatus>(`/settings/llm/providers/${provider}`, {
      method: "PUT",
      body: JSON.stringify({ api_key }),
    }),

  testProvider: (provider: string, api_key: string) =>
    apiRequest<{ success: boolean; message: string }>(
      `/settings/llm/providers/${provider}/test`,
      {
        method: "POST",
        body: JSON.stringify({ api_key }),
      },
    ),

  getAssignments: () =>
    apiRequest<TaskAssignment[]>("/settings/llm/assignments"),

  saveAssignments: (assignments: TaskAssignment[]) =>
    apiRequest<TaskAssignment[]>("/settings/llm/assignments", {
      method: "PUT",
      body: JSON.stringify({ assignments }),
    }),
};
```

**Step 2: Verify import chain works**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "api/settings" | head -5
```

Expected: No errors referencing `api/settings`.

**Step 3: Commit**

```bash
git add frontend/src/lib/api/settings.ts
git commit -m "feat(api): add settingsApi client for LLM provider + task assignment endpoints"
```

---

## Task 11: Build the Settings page

**Files:**
- Create: `frontend/src/app/settings/page.tsx`

**Step 1: Create `frontend/src/app/settings/page.tsx`** with the full three-section layout:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Monitor, Moon, Sun, CheckCircle, XCircle, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { settingsApi, type ProviderStatus, type TaskAssignment } from "@/lib/api/settings";
import { accountsApi } from "@/lib/api/accounts";
import { useSettings } from "@/hooks/use-settings";
import type { Account } from "@/types/trading";

// ── Types ─────────────────────────────────────────────────────────────────────

const PROVIDERS = ["openai", "gemini", "anthropic"] as const;
type Provider = (typeof PROVIDERS)[number];

const TASKS: { key: string; label: string }[] = [
  { key: "market_analysis",    label: "Market Analysis" },
  { key: "vision",             label: "Vision / Chart Reading" },
  { key: "execution_decision", label: "Execution Decision" },
];

const PROVIDER_LABELS: Record<Provider, string> = {
  openai:    "OpenAI",
  gemini:    "Gemini",
  anthropic: "Anthropic",
};

// ── Section 1: Theme ──────────────────────────────────────────────────────────

function ThemeSection() {
  const { theme, setTheme } = useTheme();

  const options = [
    { value: "light",  label: "Light",  icon: <Sun  className="h-4 w-4" /> },
    { value: "dark",   label: "Dark",   icon: <Moon className="h-4 w-4" /> },
    { value: "system", label: "System", icon: <Monitor className="h-4 w-4" /> },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Appearance</CardTitle>
      </CardHeader>
      <CardContent>
        <Label className="text-sm text-muted-foreground mb-3 block">Theme</Label>
        <div className="flex gap-2">
          {options.map((opt) => (
            <Button
              key={opt.value}
              variant={theme === opt.value ? "default" : "outline"}
              size="sm"
              className="flex items-center gap-2"
              onClick={() => setTheme(opt.value)}
            >
              {opt.icon}
              {opt.label}
            </Button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ── Section 2: Display Preferences ───────────────────────────────────────────

function DisplaySection() {
  const { defaultAccountId, setDefaultAccountId } = useSettings();
  const [accounts, setAccounts] = useState<Account[]>([]);

  useEffect(() => {
    accountsApi.list().then(setAccounts).catch(() => {});
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Display Preferences</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label className="text-sm">Default Account</Label>
          <p className="text-xs text-muted-foreground">
            Auto-select this account when the dashboard loads.
          </p>
          <Select
            value={defaultAccountId != null ? String(defaultAccountId) : "none"}
            onValueChange={(v) => setDefaultAccountId(v === "none" ? null : Number(v))}
          >
            <SelectTrigger className="w-64">
              <SelectValue placeholder="No default" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">No default — show all</SelectItem>
              {accounts.map((a) => (
                <SelectItem key={a.id} value={String(a.id)}>
                  {a.name} ({a.broker})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Section 3: LLM Providers ──────────────────────────────────────────────────

interface ProviderCardProps {
  provider: Provider;
  status: ProviderStatus | undefined;
  onSaved: () => void;
}

function ProviderCard({ provider, status, onSaved }: ProviderCardProps) {
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  async function handleTest() {
    if (!apiKey.trim()) {
      toast.error("Enter an API key to test");
      return;
    }
    setTesting(true);
    try {
      const result = await settingsApi.testProvider(provider, apiKey);
      if (result.success) {
        toast.success(result.message);
      } else {
        toast.error(result.message);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Test failed");
    } finally {
      setTesting(false);
    }
  }

  async function handleSave() {
    if (!apiKey.trim()) {
      toast.error("Enter an API key to save");
      return;
    }
    setSaving(true);
    try {
      await settingsApi.saveProvider(provider, apiKey);
      toast.success(`${PROVIDER_LABELS[provider]} API key saved`);
      setApiKey("");
      onSaved();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold">{PROVIDER_LABELS[provider]}</CardTitle>
          {status?.is_configured ? (
            <Badge variant="outline" className="text-xs text-green-600 border-green-600">
              <CheckCircle className="h-3 w-3 mr-1" /> Configured
            </Badge>
          ) : (
            <Badge variant="outline" className="text-xs text-muted-foreground">
              <XCircle className="h-3 w-3 mr-1" /> Not set
            </Badge>
          )}
        </div>
        {status?.key_hint && (
          <p className="text-xs text-muted-foreground font-mono">{status.key_hint}</p>
        )}
      </CardHeader>
      <CardContent className="space-y-2">
        <Input
          type="password"
          placeholder={`${PROVIDER_LABELS[provider]} API key`}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          className="font-mono text-sm"
        />
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={handleTest}
            disabled={testing || !apiKey.trim()}
            className="flex-1"
          >
            {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : null}
            Test
          </Button>
          <Button
            size="sm"
            onClick={handleSave}
            disabled={saving || !apiKey.trim()}
            className="flex-1"
          >
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : null}
            Save
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Section 4: Task Assignments ───────────────────────────────────────────────

interface TaskAssignmentsProps {
  providers: ProviderStatus[];
}

function TaskAssignmentsSection({ providers }: TaskAssignmentsProps) {
  const [assignments, setAssignments] = useState<TaskAssignment[]>([]);
  const [saving, setSaving] = useState(false);
  const connectedProviders = providers.filter((p) => p.is_configured);

  useEffect(() => {
    settingsApi.getAssignments().then(setAssignments).catch(() => {});
  }, []);

  function update(task: string, field: "provider" | "model_name", value: string) {
    setAssignments((prev) =>
      prev.map((a) => (a.task === task ? { ...a, [field]: value } : a))
    );
  }

  async function handleSave() {
    setSaving(true);
    try {
      const updated = await settingsApi.saveAssignments(assignments);
      setAssignments(updated);
      toast.success("Task assignments saved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Task LLM Assignments</CardTitle>
        <p className="text-xs text-muted-foreground">
          Choose which provider and model handles each AI task.
          Only configured providers appear in the dropdown.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {TASKS.map(({ key, label }) => {
          const a = assignments.find((x) => x.task === key) ?? { task: key, provider: "", model_name: "" };
          return (
            <div key={key} className="grid grid-cols-[160px_1fr_1fr] gap-3 items-center">
              <Label className="text-sm font-medium">{label}</Label>
              <Select
                value={a.provider || "none"}
                onValueChange={(v) => update(key, "provider", v === "none" ? "" : v)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Provider" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">— Not set —</SelectItem>
                  {connectedProviders.map((p) => (
                    <SelectItem key={p.provider} value={p.provider}>
                      {PROVIDER_LABELS[p.provider as Provider] ?? p.provider}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input
                placeholder="Model (e.g. gpt-4o)"
                value={a.model_name}
                onChange={(e) => update(key, "model_name", e.target.value)}
                className="font-mono text-sm"
                disabled={!a.provider}
              />
            </div>
          );
        })}

        <Button onClick={handleSave} disabled={saving} className="mt-2">
          {saving ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
          Save Assignments
        </Button>
      </CardContent>
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const [providers, setProviders] = useState<ProviderStatus[]>([]);

  const loadProviders = useCallback(async () => {
    try {
      const data = await settingsApi.listProviders();
      setProviders(data);
    } catch (e) {
      console.error("Failed to load providers", e);
    }
  }, []);

  useEffect(() => {
    loadProviders();
  }, [loadProviders]);

  return (
    <SidebarInset>
      <AppHeader title="Settings" />
      <div className="flex flex-1 flex-col gap-6 p-6 max-w-3xl">

        {/* Section 1 — Appearance */}
        <ThemeSection />

        {/* Section 2 — Display */}
        <DisplaySection />

        {/* Section 3 — LLM Providers */}
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
            LLM Providers
          </h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {PROVIDERS.map((p) => (
              <ProviderCard
                key={p}
                provider={p}
                status={providers.find((s) => s.provider === p)}
                onSaved={loadProviders}
              />
            ))}
          </div>
        </div>

        {/* Section 4 — Task Assignments */}
        <TaskAssignmentsSection providers={providers} />

      </div>
    </SidebarInset>
  );
}
```

**Step 2: Run the dev server and navigate to `/settings`**

```bash
cd frontend && npm run dev
```

Open `http://localhost:3000/settings`. Verify:
- All 3 sections render
- Theme buttons change the page theme
- Provider cards show "Not set" badges initially
- Entering a key and clicking Test/Save calls the backend

**Step 3: Run a type check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | tail -20
```

Expected: No new errors.

**Step 4: Commit**

```bash
git add frontend/src/app/settings/
git commit -m "feat(settings): full settings page — theme, display, LLM providers, task assignments"
```

---

## Final Verification Checklist

- [ ] `GET /api/v1/settings/llm/providers` returns 3 rows (all unconfigured initially)
- [ ] `PUT /api/v1/settings/llm/providers/openai` with a test key → returns `is_configured: true`
- [ ] `POST /api/v1/settings/llm/providers/openai/test` with a valid key → `{"success": true, ...}`
- [ ] `GET /api/v1/settings/llm/assignments` returns 3 tasks with empty provider/model
- [ ] `PUT /api/v1/settings/llm/assignments` persists and is read back correctly
- [ ] Orchestrator uses the DB assignment on next pipeline run (check logs for `provider=` in `llm_analyzed` step)
- [ ] Theme toggle in header cycles correctly
- [ ] Dark mode works (page goes dark)
- [ ] Settings page renders without console errors
- [ ] Selecting a default account persists across page refresh (localStorage)
