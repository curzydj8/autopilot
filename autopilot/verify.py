#!/usr/bin/env python3
"""
验证与修复引擎 (Verify & Repair Engine)
不断测试 → 分析失败 → 提出修复 → 确认结果

这是"可靠执行闭环"的核心：
  每个模块声称自己正常？不信，测一下。
  测失败了？分析原因，修，修完再测。
  修不好？升级问题，记入记忆，通知。

与 healer 的区别：
- healer: 已知问题的固定修复
- verify: 未知问题的主动发现+诊断+修复验证
"""

import os
import sys
import time
import subprocess
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recorder import record
from memory import remember, recall
from learner import learn_new_skill, find_skill

MODULE_DIR = os.path.expanduser("~/workspace/autopilot")


def _run(cmd, timeout=30):
    try:
        out = subprocess.check_output(
            cmd, shell=True, text=True, timeout=timeout,
            stderr=subprocess.STDOUT).strip()
        return True, out
    except subprocess.CalledProcessError as e:
        return False, f"EXIT{e.returncode}: {e.output[:300]}"
    except Exception as e:
        return False, f"ERROR: {e}"


# ============ 测试用例注册表 ============
# 每个模块的自测：怎么测算"正常"
TEST_CASES = {
    "supervisor": {
        "test": lambda: _run(
            "pgrep -f 'supervisor.py' | head -1")[0],
        "expect": True,
        "desc": "进程存活",
    },
    "emergency": {
        "test": lambda: _run(
            "pgrep -f 'emergency.py' | head -1")[0],
        "expect": True,
        "desc": "进程存活",
    },
    "monitor": {
        "test": lambda: _test_import("monitor", "get_full_status"),
        "expect": True,
        "desc": "可导入+函数存在",
    },
    "memory": {
        "test": lambda: _test_import("memory", "remember"),
        "expect": True,
        "desc": "可导入+函数存在",
    },
    "recorder": {
        "test": lambda: _test_import("recorder", "record"),
        "expect": True,
        "desc": "可导入+函数存在",
    },
    "human_input": {
        "test": lambda: _test_import("human_input", "HumanInput"),
        "expect": True,
        "desc": "可导入+类存在",
    },
}


def _test_import(module, attr):
    try:
        m = __import__(module)
        return hasattr(m, attr)
    except Exception:
        return False


def run_test(name):
    """跑单个模块测试"""
    if name not in TEST_CASES:
        return None, "无测试用例"
    tc = TEST_CASES[name]
    try:
        result = tc["test"]()
        passed = (result == tc["expect"])
        return passed, tc["desc"]
    except Exception as e:
        return False, f"测试异常: {e}"


def run_all_tests():
    """跑全部测试"""
    results = {}
    for name in TEST_CASES:
        passed, desc = run_test(name)
        results[name] = {"passed": passed, "desc": desc}
        status = "✅" if passed else "❌"
        record("verify", "test", f"{status} {name}: {desc}",
               level="info" if passed else "error")
    return results


def analyze_failure(name, desc):
    """分析失败原因"""
    record("verify", "analyze", f"分析 {name} 失败: {desc}")

    # 查记忆有没有类似问题
    memories = recall(query=name, limit=3)
    hints = [m["content"][:80] for m in memories]

    # 查技能库
    skill = find_skill(f"{name} {desc}")

    diagnosis = {
        "module": name,
        "symptom": desc,
        "memory_hints": hints,
        "skill_match": skill["solution"] if skill else None,
    }

    # 简单规则诊断
    if "进程存活" in desc:
        diagnosis["likely_cause"] = "进程崩溃或未启动"
        diagnosis["suggested_fix"] = f"master.py start {name}"
    elif "可导入" in desc:
        diagnosis["likely_cause"] = "语法错误或依赖缺失"
        diagnosis["suggested_fix"] = "检查语法和 import"

    record("verify", "analyze",
           f"诊断 {name}: {diagnosis.get('likely_cause', '未知')}")
    return diagnosis


def propose_fix(diagnosis):
    """提出修复方案"""
    name = diagnosis["module"]
    fix = diagnosis.get("suggested_fix", "需人工诊断")

    # 如果有技能库匹配，优先用
    if diagnosis.get("skill_match"):
        fix = diagnosis["skill_match"]

    record("verify", "propose", f"{name} 修复方案: {fix}")
    return fix


def apply_fix(name, fix):
    """执行修复"""
    record("verify", "fix", f"执行修复 {name}: {fix}",
           level="warning")
    # 目前只支持重启类修复
    if fix.startswith("master.py start"):
        ok, out = _run(
            f"cd {MODULE_DIR} && python3 master.py start {name}",
            timeout=30)
        return ok, out
    return False, "不支持自动修复，需人工"


def verify_fix(name):
    """确认修复结果：重测"""
    time.sleep(3)
    passed, desc = run_test(name)
    if passed:
        record("verify", "confirm", f"✅ {name} 修复确认有效")
        remember("episodic", f"verify-fix-{name}-{int(time.time())}",
                 f"验证修复 {name} 成功: {desc}",
                 importance=0.7, tags=["verify", "fix"])
        # 记入技能库
        learn_new_skill(f"{name} 测试失败", fix if (
            fix := True) else "", f"验证引擎自动修复")
    else:
        record("verify", "confirm", f"❌ {name} 修复无效",
               level="error")
    return passed


def verify_cycle():
    """完整验证循环：测试→分析→修复→确认"""
    print("🔍 验证循环开始...")
    results = run_all_tests()

    failed = [n for n, r in results.items() if not r["passed"]]
    if not failed:
        print("  ✅ 全部通过")
        return {"passed": len(results), "failed": []}

    print(f"  ❌ {len(failed)} 个失败: {failed}")
    repairs = []
    for name in failed:
        desc = results[name]["desc"]
        # 分析
        diagnosis = analyze_failure(name, desc)
        # 提方案
        fix = propose_fix(diagnosis)
        print(f"  🔧 {name}: {fix}")
        # 执行
        ok, out = apply_fix(name, fix)
        # 确认
        if ok:
            confirmed = verify_fix(name)
            repairs.append({"module": name, "fix": fix,
                            "confirmed": confirmed})
        else:
            repairs.append({"module": name, "fix": fix,
                            "confirmed": False,
                            "note": "需人工"})

    return {"passed": len(results) - len(failed),
            "failed": repairs}


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "--test":
        r = run_all_tests()
        for n, v in r.items():
            print(f"  {'✅' if v['passed'] else '❌'} {n}: {v['desc']}")
    else:
        r = verify_cycle()
        print(f"\n结果: {r['passed']}通过, {len(r['failed'])}修复尝试")
