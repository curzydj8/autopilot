#!/usr/bin/env python3
"""
记忆整合 (Memory Consolidation)
把 recorder 的短期事件提炼成 memory.py 的长期记忆
仿人类睡眠时的记忆巩固过程

运行: 每天一次 (supervisor 每 N 轮调用)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recorder import query
from memory import remember, decay
import time


def consolidate(hours=24):
    """整合最近 N 小时的事件 → 长期记忆"""
    print(f"🧠 记忆整合 (最近{hours}小时)...")

    # 1. 错误事件 → 情景记忆 (教训)
    errors = query(level="error", hours=hours, limit=50)
    n_error = 0
    for e in errors:
        # 去重：同一模块+相似消息只记一次
        key = f"lesson-{e['module']}-{hash(e['message'][:40]) % 10000}"
        remember(
            "episodic",
            key,
            f"{e['time']} [{e['module']}] 出错: {e['message'][:100]}",
            importance=0.6,
            tags=["lesson", e["module"]],
        )
        n_error += 1

    # 2. 关键动作 → 情景记忆
    actions = query(event_type="action", hours=hours, limit=50)
    n_action = 0
    for e in actions:
        if e["level"] in ("warning", "critical"):
            key = f"action-{e['module']}-{hash(e['message'][:40]) % 10000}"
            remember(
                "episodic",
                key,
                f"{e['time']} [{e['module']}] {e['message'][:100]}",
                importance=0.5,
                tags=["action", e["module"]],
            )
            n_action += 1

    # 3. 进化成功 → 程序记忆
    evolves = query(module="evolve", hours=hours, limit=20)
    n_evolve = 0
    for e in evolves:
        if "成功" in e["message"] or "evolved" in e["message"]:
            key = f"evolve-{hash(e['message'][:40]) % 10000}"
            remember(
                "procedural",
                key,
                f"自进化: {e['message'][:120]}",
                importance=0.7,
                tags=["evolve"],
            )
            n_evolve += 1

    # 4. 记忆衰减
    decay(hours=hours)

    print(f"  教训: {n_error}, 动作: {n_action}, 进化: {n_evolve}")
    print(f"  衰减完成")
    return {"lessons": n_error, "actions": n_action,
            "evolves": n_evolve}


if __name__ == "__main__":
    consolidate()
