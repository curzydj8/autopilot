#!/usr/bin/env python3
"""
键盘人类模拟模块 (Human Keyboard Simulation)
基于 uinput 内核级模拟 —— 应用看到的是真实硬件键盘事件

人类打字特征:
- 按键间隔随机 (不是固定值)
- 词内快、词间停顿、句间长停顿
- 偶尔打错字 → 退格删除 → 重打 (可配置概率)
- 大小写切换用 Shift，有真实按下时长
- 常用键更快，生僻组合更慢

依赖: python3-evdev, 用户在 input 组
"""

import time
import random
from evdev import UInput, ecodes as E

# 字符 → evdev 按键码 (小写)
CHAR_TO_KEY = {
    'a': E.KEY_A, 'b': E.KEY_B, 'c': E.KEY_C, 'd': E.KEY_D,
    'e': E.KEY_E, 'f': E.KEY_F, 'g': E.KEY_G, 'h': E.KEY_H,
    'i': E.KEY_I, 'j': E.KEY_J, 'k': E.KEY_K, 'l': E.KEY_L,
    'm': E.KEY_M, 'n': E.KEY_N, 'o': E.KEY_O, 'p': E.KEY_P,
    'q': E.KEY_Q, 'r': E.KEY_R, 's': E.KEY_S, 't': E.KEY_T,
    'u': E.KEY_U, 'v': E.KEY_V, 'w': E.KEY_W, 'x': E.KEY_X,
    'y': E.KEY_Y, 'z': E.KEY_Z,
    '0': E.KEY_0, '1': E.KEY_1, '2': E.KEY_2, '3': E.KEY_3,
    '4': E.KEY_4, '5': E.KEY_5, '6': E.KEY_6, '7': E.KEY_7,
    '8': E.KEY_8, '9': E.KEY_9,
    ' ': E.KEY_SPACE, '.': E.KEY_DOT, ',': E.KEY_COMMA,
    '-': E.KEY_MINUS, '=': E.KEY_EQUAL, '/': E.KEY_SLASH,
    ';': E.KEY_SEMICOLON, "'": E.KEY_APOSTROPHE,
    '[': E.KEY_LEFTBRACE, ']': E.KEY_RIGHTBRACE,
    '\n': E.KEY_ENTER, '\t': E.KEY_TAB,
}
# 需要 Shift 的字符 → 基础键
SHIFT_CHARS = {
    '!': '1', '@': '2', '#': '3', '$': '4', '%': '5',
    '^': '6', '&': '7', '*': '8', '(': '9', ')': '0',
    '_': '-', '+': '=', ':': ';', '"': "'", '<': ',',
    '>': '.', '?': '/', '{': '[', '}': ']', '|': '\\',
    '~': '`',
}

# QWERTY 键盘邻键 (用于模拟打错字)
NEIGHBOR_KEYS = {
    'a': ['s', 'q', 'w'], 'b': ['v', 'g', 'h', 'n'],
    'c': ['x', 'd', 'f', 'v'], 'd': ['s', 'e', 'r', 'f', 'c'],
    'e': ['w', 'r', 'd', 's'], 'f': ['d', 'r', 't', 'g', 'v'],
    'g': ['f', 't', 'y', 'h', 'b'], 'h': ['g', 'y', 'u', 'j', 'n'],
    'i': ['u', 'o', 'k', 'j'], 'j': ['h', 'u', 'i', 'k', 'm'],
    'k': ['j', 'i', 'o', 'l'], 'l': ['k', 'o', 'p', ';'],
    'm': ['n', 'j', 'k'], 'n': ['b', 'h', 'j', 'm'],
    'o': ['i', 'p', 'l', 'k'], 'p': ['o', 'l', ';'],
    'q': ['w', 'a'], 'r': ['e', 't', 'f', 'd'],
    's': ['a', 'w', 'e', 'd', 'x'], 't': ['r', 'y', 'g', 'f'],
    'u': ['y', 'i', 'j', 'h'], 'v': ['c', 'f', 'g', 'b'],
    'w': ['q', 'e', 's', 'a'], 'x': ['z', 's', 'd', 'c'],
    'y': ['t', 'u', 'h', 'g'], 'z': ['x', 's'],
}


class KeyboardSim:
    def __init__(self, typo_rate=0.02):
        """typo_rate: 打错字概率 (0~1)，默认 2%"""
        caps = {E.EV_KEY: list(set(CHAR_TO_KEY.values()).union([
                 E.KEY_LEFTSHIFT, E.KEY_RIGHTSHIFT,
                 E.KEY_BACKSPACE, E.KEY_ENTER, E.KEY_TAB,
                 E.KEY_LEFTCTRL, E.KEY_LEFTALT, E.KEY_DELETE,
                 E.KEY_UP, E.KEY_DOWN, E.KEY_LEFT, E.KEY_RIGHT,
                 E.KEY_HOME, E.KEY_END, E.KEY_ESC]))}
        self.ui = UInput(caps, name="kbd-sim-virtual", version=0x1)
        time.sleep(0.3)
        self.typo_rate = typo_rate

    def _press(self, key, hold_ms=None):
        """按下并松开一个键，按住时长随机"""
        hold = hold_ms if hold_ms else random.uniform(0.03, 0.09)
        self.ui.write(E.EV_KEY, key, 1)
        self.ui.syn()
        time.sleep(hold)
        self.ui.write(E.EV_KEY, key, 0)
        self.ui.syn()

    def _type_char(self, ch):
        """打一个字符 (处理大小写和 Shift 符号)"""
        need_shift = False
        base = ch
        if ch.isupper():
            need_shift = True
            base = ch.lower()
        elif ch in SHIFT_CHARS:
            need_shift = True
            base = SHIFT_CHARS[ch]

        key = CHAR_TO_KEY.get(base)
        if key is None:
            return  # 不支持的字符跳过

        if need_shift:
            # 按住 Shift → 按字符键 → 松开 (人类节奏)
            self.ui.write(E.EV_KEY, E.KEY_LEFTSHIFT, 1)
            self.ui.syn()
            time.sleep(random.uniform(0.02, 0.06))
            self._press(key)
            time.sleep(random.uniform(0.01, 0.04))
            self.ui.write(E.EV_KEY, E.KEY_LEFTSHIFT, 0)
            self.ui.syn()
        else:
            self._press(key)

    def _inter_key_delay(self, prev_ch, ch):
        """人类按键间隔：词内快、空格后慢、标点后更慢"""
        if ch == ' ':
            delay = random.uniform(0.08, 0.22)  # 词间停顿
        elif ch in '.,!?;:':
            delay = random.uniform(0.15, 0.35)  # 句间停顿
        elif ch == '\n':
            delay = random.uniform(0.2, 0.5)
        elif prev_ch == ' ':
            delay = random.uniform(0.06, 0.16)  # 词首稍慢
        else:
            # 词内：60~180ms，高斯分布更像人
            delay = max(0.04, random.gauss(0.11, 0.04))
        time.sleep(delay)

    def _maybe_typo(self, ch):
        """随机打错字 → 停顿 → 退格 → 重打"""
        if (ch.isalpha() and ch.lower() in NEIGHBOR_KEYS
                and random.random() < self.typo_rate):
            wrong = random.choice(NEIGHBOR_KEYS[ch.lower()])
            if ch.isupper():
                wrong = wrong.upper()
            self._type_char(wrong)
            # 发现错误后的停顿 (人类会愣一下)
            time.sleep(random.uniform(0.15, 0.4))
            self._press(E.KEY_BACKSPACE)
            time.sleep(random.uniform(0.05, 0.15))
            return True  # 已处理错字，外层继续打正确的
        return False

    def type_text(self, text, typo_rate=None):
        """人类速度打字"""
        if typo_rate is not None:
            self.typo_rate = typo_rate
        prev = ''
        for ch in text:
            if self._maybe_typo(ch):
                pass  # 错字已打并删除
            self._type_char(ch)
            self._inter_key_delay(prev, ch)
            prev = ch

    def press_key(self, key_name):
        """按特殊键: enter/tab/esc/ctrl+c 等"""
        combos = {
            'enter': [E.KEY_ENTER],
            'tab': [E.KEY_TAB],
            'esc': [E.KEY_ESC],
            'backspace': [E.KEY_BACKSPACE],
            'delete': [E.KEY_DELETE],
            'ctrl+c': [E.KEY_LEFTCTRL, E.KEY_C],
            'ctrl+v': [E.KEY_LEFTCTRL, E.KEY_V],
            'ctrl+a': [E.KEY_LEFTCTRL, E.KEY_A],
            'ctrl+z': [E.KEY_LEFTCTRL, E.KEY_Z],
            'alt+tab': [E.KEY_LEFTALT, E.KEY_TAB],
        }
        keys = combos.get(key_name)
        if not keys:
            return
        for k in keys:
            self.ui.write(E.EV_KEY, k, 1)
            self.ui.syn()
            time.sleep(random.uniform(0.02, 0.05))
        time.sleep(random.uniform(0.04, 0.1))
        for k in reversed(keys):
            self.ui.write(E.EV_KEY, k, 0)
            self.ui.syn()

    def close(self):
        self.ui.close()


if __name__ == "__main__":
    import sys
    k = KeyboardSim()
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "type":
            text = " ".join(sys.argv[2:])
            print(f"打字: {text[:40]}...")
            time.sleep(1)  # 给用户1秒切窗口
            k.type_text(text)
            print("完成")
        elif len(sys.argv) > 1 and sys.argv[1] == "key":
            print(f"按键: {sys.argv[2]}")
            time.sleep(1)
            k.press_key(sys.argv[2])
        else:
            print("用法:")
            print("  keyboard_sim.py type <文字>   # 人类速度打字")
            print("  keyboard_sim.py key <enter|tab|esc|ctrl+c|...>")
    finally:
        k.close()
