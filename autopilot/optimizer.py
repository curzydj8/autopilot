#!/usr/bin/env python3
"""
优化器模块 (Optimizer)
定期优化：机器 + 模块 + 应用 + 后台状态
保持系统一直在最佳状态

优化项：
1. 日志轮转：supervisor/emergency 日志过大时压缩归档
2. 内存整理：清文件缓存
3. 磁盘清理：/tmp、apt缓存
4. 僵尸进程：清理 defunct
5. 模块自检：坏模块自动回滚
6. 后台状态：确保关键进程都在
"""

import os
import sys
import subprocess
import time
import gzip
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recorder import record
from memory import remember

LOG_DIR = os.path.expanduser("~/workspace/autopilot/logs")
MAX_LOG_MB = 10


def _run(cmd, timeout=30):
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, timeout=timeout,
            stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def optimize_logs():
    """日志轮转：超过10M就压缩归档"""
    rotated = []
    if not os.path.exists(LOG_DIR):
        return rotated
    for f in os.listdir(LOG_DIR):
        path = f"{LOG_DIR}/{f}"
        if not os.path.isfile(path) or not f.endswith(".log"):
            continue
        size_mb = os.path.getsize(path) / 1024 / 1024
        if size_mb > MAX_LOG_MB:
            ts = time.strftime("%Y%m%d_%H%M%S")
            gz_path = f"{path}.{ts}.gz"
            with open(path, "rb") as fin, \
                 gzip.open(gz_path, "wb") as fout:
                shutil.copyfileobj(fin, fout)
            open(path, "w").close()  # 清空
            rotated.append(f"{f} ({size_mb:.1f}M→压缩)")
            record("optimizer", "action", f"日志轮转: {f}")
    # 删30天前的压缩包
    for f in os.listdir(LOG_DIR):
        if f.endswith(".gz"):
            path = f"{LOG_DIR}/{f}"
            if time.time() - os.path.getmtime(path) > 30 * 86400:
                os.remove(path)
                rotated.append(f"删除旧压缩: {f}")
    return rotated


def optimize_memory():
    """清文件缓存（安全，不杀进程）"""
    before = _run("free | awk 'NR==2{print $7}'")
    _run("sudo sh -c 'echo 1 > /proc/sys/vm/drop_caches' 2>/dev/null")
    after = _run("free | awk 'NR==2{print $7}'")
    try:
        freed_kb = int(after or 0) - int(before or 0)
        if freed_kb > 10240:  # >10M 才记录
            record("optimizer", "action",
                   f"清缓存释放 {freed_kb//1024}M")
            return freed_kb // 1024
    except Exception:
        pass
    return 0


def optimize_disk():
    """轻量磁盘清理"""
    _run("sudo apt-get clean 2>/dev/null")
    _run("find /tmp -type f -atime +1 -delete 2>/dev/null")
    return True


def kill_zombies():
    """找僵尸进程并记录（init会收尸，只记录）"""
    zombies = _run("ps aux | awk '$8~/Z/{print $2, $11}' | head -5")
    if zombies:
        record("optimizer", "check", f"僵尸进程:\n{zombies}",
               level="warning")
        return zombies
    return None


def check_background():
    """后台关键进程状态"""
    critical = {
        "supervisor.py": "总控",
        "emergency.py": "紧急",
    }
    status = {}
    for proc, desc in critical.items():
        alive = bool(_run(f"pgrep -f '{proc}' | head -1"))
        status[proc] = alive
        if not alive:
            record("optimizer", "error",
                   f"后台 {desc}({proc}) 不在运行！", level="error")
    return status


def optimize_all():
    """一轮完整优化"""
    report = {"time": time.strftime("%Y-%m-%d %H:%M:%S")}
    report["logs"] = optimize_logs()
    report["mem_freed_mb"] = optimize_memory()
    report["disk"] = optimize_disk()
    report["zombies"] = kill_zombies()
    report["background"] = check_background()

    # 记到记忆
    if any([report["logs"], report["mem_freed_mb"] > 0,
            not all(report["background"].values())]):
        remember("episodic",
                 f"optimize-{int(time.time())}",
                 f"优化: 日志{len(report['logs'])}个, "
                 f"内存{report['mem_freed_mb']}M, "
                 f"后台{report['background']}",
                 importance=0.4, tags=["optimize"])

    record("optimizer", "action", f"优化完成: {report}")
    return report


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "--bg":
        r = optimize_all()
        print(f"后台: {r['background']}")
        print(f"日志轮转: {r['logs'] or '无'}")
        print(f"内存释放: {r['mem_freed_mb']}M")
    else:
        print("优化器")
        print("  --bg  后台优化一轮")
