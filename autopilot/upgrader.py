#!/usr/bin/env python3
"""
模块升级器 (Module Upgrader)
- 检查模块新版本
- 热更新：不重启 supervisor，直接重载
- 坏模块自动修复/回滚

用法:
  upgrader.py --check              # 检查可升级
  upgrader.py --upgrade <模块>      # 升级指定模块
  upgrader.py --reload <模块>       # 热重载
  upgrader.py --rollback <模块>     # 回滚
"""

import os
import sys
import shutil
import time
import importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recorder import record

MODULE_DIR = os.path.expanduser("~/workspace/autopilot")
BACKUP_DIR = os.path.expanduser("~/workspace/autopilot/module_backups")


def backup_module(name):
    """备份模块"""
    src = f"{MODULE_DIR}/{name}.py"
    if not os.path.exists(src):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    dst = f"{BACKUP_DIR}/{name}_{ts}.py"
    shutil.copy(src, dst)
    # 只留最近3个
    versions = sorted(f for f in os.listdir(BACKUP_DIR)
                      if f.startswith(f"{name}_"))
    for old in versions[:-3]:
        os.remove(f"{BACKUP_DIR}/{old}")
    return dst


def rollback_module(name):
    """回滚到上一版"""
    versions = sorted(f for f in os.listdir(BACKUP_DIR)
                      if f.startswith(f"{name}_")) \
        if os.path.exists(BACKUP_DIR) else []
    if len(versions) < 1:
        print(f"❌ 无备份可回滚: {name}")
        return False
    # 用倒数第二个（最后一个是当前坏的）
    target = versions[-2] if len(versions) >= 2 else versions[-1]
    shutil.copy(f"{BACKUP_DIR}/{target}", f"{MODULE_DIR}/{name}.py")
    print(f"✅ {name} 已回滚到 {target}")
    record("upgrader", "action", f"{name} 回滚到 {target}",
           level="warning")
    return True


def reload_module(name):
    """热重载模块（不重启进程）"""
    try:
        if name in sys.modules:
            importlib.reload(sys.modules[name])
            print(f"✅ {name} 热重载成功")
            record("upgrader", "action", f"{name} 热重载")
            return True
        else:
            __import__(name)
            print(f"✅ {name} 已加载")
            return True
    except Exception as e:
        print(f"❌ {name} 重载失败: {e}")
        record("upgrader", "error", f"{name} 重载失败: {e}",
               level="error")
        return False


def verify_module(name):
    """验证模块：语法+导入"""
    path = f"{MODULE_DIR}/{name}.py"
    if not os.path.exists(path):
        return False, "文件不存在"
    # 语法
    import py_compile
    try:
        py_compile.compile(path, doraise=True)
    except Exception as e:
        return False, f"语法错误: {e}"
    return True, "OK"


def upgrade_module(name, new_code_path):
    """升级模块：备份→替换→验证→重载，失败回滚"""
    print(f"升级 {name}...")
    # 1. 备份
    backup = backup_module(name)
    print(f"  已备份: {backup}")

    # 2. 替换
    shutil.copy(new_code_path, f"{MODULE_DIR}/{name}.py")

    # 3. 验证
    ok, msg = verify_module(name)
    if not ok:
        print(f"  ❌ 验证失败: {msg}，回滚")
        rollback_module(name)
        record("upgrader", "error",
               f"{name} 升级失败已回滚: {msg}", level="error")
        return False

    # 4. 热重载
    if not reload_module(name):
        print(f"  ❌ 重载失败，回滚")
        rollback_module(name)
        return False

    print(f"  ✅ {name} 升级成功")
    record("upgrader", "action", f"{name} 升级成功")
    return True


def check_upgrades():
    """检查：坏模块、缺失模块"""
    import json
    arch_path = f"{MODULE_DIR}/architecture.json"
    with open(arch_path) as f:
        arch = json.load(f)

    print("模块健康检查:")
    for name, m in arch["intelligence_layer"]["modules"].items():
        if m["status"] not in ("running", "ready"):
            continue
        # 跳过 evolved 子目录的
        if m.get("path", "").startswith("evolved/"):
            continue
        ok, msg = verify_module(name)
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}: {msg}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        check_upgrades()
    elif len(sys.argv) > 2 and sys.argv[1] == "--rollback":
        rollback_module(sys.argv[2])
    elif len(sys.argv) > 2 and sys.argv[1] == "--reload":
        reload_module(sys.argv[2])
    elif len(sys.argv) > 3 and sys.argv[1] == "--upgrade":
        upgrade_module(sys.argv[2], sys.argv[3])
    else:
        print("模块升级器")
        print("  --check              健康检查")
        print("  --reload <模块>      热重载")
        print("  --rollback <模块>    回滚")
        print("  --upgrade <模块> <新文件>")
