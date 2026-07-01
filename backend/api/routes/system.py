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


def _fetch_one_container_stat(c) -> ContainerStat:  # type: ignore[no-untyped-def]
    """Fetch stats for a single container (runs in its own thread)."""
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
    return ContainerStat(
        name=c.name,
        status=c.status,
        cpu_percent=cpu_pct,
        memory_used_bytes=mem_used,
        memory_limit_bytes=mem_limit,
    )


def _get_docker_stats() -> list[ContainerStat] | None:
    try:
        from concurrent.futures import ThreadPoolExecutor

        import docker  # optional — graceful skip if Docker unreachable
        client = docker.from_env(timeout=3)
        containers = client.containers.list(all=True)
        if not containers:
            return []
        # Fetch all container stats in parallel — each stats(stream=False) blocks ~1s
        with ThreadPoolExecutor(max_workers=len(containers)) as pool:
            return list(pool.map(_fetch_one_container_stat, containers))
    except Exception:
        return None


# ── Async helper ───────────────────────────────────────────────────────────────

async def _get_ollama_models() -> list[OllamaModel] | None:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=1.0, read=3.0, write=3.0, pool=3.0)) as client:
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

@router.get("/usage", response_model=SystemUsage)
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
