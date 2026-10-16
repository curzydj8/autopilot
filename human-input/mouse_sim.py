#!/usr/bin/env python3
"""
鼠标指针模拟模块 (Mouse Pointer Simulation)
适用于 Wayland (KDE Plasma) —— 基于 uinput 内核级输入模拟

功能:
- 移动鼠标指针 (绝对/相对坐标)
- 左/中/右键点击、双击
- 按住拖拽
- 滚轮滚动

依赖: python3-evdev (sudo apt install python3-evdev)
权限: 用户需在 input 组 (sudo usermod -aG input $USER)，或 root 运行

用法示例见底部 __main__
"""

import time
import math
import random
from evdev import UInput, ecodes as E

# 屏幕分辨率 (按实际修改，或用 get_resolution() 自动获取)
SCREEN_W = 1920
SCREEN_H = 1080


class MouseSim:
    def __init__(self):
        # Wayland 下相对移动最可靠；绝对坐标用相对移动逼近
        caps = {
            E.EV_REL: [E.REL_X, E.REL_Y, E.REL_WHEEL, E.REL_HWHEEL],
            E.EV_KEY: [E.BTN_LEFT, E.BTN_MIDDLE, E.BTN_RIGHT],
        }
        self.ui = UInput(caps, name="mouse-sim-virtual", version=0x1)
        time.sleep(0.3)  # 等待设备就绪
        # 记录逻辑指针位置 (相对移动累积)
        self._x = SCREEN_W // 2
        self._y = SCREEN_H // 2

    def _sync(self):
        self.ui.syn()

    # ---------- 移动 ----------
    def move_rel(self, dx, dy):
        """相对移动"""
        self.ui.write(E.EV_REL, E.REL_X, dx)
        self.ui.write(E.EV_REL, E.REL_Y, dy)
        self._sync()
        self._x = max(0, min(SCREEN_W - 1, self._x + dx))
        self._y = max(0, min(SCREEN_H - 1, self._y + dy))

    def move_to(self, x, y, steps=20, delay=0.008):
        """平滑移动到绝对坐标 (x, y) —— 用相对移动逼近"""
        x = max(0, min(SCREEN_W - 1, x))
        y = max(0, min(SCREEN_H - 1, y))
        dx_total = x - self._x
        dy_total = y - self._y
        if steps <= 0:
            steps = 1
        for _ in range(steps):
            self.move_rel(dx_total // steps, dy_total // steps)
            time.sleep(delay)
        # 修正余数
        self.move_rel(x - self._x, y - self._y)

    # ---------- 点击 ----------
    def _click_btn(self, btn, count=1, interval=0.06):
        for _ in range(count):
            self.ui.write(E.EV_KEY, btn, 1)
            self._sync()
            time.sleep(0.03)
            self.ui.write(E.EV_KEY, btn, 0)
            self._sync()
            time.sleep(interval)

    def click(self, x=None, y=None, button="left"):
        """点击。button: left/middle/right"""
        btn = {"left": E.BTN_LEFT, "middle": E.BTN_MIDDLE,
               "right": E.BTN_RIGHT}[button]
        if x is not None and y is not None:
            self.move_to(x, y)
            time.sleep(0.05)
        self._click_btn(btn)

    def double_click(self, x=None, y=None):
        if x is not None and y is not None:
            self.move_to(x, y)
            time.sleep(0.05)
        self._click_btn(E.BTN_LEFT, count=2, interval=0.08)

    def right_click(self, x=None, y=None):
        self.click(x, y, button="right")

    # ---------- 拖拽 ----------
    def drag(self, x1, y1, x2, y2, steps=30, delay=0.01):
        """从 (x1,y1) 拖到 (x2,y2)"""
        self.move_to(x1, y1)
        time.sleep(0.1)
        self.ui.write(E.EV_KEY, E.BTN_LEFT, 1)
        self._sync()
        time.sleep(0.05)
        dx = (x2 - x1) / steps
        dy = (y2 - y1) / steps
        for _ in range(steps):
            self.move_rel(int(dx), int(dy))
            time.sleep(delay)
        self.ui.write(E.EV_KEY, E.BTN_LEFT, 0)
        self._sync()

    # ---------- 滚轮 ----------
    def scroll(self, clicks, horizontal=False):
        """滚轮。clicks>0 上滚，<0 下滚"""
        rel = E.REL_HWHEEL if horizontal else E.REL_WHEEL
        direction = 1 if clicks > 0 else -1
        for _ in range(abs(clicks)):
            self.ui.write(E.EV_REL, rel, direction)
            self._sync()
            time.sleep(0.03)

    # ---------- 人类模拟 ----------
    def human_move_to(self, x, y, speed="normal"):
        """像人一样移动到 (x, y)：贝塞尔曲线 + 先加速后减速 + 微抖动

        speed: slow / normal / fast
        """
        x = max(0, min(SCREEN_W - 1, x))
        y = max(0, min(SCREEN_H - 1, y))
        x0, y0 = self._x, self._y
        dist = math.hypot(x - x0, y - y0)
        if dist < 2:
            return

        # 速度档: 每秒像素
        px_per_sec = {"slow": 400, "normal": 900, "fast": 1800}[speed]
        # 人类移动时间: 距离/速度 + 随机
        duration = dist / px_per_sec * random.uniform(0.85, 1.25)
        duration = max(0.08, min(duration, 2.0))

        # 贝塞尔控制点: 随机偏移，人类走弧线
        mx, my = (x0 + x) / 2, (y0 + y) / 2
        perp = random.uniform(-0.15, 0.15) * dist  # 垂直偏移
        angle = math.atan2(y - y0, x - x0) + math.pi / 2
        cx = mx + math.cos(angle) * perp
        cy = my + math.sin(angle) * perp

        steps = max(8, min(80, int(dist / 6)))
        start = time.time()
        for i in range(1, steps + 1):
            t = i / steps
            # ease-in-out: 开始慢、中间快、结尾慢
            te = t * t * (3 - 2 * t)
            # 二次贝塞尔
            bx = (1 - te) ** 2 * x0 + 2 * (1 - te) * te * cx + te ** 2 * x
            by = (1 - te) ** 2 * y0 + 2 * (1 - te) * te * cy + te ** 2 * y
            # 微抖动 (±1px)
            bx += random.uniform(-1, 1)
            by += random.uniform(-1, 1)
            self.move_rel(int(bx - self._x), int(by - self._y))
            # 按 ease 节奏 sleep
            elapsed = time.time() - start
            target = duration * te
            if target > elapsed:
                time.sleep(target - elapsed)

        # 偶尔轻微过冲再修正 (人类特征)
        if dist > 80 and random.random() < 0.3:
            ox = x + random.randint(-6, 6)
            oy = y + random.randint(-6, 6)
            self.move_rel(ox - self._x, oy - self._y)
            time.sleep(random.uniform(0.03, 0.08))
        self.move_rel(x - self._x, y - self._y)

    def _human_pause(self, base=0.1):
        """人类随机停顿"""
        time.sleep(base * random.uniform(0.6, 1.6))

    def human_click(self, x, y, button="left", speed="normal"):
        """人类式点击：自然移动 + 随机停顿 + 按压力度变化"""
        btn = {"left": E.BTN_LEFT, "middle": E.BTN_MIDDLE,
               "right": E.BTN_RIGHT}[button]
        self.human_move_to(x, y, speed)
        self._human_pause(0.12)  # 瞄准停顿
        # 按下时长随机 40~120ms
        press_ms = random.uniform(0.04, 0.12)
        self.ui.write(E.EV_KEY, btn, 1)
        self._sync()
        time.sleep(press_ms)
        self.ui.write(E.EV_KEY, btn, 0)
        self._sync()
        self._human_pause(0.08)

    def human_double_click(self, x, y, speed="normal"):
        """人类式双击：两次点击间隔 80~200ms"""
        self.human_click(x, y, "left", speed)
        time.sleep(random.uniform(0.08, 0.2))
        # 第二次不移动，直接点
        press_ms = random.uniform(0.04, 0.1)
        self.ui.write(E.EV_KEY, E.BTN_LEFT, 1)
        self._sync()
        time.sleep(press_ms)
        self.ui.write(E.EV_KEY, E.BTN_LEFT, 0)
        self._sync()
        self._human_pause(0.08)

    def human_drag(self, x1, y1, x2, y2, speed="normal"):
        """人类式拖拽"""
        self.human_move_to(x1, y1, speed)
        self._human_pause(0.15)
        self.ui.write(E.EV_KEY, E.BTN_LEFT, 1)
        self._sync()
        time.sleep(random.uniform(0.08, 0.18))
        # 拖拽中途用 human 移动 (不松开)
        # 临时：分段 human_move
        dist = math.hypot(x2 - x1, y2 - y1)
        segs = max(2, int(dist / 200))
        for i in range(1, segs + 1):
            ix = x1 + (x2 - x1) * i / segs
            iy = y1 + (y2 - y1) * i / segs
            self.human_move_to(int(ix), int(iy), "slow")
        self._human_pause(0.1)
        self.ui.write(E.EV_KEY, E.BTN_LEFT, 0)
        self._sync()
        self._human_pause(0.1)

    def close(self):
        self.ui.close()


def get_resolution():
    """尝试自动获取屏幕分辨率"""
    try:
        import subprocess
        out = subprocess.check_output(
            ["kscreen-doctor", "-o"], text=True, stderr=subprocess.DEVNULL
        )
        import re
        m = re.search(r"(\d+)x(\d+)@", out)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return SCREEN_W, SCREEN_H


if __name__ == "__main__":
    import sys
    w, h = get_resolution()
    SCREEN_W, SCREEN_H = w, h
    print(f"屏幕: {w}x{h}")

    m = MouseSim()
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "test":
            # 自检: 移动一圈 + 点击
            print("移动测试...")
            cx, cy = w // 2, h // 2
            m.move_to(cx - 100, cy)
            time.sleep(0.3)
            m.move_to(cx + 100, cy)
            time.sleep(0.3)
            m.move_to(cx, cy)
            print("自检完成 (未点击)")
        elif len(sys.argv) >= 4 and sys.argv[1] == "click":
            x, y = int(sys.argv[2]), int(sys.argv[3])
            btn = sys.argv[4] if len(sys.argv) > 4 else "left"
            print(f"点击 ({x},{y}) [{btn}]")
            m.click(x, y, btn)
        elif len(sys.argv) >= 3 and sys.argv[1] == "move":
            x, y = int(sys.argv[2]), int(sys.argv[3])
            print(f"移动到 ({x},{y})")
            m.move_to(x, y)
        elif len(sys.argv) >= 4 and sys.argv[1] == "hclick":
            # 人类式点击
            x, y = int(sys.argv[2]), int(sys.argv[3])
            btn = sys.argv[4] if len(sys.argv) > 4 else "left"
            spd = sys.argv[5] if len(sys.argv) > 5 else "normal"
            print(f"人类点击 ({x},{y}) [{btn}] [{spd}]")
            m.human_click(x, y, btn, spd)
        elif len(sys.argv) >= 4 and sys.argv[1] == "hdouble":
            x, y = int(sys.argv[2]), int(sys.argv[3])
            print(f"人类双击 ({x},{y})")
            m.human_double_click(x, y)
        elif len(sys.argv) >= 3 and sys.argv[1] == "hmove":
            x, y = int(sys.argv[2]), int(sys.argv[3])
            spd = sys.argv[4] if len(sys.argv) > 4 else "normal"
            print(f"人类移动到 ({x},{y}) [{spd}]")
            m.human_move_to(x, y, spd)
        else:
            print("用法:")
            print("  mouse_sim.py test              # 自检 (只移动不点击)")
            print("  mouse_sim.py move X Y          # 移动指针到 X,Y")
            print("  mouse_sim.py click X Y [left|right|middle]")
            print("  --- 人类模拟 ---")
            print("  mouse_sim.py hmove X Y [slow|normal|fast]")
            print("  mouse_sim.py hclick X Y [left|right|middle] [slow|normal|fast]")
            print("  mouse_sim.py hdouble X Y       # 人类双击")
    finally:
        m.close()
