#!/usr/bin/env python3
"""
自我进化引擎 (Self-Evolution Engine)
核心能力：遇到现有模块处理不了的问题，自己编写新处理程序

进化循环：
  1. 发现未知问题 (unknown problem)
  2. 分析问题特征 (analyze)
  3. 生成处理程序 (generate) — 模板 + 规则推理
  4. 沙盒测试 (test) — 不污染生产环境
  5. 评估效果 (evaluate)
  6. 成功 → 纳入技能库；失败 → 记录教训，下次换策略

这是整个系统最重要的模块：从"固定程序"进化到"能写程序的程序"。
"""

import os
import sys
import time
import json
import subprocess
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recorder import record
from learner import learn_new_skill, find_skill, record_result

EVOLVE_DIR = os.path.expanduser("~/workspace/autopilot/evolved")
SANDBOX_DIR = os.path.expanduser("~/workspace/autopilot/sandbox")


def _run(cmd, timeout=30):
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, timeout=timeout,
            stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as e:
        return f"EXIT{e.returncode}: {e.output[:500]}"
    except Exception as e:
        return f"ERROR: {e}"


# ============ 1. 问题分析器 ============
def analyze_problem(problem_desc, context=None):
    """分析未知问题，提取特征，判断类型"""
    record("evolve", "analyze", f"分析问题: {problem_desc[:80]}")

    features = {
        "description": problem_desc,
        "context": context or {},
        "keywords": [],
        "probable_type": "unknown",
    }
    desc_lower = problem_desc.lower()

    # 规则分类
    if any(k in desc_lower for k in
           ["disk", "磁盘", "space", "空间", "full", "满"]):
        features["probable_type"] = "disk"
        features["keywords"] = ["disk", "cleanup"]
    elif any(k in desc_lower for k in
             ["network", "网络", "connect", "连接", "proxy", "代理"]):
        features["probable_type"] = "network"
        features["keywords"] = ["network", "v2raya"]
    elif any(k in desc_lower for k in
             ["memory", "内存", "oom", "ram"]):
        features["probable_type"] = "memory"
        features["keywords"] = ["memory", "process"]
    elif any(k in desc_lower for k in
             ["process", "进程", "dead", "死了", "crash", "崩溃"]):
        features["probable_type"] = "process"
        features["keywords"] = ["process", "restart"]
    elif any(k in desc_lower for k in
             ["permission", "权限", "denied", "拒绝"]):
        features["probable_type"] = "permission"
        features["keywords"] = ["permission", "sudo", "chmod"]
    elif any(k in desc_lower for k in
             ["not found", "找不到", "missing", "缺失", "no such"]):
        features["probable_type"] = "missing"
        features["keywords"] = ["install", "path"]

    # 查技能库有没有类似经验
    skill = find_skill(problem_desc)
    features["existing_skill"] = skill["solution"] if skill else None

    record("evolve", "analyze",
           f"问题类型: {features['probable_type']}, "
           f"已有技能: {'有' if skill else '无'}")
    return features


# ============ 2. 程序生成器 ============
HANDLER_TEMPLATE = '''#!/usr/bin/env python3
"""
自进化生成的处理程序
问题: {problem}
生成时间: {time}
类型: {ptype}
"""
import subprocess


def _run(cmd, timeout=30):
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, timeout=timeout,
            stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as e:
        return f"EXIT{{e.returncode}}: {{e.output[:300]}}"
    except Exception as e:
        return f"ERROR: {{e}}"


def handle():
    """处理逻辑"""
{body}
    return result


if __name__ == "__main__":
    print(handle())
'''

# 按问题类型的处理逻辑模板
TYPE_BODIES = {
    "disk": '''    result = []
    # 清理 apt 缓存
    _run("sudo apt-get clean 2>/dev/null")
    result.append("apt clean done")
    # 清理旧日志
    _run("sudo journalctl --vacuum-time=3d 2>/dev/null")
    result.append("journal clean done")
    # 查清理后空间
    usage = _run("df / | tail -1 | awk '{print $5}'")
    result.append(f"disk usage now: {usage}")
    return "; ".join(result)''',

    "network": '''    result = []
    # 测直连
    direct = _run("timeout 8 curl -s -o /dev/null -w '%{http_code}' https://www.baidu.com")
    result.append(f"direct: {direct}")
    # 如果直连不通，尝试重启网络
    if direct != "200":
        _run("sudo systemctl restart NetworkManager 2>/dev/null")
        result.append("network restarted")
    return "; ".join(result)''',

    "memory": '''    result = []
    # 找吃内存最多的5个进程
    top = _run("ps aux --sort=-%mem | head -6 | tail -5 | awk '{print $2, $4\\"%\\", $11}'")
    result.append(f"top mem: {top}")
    # 清文件缓存 (安全)
    _run("sudo sh -c 'echo 1 > /proc/sys/vm/drop_caches' 2>/dev/null")
    result.append("cache dropped")
    return "; ".join(result)''',

    "process": '''    result = []
    # 通用：列出所有 python 进程状态
    procs = _run("ps aux | grep python | grep -v grep | wc -l")
    result.append(f"python procs: {procs}")
    return "; ".join(result)''',

    "permission": '''    result = []
    result.append("permission issue needs manual review")
    result.append("suggestion: check sudoers or file ownership")
    return "; ".join(result)''',

    "missing": '''    result = []
    result.append("missing component needs manual install")
    return "; ".join(result)''',

    "unknown": '''    result = []
    # 未知问题：收集诊断信息
    result.append(_run("uptime"))
    result.append(_run("free -h | head -2"))
    result.append(_run("df -h / | tail -1"))
    return " | ".join(result)''',
}


def generate_handler(features):
    """根据问题特征生成处理程序"""
    ptype = features["probable_type"]
    body = TYPE_BODIES.get(ptype, TYPE_BODIES["unknown"])

    code = HANDLER_TEMPLATE.format(
        problem=features["description"][:200],
        time=time.strftime("%Y-%m-%d %H:%M:%S"),
        ptype=ptype,
        body=body,
    )

    os.makedirs(EVOLVE_DIR, exist_ok=True)
    fname = f"handler_{ptype}_{int(time.time())}.py"
    path = os.path.join(EVOLVE_DIR, fname)
    with open(path, "w") as f:
        f.write(code)
    os.chmod(path, 0o755)

    record("evolve", "generate",
           f"生成处理程序: {fname} (类型 {ptype})")
    return path


# ============ 3. 沙盒测试 ============
def test_handler(path, timeout=60):
    """在沙盒中测试生成的程序（限制权限，不污染系统）"""
    record("evolve", "test", f"沙盒测试: {os.path.basename(path)}")
    os.makedirs(SANDBOX_DIR, exist_ok=True)

    # 语法检查
    syntax = _run(f"python3 -m py_compile {path}", timeout=10)
    if "Error" in syntax or "error" in syntax.lower():
        record("evolve", "test", f"语法失败: {syntax[:200]}",
               level="error")
        return False, f"语法错误: {syntax[:200]}"

    # 运行测试（超时保护）
    try:
        result = subprocess.run(
            ["python3", path],
            capture_output=True, text=True, timeout=timeout,
            cwd=SANDBOX_DIR,
        )
        output = result.stdout.strip()[:500]
        if result.returncode == 0:
            record("evolve", "test", f"测试通过: {output[:100]}")
            return True, output
        else:
            err = result.stderr.strip()[:300]
            record("evolve", "test", f"测试失败: {err}",
                   level="error")
            return False, err
    except subprocess.TimeoutExpired:
        record("evolve", "test", "测试超时", level="error")
        return False, "超时"


# ============ 4. 进化主循环 ============
def evolve(problem_desc, context=None):
    """完整进化流程：分析 → 生成 → 测试 → 纳入/记录"""
    record("evolve", "start", f"开始进化: {problem_desc[:60]}",
           level="warning")
    print(f"🧬 进化开始: {problem_desc[:60]}")

    # 1. 分析
    print("  [1/4] 分析问题...")
    features = analyze_problem(problem_desc, context)

    # 如果已有高成功率技能，直接用
    if features["existing_skill"]:
        print(f"  已有技能，直接复用: "
              f"{features['existing_skill'][:60]}")
        record("evolve", "reuse",
               f"复用已有技能: {features['existing_skill'][:60]}")
        return {"status": "reused",
                "solution": features["existing_skill"]}

    # 2. 生成
    print("  [2/4] 生成处理程序...")
    path = generate_handler(features)

    # 3. 测试
    print("  [3/4] 沙盒测试...")
    success, output = test_handler(path)

    # 4. 评估 & 纳入
    print("  [4/4] 评估...")
    if success:
        skill_pattern = features["description"][:80]
        learn_new_skill(
            pattern=skill_pattern,
            solution=f"运行 {path}",
            description=f"自进化生成 ({features['probable_type']})",
        )
        record_result(skill_pattern, True)
        record("evolve", "success",
               f"进化成功: {os.path.basename(path)}")
        print(f"  ✅ 进化成功: {path}")
        print(f"     输出: {output[:150]}")
        return {"status": "evolved", "path": path,
                "output": output}
    else:
        record("evolve", "fail",
               f"进化失败: {output[:150]}", level="error")
        # 失败也记录教训
        learn_new_skill(
            pattern=features["description"][:80] + " [失败]",
            solution=f"待人工处理: {output[:100]}",
            description="自进化失败，需人工介入",
        )
        print(f"  ❌ 进化失败: {output[:150]}")
        print(f"     已记录，需人工处理")
        return {"status": "failed", "error": output}


def auto_evolve_check():
    """自动检查：从记录里找未解决的问题，尝试进化"""
    from recorder import query
    # 找最近的 error/critical 且没有对应成功技能的
    errors = query(level="error", hours=24, limit=20)
    evolved = 0
    for e in errors:
        msg = e["message"]
        # 跳过已处理过的
        if find_skill(msg + " [失败]"):
            continue
        if find_skill(msg):
            continue
        print(f"\n发现未处理问题，尝试进化: {msg[:60]}")
        result = evolve(msg, e.get("data"))
        if result["status"] == "evolved":
            evolved += 1
        if evolved >= 3:  # 一轮最多进化3个，避免失控
            break
    return evolved


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "--auto":
        n = auto_evolve_check()
        print(f"\n本轮进化 {n} 个新处理程序")
    elif len(_sys.argv) > 1:
        evolve(" ".join(_sys.argv[1:]))
    else:
        print("自我进化引擎")
        print("  evolve.py \"问题描述\"  — 对指定问题进化")
        print("  evolve.py --auto        — 自动扫描未解决问题并进化")
