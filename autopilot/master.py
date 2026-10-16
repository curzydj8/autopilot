#!/usr/bin/env python3
"""
主控模块 (Master Control)
整个自主 AI 系统的唯一入口和控制中心

功能：
- 一键启动/停止/重启所有模块
- 实时状态总览
- 模块级精细控制
- 系统级命令

用法:
  master.py start          # 启动全部
  master.py stop           # 停止全部
  master.py restart        # 重启全部
  master.py status         # 状态总览
  master.py start <模块>   # 启动单个
  master.py stop <模块>    # 停止单个
  master.py logs [模块]    # 看日志
"""

import os
import sys
import subprocess
import time
import signal
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from procutil import find_script_pids, pid_matches_script

MODULE_DIR = os.path.expanduser("~/workspace/autopilot")
LOG_DIR = f"{MODULE_DIR}/logs"
PID_DIR = f"{MODULE_DIR}/pids"

# 模块定义：name → {cmd, desc, daemon}
MODULES = {
    "supervisor": {
        "cmd": "python3 supervisor.py",
        "desc": "总控 (5分钟循环)",
        "daemon": True,
    },
    "emergency": {
        "cmd": "python3 emergency.py",
        "desc": "紧急处理 (30秒)",
        "daemon": True,
    },
    "brain": {
        "cmd": "python3 brain.py",
        "desc": "认知主循环",
        "daemon": True,
    },
}

# systemd 服务名映射（存在则优先用 systemctl 管理）
SYSTEMD_UNITS = {
    "supervisor": "autopilot-supervisor",
    "emergency": "autopilot-emergency",
}


def _script_of(name):
    """模块对应的脚本文件名，如 supervisor.py"""
    return MODULES[name]["cmd"].split()[-1]


def _has_unit(name):
    """该模块是否有 systemd 单元（只在装了服务的那台机器上为真）"""
    unit = SYSTEMD_UNITS.get(name)
    if not unit:
        return False
    return os.path.exists(f"/etc/systemd/system/{unit}.service")


def _systemctl(action, name):
    """经 sudo 调 systemctl；返回是否成功"""
    unit = SYSTEMD_UNITS[name]
    try:
        r = subprocess.run(
            ["sudo", "systemctl", action, unit],
            capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def _run(cmd, timeout=15):
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, timeout=timeout,
            stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def get_pid(name):
    """取模块 PID（精确版）。

    1. PID 文件存在 → 校验 /proc/<pid>/cmdline 真的是该模块
       （防 PID 复用：老 PID 被别的进程占用时不再误报）。
    2. 否则直接扫描 /proc，不经过 shell（杜绝 pgrep -f 把
       执行它的 shell 自身匹配上的误报）。
    """
    script = _script_of(name)
    pid_file = f"{PID_DIR}/{name}.pid"
    if os.path.exists(pid_file):
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip())
            if pid_matches_script(pid, script):
                return pid
        except Exception:
            pass
    pids = find_script_pids(script)
    if pids:
        save_pid(name, pids[0])
        return pids[0]
    return None


def save_pid(name, pid):
    os.makedirs(PID_DIR, exist_ok=True)
    with open(f"{PID_DIR}/{name}.pid", "w") as f:
        f.write(str(pid))


def start_module(name):
    """启动单个模块（有 systemd 单元时走 systemctl）"""
    if name not in MODULES:
        print(f"❌ 未知模块: {name}")
        return False
    if get_pid(name):
        print(f"  {name} 已在运行")
        return True

    if _has_unit(name):
        if _systemctl("start", name):
            time.sleep(3)
            pid = get_pid(name)
            if pid:
                print(f"  ✅ {name} 已启动 (systemd, PID {pid})")
                return True
        print(f"  ❌ {name} 启动失败 (systemctl)")
        return False

    mod = MODULES[name]
    log_file = f"{LOG_DIR}/{name}.log"
    os.makedirs(LOG_DIR, exist_ok=True)

    proc = subprocess.Popen(
        mod["cmd"].split(),
        cwd=MODULE_DIR,
        stdout=open(log_file, "a"),
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # 脱离终端
    )
    save_pid(name, proc.pid)
    time.sleep(2)

    if get_pid(name):
        print(f"  ✅ {name} 已启动 (PID {proc.pid})")
        return True
    else:
        print(f"  ❌ {name} 启动失败，看 {log_file}")
        return False


def _kill_pid(pid):
    """SIGTERM → 等 → SIGKILL → 还不死则 sudo kill -9（本机有免密 sudo）"""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except Exception:
        return False
    time.sleep(2)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        pass
    time.sleep(1)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    # 最后手段：免密 sudo（曾遇到普通 kill 杀不掉、sudo kill -9 才死的 case）
    try:
        subprocess.run(["sudo", "kill", "-9", str(pid)],
                       capture_output=True, timeout=10)
    except Exception:
        pass
    time.sleep(1)
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True


def stop_module(name):
    """停止单个模块（有 systemd 单元时走 systemctl，避免被 Restart 拉起）"""
    if _has_unit(name):
        _systemctl("stop", name)
        # 迁移兜底：单元接管前可能有 nohup 遗留进程，systemctl 管不到，一并杀掉
        leftover = get_pid(name)
        if leftover:
            _kill_pid(leftover)
        pid_file = f"{PID_DIR}/{name}.pid"
        if os.path.exists(pid_file):
            os.remove(pid_file)
        alive = get_pid(name)
        print(f"  {'✅' if not alive else '❌'} {name} 已停止 (systemd)"
              f"{'' if not alive else '，仍有残留进程!'}")
        return not alive

    pid = get_pid(name)
    if not pid:
        print(f"  {name} 未运行")
        return True
    if _kill_pid(pid):
        pid_file = f"{PID_DIR}/{name}.pid"
        if os.path.exists(pid_file):
            os.remove(pid_file)
        print(f"  ✅ {name} 已停止")
        return True
    print(f"  ❌ 停止 {name} 失败")
    return False


def start_all():
    print("🚀 启动自主 AI 系统...")
    for name in MODULES:
        start_module(name)
    print("\n用 'master.py status' 看状态")


def stop_all():
    print("🛑 停止自主 AI 系统...")
    for name in MODULES:
        stop_module(name)


def status():
    """状态总览"""
    print("\n🎛️  自主 AI 系统状态")
    print("=" * 45)

    # 守护进程
    print("\n守护进程:")
    for name, mod in MODULES.items():
        pid = get_pid(name)
        icon = "🟢" if pid else "⚪"
        via = " [systemd]" if _has_unit(name) else ""
        print(f"  {icon} {name:12} {mod['desc']:20} "
              f"{'PID '+str(pid) if pid else '未运行'}{via}")

    # 系统资源
    try:
        cpu_line = _run("top -bn1 | grep '%Cpu' | head -1")
        mem = _run("free | awk 'NR==2{printf \"%d%%\", $3/$2*100}'")
        disk = _run("df / | tail -1 | awk '{print $5}'")
        print(f"\n资源: CPU {cpu_line[:30] if cpu_line else '?'} "
              f"| 内存 {mem} | 硬盘 {disk}")
    except Exception:
        pass

    # 架构版本
    try:
        with open(f"{MODULE_DIR}/architecture.json") as f:
            arch = json.load(f)
        v = arch["architecture"]["version"]
        n_mod = len(arch["intelligence_layer"]["modules"])
        print(f"架构: v{v} ({n_mod}模块)")
    except Exception:
        pass

    # 记忆
    try:
        sys.path.insert(0, MODULE_DIR)
        from memory import stats as mem_stats
        s = mem_stats()
        print(f"记忆: {s['total']} 条 {s['by_type']}")
    except Exception:
        pass
    print()


def logs(module=None, lines=20):
    """看日志"""
    if module:
        path = f"{LOG_DIR}/{module}.log"
        if os.path.exists(path):
            print(f"--- {module} (末{lines}行) ---")
            print(_run(f"tail -{lines} {path}"))
        else:
            print(f"无日志: {module}")
    else:
        for name in MODULES:
            path = f"{LOG_DIR}/{name}.log"
            if os.path.exists(path):
                print(f"\n--- {name} ---")
                print(_run(f"tail -5 {path}"))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        status()
    elif sys.argv[1] == "start":
        if len(sys.argv) > 2:
            start_module(sys.argv[2])
        else:
            start_all()
    elif sys.argv[1] == "stop":
        if len(sys.argv) > 2:
            stop_module(sys.argv[2])
        else:
            stop_all()
    elif sys.argv[1] == "restart":
        stop_all()
        time.sleep(2)
        start_all()
    elif sys.argv[1] == "status":
        status()
    elif sys.argv[1] == "logs":
        mod = sys.argv[2] if len(sys.argv) > 2 else None
        logs(mod)
    else:
        print(__doc__)
