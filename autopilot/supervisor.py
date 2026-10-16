#!/usr/bin/env python3
"""
总控模块 (Supervisor) —— 自主运维大脑
主循环: 监控 → 分析 → 自愈 → 学习 → 上报

运行: nohup python3 supervisor.py > logs/supervisor.log 2>&1 &
停止: pkill -f supervisor.py
"""

import time
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monitor import get_full_status
from healer import run_all_heals
from learner import find_skill, record_result
from recorder import record
from local_net import guard_cycle
from scenarios import run_all_scenarios
from evolve import auto_evolve_check

LOG_DIR = os.path.expanduser("~/workspace/autopilot/logs")
STATE_FILE = os.path.expanduser("~/workspace/autopilot/state.json")
CHECK_INTERVAL = 300  # 5分钟一轮


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(f"{LOG_DIR}/supervisor.log", "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


def save_state(status, heals):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_check": status["timestamp"],
                   "status": status, "heals": heals},
                  f, ensure_ascii=False, indent=2)


def analyze(status):
    """分析状态，返回问题列表"""
    issues = []
    if status["disk_pct"] > 90:
        issues.append(f"disk usage > 90% (当前 {status['disk_pct']}%)")
    if status["mem_pct"] > 92:
        issues.append(f"内存 > 92% (当前 {status['mem_pct']}%)")
    if not status["network"]:
        issues.append("网络不通")
    if status["waydroid"] == "stopped":
        issues.append("waydroid status STOPPED")
    if status["temp_c"] > 85:
        issues.append(f"CPU温度过高 {status['temp_c']}°C")
    return issues


def main():
    log("=" * 50)
    log("Supervisor 启动 —— 自主运维开始")
    log(f"检查间隔: {CHECK_INTERVAL}秒")
    log("=" * 50)

    consecutive_errors = 0
    while True:
        try:
            # 1. 监控
            status = get_full_status()
            log(f"状态 CPU:{status['cpu_pct']}% MEM:{status['mem_pct']}% "
                f"硬盘:{status['disk_pct']}% Waydroid:{status['waydroid']} "
                f"任务:{status['tasks']['done']}/{status['tasks']['total']}")

            # 2. 分析
            issues = analyze(status)

            # 3. 自愈 (先查技能库，再执行)
            heals = []
            for issue in issues:
                skill = find_skill(issue)
                if skill:
                    log(f"  技能库命中: {skill['pattern']} → {skill['solution']}")
                heals.extend(run_all_heals())

            for h in heals:
                log(f"  自愈: {h}")

            # 3.5 本地网络守护 (保命，优先级最高)
            try:
                net_result = guard_cycle()
                if net_result != "ok":
                    log(f"  网络守护: {net_result}")
                    record("supervisor", "action",
                           f"网络守护触发: {net_result}", level="warning")
            except Exception as e:
                log(f"  网络守护异常: {e}")

            # 3.6 复杂场景检查 (每3轮跑一次，省资源)
            if not hasattr(main, "_cycle"):
                main._cycle = 0
            main._cycle += 1
            if main._cycle % 3 == 0:
                try:
                    sc = run_all_scenarios()
                    for k, v in sc.items():
                        if v not in ("ok", "all_alive", "downloading",
                                     "not_running"):
                            log(f"  场景[{k}]: {v}")
                except Exception as e:
                    log(f"  场景检查异常: {e}")

            # 3.7 自我进化 (每6轮跑一次：扫描未解决问题，自己写程序)
            if main._cycle % 6 == 0:
                try:
                    n = auto_evolve_check()
                    if n > 0:
                        log(f"  🧬 本轮进化出 {n} 个新处理程序")
                        record("supervisor", "evolve",
                               f"进化出 {n} 个新程序", level="warning")
                except Exception as e:
                    log(f"  进化异常: {e}")

            # 4. 存状态
            save_state(status, heals)
            consecutive_errors = 0

        except Exception as e:
            consecutive_errors += 1
            log(f"  !! 异常: {e} (连续 {consecutive_errors} 次)")
            if consecutive_errors > 5:
                log("  连续异常太多，暂停1小时")
                time.sleep(3600)
                consecutive_errors = 0

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
