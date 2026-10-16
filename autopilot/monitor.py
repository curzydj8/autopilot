#!/usr/bin/env python3
"""
系统监控模块 (System Monitor)
采集：CPU/内存/硬盘/温度/关键进程/网络/Waydroid/任务队列状态
输出统一的状态字典，供 healer 和 supervisor 决策
"""

import subprocess
import json
import time
import os
import shutil


def _run(cmd, timeout=10):
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, timeout=timeout,
            stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def cpu_mem():
    """CPU% / 内存"""
    try:
        # CPU: 取1秒采样
        with open("/proc/stat") as f:
            l1 = f.readline().split()
        time.sleep(0.5)
        with open("/proc/stat") as f:
            l2 = f.readline().split()
        idle1, total1 = int(l1[4]), sum(map(int, l1[1:]))
        idle2, total2 = int(l2[4]), sum(map(int, l2[1:]))
        cpu = 100 * (1 - (idle2 - idle1) / max(1, total2 - total1))
    except Exception:
        cpu = -1
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        total = int(lines[0].split()[1])
        avail = int(lines[2].split()[1])
        mem_pct = 100 * (1 - avail / total)
        mem_gb = (total - avail) / 1024 / 1024
    except Exception:
        mem_pct, mem_gb = -1, -1
    return round(cpu, 1), round(mem_pct, 1), round(mem_gb, 2)


def disk():
    """根分区使用率"""
    try:
        total, used, free = shutil.disk_usage("/")
        return round(100 * used / total, 1), round(free / 1024**3, 2)
    except Exception:
        return -1, -1


def temperature():
    """CPU温度 (如有传感器)"""
    out = _run("cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null")
    try:
        return round(int(out) / 1000, 1)
    except Exception:
        return -1


def process_alive(name):
    """关键进程是否存活"""
    out = _run(f"pgrep -f '{name}' | head -1")
    return bool(out)


def network_ok():
    """外网连通性"""
    out = _run("ping -c1 -W3 8.8.8.8 2>/dev/null | grep '1 received'")
    return bool(out)


def waydroid_status():
    """Waydroid 状态"""
    out = _run("waydroid status 2>/dev/null", timeout=15)
    if "RUNNING" in out:
        return "running"
    if "STOPPED" in out:
        return "stopped"
    return "unknown"


def task_queue_status():
    """任务队列状态"""
    path = os.path.expanduser("~/workspace/task-queue/tasks.json")
    try:
        with open(path) as f:
            data = json.load(f)
        total = sum(len(w["tasks"]) for w in data["waves"])
        done = sum(1 for w in data["waves"]
                   for t in w["tasks"] if t["status"] == "done")
        pending = sum(1 for w in data["waves"]
                      for t in w["tasks"] if t["status"] == "pending")
        return {"total": total, "done": done, "pending": pending,
                "current_wave": data.get("current_wave")}
    except Exception:
        return {"total": 0, "done": 0, "pending": 0, "current_wave": 0}


def get_full_status():
    """完整状态快照"""
    cpu, mem_pct, mem_gb = cpu_mem()
    disk_pct, disk_free_gb = disk()
    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cpu_pct": cpu,
        "mem_pct": mem_pct,
        "mem_used_gb": mem_gb,
        "disk_pct": disk_pct,
        "disk_free_gb": disk_free_gb,
        "temp_c": temperature(),
        "network": network_ok(),
        "processes": {
            "waydroid_init": process_alive("waydroid init"),
            "task_runner": process_alive("task_runner.py"),
            "supervisor": process_alive("supervisor.py"),
        },
        "waydroid": waydroid_status(),
        "tasks": task_queue_status(),
    }


if __name__ == "__main__":
    import sys
    s = get_full_status()
    if len(sys.argv) > 1 and sys.argv[1] == "--json":
        print(json.dumps(s, ensure_ascii=False, indent=2))
    else:
        print(f"[{s['timestamp']}] "
              f"CPU:{s['cpu_pct']}% MEM:{s['mem_pct']}% "
              f"硬盘:{s['disk_pct']}% Net:{'✓' if s['network'] else '✗'} "
              f"Waydroid:{s['waydroid']} "
              f"任务:{s['tasks']['done']}/{s['tasks']['total']}")
