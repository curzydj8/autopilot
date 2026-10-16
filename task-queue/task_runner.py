#!/usr/bin/env python3
"""
自主任务执行器 (Autonomous Task Runner)
从任务队列取任务，用人类模拟输入发给 Waydroid 里的 Muse，
按预测时间等待，完成后取下一个；一波做完后更新任务列表。

架构:
  tasks.json → TaskRunner → human_input → Waydroid(Muse App)
                                    ↓
                              预测时间等待
                                    ↓
                              更新状态 → 下一个任务

用法:
  python3 task_runner.py              # 跑当前波次
  python3 task_runner.py --wave 2     # 跑指定波次
  python3 task_runner.py --status     # 看进度
"""

import json
import time
import sys
import os
import subprocess

sys.path.insert(0, os.path.expanduser("~/workspace"))
from human_input import HumanInput

TASK_FILE = os.path.expanduser("~/workspace/task-queue/tasks.json")

# Muse App 在 Waydroid 中的输入框坐标 (需根据实际屏幕校准)
# 用 task_runner.py --calibrate 来标定
MUSE_INPUT_X = 960
MUSE_INPUT_Y = 950


def load_tasks():
    with open(TASK_FILE) as f:
        return json.load(f)


def save_tasks(data):
    with open(TASK_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def waydroid_running():
    """检查 Waydroid 会话是否在跑"""
    try:
        out = subprocess.check_output(
            ["waydroid", "status"], text=True, stderr=subprocess.DEVNULL
        )
        return "RUNNING" in out
    except Exception:
        return False


def start_waydroid():
    """启动 Waydroid 会话"""
    print("启动 Waydroid...")
    subprocess.Popen(
        ["waydroid", "show-full-ui"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    for _ in range(30):
        if waydroid_running():
            print("Waydroid 已运行")
            return True
        time.sleep(2)
    print("Waydroid 启动超时")
    return False


def open_muse_app(hi):
    """在 Waydroid 里打开 Muse App
    方案: 点击应用抽屉 → 找 Muse 图标
    (首次需手动标定坐标，或用 --calibrate)
    """
    print("打开 Muse App...")
    # TODO: 首次运行需标定 Muse 图标坐标
    # 这里先用占位：假设 Muse 在主屏幕
    # 实际用时跑 --calibrate 标定
    print("  (需先标定 Muse 图标位置，跑 --calibrate)")
    return False


def run_wave(wave_id=None):
    data = load_tasks()
    waves = data["waves"]

    # 找目标波次
    target = None
    for w in waves:
        if wave_id is None and w["wave_id"] == data["current_wave"]:
            target = w
            break
        if w["wave_id"] == wave_id:
            target = w
            break
    if not target:
        print("没找到目标波次")
        return

    print(f"\n{'='*50}")
    print(f"开始波次: {target['name']}")
    print(f"{'='*50}\n")

    # 确保 Waydroid 运行
    if not waydroid_running():
        if not start_waydroid():
            return

    hi = HumanInput()
    try:
        # 打开 Muse
        if not open_muse_app(hi):
            print("请先标定: python3 task_runner.py --calibrate")
            return

        pending = [t for t in target["tasks"] if t["status"] == "pending"]
        print(f"待执行任务: {len(pending)} 个\n")

        for i, task in enumerate(pending):
            print(f"[{i+1}/{len(pending)}] 发送任务 {task['id']}")
            print(f"  内容: {task['content'][:60]}...")
            print(f"  预测: {task['predicted_minutes']} 分钟")

            # 人类方式：点输入框 → 打字 → 回车
            hi.click_and_type(MUSE_INPUT_X, MUSE_INPUT_Y, task["content"])
            hi.press("enter")

            task["status"] = "sent"
            task["sent_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            save_tasks(data)

            # 等待预测完成时间
            wait_sec = task["predicted_minutes"] * 60
            print(f"  等待 {task['predicted_minutes']} 分钟...")
            time.sleep(wait_sec)

            task["status"] = "done"
            task["done_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            save_tasks(data)
            print(f"  ✓ 任务 {task['id']} 完成\n")

        # 波次完成
        print(f"{'='*50}")
        print(f"波次完成: {target['name']}")
        print(f"已执行 {len(pending)} 个任务")
        print(f"{'='*50}")
        print("\n下一步: 更新任务列表，规划下一波")
        print("  手动: 编辑 tasks.json 加新波次")
        print("  或让 Muse 生成: 把上面的结果发给 Muse，让它规划下一波")

        data["current_wave"] = target["wave_id"] + 1
        save_tasks(data)

    finally:
        hi.close()


def show_status():
    data = load_tasks()
    print(f"\n当前波次: {data['current_wave']}")
    for w in data["waves"]:
        done = sum(1 for t in w["tasks"] if t["status"] == "done")
        total = len(w["tasks"])
        print(f"\n  波次 {w['wave_id']}: {w['name']} [{done}/{total}]")
        for t in w["tasks"]:
            icon = {"pending": "○", "sent": "◐", "done": "●"}.get(t["status"], "?")
            print(f"    {icon} {t['id']}: {t['content'][:40]}...")


def calibrate():
    print("标定模式:")
    print("1. 确保 Waydroid 和 Muse App 已打开")
    print("2. 把鼠标移到 Muse 的输入框上")
    print("3. 5秒后记录坐标")
    for i in range(5, 0, -1):
        print(f"  {i}...", flush=True)
        time.sleep(1)
    # 读鼠标位置 (需 xdotool 或其他方式)
    print("\nTODO: 需要实现鼠标位置读取")
    print("临时方案: 手动填 MUSE_INPUT_X/Y 到脚本顶部")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        show_status()
    elif len(sys.argv) > 1 and sys.argv[1] == "--calibrate":
        calibrate()
    elif len(sys.argv) > 2 and sys.argv[1] == "--wave":
        run_wave(int(sys.argv[2]))
    else:
        run_wave()
