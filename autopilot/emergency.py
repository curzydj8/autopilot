#!/usr/bin/env python3
"""
紧急处理模块 (Emergency Handler)
不走 supervisor 的5分钟循环，独立高频运行（30秒一轮）
只处理 P0 级紧急情况， fast path 直达

P0 定义（任一触发即紧急）：
- 磁盘 > 95% （再写就炸）
- 内存 > 97% （OOM killer 要杀进程了）
- v2raya 连着但代理不通 + 直连不通 （全断网）
- supervisor 死了 （总控没了）
- CPU 温度 > 95°C （硬件危险）

非 P0 交给 supervisor 正常流程。
"""

import os
import sys
import time
import subprocess
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recorder import record
from memory import remember

CHECK_INTERVAL = 30  # 30秒一轮


def _run(cmd, timeout=10):
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, timeout=timeout,
            stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def check_disk_critical():
    out = _run("df / | tail -1 | awk '{print $5}' | tr -d '%'")
    try:
        return int(out) > 95, f"磁盘 {out}%"
    except Exception:
        return False, ""


def check_mem_critical():
    out = _run("free | awk 'NR==2{printf \"%.0f\", $3/$2*100}'")
    try:
        return int(out) > 97, f"内存 {out}%"
    except Exception:
        return False, ""


def check_net_dead():
    """全断网：直连和代理都不通"""
    d = _run("timeout 5 curl -s -o /dev/null -w '%{http_code}' "
             "https://www.baidu.com", timeout=8)
    p = _run("timeout 5 curl -s -x socks5://127.0.0.1:20170 "
             "-o /dev/null -w '%{http_code}' https://www.google.com",
             timeout=8)
    dead = d != "200" and p != "200"
    return dead, f"直连:{d} 代理:{p}"


def check_supervisor_dead():
    alive = bool(_run("pgrep -f 'supervisor.py' | head -1"))
    return not alive, "supervisor 进程不存在"


def check_temp_critical():
    out = _run("cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null")
    try:
        t = int(out) / 1000
        return t > 95, f"CPU {t}°C"
    except Exception:
        return False, ""


# 紧急处理动作
def emergency_disk():
    record("emergency", "action", "P0: 磁盘>95%，紧急清理",
           level="critical")
    _run("sudo apt-get clean 2>/dev/null")
    _run("sudo journalctl --vacuum-time=1d 2>/dev/null")
    _run("find /tmp -type f -delete 2>/dev/null")
    _run("find /var/log -name '*.gz' -delete 2>/dev/null")
    remember("episodic", f"emergency-disk-{int(time.time())}",
             "P0磁盘告警，执行紧急清理", importance=0.9,
             tags=["emergency", "disk"])


def emergency_mem():
    record("emergency", "action", "P0: 内存>97%，清缓存",
           level="critical")
    _run("sudo sh -c 'echo 1 > /proc/sys/vm/drop_caches' 2>/dev/null")
    # 找最大内存进程并记录（不自动杀，等人工）
    top = _run("ps aux --sort=-%mem | head -2 | tail -1 | "
               "awk '{print $2, $4\"%\", $11}'")
    record("emergency", "check", f"最大内存进程: {top}",
           level="critical")


def emergency_net():
    record("emergency", "action", "P0: 全断网，断开v2raya",
           level="critical")
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from local_net import v2raya_disconnect
        v2raya_disconnect()
    except Exception as e:
        record("emergency", "error", f"断开v2raya失败: {e}",
               level="critical")
    remember("episodic", f"emergency-net-{int(time.time())}",
             "P0全断网，断开v2raya保命", importance=0.95,
             tags=["emergency", "network"])


def emergency_supervisor():
    record("emergency", "action", "P0: supervisor死了，重启",
           level="critical")
    _run("cd ~/workspace/autopilot && "
         "nohup python3 supervisor.py > logs/supervisor.log 2>&1 "
         "< /dev/null & disown")
    time.sleep(3)
    alive = bool(_run("pgrep -f 'supervisor.py' | head -1"))
    record("emergency", "action",
           f"supervisor重启{'成功' if alive else '失败'}",
           level="critical" if not alive else "warning")


CHECKS = [
    ("disk", check_disk_critical, emergency_disk),
    ("mem", check_mem_critical, emergency_mem),
    ("net", check_net_dead, emergency_net),
    ("supervisor", check_supervisor_dead, emergency_supervisor),
    ("temp", check_temp_critical,
     lambda: record("emergency", "action", "P0: CPU过热！",
                    level="critical")),
]


def emergency_loop():
    print("🚨 紧急处理模块启动 (30秒一轮，只处理P0)")
    record("emergency", "start", "紧急模块启动")
    while True:
        try:
            for name, check, action in CHECKS:
                is_critical, detail = check()
                if is_critical:
                    print(f"🚨 P0 [{name}]: {detail}", flush=True)
                    action()
                    # P0 处理后立即再查一轮，不等30秒
                    time.sleep(5)
        except Exception as e:
            record("emergency", "error", f"紧急循环异常: {e}",
                   level="error")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "--check":
        print("P0 检查:")
        for name, check, _ in CHECKS:
            critical, detail = check()
            icon = "🚨" if critical else "✅"
            print(f"  {icon} {name}: {detail or '正常'}")
    else:
        emergency_loop()
