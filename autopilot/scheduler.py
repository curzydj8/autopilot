#!/usr/bin/env python3
"""
调度模块 (Scheduler)
替代 supervisor 的简单循环，提供：
- 优先级队列：P0 > P1 > P2 > P3
- Cron 风格定时任务
- 资源感知：CPU高时不跑重任务
- 任务依赖：A 完成后才跑 B

优先级定义：
  P0 紧急：emergency.py 处理（30秒）
  P1 重要：网络守护、记忆整合（5分钟）
  P2 常规：监控、自愈、优化（10分钟）
  P3 后台：进化、归档（30分钟）
"""

import os
import sys
import time
import heapq
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recorder import record

# 任务注册表：name → {func, priority, interval, last_run, depends}
_tasks = {}
_task_queue = []  # 优先队列 (priority, next_run, name)


def register_task(name, func, priority=2, interval=300, depends=None):
    """注册任务
    priority: 0最高(紧急) 1高 2中 3低
    interval: 秒
    depends: 依赖的任务名列表
    """
    _tasks[name] = {
        "func": func,
        "priority": priority,
        "interval": interval,
        "last_run": 0,
        "depends": depends or [],
        "run_count": 0,
        "fail_count": 0,
    }
    heapq.heappush(_task_queue, (priority, 0, name))
    record("scheduler", "action", f"注册任务: {name} P{priority}/{interval}s")


def _cpu_high(threshold=80):
    """CPU 是否过高"""
    try:
        with open("/proc/stat") as f:
            l1 = f.readline().split()
        time.sleep(0.3)
        with open("/proc/stat") as f:
            l2 = f.readline().split()
        idle1, total1 = int(l1[4]), sum(map(int, l1[1:]))
        idle2, total2 = int(l2[4]), sum(map(int, l2[1:]))
        cpu = 100 * (1 - (idle2 - idle1) / max(1, total2 - total1))
        return cpu > threshold
    except Exception:
        return False


def _deps_ok(task):
    """依赖是否满足（依赖任务至少成功跑过一次）"""
    for dep in task["depends"]:
        if dep not in _tasks or _tasks[dep]["run_count"] == 0:
            return False
    return True


def run_due_tasks():
    """跑到期的任务，按优先级"""
    now = time.time()
    ran = []

    # 收集到期任务
    due = []
    temp = []
    while _task_queue:
        pri, next_run, name = heapq.heappop(_task_queue)
        if name not in _tasks:
            continue
        task = _tasks[name]
        # 更新下次运行时间
        actual_next = task["last_run"] + task["interval"]
        if now >= actual_next and _deps_ok(task):
            # P2/P3 任务：CPU高时跳过
            if task["priority"] >= 2 and _cpu_high():
                record("scheduler", "check",
                       f"{name} 跳过：CPU过高")
                heapq.heappush(temp, (pri, now + 60, name))
                continue
            due.append((pri, name))
        heapq.heappush(temp, (pri, actual_next, name))

    # 恢复队列
    while temp:
        heapq.heappush(_task_queue, heapq.heappop(temp))

    # 按优先级执行
    due.sort()
    for pri, name in due:
        task = _tasks[name]
        try:
            record("scheduler", "action", f"执行 P{pri}: {name}")
            task["func"]()
            task["last_run"] = now
            task["run_count"] += 1
            ran.append(name)
        except Exception as e:
            task["fail_count"] += 1
            record("scheduler", "error",
                   f"{name} 失败: {e}", level="error")

    return ran


def scheduler_loop():
    """调度主循环"""
    print("📅 调度器启动")
    record("scheduler", "start", "调度器启动")
    while True:
        try:
            ran = run_due_tasks()
            if ran:
                print(f"[{time.strftime('%H:%M:%S')}] 执行: {ran}",
                      flush=True)
        except Exception as e:
            record("scheduler", "error", f"调度异常: {e}",
                   level="error")
        time.sleep(10)  # 10秒检查一次


def list_tasks():
    """列出任务"""
    for name, t in sorted(_tasks.items(),
                          key=lambda x: x[1]["priority"]):
        print(f"  P{t['priority']} {name}: "
              f"每{t['interval']}s, 跑{t['run_count']}次, "
              f"失败{t['fail_count']}次")


if __name__ == "__main__":
    # 演示
    def demo_task():
        print("  demo 执行")

    register_task("demo", demo_task, priority=3, interval=60)
    list_tasks()
