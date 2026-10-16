#!/usr/bin/env python3
"""
LLM 进化引擎 (LLM Evolution Engine)
OpenEvolve 模式 + 本地 Ollama + 确定性验证器

核心思想（来自研究报告）：
  小模型当"提议者"（生成代码变体）
  确定性验证器当"裁判"（跑测试打分）
  适者生存，迭代进化

与旧 evolve.py 的区别：
  旧：规则模板，只能处理预设问题类型
  新：LLM 自由生成，验证器打分，可处理未知问题
"""

import os
import sys
import time
import json
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recorder import record
from memory import remember
from llm import ask, is_available
from safety import check_command

MODULE_DIR = os.path.expanduser("~/workspace/autopilot")
EVOLVED_DIR = f"{MODULE_DIR}/evolved"


def _llm_propose(problem, current_code=None, feedback=None,
                 model="qwen2.5:1.5b"):
    """LLM 生成代码变体"""
    system = (
        "你是代码进化引擎。给定一个问题，生成 Python 代码来解决它。"
        "只输出 Python 代码，不要解释，不要 markdown 标记。"
        "代码必须：1) 有 main() 函数 2) 可独立运行 3) 有基本错误处理"
    )
    prompt = f"问题：{problem}\n"
    if current_code:
        prompt += f"\n当前代码（可改进）：\n{current_code[:2000]}\n"
    if feedback:
        prompt += f"\n上次反馈：{feedback}\n"
    prompt += "\n生成改进后的完整 Python 代码："

    code = ask(prompt, model=model, system=system, timeout=180)
    if not code:
        return None

    # 清理：去掉可能的 markdown 标记
    code = code.strip()
    if code.startswith("```"):
        lines = code.split("\n")
        # 去掉第一行 ```python 和最后 ``` 
        lines = [l for l in lines
                 if not l.strip().startswith("```")]
        code = "\n".join(lines)

    return code


def _evaluate(code, test_cmd="python3", timeout=30):
    """确定性验证器：跑代码打分
    返回 (score 0-1, feedback)
    """
    import subprocess
    import tempfile

    # 安全检查
    allowed, risk, reason = check_command(
        f"python3 {test_cmd}")
    # 写临时文件
    with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        tmp = f.name

    try:
        # 1. 语法检查
        import py_compile
        try:
            py_compile.compile(tmp, doraise=True)
        except Exception as e:
            return 0.0, f"语法错误: {e}"

        # 2. 试运行
        r = subprocess.run(
            ["python3", tmp], capture_output=True,
            text=True, timeout=timeout)
        if r.returncode != 0:
            return 0.3, f"运行失败: {r.stderr[:200]}"

        # 3. 有输出 = 基本可用
        if r.stdout.strip():
            return 0.7, f"运行成功，输出: {r.stdout[:100]}"
        return 0.5, "运行成功但无输出"

    except subprocess.TimeoutExpired:
        return 0.2, "超时"
    except Exception as e:
        return 0.0, f"评估异常: {e}"
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def evolve_with_llm(problem, iterations=3,
                    model="qwen2.5:1.5b"):
    """LLM 驱动的进化主循环"""
    avail, models = is_available()
    if not avail:
        print("❌ Ollama 不可用，无法 LLM 进化")
        return None

    print(f"🧬 LLM 进化开始: {problem[:50]}...")
    print(f"   模型: {model}, 迭代: {iterations}")
    record("evolve_llm", "start", f"LLM进化: {problem[:60]}")

    best_code = None
    best_score = 0
    history = []

    for i in range(iterations):
        print(f"\n  第 {i+1}/{iterations} 代...")
        feedback = history[-1]["feedback"] if history else None

        # 变异：LLM 生成
        code = _llm_propose(problem, best_code, feedback, model)
        if not code:
            print("    LLM 生成失败，跳过")
            continue

        # 评估：验证器打分
        score, fb = _evaluate(code)
        print(f"    得分: {score:.2f} - {fb[:60]}")

        history.append({"code": code, "score": score,
                        "feedback": fb})

        # 选择：保留最优
        if score > best_score:
            best_score = score
            best_code = code
            print(f"    ✅ 新最优! ({score:.2f})")

        record("evolve_llm", "generation",
               f"第{i+1}代: {score:.2f}", level="info")

        # 满分提前结束
        if score >= 0.9:
            print("    🎯 达到目标，提前结束")
            break

    if best_code and best_score >= 0.5:
        # 保存最优
        os.makedirs(EVOLVED_DIR, exist_ok=True)
        ts = int(time.time())
        path = f"{EVOLVED_DIR}/llm_evolved_{ts}.py"
        with open(path, "w") as f:
            f.write(best_code)

        print(f"\n✅ 进化完成，最优得分 {best_score:.2f}")
        print(f"   保存: {path}")
        record("evolve_llm", "success",
               f"进化成功: {path} ({best_score:.2f})",
               level="warning")
        remember("episodic", f"llm-evolve-{ts}",
                 f"LLM进化 '{problem[:40]}' 得分{best_score:.2f}",
                 importance=0.8, tags=["evolve", "llm"])
        return path, best_score
    else:
        print(f"\n❌ 进化失败，最优 {best_score:.2f}")
        record("evolve_llm", "fail",
               f"LLM进化未达标: {problem[:40]}", level="error")
        return None


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "--test":
        avail, models = is_available()
        print(f"Ollama: {avail}, 模型: {models}")
        if avail:
            r = evolve_with_llm("写一个函数计算斐波那契数列前10项并打印",
                                iterations=2)
            print(f"结果: {r}")
    else:
        print("LLM 进化引擎")
        print("  --test  测试（需 Ollama + 模型）")
