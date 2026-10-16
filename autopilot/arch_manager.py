#!/usr/bin/env python3
"""
架构管理器 (Architecture Manager)
- 查看架构状态
- 验证模块完整性
- 注册新模块
- 升级检查
- 版本回滚

架构是活的：系统自己可以升级它。
"""

import json
import os
import sys
import shutil
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recorder import record

ARCH_FILE = os.path.expanduser("~/workspace/autopilot/architecture.json")
ARCH_BACKUP_DIR = os.path.expanduser("~/workspace/autopilot/arch_backups")
MODULE_DIR = os.path.expanduser("~/workspace/autopilot")


def load_arch():
    with open(ARCH_FILE) as f:
        return json.load(f)


def save_arch(arch, backup=True):
    """保存架构，自动备份旧版"""
    if backup and os.path.exists(ARCH_FILE):
        os.makedirs(ARCH_BACKUP_DIR, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        shutil.copy(ARCH_FILE,
                    f"{ARCH_BACKUP_DIR}/architecture_{ts}.json")
        # 只留最近5个备份
        backups = sorted(os.listdir(ARCH_BACKUP_DIR))
        for old in backups[:-5]:
            os.remove(f"{ARCH_BACKUP_DIR}/{old}")

    # 版本+1
    v = arch["architecture"]["version"]
    major, minor = map(int, v.split("."))
    arch["architecture"]["version"] = f"{major}.{minor + 1}"
    arch["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    with open(ARCH_FILE, "w") as f:
        json.dump(arch, f, ensure_ascii=False, indent=2)
    record("arch_manager", "action",
           f"架构升级到 v{arch['architecture']['version']}")
    return arch["architecture"]["version"]


def status():
    """架构状态总览"""
    arch = load_arch()
    print(f"\n🏗️  架构 v{arch['architecture']['version']} "
          f"({arch['updated']})")
    print(f"\n机器: {arch['machine']['hostname']} "
          f"({arch['hardware']['cpu']}, "
          f"{arch['hardware']['memory']}内存)")

    print("\n智能层模块:")
    for name, m in arch["intelligence_layer"]["modules"].items():
        icon = {"running": "🟢", "ready": "🟡",
                "standby": "⚪", "degraded": "🟠"}.get(
                    m["status"], "❓")
        print(f"  {icon} {name:12} [{m['status']:8}] {m['desc']}")

    print("\n应用:")
    for app in arch["applications"]["desktop"]:
        print(f"  📦 {app['name']} ({app['category']})")

    if arch["gaps"]:
        print("\n缺口:")
        for g in arch["gaps"]:
            print(f"  ⚠️  {g['item']}: {g['plan']}")


def validate():
    """验证：所有 running 的模块文件存在且可导入"""
    arch = load_arch()
    ok, fail = [], []
    for name, m in arch["intelligence_layer"]["modules"].items():
        if m["status"] in ("running", "ready"):
            path = f"{MODULE_DIR}/{name}.py"
            if os.path.exists(path):
                # 试导入
                try:
                    __import__(name)
                    ok.append(name)
                except Exception as e:
                    fail.append(f"{name}: 导入失败 {e}")
            else:
                fail.append(f"{name}: 文件缺失")
    print(f"\n验证: {len(ok)} 通过, {len(fail)} 失败")
    for f in fail:
        print(f"  ❌ {f}")
        record("arch_manager", "error", f"架构验证失败: {f}",
               level="error")
    if not fail:
        print("  ✅ 架构完整")
    return len(fail) == 0


def register(module_name, desc, depends=None, status="ready"):
    """注册新模块到架构"""
    arch = load_arch()
    path = f"{MODULE_DIR}/{module_name}.py"
    if not os.path.exists(path):
        print(f"❌ 模块文件不存在: {path}")
        return False

    arch["intelligence_layer"]["modules"][module_name] = {
        "desc": desc,
        "status": status,
        "depends": depends or [],
    }
    v = save_arch(arch)
    print(f"✅ 已注册 {module_name} (架构 v{v})")
    record("arch_manager", "action", f"注册新模块: {module_name}")
    return True


def upgrade_check():
    """检查可升级项"""
    arch = load_arch()
    print("\n🔍 升级检查:")
    upgrades = []

    # 1. degraded 模块
    for name, m in arch["intelligence_layer"]["modules"].items():
        if m["status"] == "degraded":
            upgrades.append(f"{name}: {m['desc']} 需要修复")
        if m["status"] == "standby":
            upgrades.append(f"{name}: {m['desc']} 可启动")

    # 2. 缺口
    for g in arch["gaps"]:
        upgrades.append(f"缺口: {g['item']} → {g['plan']}")

    # 3. evolved/ 有新模块未注册
    evolved_dir = os.path.expanduser("~/workspace/autopilot/evolved")
    if os.path.exists(evolved_dir):
        for f in os.listdir(evolved_dir):
            if f.startswith("handler_") and f.endswith(".py"):
                mod = f[:-3]
                if mod not in arch["intelligence_layer"]["modules"]:
                    upgrades.append(f"新进化模块未注册: {mod}")

    for u in upgrades:
        print(f"  📌 {u}")
    if not upgrades:
        print("  ✅ 无待升级项")
    return upgrades


def rollback():
    """回滚到上一版架构"""
    backups = sorted(os.listdir(ARCH_BACKUP_DIR)) \
        if os.path.exists(ARCH_BACKUP_DIR) else []
    if not backups:
        print("❌ 无备份可回滚")
        return False
    latest = backups[-1]
    shutil.copy(f"{ARCH_BACKUP_DIR}/{latest}", ARCH_FILE)
    print(f"✅ 已回滚到 {latest}")
    record("arch_manager", "action", f"架构回滚到 {latest}",
           level="warning")
    return True


def close_gap(gap_item):
    """标记缺口已解决"""
    arch = load_arch()
    arch["gaps"] = [g for g in arch["gaps"]
                    if g["item"] != gap_item]
    v = save_arch(arch)
    print(f"✅ 缺口已关闭: {gap_item} (架构 v{v})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        status()
    elif sys.argv[1] == "--validate":
        validate()
    elif sys.argv[1] == "--upgrade":
        upgrade_check()
    elif sys.argv[1] == "--rollback":
        rollback()
    elif sys.argv[1] == "--register" and len(sys.argv) >= 4:
        register(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "--close-gap" and len(sys.argv) >= 3:
        close_gap(sys.argv[2])
    else:
        print("用法:")
        print("  arch_manager.py              # 状态")
        print("  arch_manager.py --validate   # 验证")
        print("  arch_manager.py --upgrade    # 升级检查")
        print("  arch_manager.py --rollback   # 回滚")
        print("  arch_manager.py --register <模块> <描述>")
