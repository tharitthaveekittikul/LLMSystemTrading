# Settings Page Design

**Date:** 2026-03-01
**Status:** Approved

---

## Overview

Add a `/settings` page (already in sidebar nav) with three sections:

1. **Appearance** — theme (light/dark/system) + header toggle
2. **Display** — default account preference (localStorage)
3. **LLM Configuration** — provider API keys + per-task model assignment (backend + DB)

---

## Section 1: Appearance & Display

### Theme

- Use `next-themes` (already installed v0.4.6)
- Add `ThemeProvider` wrapping `<body>` in `layout.tsx` (attribute="class", defaultTheme="system")
- Three choices: Light / Dark / System
- Stored automatically in `localStorage` by `next-themes`

### App Header Toggle

- Add `ThemeToggle` component to `AppHeader` (right side, after `ConnectionStatus`)
- Cycles: System → Light → Dark → System on each click
- Icons: `Monitor` → `Sun` → `Moon` (lucide-react, already installed)

### Display Preferences

- New `useSettings` Zustand slice with `localStorage` persistence
- Initial field: `defaultAccountId: number | null` — auto-selects account on load
- Rendered as a dropdown on the settings page (fetches account list)

---

## Section 2: LLM Providers

Three provider cards side-by-side (or stacked on mobile): **OpenAI**, **Gemini**, **Anthropic**.

Each card shows:
- Provider logo/name + status badge (`Connected` / `Not configured`)
- Masked API key input (shows `sk-...****` when key is already saved)
- **Test Connection** button — calls `POST /api/v1/settings/llm/providers/{provider}/test`
- **Save** button — calls `PUT /api/v1/settings/llm/providers/{provider}`

### Storage

- New `llm_provider_configs` table (PostgreSQL)
- API key encrypted with Fernet (same pattern as `accounts.encrypted_password`)
- One row per provider (upsert on save)

### Backend Routes (`api/routes/settings.py`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/settings/llm/providers` | List all providers with status (never returns raw key) |
| `PUT` | `/api/v1/settings/llm/providers/{provider}` | Save/update API key |
| `POST` | `/api/v1/settings/llm/providers/{provider}/test` | Test API key (live call) |

### Provider enum values: `openai`, `gemini`, `anthropic`

---

## Section 3: Task Assignments

A table with 3 configurable tasks:

| Task key | Label |
|----------|-------|
| `market_analysis` | Market Analysis |
| `vision` | Vision / Chart Reading |
| `execution_decision` | Execution Decision |

For each task: **Provider dropdown** (only connected providers) + **Model text input** (e.g., `gpt-4o`).

### Storage

- New `task_llm_assignments` table (PostgreSQL)
- One row per task (upsert on save)

### Backend Routes

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/settings/llm/assignments` | Get all 3 task assignments |
| `PUT` | `/api/v1/settings/llm/assignments` | Save all 3 at once |

### Orchestrator Integration

- `ai/orchestrator.py` reads task assignments from DB at start of each pipeline run
- Builds a task-specific LangChain LLM instance for each task
- Falls back to `LLM_PROVIDER` env var if no assignment is saved for a task
- `services/ai_trading.py` passes task-specific LLMs to orchestrator calls

---

## Database Schema

### Migration: one new Alembic migration file

```sql
CREATE TABLE llm_provider_configs (
    id          SERIAL PRIMARY KEY,
    provider    VARCHAR(32) UNIQUE NOT NULL,   -- 'openai' | 'gemini' | 'anthropic'
    encrypted_api_key TEXT NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE task_llm_assignments (
    task        VARCHAR(64) PRIMARY KEY,       -- 'market_analysis' | 'vision' | 'execution_decision'
    provider    VARCHAR(32) NOT NULL,
    model_name  VARCHAR(128) NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## File Changes Summary

### Backend (new/modified)

| File | Action |
|------|--------|
| `db/models.py` | Add `LLMProviderConfig` + `TaskLLMAssignment` SQLAlchemy models |
| `alembic/versions/<hash>_add_llm_settings.py` | Migration for both tables |
| `api/routes/settings.py` | New: 5 routes (providers list, provider save, provider test, assignments get, assignments save) |
| `main.py` | Register `/api/v1/settings` router |
| `ai/orchestrator.py` | Accept task-specific LLM config; fall back to env default |
| `services/ai_trading.py` | Load task assignments from DB, pass to orchestrator calls |

### Frontend (new/modified)

| File | Action |
|------|--------|
| `src/app/layout.tsx` | Wrap body with `ThemeProvider` from `next-themes` |
| `src/components/theme-toggle.tsx` | New: cycling Sun/Moon/Monitor button |
| `src/components/app-header.tsx` | Add `ThemeToggle` |
| `src/hooks/use-settings.ts` | New: Zustand slice with localStorage persistence |
| `src/lib/api/settings.ts` | New: API client for LLM settings routes |
| `src/app/settings/page.tsx` | New: settings page with 3 sections |

---

## Implementation Notes

- `next-themes` requires `suppressHydrationWarning` on `<html>` — already present in `layout.tsx`
- API key input should never display the raw key — backend returns only a masked hint (`gpt...****`)
- Test connection makes a minimal real API call (e.g., list models or a 1-token completion)
- Orchestrator fallback: if `task_llm_assignments` is empty for a task, use the existing `LLM_PROVIDER` env config
- Settings page is a standard Next.js `page.tsx` with `"use client"` — no SSR needed
