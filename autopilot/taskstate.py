#!/usr/bin/env python3
"""
任务状态机 + checkpoint (taskstate.py)

替代 supervisor 裸循环里的" fire-and-forget"任务：
  pending → running → done
      ↓
    failed → retry → running → done
                      ↓ (attempt 耗尽)
                 dead_letter

- SQLite 持久化，进程崩溃/重启后可恢复
- attempt / timeout / next_retry（指数退避）/ checkpoint / trace_id
- 幂等提交：同一 task_id 重复 submit 返回已存在任务
- claim_next 原子领取，支持多 worker

用法:
  taskstate.py submit <name> [payload_json]
  taskstate.py claim | complete <id> | fail <id> <error>
  taskstate.py list [state] | stats | recover | reap
  taskstate.py --test
"""

import os
import sys
import json
import time
import uuid
import sqlite3

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(MODULE_DIR, "tasks.db")

STATES = ("pending", "running", "done", "failed",
          "retry", "dead_letter")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    payload      TEXT NOT NULL DEFAULT '{}',
    state        TEXT NOT NULL DEFAULT 'pending',
    attempt      INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    timeout_sec  INTEGER NOT NULL DEFAULT 300,
    next_retry_at REAL NOT NULL DEFAULT 0,
    checkpoint   TEXT NOT NULL DEFAULT '{}',
    trace_id     TEXT NOT NULL DEFAULT '',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    started_at   REAL NOT NULL DEFAULT 0,
    last_error   TEXT NOT NULL DEFAULT '',
    result       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state, next_retry_at);
"""


def _db():
    os.path.dirname(DB_PATH) or None
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _now():
    return time.time()


def _row_to_dict(r):
    return dict(r) if r else None


def submit(name, payload=None, max_attempts=3, timeout_sec=300,
           trace_id=None, run_at=None, task_id=None):
    """提交任务。task_id 已存在则幂等返回（不重复建）。"""
    tid = task_id or f"t_{uuid.uuid4().hex[:12]}"
    now = _now()
    conn = _db()
    try:
        cur = conn.execute("SELECT * FROM tasks WHERE id=?", (tid,))
        existing = _row_to_dict(cur.fetchone())
        if existing:
            return existing
        conn.execute(
            """INSERT INTO tasks
               (id,name,payload,state,attempt,max_attempts,timeout_sec,
                next_retry_at,checkpoint,trace_id,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (tid, name, json.dumps(payload or {}), "pending", 0,
             max_attempts, timeout_sec, run_at or 0, "{}",
             trace_id or uuid.uuid4().hex[:16], now, now))
        conn.commit()
        return get(tid)
    finally:
        conn.close()


def get(task_id):
    conn = _db()
    try:
        cur = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        return _row_to_dict(cur.fetchone())
    finally:
        conn.close()


def claim_next():
    """原子领取一个可执行任务（pending 或到期的 retry），返回任务 dict 或 None。

    领取后状态 → running，attempt+1，started_at=now。
    """
    now = _now()
    conn = _db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            """SELECT id FROM tasks
               WHERE (state='pending' OR
                      (state='retry' AND next_retry_at <= ?))
               ORDER BY created_at LIMIT 1""", (now,))
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return None
        tid = row["id"]
        conn.execute(
            """UPDATE tasks SET state='running', attempt=attempt+1,
               started_at=?, updated_at=? WHERE id=?""",
            (now, now, tid))
        conn.commit()
        return get(tid)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    finally:
        conn.close()


def heartbeat(task_id, checkpoint=None):
    """执行中上报：刷新 updated_at，可选保存 checkpoint（json 可序列化）。"""
    conn = _db()
    try:
        if checkpoint is not None:
            conn.execute(
                "UPDATE tasks SET checkpoint=?, updated_at=? WHERE id=?",
                (json.dumps(checkpoint), _now(), task_id))
        else:
            conn.execute("UPDATE tasks SET updated_at=? WHERE id=?",
                         (_now(), task_id))
        conn.commit()
        return True
    finally:
        conn.close()


def complete(task_id, result=None):
    conn = _db()
    try:
        conn.execute(
            """UPDATE tasks SET state='done', result=?, updated_at=?
               WHERE id=? AND state='running'""",
            (json.dumps(result) if result is not None else "",
             _now(), task_id))
        conn.commit()
        return conn.total_changes > 0
    finally:
        conn.close()


def _backoff_delay(attempt):
    return min(30 * (2 ** max(0, attempt - 1)), 1800)


def fail(task_id, error="", retry_delay=None):
    """任务失败：attempt < max_attempts → retry（指数退避），否则 dead_letter。"""
    conn = _db()
    try:
        t = get(task_id)
        if not t or t["state"] != "running":
            return None
        now = _now()
        if t["attempt"] >= t["max_attempts"]:
            new_state, nxt = "dead_letter", 0
        else:
            new_state = "retry"
            nxt = now + (retry_delay if retry_delay is not None
                         else _backoff_delay(t["attempt"]))
        conn.execute(
            """UPDATE tasks SET state=?, next_retry_at=?, last_error=?,
               updated_at=? WHERE id=?""",
            (new_state, nxt, str(error)[:500], now, task_id))
        conn.commit()
        return get(task_id)
    finally:
        conn.close()


def reap_timeouts():
    """把超时的 running 任务（started_at + timeout < now）转回 retry/dead_letter。"""
    now = _now()
    conn = _db()
    try:
        cur = conn.execute(
            "SELECT id FROM tasks WHERE state='running' "
            "AND started_at + timeout_sec < ?", (now,))
        ids = [r["id"] for r in cur.fetchall()]
    finally:
        conn.close()
    for tid in ids:
        fail(tid, "timeout: 执行超时")
    return ids


def recover():
    """启动恢复：崩溃时卡在 running 的任务 → retry（立即），attempt 保留。"""
    now = _now()
    conn = _db()
    try:
        cur = conn.execute(
            "SELECT id, attempt, max_attempts FROM tasks WHERE state='running'")
        rows = cur.fetchall()
        n = 0
        for r in rows:
            if r["attempt"] >= r["max_attempts"]:
                conn.execute(
                    "UPDATE tasks SET state='dead_letter', last_error=?,"
                    " updated_at=? WHERE id=?",
                    ("recover: 重启时已耗尽重试", now, r["id"]))
            else:
                conn.execute(
                    "UPDATE tasks SET state='retry', next_retry_at=?,"
                    " last_error=?, updated_at=? WHERE id=?",
                    (now, "recover: 重启前卡在 running", now, r["id"]))
            n += 1
        conn.commit()
        return n
    finally:
        conn.close()


def list_tasks(state=None, limit=50):
    conn = _db()
    try:
        if state:
            cur = conn.execute(
                "SELECT * FROM tasks WHERE state=? "
                "ORDER BY updated_at DESC LIMIT ?", (state, limit))
        else:
            cur = conn.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?",
                (limit,))
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def stats():
    conn = _db()
    try:
        cur = conn.execute(
            "SELECT state, COUNT(*) c FROM tasks GROUP BY state")
        return {r["state"]: r["c"] for r in cur.fetchall()}
    finally:
        conn.close()


def _self_test():
    """自测：提交→领取→checkpoint→完成→失败→退避→死信→崩溃恢复"""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    # 1. 幂等提交
    t1 = submit("demo_task", {"k": 1}, task_id="selftest_1")
    t1b = submit("demo_task", {"k": 2}, task_id="selftest_1")
    assert t1["id"] == t1b["id"] and t1b["payload"] == '{"k": 1}', "幂等提交"
    # 2. 领取 → running, attempt=1
    c = claim_next()
    assert c and c["id"] == "selftest_1" and c["state"] == "running" \
        and c["attempt"] == 1, "领取"
    assert claim_next() is None, "无重复领取"
    # 3. checkpoint
    heartbeat("selftest_1", {"step": 2, "note": "做到一半"})
    assert json.loads(get("selftest_1")["checkpoint"])["step"] == 2, \
        "checkpoint"
    # 4. 完成
    assert complete("selftest_1", {"ok": True}), "完成"
    assert get("selftest_1")["state"] == "done", "done 状态"
    assert complete("selftest_1") is False, "非 running 不能重复完成"
    # 5. 失败 → retry（退避），耗尽 → dead_letter
    submit("fail_task", task_id="selftest_2", max_attempts=2)
    claim_next(); fail("selftest_2", "boom1")
    t = get("selftest_2")
    assert t["state"] == "retry" and t["next_retry_at"] > _now(), "退避重试"
    t["next_retry_at"] = 0  # 手动到期以便测试
    conn = _db(); conn.execute(
        "UPDATE tasks SET next_retry_at=0 WHERE id='selftest_2'"); conn.commit(); conn.close()
    c2 = claim_next()
    assert c2 and c2["id"] == "selftest_2" and c2["attempt"] == 2, "重试领取"
    fail("selftest_2", "boom2")
    assert get("selftest_2")["state"] == "dead_letter", "死信"
    # 6. 崩溃恢复：running 卡死 → recover → retry
    submit("crash_task", task_id="selftest_3")
    claim_next()
    assert recover() == 1, "恢复数量"
    assert get("selftest_3")["state"] == "retry", "恢复为 retry"
    # 让 selftest_3 的重试暂未到期，避免干扰后面的领取顺序
    conn = _db(); conn.execute(
        "UPDATE tasks SET next_retry_at=? WHERE id='selftest_3'",
        (_now() + 3600,)); conn.commit(); conn.close()
    # 7. 超时回收
    submit("timeout_task", task_id="selftest_4", timeout_sec=1)
    claim_next()
    time.sleep(1.2)
    assert reap_timeouts() == ["selftest_4"], "超时回收"
    assert get("selftest_4")["state"] == "retry", "超时转 retry"
    s = stats()
    assert s.get("done") == 1 and s.get("dead_letter") == 1, f"统计 {s}"
    os.remove(DB_PATH)
    print("taskstate 自测全部通过 (7组)")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "help"
    if a == "--test":
        _self_test()
    elif a == "submit" and len(sys.argv) > 2:
        payload = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        t = submit(sys.argv[2], payload)
        print(json.dumps(t, ensure_ascii=False, indent=1)[:600])
    elif a == "claim":
        t = claim_next()
        print(json.dumps(t, ensure_ascii=False) if t else "无可领取任务")
    elif a == "complete" and len(sys.argv) > 2:
        print("ok" if complete(sys.argv[2]) else "失败(非running?)")
    elif a == "fail" and len(sys.argv) > 3:
        t = fail(sys.argv[2], sys.argv[3])
        print(t["state"] if t else "失败")
    elif a == "list":
        st = sys.argv[2] if len(sys.argv) > 2 else None
        for t in list_tasks(st):
            print(f"{t['id']} {t['name']:20} {t['state']:10} "
                  f"attempt={t['attempt']}/{t['max_attempts']}")
    elif a == "stats":
        print(stats())
    elif a == "recover":
        print(f"恢复 {recover()} 个卡死的 running 任务")
    elif a == "reap":
        print(f"回收超时: {reap_timeouts()}")
    else:
        print(__doc__)
