import asyncio
from datetime import datetime, timezone

import docker
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/monitoring", tags=["Monitoring"])

client = docker.from_env()


def cpu(stats):
    cpu = stats.get("cpu_stats", {})
    precpu = stats.get("precpu_stats", {})

    current = cpu.get("cpu_usage", {}).get("total_usage", 0)
    previous = precpu.get("cpu_usage", {}).get("total_usage", 0)

    system = cpu.get("system_cpu_usage", 0)
    previous_system = precpu.get("system_cpu_usage", 0)

    cpu_delta = current - previous
    system_delta = system - previous_system

    if cpu_delta <= 0 or system_delta <= 0:
        return 0.0

    online_cpus = cpu.get("online_cpus") or len(
        cpu.get("cpu_usage", {}).get("percpu_usage", []) or [1]
    )

    return round((cpu_delta / system_delta) * online_cpus * 100, 2)


def collect_container(container):
    attrs = container.attrs
    state = attrs.get("State", {})
    config = attrs.get("Config", {})
    name = container.name

    result = {
        "id": container.id,
        "name": name,
        "image": config.get("Image", "unknown"),
        "status": state.get("Status", "unknown"),
        "health": state.get("Health", {}).get("Status", "unknown"),
        "restart_count": attrs.get("RestartCount", 0),
        "exit_code": state.get("ExitCode", 0),
        "started_at": state.get("StartedAt"),
        "cpu_percent": 0,
        "memory_usage": 0,
        "memory_limit": 0,
        "memory_percent": 0,
        "network_rx": 0,
        "network_tx": 0,
        "block_read": 0,
        "block_write": 0,
        "pids": 0,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }

    if result["status"] != "running":
        return result

    try:
        stats = container.stats(stream=False)

        memory = stats.get("memory_stats", {})
        memory_usage = memory.get("usage", 0)
        cache = memory.get("stats", {}).get("inactive_file", 0)

        # Linux cgroup v1 compatibility
        if not cache:
            cache = memory.get("stats", {}).get("cache", 0)

        used = max(0, memory_usage - cache)
        limit = memory.get("limit", 0)

        result["cpu_percent"] = calculate_cpu(stats)
        result["memory_usage"] = used
        result["memory_limit"] = limit
        result["memory_percent"] = round((used / limit) * 100, 2) if limit else 0

        networks = stats.get("networks", {}).values()

        result["network_rx"] = sum(n.get("rx_bytes", 0) for n in networks)
        result["network_tx"] = sum(n.get("tx_bytes", 0) for n in networks)

        blkio = stats.get("blkio_stats", {}).get("io_service_bytes_recursive") or []

        result["block_read"] = sum(
            item.get("value", 0)
            for item in blkio
            if item.get("op", "").lower() == "read"
        )

        result["block_write"] = sum(
            item.get("value", 0)
            for item in blkio
            if item.get("op", "").lower() == "write"
        )

        result["pids"] = stats.get("pids_stats", {}).get("current", 0) or 0

    except Exception as exc:
        result["metrics_error"] = str(exc)

    return result


def get_containers():
    try:
        return client.containers.list(all=True)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Docker unavailable: {exc}",
        )


@router.get("/containers")
async def container_metrics():
    containers = get_containers()

    # Docker SDK calls are blocking; don't block FastAPI's event loop.
    results = await asyncio.gather(
        *[asyncio.to_thread(collect_container, container) for container in containers]
    )

    return {
        "containers": results,
        "total": len(results),
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/summary")
async def monitoring_summary():
    containers = get_containers()

    results = await asyncio.gather(
        *[asyncio.to_thread(collect_container, container) for container in containers]
    )

    running = [c for c in results if c["status"] == "running"]

    return {
        "total": len(results),
        "running": len(running),
        "stopped": len(results) - len(running),
        "unhealthy": sum(c["health"] == "unhealthy" for c in results),
        "cpu_percent": round(sum(c["cpu_percent"] for c in running), 2),
        "memory_usage": sum(c["memory_usage"] for c in running),
        "memory_limit": sum(c["memory_limit"] for c in running),
        "restart_count": sum(c["restart_count"] for c in results),
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
