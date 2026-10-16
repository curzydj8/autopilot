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


def _run(cmd, timeout=15):
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, timeout=timeout,
            stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def get_pid(name):
    """取模块 PID"""
    pid_file = f"{PID_DIR}/{name}.pid"
    if os.path.exists(pid_file):
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip())
            # 验证进程还在
            os.kill(pid, 0)
            return pid
        except Exception:
            pass
    # 备选：pgrep
    out = _run(f"pgrep -f '{MODULES[name]['cmd']}' | head -1")
    return int(out) if out.isdigit() else None


def save_pid(name, pid):
    os.makedirs(PID_DIR, exist_ok=True)
    with open(f"{PID_DIR}/{name}.pid", "w") as f:
        f.write(str(pid))


def start_module(name):
    """启动单个模块"""
    if name not in MODULES:
        print(f"❌ 未知模块: {name}")
        return False
    if get_pid(name):
        print(f"  {name} 已在运行")
        return True

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


def stop_module(name):
    """停止单个模块"""
    pid = get_pid(name)
    if not pid:
        print(f"  {name} 未运行")
        return True
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(2)
        # 还在就 SIGKILL
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        pid_file = f"{PID_DIR}/{name}.pid"
        if os.path.exists(pid_file):
            os.remove(pid_file)
        print(f"  ✅ {name} 已停止")
        return True
    except Exception as e:
        print(f"  ❌ 停止 {name} 失败: {e}")
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
        print(f"  {icon} {name:12} {mod['desc']:20} "
              f"{'PID '+str(pid) if pid else '未运行'}")

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
