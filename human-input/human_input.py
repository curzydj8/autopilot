#!/usr/bin/env python3
"""
人类输入统一模块 (Human Input)
鼠标 + 键盘的人类行为模拟，内核级 uinput —— 应用视为真实硬件

反机器人检测要点:
1. uinput 内核级事件 = 真实硬件 (不是后台 API 调用)
2. 贝塞尔曲线移动 + 变速 + 抖动 (鼠标)
3. 高斯分布按键间隔 + 偶发错字纠正 (键盘)
4. 所有 timing 都是随机范围，不是固定值

用法:
    from human_input import HumanInput
    hi = HumanInput()
    hi.click(500, 300)          # 人类点击
    hi.type("hello world")      # 人类打字
    hi.close()
"""

from mouse_sim import MouseSim
from keyboard_sim import KeyboardSim
import time
import random


class HumanInput:
    def __init__(self, typo_rate=0.02):
        self.mouse = MouseSim()
        self.kbd = KeyboardSim(typo_rate=typo_rate)

    # ---- 鼠标 ----
    def move(self, x, y, speed="normal"):
        self.mouse.human_move_to(x, y, speed)

    def click(self, x, y, button="left", speed="normal"):
        self.mouse.human_click(x, y, button, speed)

    def double_click(self, x, y, speed="normal"):
        self.mouse.human_double_click(x, y, speed)

    def right_click(self, x, y, speed="normal"):
        self.mouse.human_click(x, y, "right", speed)

    def drag(self, x1, y1, x2, y2, speed="normal"):
        self.mouse.human_drag(x1, y1, x2, y2, speed)

    def scroll(self, clicks):
        self.mouse.scroll(clicks)

    # ---- 键盘 ----
    def type(self, text, typo_rate=None):
        self.kbd.type_text(text, typo_rate)

    def press(self, key_name):
        self.kbd.press_key(key_name)

    # ---- 组合 ----
    def click_and_type(self, x, y, text, speed="normal"):
        """点输入框 → 人类打字 (最常用组合)"""
        self.click(x, y, speed=speed)
        time.sleep(random.uniform(0.15, 0.35))
        self.type(text)

    def close(self):
        self.mouse.close()
        self.kbd.close()


if __name__ == "__main__":
    import sys
    hi = HumanInput()
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "demo":
            print("演示: 3秒后移动+打字 (切到文本框)")
            time.sleep(3)
            hi.click_and_type(960, 500, "Hello, this is human typing!")
            print("完成")
        else:
            print("用法: human_input.py demo")
            print("  或 import human_input 使用 HumanInput 类")
    finally:
        hi.close()
