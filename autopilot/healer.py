#!/usr/bin/env python3
"""
自愈模块 (Self-Healer)
检测常见问题 → 自动修复 → 记录结果到技能库

修复策略 (按严重程度):
1. 磁盘空间不足 → 清理 /tmp、apt缓存、旧日志
2. Waydroid 未运行 → 尝试启动
3. 内存过高 → 找吃内存大户并记录 (不自动杀)
4. 网络不通 → 记录 (等恢复，不瞎折腾)
5. 任务执行器卡死 → 重启
"""

import subprocess
import time
import os
import json

SKILL_FILE = os.path.expanduser("~/workspace/autopilot/skills/heal_log.json")


def _run(cmd, timeout=30):
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, timeout=timeout,
            stderr=subprocess.DEVNULL).strip()
    except Exception as e:
        return f"ERROR: {e}"


def log_heal(issue, action, result):
    """记录修复历史 → 技能库"""
    os.makedirs(os.path.dirname(SKILL_FILE), exist_ok=True)
    entry = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "issue": issue,
        "action": action,
        "result": result,
    }
    history = []
    if os.path.exists(SKILL_FILE):
        try:
            with open(SKILL_FILE) as f:
                history = json.load(f)
        except Exception:
            pass
    history.append(entry)
    # 只保留最近200条
    with open(SKILL_FILE, "w") as f:
        json.dump(history[-200:], f, ensure_ascii=False, indent=2)
    return entry


def heal_disk(threshold=90):
    """磁盘使用超阈值 → 清理"""
    import shutil
    _, used, _ = shutil.disk_usage("/")
    import os as _os
    pct = 100 * used / _os.statvfs("/").f_blocks / 512 * 512  # 简化
    # 直接用 df
    out = _run("df / | tail -1 | awk '{print $5}' | tr -d '%'")
    try:
        pct = int(out)
    except Exception:
        return None
    if pct < threshold:
        return None

    actions = []
    # 清 apt 缓存
    _run("sudo apt-get clean 2>/dev/null")
    actions.append("apt clean")
    # 清 /tmp 旧文件 (7天前)
    _run("find /tmp -type f -atime +7 -delete 2>/dev/null")
    actions.append("/tmp 旧文件")
    # 清旧日志
    _run("journalctl --vacuum-time=3d 2>/dev/null")
    actions.append("journal 旧日志")

    out2 = _run("df / | tail -1 | awk '{print $5}' | tr -d '%'")
    result = f"磁盘 {pct}% → {out2}%"
    log_heal(f"磁盘使用率 {pct}%", "; ".join(actions), result)
    return result


def heal_waydroid():
    """Waydroid 没跑 → 启动"""
    status = _run("waydroid status 2>/dev/null", timeout=15)
    if "RUNNING" in status:
        return None
    if "STOPPED" not in status:
        return None  # 未初始化，不管
    _run("nohup waydroid show-full-ui > /tmp/waydroid-ui.log 2>&1 &")
    time.sleep(5)
    status2 = _run("waydroid status 2>/dev/null", timeout=15)
    result = "启动成功" if "RUNNING" in status2 else "启动失败"
    log_heal("Waydroid 未运行", "waydroid show-full-ui", result)
    return result


def heal_stuck_task_runner(max_minutes=120):
    """任务执行器卡死太久 → 记录 (不自动杀，让 supervisor 决定)"""
    out = _run("pgrep -f 'task_runner.py' | head -1")
    if not out:
        return None
    # 查运行时长
    etime = _run(f"ps -o etime= -p {out}")
    # 解析 etime (可能是 MM:SS, HH:MM:SS, D-HH:MM:SS)
    # 简化：超过阈值就告警
    log_heal(f"task_runner 运行中 (PID {out}, 已运行 {etime.strip()})",
             "观察中", "待 supervisor 决策")
    return f"task_runner 运行中 {etime.strip()}"


def check_memory_warnings(threshold=90):
    """内存告警 (只记录不自动杀)"""
    out = _run("free | awk 'NR==2{printf \"%.0f\", $3/$2*100}'")
    try:
        pct = int(out)
    except Exception:
        return None
    if pct < threshold:
        return None
    # 找 top 3 吃内存进程
    top = _run("ps aux --sort=-%mem | head -4 | tail -3 | "
               "awk '{print $11\" \"$4\"%\"}'")
    log_heal(f"内存使用率 {pct}%", "观察", f"Top: {top}")
    return f"内存 {pct}%, top: {top}"


def run_all_heals(status=None):
    """跑一轮自愈，返回修复报告"""
    report = []
    r = heal_disk()
    if r:
        report.append(f"💾 {r}")
    r = heal_waydroid()
    if r:
        report.append(f"📱 Waydroid: {r}")
    r = check_memory_warnings()
    if r:
        report.append(f"🧠 {r}")
    return report


if __name__ == "__main__":
    print("自愈检查...")
    for line in run_all_heals():
        print(f"  {line}")
    if not run_all_heals():
        print("  一切正常，无需修复")
