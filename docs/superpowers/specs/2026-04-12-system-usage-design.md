# System Usage Page — Design Spec

**Date:** 2026-04-12
**Status:** Approved

---

## Overview

A real-time system monitoring page for the LLM System Trading dashboard. Shows host machine health, Docker container stats, and Ollama local LLM status in a single scrollable view. Targets both traders (is the system OK to trade?) and developers (deep resource diagnostics).

---

## Goals

- Give traders a fast health check: is CPU/RAM under control, are Docker services up, is Ollama loaded?
- Give developers per-core, per-container, per-model detail without switching tools
- Alert proactively when resources are critically high (Sonner toast + color-coded cards)

---

## Architecture

### Backend

**New endpoint:** `GET /api/v1/system/usage`

Returns all metrics in one JSON payload. Polled every 5s from frontend. New router file:
`backend/api/routes/system.py`

**Data sources (all with graceful fallback):**

| Source | Library | Metrics |
|--------|---------|---------|
| Host CPU | `psutil` | overall %, per-core %, frequency, process count |
| Host RAM | `psutil` | used, total, available, swap used/total |
| Host Disk | `psutil` | per-mount used/total/percent, read/write bytes/s |
| Host GPU | `pynvml` (optional) | name, utilization %, VRAM used/total, temperature |
| Docker containers | `docker` SDK | name, status, CPU %, memory used/limit |
| Ollama models | HTTP `GET localhost:11434/api/ps` | loaded models, size_vram, status |

**Fallback rules:**
- No GPU → `gpu: null` in response
- Docker unreachable → `docker: null`
- Ollama unreachable → `ollama: null`

**New dependencies to add to `pyproject.toml`:**
- `psutil` — host metrics
- `pynvml` — GPU metrics (optional extra, skip if unavailable at runtime)
- `docker` — Docker SDK for container stats

### Frontend

| File | Purpose |
|------|---------|
| `frontend/src/app/system-usage/page.tsx` | Page entry point |
| `frontend/src/types/system.ts` | TypeScript types for all metric shapes |
| `frontend/src/lib/api/system.ts` | `systemApi.getUsage()` client |
| `frontend/src/components/system-usage/kpi-bar.tsx` | 4-card summary row |
| `frontend/src/components/system-usage/host-section.tsx` | CPU, RAM, Disk, GPU cards |
| `frontend/src/components/system-usage/docker-section.tsx` | Container table/cards |
| `frontend/src/components/system-usage/ollama-section.tsx` | Loaded models list |

**Polling:** `setInterval` every 5000ms. Paused when `document.visibilityState === "hidden"` to avoid unnecessary requests when tab is backgrounded.

**Alert deduplication:** A `useRef<Set<string>>` tracks which thresholds have already triggered toasts. A threshold re-arms only after it drops back below the warning level.

---

## Page Layout

Single scrollable page (no tabs). Top to bottom:

```
┌─────────────────────────────────────────┐
│ AppHeader: "System Usage"  [Refresh btn] │
├──────────┬──────────┬──────────┬─────────┤
│  CPU %   │  RAM %   │  Disk %  │  GPU %  │  ← KPI bar (4 cards)
├──────────┴──────────┴──────────┴─────────┤
│ HOST                                     │
│  ┌─ CPU ──────────┐ ┌─ RAM ────────────┐ │
│  │ overall + bars │ │ used/total + swap│ │
│  └────────────────┘ └─────────────────┘ │
│  ┌─ Disk ─────────┐ ┌─ GPU ───────────┐ │
│  │ mounts + speed │ │ VRAM + temp     │ │
│  └────────────────┘ └─────────────────┘ │
├──────────────────────────────────────────┤
│ DOCKER CONTAINERS  (hidden if null)      │
│  name | status | CPU% | memory           │
├──────────────────────────────────────────┤
│ OLLAMA  (hidden if null)                 │
│  model name | size | VRAM | status       │
└──────────────────────────────────────────┘
```

---

## Color Coding

Applied to cards and progress bars:

| Level | Threshold | Color |
|-------|-----------|-------|
| Normal | < 60% | green |
| Warning | 60–80% | yellow |
| Critical | > 80% | red |

Applies to: CPU %, RAM %, Disk %, GPU VRAM %

---

## Alert Thresholds (Sonner Toast)

| Metric | Warning toast | Critical toast |
|--------|--------------|----------------|
| CPU | > 80% | > 95% |
| RAM | > 85% | > 95% |
| VRAM | > 85% | > 95% |
| Disk | > 85% | > 95% |

- Warning → `toast.warning(...)` (yellow)
- Critical → `toast.error(...)` (red)
- Each threshold fires **once** per crossing; re-arms when metric drops below warning level

---

## Unavailable Metric Handling (Mix Strategy)

| Scenario | Behavior |
|----------|---------|
| Docker entirely unreachable | Docker section hidden |
| Ollama entirely unreachable | Ollama section hidden, no error shown |
| No GPU detected | GPU card shows "No GPU" badge, not hidden |
| Individual sub-metric missing | Shows "N/A" within card |

---

## TypeScript Types (`types/system.ts`)

```ts
interface CpuInfo {
  overall_percent: number;
  per_core_percent: number[];
  frequency_mhz: number | null;
  process_count: number;
}

interface RamInfo {
  used_bytes: number;
  total_bytes: number;
  available_bytes: number;
  swap_used_bytes: number;
  swap_total_bytes: number;
}

interface DiskMount {
  mountpoint: string;
  used_bytes: number;
  total_bytes: number;
  percent: number;
  read_bytes_per_sec: number | null;
  write_bytes_per_sec: number | null;
}

interface GpuInfo {
  name: string;
  utilization_percent: number;
  vram_used_bytes: number;
  vram_total_bytes: number;
  temperature_celsius: number | null;
}

interface ContainerStat {
  name: string;
  status: string;
  cpu_percent: number | null;
  memory_used_bytes: number | null;
  memory_limit_bytes: number | null;
}

interface OllamaModel {
  name: string;
  size_vram_bytes: number;
  status: string;
}

interface SystemUsage {
  timestamp: string;
  cpu: CpuInfo;
  ram: RamInfo;
  disk: DiskMount[];
  gpu: GpuInfo | null;
  docker: ContainerStat[] | null;
  ollama: OllamaModel[] | null;
}
```

---

## Sidebar Navigation

Add "System Usage" entry to `frontend/src/components/app-sidebar.tsx` with a `Monitor` icon (lucide).

---

## Backend Route Registration

Register new router in `backend/main.py`:
```python
from api.routes.system import router as system_router
app.include_router(system_router, prefix="/api/v1/system", tags=["system"])
```

---

## Out of Scope (v1)

- Historical trending / charts over time
- Configurable alert thresholds (hardcoded in v1)
- Per-process breakdown (top N processes by CPU/RAM)
- Network interface stats
- Push alerts via Telegram/email
