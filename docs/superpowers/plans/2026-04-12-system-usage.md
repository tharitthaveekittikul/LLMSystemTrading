# System Usage Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a real-time System Usage page showing host machine (CPU/RAM/Disk/GPU), Docker container stats, and Ollama loaded models with 5-second auto-polling and Sonner toast alerts.

**Architecture:** Single FastAPI endpoint `GET /api/v1/system/usage` collects all metrics (psutil for host, Docker SDK for containers, httpx for Ollama) and returns a unified JSON payload. The Next.js page polls every 5s, renders color-coded cards, and fires Sonner toasts when thresholds are crossed.

**Tech Stack:** Python `psutil`, `pynvml` (optional GPU), `docker` SDK, `httpx` (already installed); Next.js with shadcn/ui cards, lucide-react icons, `sonner` (already installed).

**Spec:** `docs/superpowers/specs/2026-04-12-system-usage-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `backend/api/routes/system.py` | Pydantic models + psutil/GPU/Docker/Ollama helpers + endpoint |
| Modify | `backend/main.py` | Register system router |
| Modify | `backend/pyproject.toml` | Add psutil, pynvml, docker dependencies |
| Create | `backend/tests/test_system_route.py` | Route unit tests with mocked helpers |
| Create | `frontend/src/types/system.ts` | TypeScript interfaces matching backend response |
| Create | `frontend/src/lib/api/system.ts` | `systemApi.getUsage()` client |
| Create | `frontend/src/components/system-usage/kpi-bar.tsx` | 4-card summary row |
| Create | `frontend/src/components/system-usage/host-section.tsx` | CPU/RAM/Disk/GPU detail cards |
| Create | `frontend/src/components/system-usage/docker-section.tsx` | Container table |
| Create | `frontend/src/components/system-usage/ollama-section.tsx` | Loaded models list |
| Create | `frontend/src/app/system-usage/page.tsx` | Page: polling + alert logic |
| Modify | `frontend/src/components/app-sidebar.tsx` | Add "System Usage" nav entry |

---

## Task 1: Add Python Dependencies

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add psutil, pynvml, docker to dependencies**

In `backend/pyproject.toml`, add these three lines inside the `dependencies = [` array, after `"httpx>=0.28.0"`:

```toml
    "psutil>=6.0.0",
    "pynvml>=11.5.0",
    "docker>=7.0.0",
```

- [ ] **Step 2: Sync dependencies**

```bash
cd backend && uv sync
```

Expected: Lock file updated, packages installed with no errors.

- [ ] **Step 3: Verify imports work**

```bash
cd backend && uv run python -c "import psutil, docker; print('OK')"
```

Expected: `OK` (pynvml may warn if no NVIDIA driver — that is fine).

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "feat(system): add psutil, pynvml, docker dependencies"
```

---

## Task 2: Create Backend System Route

**Files:**
- Create: `backend/api/routes/system.py`

- [ ] **Step 1: Create the route file**

Create `backend/api/routes/system.py` with the full content below:

```python
"""System resource usage API — CPU, RAM, Disk, GPU, Docker containers, Ollama models."""
import asyncio
import logging
import time
from datetime import UTC, datetime

import httpx
import psutil
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)

# ── Module-level IO counter cache (for disk read/write rate calculation) ──────
_last_disk_io: tuple[float, object] | None = None


# ── Response models ────────────────────────────────────────────────────────────

class CpuInfo(BaseModel):
    overall_percent: float
    per_core_percent: list[float]
    frequency_mhz: float | None
    process_count: int


class RamInfo(BaseModel):
    used_bytes: int
    total_bytes: int
    available_bytes: int
    swap_used_bytes: int
    swap_total_bytes: int


class DiskMount(BaseModel):
    mountpoint: str
    used_bytes: int
    total_bytes: int
    percent: float
    read_bytes_per_sec: float | None
    write_bytes_per_sec: float | None


class GpuInfo(BaseModel):
    name: str
    utilization_percent: float
    vram_used_bytes: int
    vram_total_bytes: int
    temperature_celsius: float | None


class ContainerStat(BaseModel):
    name: str
    status: str
    cpu_percent: float | None
    memory_used_bytes: int | None
    memory_limit_bytes: int | None


class OllamaModel(BaseModel):
    name: str
    size_vram_bytes: int
    status: str


class SystemUsage(BaseModel):
    timestamp: str
    cpu: CpuInfo
    ram: RamInfo
    disk: list[DiskMount]
    gpu: GpuInfo | None
    docker: list[ContainerStat] | None
    ollama: list[OllamaModel] | None


# ── Sync helper functions (run in executor) ────────────────────────────────────

def _get_cpu() -> CpuInfo:
    per_core: list[float] = psutil.cpu_percent(percpu=True, interval=0.5)  # type: ignore[assignment]
    overall = sum(per_core) / len(per_core) if per_core else 0.0
    freq = psutil.cpu_freq()
    return CpuInfo(
        overall_percent=round(overall, 1),
        per_core_percent=[round(p, 1) for p in per_core],
        frequency_mhz=round(freq.current, 1) if freq else None,
        process_count=len(psutil.pids()),
    )


def _get_ram() -> RamInfo:
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    return RamInfo(
        used_bytes=vm.used,
        total_bytes=vm.total,
        available_bytes=vm.available,
        swap_used_bytes=sw.used,
        swap_total_bytes=sw.total,
    )


def _get_disk() -> list[DiskMount]:
    global _last_disk_io
    now = time.monotonic()
    io_now = psutil.disk_io_counters(perdisk=False)

    read_rate: float | None = None
    write_rate: float | None = None
    if _last_disk_io is not None and io_now is not None:
        elapsed = now - _last_disk_io[0]
        prev_io = _last_disk_io[1]
        if elapsed > 0:
            read_rate = round((io_now.read_bytes - prev_io.read_bytes) / elapsed, 0)  # type: ignore[attr-defined]
            write_rate = round((io_now.write_bytes - prev_io.write_bytes) / elapsed, 0)  # type: ignore[attr-defined]
    if io_now is not None:
        _last_disk_io = (now, io_now)

    mounts: list[DiskMount] = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            mounts.append(DiskMount(
                mountpoint=part.mountpoint,
                used_bytes=usage.used,
                total_bytes=usage.total,
                percent=round(usage.percent, 1),
                read_bytes_per_sec=read_rate,
                write_bytes_per_sec=write_rate,
            ))
        except PermissionError:
            continue
    return mounts


def _get_gpu() -> GpuInfo | None:
    try:
        import pynvml  # optional — not available on non-NVIDIA systems
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        raw_name = pynvml.nvmlDeviceGetName(handle)
        name = raw_name if isinstance(raw_name, str) else raw_name.decode()
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        try:
            temp: float | None = float(pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU))
        except Exception:
            temp = None
        return GpuInfo(
            name=name,
            utilization_percent=float(util.gpu),
            vram_used_bytes=int(mem.used),
            vram_total_bytes=int(mem.total),
            temperature_celsius=temp,
        )
    except Exception:
        return None


def _get_docker_stats() -> list[ContainerStat] | None:
    try:
        import docker  # optional — graceful skip if Docker unreachable
        client = docker.from_env(timeout=3)
        containers = client.containers.list(all=True)
        stats: list[ContainerStat] = []
        for c in containers:
            cpu_pct: float | None = None
            mem_used: int | None = None
            mem_limit: int | None = None
            if c.status == "running":
                try:
                    raw = c.stats(stream=False)
                    cpu_delta = (
                        raw["cpu_stats"]["cpu_usage"]["total_usage"]
                        - raw["precpu_stats"]["cpu_usage"]["total_usage"]
                    )
                    sys_delta = (
                        raw["cpu_stats"]["system_cpu_usage"]
                        - raw["precpu_stats"]["system_cpu_usage"]
                    )
                    num_cpus = raw["cpu_stats"].get("online_cpus", 1)
                    if sys_delta > 0:
                        cpu_pct = round((cpu_delta / sys_delta) * num_cpus * 100.0, 2)
                    mem_stats = raw.get("memory_stats", {})
                    mem_used = mem_stats.get("usage")
                    mem_limit = mem_stats.get("limit")
                except Exception:
                    pass
            stats.append(ContainerStat(
                name=c.name,
                status=c.status,
                cpu_percent=cpu_pct,
                memory_used_bytes=mem_used,
                memory_limit_bytes=mem_limit,
            ))
        return stats
    except Exception:
        return None


# ── Async helper ───────────────────────────────────────────────────────────────

async def _get_ollama_models() -> list[OllamaModel] | None:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("http://localhost:11434/api/ps")
            if resp.status_code != 200:
                return None
            data = resp.json()
            return [
                OllamaModel(
                    name=m.get("name", "unknown"),
                    size_vram_bytes=m.get("size_vram", 0),
                    status="loaded",
                )
                for m in data.get("models", [])
            ]
    except Exception:
        return None


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.get("", response_model=SystemUsage)
async def get_system_usage() -> SystemUsage:
    """Return a snapshot of host, Docker, and Ollama resource usage."""
    loop = asyncio.get_event_loop()
    cpu, ram, disk, gpu, docker_stats, ollama = await asyncio.gather(
        loop.run_in_executor(None, _get_cpu),
        loop.run_in_executor(None, _get_ram),
        loop.run_in_executor(None, _get_disk),
        loop.run_in_executor(None, _get_gpu),
        loop.run_in_executor(None, _get_docker_stats),
        _get_ollama_models(),
    )
    return SystemUsage(
        timestamp=datetime.now(UTC).isoformat(),
        cpu=cpu,
        ram=ram,
        disk=disk,
        gpu=gpu,
        docker=docker_stats,
        ollama=ollama,
    )
```

- [ ] **Step 2: Verify the file has no syntax errors**

```bash
cd backend && uv run python -c "from api.routes.system import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/api/routes/system.py
git commit -m "feat(system): add system usage route with psutil/GPU/Docker/Ollama helpers"
```

---

## Task 3: Register System Router in main.py

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add import**

In `backend/main.py`, after the line:
```python
from api.routes import news as news_routes
```
Add:
```python
from api.routes import system as system_routes
```

- [ ] **Step 2: Register the router**

After the line:
```python
app.include_router(news_routes.router,        prefix="/api/v1/news",        tags=["news"])
```
Add:
```python
app.include_router(system_routes.router,      prefix="/api/v1/system",      tags=["system"])
```

- [ ] **Step 3: Verify startup**

```bash
cd backend && uv run python -c "from main import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat(system): register system usage router at /api/v1/system"
```

---

## Task 4: Write Backend Tests

**Files:**
- Create: `backend/tests/test_system_route.py`

- [ ] **Step 1: Create the test file**

Create `backend/tests/test_system_route.py`:

```python
"""Tests for GET /api/v1/system/usage."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


def _make_cpu():
    from api.routes.system import CpuInfo
    return CpuInfo(overall_percent=45.0, per_core_percent=[40.0, 50.0], frequency_mhz=3600.0, process_count=120)


def _make_ram():
    from api.routes.system import RamInfo
    return RamInfo(used_bytes=8 * 2**30, total_bytes=16 * 2**30, available_bytes=8 * 2**30, swap_used_bytes=0, swap_total_bytes=4 * 2**30)


def _make_disk():
    from api.routes.system import DiskMount
    return [DiskMount(mountpoint="C:\\", used_bytes=100 * 2**30, total_bytes=500 * 2**30, percent=20.0, read_bytes_per_sec=None, write_bytes_per_sec=None)]


@pytest.mark.asyncio
async def test_system_usage_returns_200():
    with (
        patch("api.routes.system._get_cpu", return_value=_make_cpu()),
        patch("api.routes.system._get_ram", return_value=_make_ram()),
        patch("api.routes.system._get_disk", return_value=_make_disk()),
        patch("api.routes.system._get_gpu", return_value=None),
        patch("api.routes.system._get_docker_stats", return_value=None),
        patch("api.routes.system._get_ollama_models", new=AsyncMock(return_value=None)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/system/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert "cpu" in data
    assert "ram" in data
    assert "disk" in data
    assert data["gpu"] is None
    assert data["docker"] is None
    assert data["ollama"] is None


@pytest.mark.asyncio
async def test_system_usage_includes_gpu_when_available():
    from api.routes.system import GpuInfo
    gpu = GpuInfo(name="RTX 4090", utilization_percent=30.0, vram_used_bytes=4 * 2**30, vram_total_bytes=24 * 2**30, temperature_celsius=65.0)
    with (
        patch("api.routes.system._get_cpu", return_value=_make_cpu()),
        patch("api.routes.system._get_ram", return_value=_make_ram()),
        patch("api.routes.system._get_disk", return_value=_make_disk()),
        patch("api.routes.system._get_gpu", return_value=gpu),
        patch("api.routes.system._get_docker_stats", return_value=None),
        patch("api.routes.system._get_ollama_models", new=AsyncMock(return_value=None)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/system/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["gpu"]["name"] == "RTX 4090"
    assert data["gpu"]["utilization_percent"] == 30.0


@pytest.mark.asyncio
async def test_system_usage_includes_docker_containers():
    from api.routes.system import ContainerStat
    containers = [
        ContainerStat(name="postgres", status="running", cpu_percent=1.2, memory_used_bytes=256 * 2**20, memory_limit_bytes=2 * 2**30),
        ContainerStat(name="questdb", status="running", cpu_percent=0.5, memory_used_bytes=128 * 2**20, memory_limit_bytes=1 * 2**30),
    ]
    with (
        patch("api.routes.system._get_cpu", return_value=_make_cpu()),
        patch("api.routes.system._get_ram", return_value=_make_ram()),
        patch("api.routes.system._get_disk", return_value=_make_disk()),
        patch("api.routes.system._get_gpu", return_value=None),
        patch("api.routes.system._get_docker_stats", return_value=containers),
        patch("api.routes.system._get_ollama_models", new=AsyncMock(return_value=None)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/system/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["docker"]) == 2
    assert data["docker"][0]["name"] == "postgres"


@pytest.mark.asyncio
async def test_system_usage_includes_ollama_models():
    from api.routes.system import OllamaModel
    models = [OllamaModel(name="llama3:8b", size_vram_bytes=5 * 2**30, status="loaded")]
    with (
        patch("api.routes.system._get_cpu", return_value=_make_cpu()),
        patch("api.routes.system._get_ram", return_value=_make_ram()),
        patch("api.routes.system._get_disk", return_value=_make_disk()),
        patch("api.routes.system._get_gpu", return_value=None),
        patch("api.routes.system._get_docker_stats", return_value=None),
        patch("api.routes.system._get_ollama_models", new=AsyncMock(return_value=models)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/system/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ollama"][0]["name"] == "llama3:8b"
```

- [ ] **Step 2: Run the tests**

```bash
cd backend && uv run pytest tests/test_system_route.py -v
```

Expected: 4 tests PASSED.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_system_route.py
git commit -m "test(system): add system usage route tests with mocked helpers"
```

---

## Task 5: Frontend Types and API Client

**Files:**
- Create: `frontend/src/types/system.ts`
- Create: `frontend/src/lib/api/system.ts`

- [ ] **Step 1: Create TypeScript types**

Create `frontend/src/types/system.ts`:

```typescript
export interface CpuInfo {
  overall_percent: number;
  per_core_percent: number[];
  frequency_mhz: number | null;
  process_count: number;
}

export interface RamInfo {
  used_bytes: number;
  total_bytes: number;
  available_bytes: number;
  swap_used_bytes: number;
  swap_total_bytes: number;
}

export interface DiskMount {
  mountpoint: string;
  used_bytes: number;
  total_bytes: number;
  percent: number;
  read_bytes_per_sec: number | null;
  write_bytes_per_sec: number | null;
}

export interface GpuInfo {
  name: string;
  utilization_percent: number;
  vram_used_bytes: number;
  vram_total_bytes: number;
  temperature_celsius: number | null;
}

export interface ContainerStat {
  name: string;
  status: string;
  cpu_percent: number | null;
  memory_used_bytes: number | null;
  memory_limit_bytes: number | null;
}

export interface OllamaModel {
  name: string;
  size_vram_bytes: number;
  status: string;
}

export interface SystemUsage {
  timestamp: string;
  cpu: CpuInfo;
  ram: RamInfo;
  disk: DiskMount[];
  gpu: GpuInfo | null;
  docker: ContainerStat[] | null;
  ollama: OllamaModel[] | null;
}
```

- [ ] **Step 2: Create API client**

Create `frontend/src/lib/api/system.ts`:

```typescript
import { apiRequest } from "@/lib/api";
import type { SystemUsage } from "@/types/system";

export const systemApi = {
  getUsage: () => apiRequest<SystemUsage>("/system/usage"),
};
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/system.ts frontend/src/lib/api/system.ts
git commit -m "feat(system): add frontend types and API client for system usage"
```

---

## Task 6: KPI Bar Component

**Files:**
- Create: `frontend/src/components/system-usage/kpi-bar.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/system-usage/kpi-bar.tsx`:

```tsx
import { Card, CardContent } from "@/components/ui/card";
import type { SystemUsage } from "@/types/system";
import { Cpu, HardDrive, MemoryStick, Microchip } from "lucide-react";

interface Props {
  data: SystemUsage;
}

function pct(used: number, total: number): number {
  return total > 0 ? Math.round((used / total) * 100) : 0;
}

function colorClass(percent: number): string {
  if (percent >= 80) return "text-red-500";
  if (percent >= 60) return "text-yellow-500";
  return "text-green-500";
}

function barClass(percent: number): string {
  if (percent >= 80) return "bg-red-500";
  if (percent >= 60) return "bg-yellow-500";
  return "bg-green-500";
}

function KpiCard({
  label,
  percent,
  sub,
  icon: Icon,
}: {
  label: string;
  percent: number;
  sub: string;
  icon: React.ElementType;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Icon className="h-4 w-4" />
            {label}
          </div>
          <span className={`text-xl font-bold tabular-nums ${colorClass(percent)}`}>
            {percent}%
          </span>
        </div>
        <div className="h-2 rounded-full bg-muted overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${barClass(percent)}`}
            style={{ width: `${percent}%` }}
          />
        </div>
        <p className="text-xs text-muted-foreground mt-1">{sub}</p>
      </CardContent>
    </Card>
  );
}

function formatBytes(bytes: number): string {
  if (bytes >= 2 ** 30) return `${(bytes / 2 ** 30).toFixed(1)} GB`;
  if (bytes >= 2 ** 20) return `${(bytes / 2 ** 20).toFixed(0)} MB`;
  return `${(bytes / 2 ** 10).toFixed(0)} KB`;
}

export function SystemKpiBar({ data }: Props) {
  const ramPct = pct(data.ram.used_bytes, data.ram.total_bytes);
  const primaryDisk = data.disk[0];
  const diskPct = primaryDisk?.percent ?? 0;
  const gpuPct = data.gpu?.utilization_percent ?? null;
  const vramPct = data.gpu
    ? pct(data.gpu.vram_used_bytes, data.gpu.vram_total_bytes)
    : null;

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <KpiCard
        label="CPU"
        percent={data.cpu.overall_percent}
        sub={`${data.cpu.process_count} processes${data.cpu.frequency_mhz ? ` · ${(data.cpu.frequency_mhz / 1000).toFixed(2)} GHz` : ""}`}
        icon={Cpu}
      />
      <KpiCard
        label="RAM"
        percent={ramPct}
        sub={`${formatBytes(data.ram.used_bytes)} / ${formatBytes(data.ram.total_bytes)}`}
        icon={MemoryStick}
      />
      <KpiCard
        label="Disk"
        percent={diskPct}
        sub={primaryDisk ? `${formatBytes(primaryDisk.used_bytes)} / ${formatBytes(primaryDisk.total_bytes)}` : "No disk info"}
        icon={HardDrive}
      />
      {gpuPct !== null && vramPct !== null ? (
        <KpiCard
          label="GPU"
          percent={gpuPct}
          sub={`VRAM ${vramPct}% · ${data.gpu!.name}`}
          icon={Microchip}
        />
      ) : (
        <Card>
          <CardContent className="p-4 flex items-center gap-2 text-muted-foreground">
            <Microchip className="h-4 w-4" />
            <span className="text-sm">No GPU</span>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/system-usage/kpi-bar.tsx
git commit -m "feat(system): add SystemKpiBar component"
```

---

## Task 7: Host Section Component

**Files:**
- Create: `frontend/src/components/system-usage/host-section.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/system-usage/host-section.tsx`:

```tsx
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CpuInfo, DiskMount, GpuInfo, RamInfo } from "@/types/system";
import { Thermometer } from "lucide-react";

function formatBytes(bytes: number): string {
  if (bytes >= 2 ** 30) return `${(bytes / 2 ** 30).toFixed(1)} GB`;
  if (bytes >= 2 ** 20) return `${(bytes / 2 ** 20).toFixed(0)} MB`;
  return `${(bytes / 2 ** 10).toFixed(0)} KB`;
}

function formatRate(bps: number | null): string {
  if (bps === null) return "—";
  if (bps >= 2 ** 20) return `${(bps / 2 ** 20).toFixed(1)} MB/s`;
  return `${(bps / 2 ** 10).toFixed(0)} KB/s`;
}

function pct(used: number, total: number): number {
  return total > 0 ? Math.round((used / total) * 100) : 0;
}

function barClass(percent: number): string {
  if (percent >= 80) return "bg-red-500";
  if (percent >= 60) return "bg-yellow-500";
  return "bg-green-500";
}

function MiniBar({ percent }: { percent: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full ${barClass(percent)}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <span className="text-xs tabular-nums w-8 text-right">{percent}%</span>
    </div>
  );
}

function CpuCard({ cpu }: { cpu: CpuInfo }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">CPU</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <p className="text-xs text-muted-foreground mb-1">Overall</p>
          <MiniBar percent={cpu.overall_percent} />
        </div>
        <div>
          <p className="text-xs text-muted-foreground mb-1">Per Core</p>
          <div className="space-y-1">
            {cpu.per_core_percent.map((p, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground w-10">Core {i}</span>
                <MiniBar percent={p} />
              </div>
            ))}
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          {cpu.process_count} processes
          {cpu.frequency_mhz ? ` · ${(cpu.frequency_mhz / 1000).toFixed(2)} GHz` : ""}
        </p>
      </CardContent>
    </Card>
  );
}

function RamCard({ ram }: { ram: RamInfo }) {
  const usedPct = pct(ram.used_bytes, ram.total_bytes);
  const swapPct = pct(ram.swap_used_bytes, ram.swap_total_bytes);
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">RAM</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <div className="flex justify-between text-xs text-muted-foreground mb-1">
            <span>Used</span>
            <span>{formatBytes(ram.used_bytes)} / {formatBytes(ram.total_bytes)}</span>
          </div>
          <MiniBar percent={usedPct} />
        </div>
        <div>
          <div className="flex justify-between text-xs text-muted-foreground mb-1">
            <span>Available</span>
            <span>{formatBytes(ram.available_bytes)}</span>
          </div>
        </div>
        {ram.swap_total_bytes > 0 && (
          <div>
            <div className="flex justify-between text-xs text-muted-foreground mb-1">
              <span>Swap</span>
              <span>{formatBytes(ram.swap_used_bytes)} / {formatBytes(ram.swap_total_bytes)}</span>
            </div>
            <MiniBar percent={swapPct} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DiskCard({ mounts }: { mounts: DiskMount[] }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Disk</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {mounts.map((m) => (
          <div key={m.mountpoint}>
            <div className="flex justify-between text-xs text-muted-foreground mb-1">
              <span className="font-mono">{m.mountpoint}</span>
              <span>{formatBytes(m.used_bytes)} / {formatBytes(m.total_bytes)}</span>
            </div>
            <MiniBar percent={m.percent} />
          </div>
        ))}
        {mounts[0] && (
          <div className="flex gap-4 text-xs text-muted-foreground pt-1 border-t">
            <span>R: {formatRate(mounts[0].read_bytes_per_sec)}</span>
            <span>W: {formatRate(mounts[0].write_bytes_per_sec)}</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function GpuCard({ gpu }: { gpu: GpuInfo }) {
  const vramPct = pct(gpu.vram_used_bytes, gpu.vram_total_bytes);
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">GPU — {gpu.name}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <p className="text-xs text-muted-foreground mb-1">Utilization</p>
          <MiniBar percent={gpu.utilization_percent} />
        </div>
        <div>
          <div className="flex justify-between text-xs text-muted-foreground mb-1">
            <span>VRAM</span>
            <span>{formatBytes(gpu.vram_used_bytes)} / {formatBytes(gpu.vram_total_bytes)}</span>
          </div>
          <MiniBar percent={vramPct} />
        </div>
        {gpu.temperature_celsius !== null && (
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Thermometer className="h-3 w-3" />
            {gpu.temperature_celsius}°C
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface Props {
  cpu: CpuInfo;
  ram: RamInfo;
  disk: DiskMount[];
  gpu: GpuInfo | null;
}

export function HostSection({ cpu, ram, disk, gpu }: Props) {
  return (
    <div>
      <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-3">Host</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <CpuCard cpu={cpu} />
        <RamCard ram={ram} />
        <DiskCard mounts={disk} />
        {gpu ? <GpuCard gpu={gpu} /> : (
          <Card>
            <CardContent className="p-4 text-sm text-muted-foreground">No GPU detected</CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/system-usage/host-section.tsx
git commit -m "feat(system): add HostSection component with CPU/RAM/Disk/GPU cards"
```

---

## Task 8: Docker Section Component

**Files:**
- Create: `frontend/src/components/system-usage/docker-section.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/system-usage/docker-section.tsx`:

```tsx
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ContainerStat } from "@/types/system";

function formatBytes(bytes: number): string {
  if (bytes >= 2 ** 30) return `${(bytes / 2 ** 30).toFixed(1)} GB`;
  if (bytes >= 2 ** 20) return `${(bytes / 2 ** 20).toFixed(0)} MB`;
  return `${(bytes / 2 ** 10).toFixed(0)} KB`;
}

function StatusBadge({ status }: { status: string }) {
  const variant = status === "running" ? "default" : "secondary";
  return <Badge variant={variant} className="capitalize text-xs">{status}</Badge>;
}

interface Props {
  containers: ContainerStat[];
}

export function DockerSection({ containers }: Props) {
  return (
    <div>
      <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-3">
        Docker Containers
      </h2>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">{containers.length} container{containers.length !== 1 ? "s" : ""}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground border-b">
                  <th className="text-left py-2 pr-4 font-medium">Name</th>
                  <th className="text-left py-2 pr-4 font-medium">Status</th>
                  <th className="text-right py-2 pr-4 font-medium">CPU</th>
                  <th className="text-right py-2 font-medium">Memory</th>
                </tr>
              </thead>
              <tbody>
                {containers.map((c) => (
                  <tr key={c.name} className="border-b last:border-0">
                    <td className="py-2 pr-4 font-mono text-xs">{c.name}</td>
                    <td className="py-2 pr-4">
                      <StatusBadge status={c.status} />
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums text-xs">
                      {c.cpu_percent !== null ? `${c.cpu_percent.toFixed(1)}%` : "—"}
                    </td>
                    <td className="py-2 text-right tabular-nums text-xs">
                      {c.memory_used_bytes !== null && c.memory_limit_bytes !== null
                        ? `${formatBytes(c.memory_used_bytes)} / ${formatBytes(c.memory_limit_bytes)}`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/system-usage/docker-section.tsx
git commit -m "feat(system): add DockerSection component"
```

---

## Task 9: Ollama Section Component

**Files:**
- Create: `frontend/src/components/system-usage/ollama-section.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/system-usage/ollama-section.tsx`:

```tsx
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { OllamaModel } from "@/types/system";

function formatBytes(bytes: number): string {
  if (bytes >= 2 ** 30) return `${(bytes / 2 ** 30).toFixed(1)} GB`;
  if (bytes >= 2 ** 20) return `${(bytes / 2 ** 20).toFixed(0)} MB`;
  return `${bytes} B`;
}

interface Props {
  models: OllamaModel[];
}

export function OllamaSection({ models }: Props) {
  return (
    <div>
      <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-3">
        Ollama — Local LLMs
      </h2>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">
            {models.length} model{models.length !== 1 ? "s" : ""} loaded
          </CardTitle>
        </CardHeader>
        <CardContent>
          {models.length === 0 ? (
            <p className="text-sm text-muted-foreground">No models currently loaded in memory.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground border-b">
                    <th className="text-left py-2 pr-4 font-medium">Model</th>
                    <th className="text-right py-2 pr-4 font-medium">VRAM</th>
                    <th className="text-left py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((m) => (
                    <tr key={m.name} className="border-b last:border-0">
                      <td className="py-2 pr-4 font-mono text-xs">{m.name}</td>
                      <td className="py-2 pr-4 text-right tabular-nums text-xs">
                        {formatBytes(m.size_vram_bytes)}
                      </td>
                      <td className="py-2">
                        <Badge variant="default" className="text-xs capitalize">{m.status}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/system-usage/ollama-section.tsx
git commit -m "feat(system): add OllamaSection component"
```

---

## Task 10: System Usage Page with Polling and Alerts

**Files:**
- Create: `frontend/src/app/system-usage/page.tsx`

- [ ] **Step 1: Create the page**

Create `frontend/src/app/system-usage/page.tsx`:

```tsx
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { SidebarInset } from "@/components/ui/sidebar";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { systemApi } from "@/lib/api/system";
import { SystemKpiBar } from "@/components/system-usage/kpi-bar";
import { HostSection } from "@/components/system-usage/host-section";
import { DockerSection } from "@/components/system-usage/docker-section";
import { OllamaSection } from "@/components/system-usage/ollama-section";
import type { SystemUsage } from "@/types/system";

const POLL_INTERVAL_MS = 5_000;

// Thresholds: [warning, critical]
const THRESHOLDS: Record<string, [number, number]> = {
  cpu: [80, 95],
  ram: [85, 95],
  disk: [85, 95],
  vram: [85, 95],
};

export default function SystemUsagePage() {
  const [data, setData] = useState<SystemUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const firedAlerts = useRef<Set<string>>(new Set());

  function checkAlerts(d: SystemUsage) {
    function fire(key: string, level: "warning" | "error", message: string) {
      if (!firedAlerts.current.has(key)) {
        firedAlerts.current.add(key);
        if (level === "error") toast.error(message);
        else toast.warning(message);
      }
    }
    function clear(...keys: string[]) {
      keys.forEach((k) => firedAlerts.current.delete(k));
    }

    // CPU
    const [cpuWarn, cpuCrit] = THRESHOLDS.cpu;
    if (d.cpu.overall_percent > cpuCrit) fire("cpu-crit", "error", `CPU critical: ${d.cpu.overall_percent.toFixed(1)}%`);
    else if (d.cpu.overall_percent > cpuWarn) fire("cpu-warn", "warning", `CPU high: ${d.cpu.overall_percent.toFixed(1)}%`);
    else clear("cpu-crit", "cpu-warn");

    // RAM
    const [ramWarn, ramCrit] = THRESHOLDS.ram;
    const ramPct = (d.ram.used_bytes / d.ram.total_bytes) * 100;
    if (ramPct > ramCrit) fire("ram-crit", "error", `RAM critical: ${ramPct.toFixed(1)}%`);
    else if (ramPct > ramWarn) fire("ram-warn", "warning", `RAM high: ${ramPct.toFixed(1)}%`);
    else clear("ram-crit", "ram-warn");

    // Disk (primary mount)
    const [diskWarn, diskCrit] = THRESHOLDS.disk;
    const primary = d.disk[0];
    if (primary) {
      if (primary.percent > diskCrit) fire("disk-crit", "error", `Disk critical: ${primary.percent.toFixed(1)}% on ${primary.mountpoint}`);
      else if (primary.percent > diskWarn) fire("disk-warn", "warning", `Disk high: ${primary.percent.toFixed(1)}% on ${primary.mountpoint}`);
      else clear("disk-crit", "disk-warn");
    }

    // GPU VRAM
    if (d.gpu) {
      const [vramWarn, vramCrit] = THRESHOLDS.vram;
      const vramPct = (d.gpu.vram_used_bytes / d.gpu.vram_total_bytes) * 100;
      if (vramPct > vramCrit) fire("vram-crit", "error", `VRAM critical: ${vramPct.toFixed(1)}%`);
      else if (vramPct > vramWarn) fire("vram-warn", "warning", `VRAM high: ${vramPct.toFixed(1)}%`);
      else clear("vram-crit", "vram-warn");
    }
  }

  const fetchData = useCallback(async () => {
    try {
      const result = await systemApi.getUsage();
      setData(result);
      checkAlerts(result);
    } catch {
      // silently ignore — stale data stays visible
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    fetchData();
    const id = setInterval(() => {
      if (document.visibilityState === "visible") fetchData();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchData]);

  return (
    <SidebarInset>
      <AppHeader
        title="System Usage"
        subtitle="Host · Docker · Ollama — refreshes every 5 s"
        showAccountSelector={false}
        showConnectionStatus={false}
        actions={
          <Button variant="outline" size="sm" onClick={fetchData}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
        }
      />

      <div className="flex flex-col gap-8 p-4 md:p-6">
        {loading && !data ? (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-24 rounded-lg border bg-muted/40 animate-pulse" />
            ))}
          </div>
        ) : data ? (
          <>
            <SystemKpiBar data={data} />
            <HostSection cpu={data.cpu} ram={data.ram} disk={data.disk} gpu={data.gpu} />
            {data.docker !== null && <DockerSection containers={data.docker} />}
            {data.ollama !== null && <OllamaSection models={data.ollama} />}
          </>
        ) : null}
      </div>
    </SidebarInset>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/system-usage/page.tsx
git commit -m "feat(system): add system usage page with 5s polling and Sonner alerts"
```

---

## Task 11: Add Sidebar Navigation Entry

**Files:**
- Modify: `frontend/src/components/app-sidebar.tsx`

- [ ] **Step 1: Add Monitor import**

In `frontend/src/components/app-sidebar.tsx`, add `Monitor` to the lucide-react import:

```tsx
import {
  Activity,
  BarChart3,
  Brain,
  CandlestickChart,
  Coins,
  Cpu,
  Database,
  FlaskConical,
  LayoutDashboard,
  Monitor,
  Network,
  Newspaper,
  ScrollText,
  Settings,
  Shield,
  SlidersHorizontal,
  Timer,
  TrendingUp,
  Users,
} from "lucide-react";
```

- [ ] **Step 2: Add nav item**

In the `navItems` array, after the `Storage` entry:

```tsx
  { title: "Storage", url: "/storage", icon: Database },
  { title: "System Usage", url: "/system-usage", icon: Monitor },
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/app-sidebar.tsx
git commit -m "feat(system): add System Usage entry to sidebar navigation"
```

---

## Self-Review

**Spec coverage check:**
- Host CPU/RAM/Disk/GPU — Task 2 (backend), Task 7 (host-section)
- Docker containers — Task 2 (`_get_docker_stats`), Task 8 (docker-section)
- Ollama loaded models — Task 2 (`_get_ollama_models`), Task 9 (ollama-section)
- KPI bar — Task 6 (kpi-bar)
- Auto-polling 5s + visibility pause — Task 10
- Sonner toast alerts — Task 10 (`checkAlerts`)
- Color-coded bars (green/yellow/red) — Tasks 6, 7 (`barClass`)
- Mix fallback strategy (hide Docker/Ollama if null, show "No GPU" card) — Tasks 6, 7, 10
- Sidebar nav — Task 11
- TypeScript types — Task 5
- Backend tests — Task 4

**Placeholder scan:** No TBDs, TODOs, or vague steps found.

**Type consistency:**
- `SystemUsage`, `CpuInfo`, `RamInfo`, `DiskMount`, `GpuInfo`, `ContainerStat`, `OllamaModel` — defined in Task 5, used consistently in Tasks 6–10.
- `systemApi.getUsage()` — defined in Task 5, used in Task 10.
- `SystemKpiBar`, `HostSection`, `DockerSection`, `OllamaSection` — defined in Tasks 6–9, imported in Task 10.
