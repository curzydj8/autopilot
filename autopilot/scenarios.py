#!/usr/bin/env python3
"""
复杂情况处理模块 (Scenario Handler)
处理需要多步骤、有分支逻辑的复杂场景

场景库：
1. waydroid_stuck      — Waydroid 镜像下载卡住
2. disk_full           — 磁盘满的多级清理
3. high_load           — 负载过高的诊断与处理
4. service_dead        — 关键服务死了的恢复
5. task_runner_stuck   — 任务执行器卡死的恢复
"""

import subprocess
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recorder import record
from learner import find_skill, record_result


def _run(cmd, timeout=30):
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, timeout=timeout,
            stderr=subprocess.DEVNULL).strip()
    except Exception as e:
        return f"ERROR: {e}"


# ============ 场景1: Waydroid 下载卡住 ============
def scenario_waydroid_stuck():
    """检查 waydroid init 是否卡住，尝试恢复"""
    record("scenario", "check", "检查 Waydroid 下载状态")
    proc = _run("pgrep -f 'waydroid init' | head -1")
    if not proc:
        record("scenario", "check", "waydroid init 不在运行")
        return "not_running"

    # 查下载进度
    size1 = _run("ls -l /var/lib/waydroid/cache_http/ 2>/dev/null "
                 "| awk '{s+=$5} END {print s}'")
    time.sleep(30)
    size2 = _run("ls -l /var/lib/waydroid/cache_http/ 2>/dev/null "
                 "| awk '{s+=$5} END {print s}'")
    try:
        growing = int(size2 or 0) > int(size1 or 0)
    except Exception:
        growing = False

    if growing:
        record("scenario", "check",
               f"Waydroid 下载进行中 ({size2} bytes)")
        return "downloading"

    # 卡住了 → 杀掉重来
    record("scenario", "action", "下载卡住，重启 waydroid init",
           level="warning")
    _run("sudo pkill -9 -f 'waydroid init'")
    time.sleep(3)
    _run("nohup sudo waydroid init > /tmp/waydroid-init.log 2>&1 &")
    record_result("waydroid 下载卡住", True)
    return "restarted"


# ============ 场景2: 磁盘满的多级清理 ============
def scenario_disk_full():
    """三级清理：温和 → 激进 → 告警"""
    def usage():
        out = _run("df / | tail -1 | awk '{print $5}' | tr -d '%'")
        try:
            return int(out)
        except Exception:
            return 0

    u = usage()
    record("scenario", "check", f"磁盘使用率 {u}%")
    if u < 85:
        return "ok"

    # L1 温和清理
    record("scenario", "action", "L1 温和清理", level="warning")
    _run("sudo apt-get clean 2>/dev/null")
    _run("sudo journalctl --vacuum-time=3d 2>/dev/null")
    _run("find /tmp -type f -atime +3 -delete 2>/dev/null")
    if usage() < 85:
        record("scenario", "action", "L1 清理有效")
        record_result("disk usage > 90%", True)
        return "fixed_l1"

    # L2 激进清理
    record("scenario", "action", "L2 激进清理", level="warning")
    _run("docker system prune -f 2>/dev/null")
    _run("find /var/log -name '*.gz' -delete 2>/dev/null")
    _run("find /var/log -name '*.1' -delete 2>/dev/null")
    _run("sudo apt-get autoremove -y 2>/dev/null")
    if usage() < 90:
        record("scenario", "action", "L2 清理有效")
        return "fixed_l2"

    # L3 告警
    record("scenario", "action",
           f"L3 告警：清理后仍 {usage()}%，需人工介入",
           level="critical")
    return "need_human"


# ============ 场景3: 负载过高 ============
def scenario_high_load():
    """诊断负载元凶"""
    load = _run("cat /proc/loadavg | awk '{print $1}'")
    try:
        load1 = float(load)
    except Exception:
        return "ok"
    import os as _os
    cpus = _os.cpu_count() or 1
    if load1 < cpus * 1.5:
        return "ok"

    record("scenario", "check",
           f"负载过高: {load1} (CPU数 {cpus})", level="warning")
    top = _run("ps aux --sort=-%cpu | head -6 | tail -5 | "
               "awk '{print $2, $3\"%\", $11}'")
    record("scenario", "check", f"CPU Top:\n{top}")

    # 找失控的 python 进程 (非 supervisor)
    for line in top.split("\n"):
        parts = line.split()
        if len(parts) >= 3 and "python" in parts[2]:
            try:
                cpu_pct = float(parts[1].replace("%", ""))
                pid = parts[0]
                if cpu_pct > 90 and "supervisor" not in line:
                    record("scenario", "action",
                           f"发现失控进程 PID {pid} CPU {cpu_pct}%",
                           level="warning")
            except Exception:
                pass
    return "diagnosed"


# ============ 场景4: 关键服务恢复 ============
CRITICAL_SERVICES = ["v2raya", "xrdp", "supervisor.py"]


def scenario_service_dead():
    """检查关键服务，死了就拉起来"""
    fixed = []
    for svc in CRITICAL_SERVICES:
        alive = bool(_run(f"pgrep -f '{svc}' | head -1"))
        if not alive:
            record("scenario", "action", f"{svc} 已死，尝试重启",
                   level="warning")
            if svc == "v2raya":
                _run("sudo systemctl restart v2raya")
            elif svc == "xrdp":
                _run("sudo systemctl restart xrdp")
            elif svc == "supervisor.py":
                _run("cd ~/workspace/autopilot && "
                     "nohup python3 supervisor.py "
                     "> logs/supervisor.log 2>&1 &")
            time.sleep(3)
            alive2 = bool(_run(f"pgrep -f '{svc}' | head -1"))
            if alive2:
                fixed.append(svc)
                record("scenario", "action", f"{svc} 重启成功")
                record_result(f"{svc} 服务死了", True)
            else:
                record("scenario", "action", f"{svc} 重启失败",
                       level="error")
                record_result(f"{svc} 服务死了", False)
    return fixed if fixed else "all_alive"


def run_all_scenarios():
    """跑一轮所有场景检查"""
    results = {}
    results["waydroid"] = scenario_waydroid_stuck()
    results["disk"] = scenario_disk_full()
    results["load"] = scenario_high_load()
    results["services"] = scenario_service_dead()
    return results


if __name__ == "__main__":
    print("复杂场景检查...")
    for k, v in run_all_scenarios().items():
        print(f"  {k}: {v}")
