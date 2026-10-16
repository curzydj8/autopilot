#!/usr/bin/env python3
"""
进程检测工具 (procutil)
精确检测模块进程，替代裸 `pgrep -f`。

为什么不用 pgrep -f：
  `pgrep -f 'supervisor.py'` 经 shell 执行时会产生
  `sh -c "pgrep -f 'supervisor.py' | head -1"` 进程，
  它的完整命令行里含有被查找的字符串，pgrep 会匹配到
  这个 shell 自身 → 误报"进程在运行"（master.py 曾把
  brain 错报为运行中，就是这个原因）。

本模块直接扫描 /proc/<pid>/cmdline，并排除自身及全部
祖先进程，从结构上杜绝自匹配。
"""

import os


def _self_and_ancestors():
    """自身 PID + 全部祖先 PID（调用链上的 shell/python 都排除）"""
    pids = {os.getpid()}
    try:
        pid = os.getpid()
        while True:
            ppid = 0
            try:
                with open(f"/proc/{pid}/status") as f:
                    for line in f:
                        if line.startswith("PPid:"):
                            ppid = int(line.split()[1])
                            break
            except Exception:
                break
            if not ppid or ppid in pids:
                break
            pids.add(ppid)
            pid = ppid
    except Exception:
        pass
    return pids


def _cmdline_of(pid):
    """读 /proc/<pid>/cmdline，失败返回空串"""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode(
                "utf-8", "replace").strip()
    except Exception:
        return ""


def iter_processes():
    """遍历所有进程，yield (pid, cmdline)，跳过不可读的"""
    try:
        entries = os.listdir("/proc")
    except Exception:
        return
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        cmd = _cmdline_of(pid)
        if cmd:
            yield pid, cmd


def find_script_pids(script_name):
    """命令行包含 script_name（如 "supervisor.py"）的进程 PID 列表。

    排除自身及祖先调用链。返回排序后的 PID 列表，无匹配返回 []。
    """
    skip = _self_and_ancestors()
    out = []
    for pid, cmd in iter_processes():
        if pid in skip:
            continue
        if script_name in cmd:
            out.append(pid)
    return sorted(out)


def is_script_running(script_name):
    """脚本是否在运行（精确版，不经过 shell）"""
    return bool(find_script_pids(script_name))


def pid_matches_script(pid, script_name):
    """PID 是否存在且其 cmdline 包含 script_name。

    防 PID 复用误判：PID 文件里的老 PID 被系统回收给了
    别的进程时，os.kill(pid, 0) 仍成功，但 cmdline 对不上。
    """
    try:
        os.kill(pid, 0)
    except Exception:
        return False
    return script_name in _cmdline_of(pid)


if __name__ == "__main__":
    # 自测：python3 不在运行是假；当前解释器 cmdline 含 "procutil"
    import sys as _s
    me = os.path.basename(_s.argv[0]) or "procutil"
    print("self-cmdline-match:", is_script_running(me))
    print("nonexistent-script:", is_script_running(
        "this_script_does_not_exist_xyz.py"))
