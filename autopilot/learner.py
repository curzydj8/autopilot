#!/usr/bin/env python3
"""
学习模块 (Learner) —— 系统的"经验本"
记录：什么问题 → 怎么解决的 → 效果如何
下次遇到类似问题，直接复用成功过的方案

技能格式:
{
  "pattern": "问题特征关键词",
  "solution": "解决命令/步骤",
  "success_count": 3,
  "fail_count": 0,
  "last_used": "2026-10-16 08:00:00"
}
"""

import json
import os
import time

SKILL_DB = os.path.expanduser("~/workspace/autopilot/skills/skill_registry.json")

# 预置技能 (开箱即用的经验)
BUILTIN_SKILLS = [
    {
        "pattern": "waydroid status STOPPED",
        "solution": "waydroid show-full-ui &",
        "description": "Waydroid 停止后重启 UI",
        "success_count": 0, "fail_count": 0, "last_used": "",
    },
    {
        "pattern": "disk usage > 90%",
        "solution": "sudo apt-get clean; journalctl --vacuum-time=3d",
        "description": "磁盘满清理",
        "success_count": 0, "fail_count": 0, "last_used": "",
    },
    {
        "pattern": "uinput OSError Errno 22",
        "solution": "去掉 EV_ABS，只用 EV_REL 相对移动",
        "description": "uinput ABS 参数无效时的替代方案",
        "success_count": 1, "fail_count": 0,
        "last_used": "2026-10-16 06:00:00",
    },
    {
        "pattern": "ssh Connection closed by UNKNOWN",
        "solution": "等待后重试，隧道不稳定是常态",
        "description": "SSH 隧道闪断处理",
        "success_count": 5, "fail_count": 0,
        "last_used": "2026-10-16 07:00:00",
    },
    {
        "pattern": "gradle build.gradle unable to resolve class val",
        "solution": "build.gradle 用 Groovy 语法，不用 Kotlin DSL",
        "description": "Gradle 脚本语法",
        "success_count": 1, "fail_count": 0,
        "last_used": "2026-10-15 23:00:00",
    },
]


def load_skills():
    if os.path.exists(SKILL_DB):
        try:
            with open(SKILL_DB) as f:
                return json.load(f)
        except Exception:
            pass
    # 首次：写入预置技能
    save_skills(BUILTIN_SKILLS)
    return BUILTIN_SKILLS.copy()


def save_skills(skills):
    os.makedirs(os.path.dirname(SKILL_DB), exist_ok=True)
    with open(SKILL_DB, "w") as f:
        json.dump(skills, f, ensure_ascii=False, indent=2)


def find_skill(problem_text):
    """按关键词找最匹配的技能 (成功率优先)"""
    skills = load_skills()
    candidates = []
    for s in skills:
        if s["pattern"].lower() in problem_text.lower():
            total = s["success_count"] + s["fail_count"]
            rate = s["success_count"] / max(1, total)
            candidates.append((rate, s))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]


def record_result(pattern, success):
    """记录一次技能使用结果 → 成功率进化"""
    skills = load_skills()
    for s in skills:
        if s["pattern"] == pattern:
            if success:
                s["success_count"] += 1
            else:
                s["fail_count"] += 1
            s["last_used"] = time.strftime("%Y-%m-%d %H:%M:%S")
            break
    else:
        # 新技能
        skills.append({
            "pattern": pattern,
            "solution": "",
            "description": "新记录，待补充方案",
            "success_count": 1 if success else 0,
            "fail_count": 0 if success else 1,
            "last_used": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
    save_skills(skills)


def learn_new_skill(pattern, solution, description=""):
    """学到新技能"""
    skills = load_skills()
    # 去重
    for s in skills:
        if s["pattern"] == pattern:
            s["solution"] = solution
            if description:
                s["description"] = description
            save_skills(skills)
            return
    skills.append({
        "pattern": pattern,
        "solution": solution,
        "description": description,
        "success_count": 0, "fail_count": 0, "last_used": "",
    })
    save_skills(skills)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        for s in load_skills():
            total = s["success_count"] + s["fail_count"]
            rate = s["success_count"] / max(1, total) * 100
            print(f"  [{rate:.0f}%] {s['pattern']}")
            print(f"       → {s['solution']}")
    elif len(sys.argv) > 2 and sys.argv[1] == "--find":
        s = find_skill(" ".join(sys.argv[2:]))
        if s:
            print(f"找到: {s['solution']}")
        else:
            print("没找到匹配技能")
    else:
        print(f"技能库: {len(load_skills())} 个")
        print("  --list 看全部, --find <关键词> 搜索")
