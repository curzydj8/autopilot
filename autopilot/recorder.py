#!/usr/bin/env python3
"""
记录模块 (Recorder) —— 系统的"黑匣子"
记录所有：决策、动作、状态变化、异常
支持按时间/类型/模块查询，用于复盘和排障
"""

import json
import os
import time
from datetime import datetime, timedelta

LOG_FILE = os.path.expanduser("~/workspace/autopilot/logs/events.jsonl")
MAX_DAYS = 30


def record(module, event_type, message, data=None, level="info"):
    """记一条事件
    module: 哪个模块 (monitor/healer/supervisor/task_runner/local_net)
    event_type: 事件类型 (check/heal/error/action/state_change)
    level: info/warning/error/critical
    """
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    entry = {
        "ts": time.time(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "module": module,
        "type": event_type,
        "level": level,
        "message": message,
        "data": data or {},
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    # 自动清理旧日志
    _cleanup()
    return entry


def _cleanup():
    """删除30天前的记录"""
    if not os.path.exists(LOG_FILE):
        return
    cutoff = time.time() - MAX_DAYS * 86400
    tmp = LOG_FILE + ".tmp"
    try:
        with open(LOG_FILE) as fin, open(tmp, "w") as fout:
            for line in fin:
                try:
                    e = json.loads(line)
                    if e.get("ts", 0) > cutoff:
                        fout.write(line)
                except Exception:
                    pass
        os.replace(tmp, LOG_FILE)
    except Exception:
        pass


def query(module=None, event_type=None, level=None,
          hours=24, limit=50):
    """查记录"""
    if not os.path.exists(LOG_FILE):
        return []
    cutoff = time.time() - hours * 3600
    results = []
    with open(LOG_FILE) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("ts", 0) < cutoff:
                continue
            if module and e.get("module") != module:
                continue
            if event_type and e.get("type") != event_type:
                continue
            if level and e.get("level") != level:
                continue
            results.append(e)
    return results[-limit:]


def stats(hours=24):
    """统计"""
    events = query(hours=hours, limit=10000)
    by_module = {}
    by_level = {}
    errors = []
    for e in events:
        by_module[e["module"]] = by_module.get(e["module"], 0) + 1
        by_level[e["level"]] = by_level.get(e["level"], 0) + 1
        if e["level"] in ("error", "critical"):
            errors.append(e)
    return {
        "total": len(events),
        "by_module": by_module,
        "by_level": by_level,
        "recent_errors": errors[-5:],
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--stats":
        s = stats()
        print(f"24小时共 {s['total']} 条记录")
        print(f"  模块: {s['by_module']}")
        print(f"  级别: {s['by_level']}")
        for e in s["recent_errors"]:
            print(f"  ✗ [{e['time']}] {e['module']}: {e['message']}")
    elif len(sys.argv) > 2 and sys.argv[1] == "--query":
        for e in query(module=sys.argv[2], limit=10):
            print(f"[{e['time']}] [{e['level']}] {e['message']}")
    else:
        # 测试
        record("recorder", "test", "记录模块自检", level="info")
        print("记录模块OK")
        print("  --stats 看统计, --query <模块名> 查记录")
