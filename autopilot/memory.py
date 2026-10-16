#!/usr/bin/env python3
"""
本地记忆模块 (Local Memory) —— AI 的"海马体"
解决"失忆"问题：所有重要记忆存本地 SQLite，重启不丢。

三类记忆 (仿人类)：
- episodic (情景记忆)：发生过的事 "2026-10-16 装了XFCE"
- semantic (语义记忆)：事实知识 "uinput 需要 input 组权限"
- procedural (程序记忆)：怎么做 "磁盘满→apt clean+journal清理"

记忆有重要度 (0-1)，会随时间衰减，重要的反复强化。
"""

import sqlite3
import os
import time
import json

DB_PATH = os.path.expanduser("~/workspace/autopilot/memory.db")


def _db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mtype TEXT NOT NULL,          -- episodic/semantic/procedural
            key TEXT NOT NULL,            -- 记忆键 (去重用)
            content TEXT NOT NULL,        -- 记忆内容
            importance REAL DEFAULT 0.5,  -- 重要度 0-1
            created REAL NOT NULL,        -- 创建时间戳
            accessed REAL NOT NULL,       -- 最后访问时间戳
            access_count INTEGER DEFAULT 1,
            tags TEXT DEFAULT '[]',       -- JSON 标签列表
            UNIQUE(mtype, key)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_type ON memories(mtype)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_importance ON memories(importance DESC)
    """)
    return conn


def remember(mtype, key, content, importance=0.5, tags=None):
    """存一条记忆。已存在则更新（强化）。"""
    conn = _db()
    now = time.time()
    tags_json = json.dumps(tags or [], ensure_ascii=False)
    try:
        conn.execute(
            """INSERT INTO memories
               (mtype, key, content, importance, created, accessed, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (mtype, key, content, importance, now, now, tags_json))
    except sqlite3.IntegrityError:
        # 已存在 → 强化：重要度提升，访问计数+1
        row = conn.execute(
            "SELECT importance, access_count FROM memories "
            "WHERE mtype=? AND key=?", (mtype, key)).fetchone()
        new_imp = min(1.0, (row[0] + importance) / 2 + 0.1)
        conn.execute(
            """UPDATE memories SET content=?, importance=?,
               accessed=?, access_count=access_count+1, tags=?
               WHERE mtype=? AND key=?""",
            (content, new_imp, now, tags_json, mtype, key))
    conn.commit()
    conn.close()


def recall(query=None, mtype=None, limit=10, min_importance=0.0):
    """回忆：按关键词/类型查，重要度排序"""
    conn = _db()
    sql = "SELECT mtype, key, content, importance, access_count FROM memories WHERE 1=1"
    params = []
    if mtype:
        sql += " AND mtype=?"
        params.append(mtype)
    if query:
        sql += " AND (content LIKE ? OR key LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%"])
    if min_importance > 0:
        sql += " AND importance >= ?"
        params.append(min_importance)
    # 重要度 * 新鲜度 综合排序
    sql += " ORDER BY importance DESC, accessed DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    # 更新访问时间
    now = time.time()
    for r in rows:
        conn.execute(
            "UPDATE memories SET accessed=?, access_count=access_count+1 "
            "WHERE mtype=? AND key=?", (now, r[0], r[1]))
    conn.commit()
    conn.close()
    return [{"type": r[0], "key": r[1], "content": r[2],
             "importance": r[3], "accessed": r[4]} for r in rows]


def forget(mtype, key):
    """删一条记忆"""
    conn = _db()
    conn.execute("DELETE FROM memories WHERE mtype=? AND key=?",
                 (mtype, key))
    conn.commit()
    conn.close()


def decay(hours=24):
    """记忆衰减：N小时未访问的重要性衰减（重要的衰减慢）"""
    conn = _db()
    now = time.time()
    cutoff = now - hours * 3600
    # 未访问超过阈值的，重要度 *= 0.95 (重要记忆衰减慢)
    conn.execute(
        """UPDATE memories SET importance =
           CASE WHEN importance > 0.8 THEN importance * 0.99
                WHEN importance > 0.5 THEN importance * 0.97
                ELSE importance * 0.95 END
           WHERE accessed < ?""", (cutoff,))
    # 删除重要度 < 0.1 且 30天未访问的
    old = now - 30 * 86400
    conn.execute(
        "DELETE FROM memories WHERE importance < 0.1 AND accessed < ?",
        (old,))
    conn.commit()
    conn.close()


def stats():
    """记忆统计"""
    conn = _db()
    total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    by_type = dict(conn.execute(
        "SELECT mtype, COUNT(*) FROM memories GROUP BY mtype").fetchall())
    conn.close()
    return {"total": total, "by_type": by_type}


def export_all():
    """导出全部记忆 (备份用)"""
    conn = _db()
    rows = conn.execute(
        "SELECT mtype, key, content, importance, tags FROM memories "
        "ORDER BY importance DESC").fetchall()
    conn.close()
    return [{"type": r[0], "key": r[1], "content": r[2],
             "importance": r[3], "tags": json.loads(r[4])}
            for r in rows]


# 预置核心记忆（系统出生自带）
def seed():
    remember("semantic", "uinput-permission",
             "uinput 需要用户在 input 组，否则 OSError",
             importance=0.9, tags=["linux", "input"])
    remember("semantic", "ssh-tunnel-unstable",
             "SSH 隧道经常闪断 (Connection closed by UNKNOWN)，等待重试是常态",
             importance=0.9, tags=["ssh", "network"])
    remember("semantic", "wayland-no-xdotool",
             "Wayland 下 xdotool 不可用，用 uinput 或 ydotool",
             importance=0.8, tags=["wayland", "input"])
    remember("procedural", "disk-cleanup",
             "磁盘满时：sudo apt-get clean; journalctl --vacuum-time=3d; 清/tmp旧文件",
             importance=0.8, tags=["disk", "heal"])
    remember("procedural", "v2raya-bad-node",
             "v2raya 节点失效时必须断开，否则全机断网（含SSH）",
             importance=0.95, tags=["network", "v2raya", "critical"])
    remember("episodic", "2026-10-16-xfce",
             "2026-10-16 用户嫌KDE变暗，换到XFCE，已禁用休眠",
             importance=0.7, tags=["desktop"])
    remember("episodic", "2026-10-16-autopilot-born",
             "2026-10-16 自主AI系统 autopilot 诞生，11模块",
             importance=0.9, tags=["system"])


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "--seed":
        seed()
        print("核心记忆已植入")
    elif len(_sys.argv) > 2 and _sys.argv[1] == "--recall":
        for m in recall(query=" ".join(_sys.argv[2:])):
            print(f"[{m['type']}] {m['key']}: {m['content'][:60]} "
                  f"(重要度{m['importance']:.2f})")
    elif len(_sys.argv) > 1 and _sys.argv[1] == "--stats":
        s = stats()
        print(f"共 {s['total']} 条记忆: {s['by_type']}")
    elif len(_sys.argv) > 1 and _sys.argv[1] == "--decay":
        decay()
        print("衰减完成")
    else:
        print("本地记忆模块")
        print("  --seed              植入核心记忆")
        print("  --recall <关键词>   回忆")
        print("  --stats             统计")
        print("  --decay             记忆衰减")
