#!/usr/bin/env python3
"""
本地网络守护模块 (Local Network Guardian)
核心职责：保证机器本地网络永远可用

关键逻辑：
1. v2raya 开着但节点死了 → 整个系统断网（含SSH）→ 必须自动断开 v2raya
2. 定期检测：直连通吗？代理通吗？
3. 决策矩阵：
   - 直连通 + 代理通 → 保持代理（需要翻墙时）
   - 直连通 + 代理不通 → 断开 v2raya，用直连
   - 直连不通 + 代理通 → 保持代理（靠代理上网）
   - 都不通 → 断开 v2raya，记录告警，等网络恢复

这是保命模块：SSH 断了就什么都干不了，所以它优先级最高。
"""

import subprocess
import time
import os
import sys
import sqlite3
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recorder import record

V2RAYA_DB = "/etc/v2raya/v2raya.db"
PROXY_SOCKS = "socks5://127.0.0.1:20170"
CHECK_URL = "https://www.google.com"
CHECK_TIMEOUT = 10


def _run(cmd, timeout=15):
    try:
        return subprocess.check_output(
            cmd, shell=True, text=True, timeout=timeout,
            stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def direct_ok():
    """直连通吗"""
    code = _run(
        f"timeout {CHECK_TIMEOUT} curl -s -o /dev/null "
        f"-w '%{{http_code}}' {CHECK_URL}", timeout=CHECK_TIMEOUT + 5)
    return code == "200"


def proxy_ok():
    """代理通吗"""
    code = _run(
        f"timeout {CHECK_TIMEOUT} curl -s -x {PROXY_SOCKS} "
        f"-o /dev/null -w '%{{http_code}}' {CHECK_URL}",
        timeout=CHECK_TIMEOUT + 5)
    return code == "200"


def v2raya_connected():
    """v2raya 当前是否在连接状态"""
    try:
        conn = sqlite3.connect(V2RAYA_DB)
        row = conn.execute(
            "SELECT value FROM system_config WHERE key='system:running'"
        ).fetchone()
        conn.close()
        return row and row[0] == "true"
    except Exception:
        return False


def v2raya_disconnect():
    """断开 v2raya（恢复直连）"""
    try:
        conn = sqlite3.connect(V2RAYA_DB)
        conn.execute(
            "UPDATE system_config SET value='false' "
            "WHERE key='system:running'")
        # 清空连接的服务器
        conn.execute(
            "UPDATE system_config SET value=? WHERE key=?",
            (json.dumps({"touches": []}),
             "outbound.proxy:connectedServers"))
        conn.commit()
        conn.close()
        _run("sudo systemctl restart v2raya", timeout=20)
        record("local_net", "action", "v2raya 已断开，恢复直连",
               level="warning")
        return True
    except Exception as e:
        record("local_net", "error", f"断开 v2raya 失败: {e}",
               level="error")
        return False


def v2raya_connect(server_id):
    """连接指定节点"""
    try:
        conn = sqlite3.connect(V2RAYA_DB)
        val = json.dumps({"touches": [
            {"_type": "server", "id": server_id,
             "sub": 0, "outbound": "proxy"}]})
        conn.execute(
            "UPDATE system_config SET value=? WHERE key=?",
            (val, "outbound.proxy:connectedServers"))
        conn.execute(
            "UPDATE system_config SET value='true' "
            "WHERE key='system:running'")
        conn.commit()
        conn.close()
        _run("sudo systemctl restart v2raya", timeout=20)
        time.sleep(5)
        record("local_net", "action",
               f"v2raya 已连接节点 {server_id}")
        return proxy_ok()
    except Exception as e:
        record("local_net", "error", f"连接节点失败: {e}",
               level="error")
        return False


def get_servers():
    """取所有节点"""
    try:
        conn = sqlite3.connect(V2RAYA_DB)
        rows = conn.execute(
            "SELECT id, substr(link,1,40) FROM servers").fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def guard_cycle():
    """一轮守护检查，返回决策"""
    d_ok = direct_ok()
    p_ok = proxy_ok()
    connected = v2raya_connected()

    record("local_net", "check",
           f"直连:{'✓' if d_ok else '✗'} "
           f"代理:{'✓' if p_ok else '✗'} "
           f"v2raya:{'连接中' if connected else '断开'}")

    # 决策矩阵
    if connected and not p_ok:
        # v2raya 连着但代理不通 → 危险！可能拖死全机网络
        if d_ok:
            record("local_net", "action",
                   "代理失效但直连可用 → 断开 v2raya 保直连",
                   level="warning")
            v2raya_disconnect()
            return "disconnected_bad_proxy"
        else:
            record("local_net", "action",
                   "代理和直连都不通 → 断开 v2raya 等恢复",
                   level="critical")
            v2raya_disconnect()
            return "disconnected_no_net"

    if not connected and not d_ok and not p_ok:
        record("local_net", "check", "全断网，等待恢复",
               level="critical")
        return "waiting"

    return "ok"


def auto_select_node():
    """自动找可用节点并连接"""
    servers = get_servers()
    if not servers:
        record("local_net", "error", "节点库为空", level="error")
        return False
    for sid, link_preview in servers:
        record("local_net", "action", f"尝试节点 {sid}")
        if v2raya_connect(sid):
            record("local_net", "action",
                   f"节点 {sid} 可用，已连接")
            return True
        time.sleep(2)
    record("local_net", "error", "所有节点都不可用",
           level="critical")
    return False


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "--guard":
        print("守护检查...")
        print(f"  结果: {guard_cycle()}")
    elif len(_sys.argv) > 1 and _sys.argv[1] == "--auto":
        print("自动选节点...")
        print(f"  结果: {'成功' if auto_select_node() else '失败'}")
    elif len(_sys.argv) > 1 and _sys.argv[1] == "--disconnect":
        v2raya_disconnect()
        print("已断开")
    else:
        print("本地网络守护模块")
        print("  --guard       一轮检查")
        print("  --auto        自动找可用节点")
        print("  --disconnect  断开 v2raya")
