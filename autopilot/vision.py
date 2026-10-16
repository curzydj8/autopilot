#!/usr/bin/env python3
"""
眼睛模块 (Vision) —— 让 AI 看见屏幕
功能：
- 截屏 (Wayland/X11 通用)
- 找图 (模板匹配：在屏幕上找按钮/图标)
- 读字 (OCR：识别屏幕文字)
- 录屏 (可选)

依赖: pip install mss opencv-python pytesseract (按需)
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recorder import record

SCREENSHOT_DIR = os.path.expanduser("~/workspace/autopilot/screenshots")


def _get_xauth():
    """自动找 Xwayland 的认证文件"""
    import glob
    import subprocess
    # 从 Xwayland 命令行找 -auth 参数
    try:
        out = subprocess.check_output(
            "ps aux | grep Xwayland | grep -v grep | head -1",
            shell=True, text=True, timeout=5)
        import re
        m = re.search(r"-auth\s+(\S+)", out)
        if m and os.path.exists(m.group(1)):
            return m.group(1)
    except Exception:
        pass
    # 备选：找 /run/user/*/xauth_*
    for p in glob.glob("/run/user/*/xauth_*"):
        return p
    return None


def screenshot(path=None):
    """截屏，返回文件路径"""
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    if path is None:
        path = os.path.join(
            SCREENSHOT_DIR,
            f"shot_{time.strftime('%Y%m%d_%H%M%S')}.png")
    try:
        # 优先 mss (快，无依赖 X)
        import mss
        with mss.mss() as sct:
            sct.shot(output=path)
        return path
    except ImportError:
        pass

    # Xwayland + scrot (自动找认证)
    xauth = _get_xauth()
    if xauth:
        env = f"DISPLAY=:0 XAUTHORITY={xauth}"
        cmd = f"{env} scrot {path} 2>/dev/null"
        if os.system(cmd) == 0 and os.path.exists(path):
            # 验证是有效图片
            try:
                from PIL import Image
                img = Image.open(path)
                if img.size[0] > 100:  # 不是空图
                    return path
            except Exception:
                pass

    # 备选：其他工具
    for cmd in [f"gnome-screenshot -f {path}",
                f"import -window root {path}"]:
        if os.system(cmd + " 2>/dev/null") == 0 and os.path.exists(path):
            return path
    record("vision", "error", "截屏失败：无可用工具", level="error")
    return None


def find_on_screen(template_path, threshold=0.8):
    """在屏幕上找图，返回 (x, y) 中心坐标，找不到返回 None"""
    try:
        import cv2
        import numpy as np
    except ImportError:
        record("vision", "error", "缺 opencv", level="error")
        return None

    shot = screenshot()
    if not shot:
        return None
    try:
        screen = cv2.imread(shot)
        template = cv2.imread(template_path)
        if screen is None or template is None:
            return None
        res = cv2.matchTemplate(screen, template,
                                cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val >= threshold:
            h, w = template.shape[:2]
            cx = max_loc[0] + w // 2
            cy = max_loc[1] + h // 2
            record("vision", "check",
                   f"找到 {template_path} @ ({cx},{cy}) "
                   f"置信度 {max_val:.2f}")
            return (cx, cy)
        return None
    finally:
        if os.path.exists(shot):
            os.remove(shot)  # 临时截图用完删


def ocr_screen(region=None):
    """OCR 识别屏幕文字
    region: (x, y, w, h) 指定区域，None=全屏
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        record("vision", "error", "缺 pytesseract/PIL", level="error")
        return ""

    shot = screenshot()
    if not shot:
        return ""
    try:
        img = Image.open(shot)
        if region:
            x, y, w, h = region
            img = img.crop((x, y, x + w, y + h))
        # 中英文
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        return text.strip()
    except Exception as e:
        record("vision", "error", f"OCR失败: {e}", level="error")
        return ""
    finally:
        if os.path.exists(shot):
            os.remove(shot)


def describe_screen():
    """截屏并返回路径（供外部 AI 视觉模型分析）"""
    path = screenshot()
    if path:
        record("vision", "check", f"截屏: {path}")
    return path


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "--shot":
        p = screenshot()
        print(f"截屏: {p}")
    elif len(_sys.argv) > 2 and _sys.argv[1] == "--find":
        pos = find_on_screen(_sys.argv[2])
        print(f"位置: {pos}")
    elif len(_sys.argv) > 1 and _sys.argv[1] == "--ocr":
        print(ocr_screen())
    else:
        print("眼睛模块")
        print("  --shot          截屏")
        print("  --find <图>     找图")
        print("  --ocr           识别文字")
