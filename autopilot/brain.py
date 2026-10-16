#!/usr/bin/env python3
"""
大脑模块 (Agent Brain) —— 自主 AI 主循环

感知 → 思考 → 行动 → 学习

  感知: 截屏看屏幕 + 读系统状态 + 读任务队列
  思考: 按目标推理下一步 (规则引擎 + 可接 LLM)
  行动: 人类模拟鼠标键盘操作
  学习: 记录结果，进化技能库

这是"本地自主 AI"的核心。supervisor 管机器健康，
brain 管"做什么"。
"""

import os
import sys
import time
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser("~/workspace"))
from recorder import record
from learner import find_skill, record_result, learn_new_skill
from vision import screenshot

# 目标：从文件读，AI 自己也可以改
GOAL_FILE = os.path.expanduser("~/workspace/autopilot/goal.json")
BRAIN_LOG = os.path.expanduser("~/workspace/autopilot/logs/brain.log")


def log_brain(msg):
    line = f"[{time.strftime('%H:%M:%S')}] 🧠 {msg}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(BRAIN_LOG), exist_ok=True)
    with open(BRAIN_LOG, "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    record("brain", "think", msg)


def get_goal():
    """读当前目标"""
    if os.path.exists(GOAL_FILE):
        with open(GOAL_FILE) as f:
            return json.load(f)
    return {"objective": "待命", "steps": [], "current_step": 0}


def set_goal(objective, steps):
    """设目标"""
    goal = {"objective": objective, "steps": steps,
            "current_step": 0,
            "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(GOAL_FILE, "w") as f:
        json.dump(goal, f, ensure_ascii=False, indent=2)
    log_brain(f"新目标: {objective} ({len(steps)}步)")
    record("brain", "action", f"设定目标: {objective}")


def perceive():
    """感知：看屏幕 + 系统状态"""
    state = {}
    # 1. 看屏幕
    shot = screenshot()
    state["screenshot"] = shot
    # 2. 系统状态
    try:
        from monitor import get_full_status
        state["system"] = get_full_status()
    except Exception as e:
        state["system"] = {"error": str(e)}
    # 3. 任务队列
    try:
        with open(os.path.expanduser(
                "~/workspace/task-queue/tasks.json")) as f:
            tq = json.load(f)
        pending = sum(1 for w in tq["waves"] for t in w["tasks"]
                      if t["status"] == "pending")
        state["tasks_pending"] = pending
    except Exception:
        state["tasks_pending"] = 0
    return state


def think(state, goal):
    """思考：决定下一步行动
    当前是规则引擎版本。未来可接本地 LLM 做真正的推理。
    """
    if goal["current_step"] >= len(goal["steps"]):
        return {"action": "idle", "reason": "目标完成，待命"}

    step = goal["steps"][goal["current_step"]]
    action_type = step.get("type", "message")

    # 查技能库有没有相关经验
    skill = find_skill(step.get("description", ""))
    if skill:
        log_brain(f"技能库建议: {skill['solution']}")

    return {
        "action": action_type,
        "step": step,
        "reason": step.get("description", ""),
    }


def act(decision):
    """行动：执行决策"""
    action = decision["action"]
    if action == "idle":
        log_brain("待命中...")
        return True

    if action == "message":
        # 给用户发消息（通过记录，由外部投递）
        msg = decision["step"].get("message", "")
        log_brain(f"💬 {msg}")
        record("brain", "action", f"消息: {msg}")
        return True

    if action == "click":
        try:
            sys.path.insert(0, os.path.expanduser("~/workspace"))
            from human_input import HumanInput
            hi = HumanInput()
            x, y = decision["step"]["x"], decision["step"]["y"]
            hi.click(x, y)
            hi.close()
            log_brain(f"点击 ({x},{y})")
            return True
        except Exception as e:
            log_brain(f"点击失败: {e}")
            return False

    if action == "type":
        try:
            from human_input import HumanInput
            hi = HumanInput()
            hi.type(decision["step"]["text"])
            hi.close()
            log_brain(f"输入文字")
            return True
        except Exception as e:
            log_brain(f"输入失败: {e}")
            return False

    log_brain(f"未知动作: {action}")
    return False


def learn(decision, success):
    """学习：记录结果"""
    step = decision.get("step", {})
    desc = step.get("description", decision["action"])
    record_result(desc, success)
    record("brain", "learn",
           f"{'✓' if success else '✗'} {desc}")


def brain_loop():
    """主循环"""
    log_brain("=" * 40)
    log_brain("大脑启动 —— 自主 AI 开始工作")
    log_brain("=" * 40)

    while True:
        try:
            goal = get_goal()
            # 感知
            state = perceive()
            # 思考
            decision = think(state, goal)
            # 行动
            success = act(decision)
            # 学习
            learn(decision, success)

            # 推进目标
            if success and decision["action"] != "idle":
                goal["current_step"] += 1
                with open(GOAL_FILE, "w") as f:
                    json.dump(goal, f, ensure_ascii=False, indent=2)

            time.sleep(10)  # 思考间隔

        except KeyboardInterrupt:
            log_brain("大脑休眠")
            break
        except Exception as e:
            log_brain(f"异常: {e}")
            record("brain", "error", str(e), level="error")
            time.sleep(30)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--goal":
        # 设目标: --goal "目标描述" '["步骤1","步骤2"]'
        import json as _j
        steps = _j.loads(sys.argv[3])
        set_goal(sys.argv[2], steps)
    elif len(sys.argv) > 1 and sys.argv[1] == "--perceive":
        s = perceive()
        print(f"截屏: {s['screenshot']}")
        print(f"待办任务: {s['tasks_pending']}")
    else:
        brain_loop()
