"""系统状态信息（CPU / 内存 / 磁盘 / uptime / 网络累计量）。

使用 psutil。注意：
  - 不暴露 MAC 地址等不必要信息
  - 各字段同时给出机器可读单位（bytes / percent / seconds）
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import psutil

_BOOT_TIME = psutil.boot_time()


def get_system_info() -> Dict[str, Any]:
    """返回 PC 总体状态。"""
    # 磁盘：只统计固定磁盘（去重），排除只读/移动设备避免误报消耗
    disk_partitions: List[Dict[str, Any]] = []
    seen_devices: set = set()
    for part in psutil.disk_partitions(all=False):
        dev = part.device
        if dev in seen_devices:
            continue
        seen_devices.add(dev)
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disk_partitions.append(
                {
                    "mountpoint": part.mountpoint,
                    "total_bytes": usage.total,
                    "used_bytes": usage.used,
                    "free_bytes": usage.free,
                    "percent": usage.percent,
                }
            )
        except Exception:
            continue

    total_mem = psutil.virtual_memory()
    net_io = None
    try:
        net_io = psutil.net_io_counters()
    except Exception:
        pass

    uptime_seconds = max(0, int(time.time() - _BOOT_TIME))

    cpu_count = psutil.cpu_count(logical=True) or 0
    phys_count = psutil.cpu_count(logical=False) or cpu_count
    cpu_percent = psutil.cpu_percent(interval=None)

    return {
        "cpu": {
            "total_percent": cpu_percent,
            "logical_cores": cpu_count,
            "physical_cores": phys_count,
        },
        "memory": {
            "total_bytes": total_mem.total,
            "used_bytes": total_mem.used,
            "available_bytes": total_mem.available,
            "percent": total_mem.percent,
        },
        "disks": disk_partitions,
        "uptime_seconds": uptime_seconds,
        "network": {
            "bytes_sent": net_io.bytes_sent if net_io else None,
            "bytes_recv": net_io.bytes_recv if net_io else None,
            "packets_sent": net_io.packets_sent if net_io else None,
            "packets_recv": net_io.packets_recv if net_io else None,
        },
    }


def get_top_processes(sort_by: str = "memory", limit: int = 10) -> List[Dict[str, Any]]:
    """返回资源占用最高的进程列表。

    注意：psutil 第一次 process.cpu_percent() 返回 0。
    为避免请求停顿数秒，这里采用约 0.2 秒的短采样（可选），
    或用上一次采样值。AccessDenied / ZombieProcess 安全跳过。
    """
    limit = max(1, min(int(limit), 30))
    sort_by = "memory" if sort_by == "memory" else "cpu"

    processes = []
    try:
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                pinfo = proc.info
                processes.append(pinfo)
            except Exception:
                continue
    except Exception:
        processes = []

    # cpu 采样：先对所有进程做一次 cpu_percent(interval=None) 以重置计数器
    try:
        psutil.cpu_percent(interval=None)
        for proc in processes:
            try:
                p = psutil.Process(proc.get("pid"))
                p.cpu_percent(interval=None)
            except Exception:
                pass
        # 短采样（仅当 limit>0）
        if processes:
            time.sleep(0.2)
    except Exception:
        pass

    results: List[Dict[str, Any]] = []
    for pinfo in processes:
        pid = pinfo.get("pid")
        name = pinfo.get("name") or ""
        if not pid:
            continue
        try:
            p = psutil.Process(pid)
            mem_info = p.memory_info()
            mem_bytes = getattr(mem_info, "rss", 0) or 0
            mem_percent = 0.0
            try:
                mem_percent = p.memory_percent()
            except Exception:
                pass
            cpu_percent = 0.0
            try:
                cpu_percent = p.cpu_percent(interval=None)
            except Exception:
                pass
            results.append(
                {
                    "process_name": name,
                    "pid": pid,
                    "memory_mb": round(mem_bytes / 1024 / 1024, 1),
                    "memory_percent": round(mem_percent, 2),
                    "cpu_percent": round(cpu_percent, 2),
                }
            )
        except (psutil.AccessDenied, psutil.ZombieProcess, psutil.NoSuchProcess):
            continue
        except Exception:
            continue

    if sort_by == "memory":
        results.sort(key=lambda r: r["memory_mb"], reverse=True)
    else:
        results.sort(key=lambda r: r["cpu_percent"], reverse=True)
    return results[:limit]


def get_all_cpu_memory() -> Dict[str, Any]:
    """pc_get_pc_status 的底层简洁结构（供综合工具复用）。"""
    info = get_system_info()
    return {
        "cpu_percent": info["cpu"]["total_percent"],
        "memory_percent": info["memory"]["percent"],
        "memory_used_bytes": info["memory"]["used_bytes"],
        "uptime_seconds": info["uptime_seconds"],
    }