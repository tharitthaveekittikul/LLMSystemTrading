"""Tests for GET /api/v1/system/usage."""
from unittest.mock import AsyncMock, patch

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
