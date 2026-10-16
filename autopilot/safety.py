#!/usr/bin/env python3
"""
安全沙箱与权限控制层 (Safety & Guardrails)
Gemini 架构中的"最关键模块"

所有危险操作必须经过这一层：
  风险分级 → 白名单/黑名单检查 → 人机确认 → 审计日志

权限上下文：
  本系统以最高权限运行（sudo 免密 / root）。
  这意味着安全层不能依赖"没权限所以安全"，
  必须靠"主动拦截"来防误操作。
  权限高 = 责任大 = 检查更严。

风险等级：
  LOW      读操作，无副作用（ls, cat, ps）
  MEDIUM   写操作，可逆（mkdir, touch, apt clean）
  HIGH     写操作，难逆（rm, kill, 修改配置）
  CRITICAL 破坏性（rm -rf /, 格式化, sudo rm）—— 最高权限也拦
"""

import os
import sys
import re
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recorder import record
from memory import remember

# ============ 权限上下文 ============
# 系统以最高权限运行，安全层必须知道
PRIVILEGE_CONTEXT = {
    "level": "root",           # root / sudo / user
    "sudo_nopasswd": True,     # sudo 免密
    "can_write_system": True,  # 能写 /etc /usr
    "can_manage_services": True,  # 能 systemctl
    "can_kill_any": True,      # 能杀任何进程
    # 正因为权限最高，黑名单检查绝不放水
    "blacklist_always_enforced": True,
}


def get_privilege_level():
    """检测当前实际权限"""
    import subprocess
    try:
        # 是否 root
        if os.geteuid() == 0:
            return "root"
        # 是否 sudo 免密
        r = subprocess.run(["sudo", "-n", "true"],
                           capture_output=True, timeout=5)
        if r.returncode == 0:
            return "sudo_nopasswd"
        return "user"
    except Exception:
        return "unknown"

# ============ 黑名单：绝对禁止 ============
BLACKLIST_PATTERNS = [
    r"rm\s+-rf\s+/\s*$",           # rm -rf /
    r"rm\s+-rf\s+/\*",             # rm -rf /*
    r"mkfs\.",                     # 格式化
    r"dd\s+.*of=/dev/",            # dd 写设备
    r":\(\)\s*\{",                 # fork bomb
    r"shutdown\s+-h\s+now",        # 关机
    r"reboot",                     # 重启
    r"passwd\s+root",              # 改root密码
    r"chmod\s+-R\s+777\s+/",       # 全盘777
    r">\s*/dev/sd",                # 写磁盘设备
]

# ============ 白名单：安全命令 ============
WHITELIST_CMDS = {
    "ls", "cat", "head", "tail", "grep", "find", "ps", "top",
    "df", "du", "free", "uptime", "whoami", "pwd", "echo",
    "ping", "curl", "wget", "python3", "pip3",
}

# ============ 高风险：需人机确认 ============
HIGH_RISK_PATTERNS = [
    r"\brm\b",                     # 删除
    r"\bkill\b",                   # 杀进程
    r"systemctl\s+(stop|disable)",  # 停服务
    r"apt\s+(remove|purge)",        # 卸载
    r">\s*/etc/",                  # 写系统配置
    r"userdel", "usermod",          # 用户管理
]


def classify_risk(command):
    """风险分级"""
    cmd = command.strip()

    # 黑名单 → CRITICAL
    for pattern in BLACKLIST_PATTERNS:
        if re.search(pattern, cmd):
            return "CRITICAL", f"命中黑名单: {pattern}"

    # 高风险 → HIGH
    for pattern in HIGH_RISK_PATTERNS:
        if re.search(pattern, cmd):
            return "HIGH", f"高风险操作: {pattern}"

    # 白名单 → LOW
    first_word = cmd.split()[0] if cmd.split() else ""
    # 去掉 sudo 前缀
    if first_word == "sudo" and len(cmd.split()) > 1:
        first_word = cmd.split()[1]
    if first_word in WHITELIST_CMDS:
        return "LOW", "白名单命令"

    # sudo 开头 → MEDIUM
    if cmd.startswith("sudo"):
        return "MEDIUM", "sudo 操作"

    # 默认 → MEDIUM
    return "MEDIUM", "未分类操作"


def check_command(command):
    """检查命令是否允许执行
    返回: (allowed: bool, risk: str, reason: str)

    权限说明：本系统以最高权限运行，
    因此 HIGH/CRITICAL 的拦截更加严格——
    有权限 ≠ 可以做。
    """
    risk, reason = classify_risk(command)
    priv = get_privilege_level()

    record("safety", "check",
           f"[{risk}][{priv}] {command[:60]}: {reason}",
           level="info" if risk == "LOW" else "warning")

    if risk == "CRITICAL":
        # 最高权限也不放行
        record("safety", "block",
               f"🚫 拦截危险命令 [{priv}]: {command[:80]}",
               level="critical")
        remember("episodic", f"safety-block-{int(time.time())}",
                 f"拦截 [{priv}]: {command[:60]}", importance=0.9,
                 tags=["safety", "block"])
        return False, risk, f"⛔ 绝对禁止（{priv}权限也不行）: {reason}"

    if risk == "HIGH":
        # 高权限下 HIGH 操作更危险，必须确认
        return False, risk, f"⚠️ 需人工确认 [{priv}]: {reason}"

    return True, risk, f"{reason} [{priv}]"


def audit_log(action, command, result, risk):
    """审计日志：谁做了什么"""
    record("safety", "audit",
           f"[{risk}] {action}: {command[:60]} → {result[:40]}")


def safe_run(command, timeout=30, require_confirm=False):
    """安全执行命令（统一入口）
    所有模块执行 shell 命令都应走这里
    """
    import subprocess

    allowed, risk, reason = check_command(command)
    if not allowed:
        if risk == "HIGH" and not require_confirm:
            # HIGH风险：记录但不执行，等待确认
            return False, f"待确认: {reason}"
        return False, reason

    try:
        out = subprocess.check_output(
            command, shell=True, text=True,
            timeout=timeout, stderr=subprocess.STDOUT).strip()
        audit_log("exec", command, "OK", risk)
        return True, out
    except subprocess.CalledProcessError as e:
        audit_log("exec", command, f"EXIT{e.returncode}", risk)
        return False, f"EXIT{e.returncode}: {e.output[:200]}"
    except Exception as e:
        audit_log("exec", command, f"ERROR", risk)
        return False, str(e)


if __name__ == "__main__":
    # 自测
    tests = [
        "ls /tmp",
        "sudo apt-get clean",
        "rm -rf /tmp/test",
        "rm -rf /",
        "echo hello",
    ]
    print("安全层自测:")
    for cmd in tests:
        allowed, risk, reason = check_command(cmd)
        icon = "✅" if allowed else "🚫"
        print(f"  {icon} [{risk:8}] {cmd:25} {reason[:30]}")
