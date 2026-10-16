# 自主 AI 系统规格书 (SPEC.md)

> 版本: v1.0 | 日期: 2026-10-16
> 对应架构: v1.6 | 仓库: curzydj8/autopilot

---

## 1. 系统目标

构建运行在本地 Ubuntu 机器上的完全自主 AI，能够：
- 像人类一样操作电脑（鼠标键盘模拟，反机器人检测）
- 自我监控、自愈、学习、进化
- 长期记忆，重启不失忆
- 任务队列驱动，自主执行

### 1.1 设计原则（GPT 建议采纳）

> **先做可靠的执行闭环，再做更聪明的 AI。**
> 模型可以随时替换，但以下必须始终由系统掌握：
> - 中央控制器 (master.py)
> - 工具接口 (human_input.py)
> - 权限系统 (待建)
> - 验证机制 (verify.py)
> - 任务持久化 (tasks.json + memory.db)

### 1.2 演进路线

```
单机 Ubuntu (当前) 
  → Windows 控制代理 
  → 本地推理模型 
  → 专业智能体 
  → 跨机器协作平台
```

---

## 2. 模块规格

### 2.1 master.py — 主控中心

**接口：**
```
master.py start [模块]     # 启动
master.py stop [模块]      # 停止
master.py restart          # 重启全部
master.py status           # 状态总览
master.py logs [模块]      # 日志
```

**数据结构：**
```python
MODULES = {
    "name": {"cmd": str, "desc": str, "daemon": bool}
}
PID_DIR = "pids/{name}.pid"
```

**权限：** 需 sudo 启动服务类模块

**测试用例：**
- [ ] start 后 pgrep 能找到进程
- [ ] stop 后进程消失，PID文件删除
- [ ] status 显示正确

---

### 2.2 scheduler.py — 调度器

**接口：**
```python
register_task(name, func, priority=2, interval=300, depends=None)
run_due_tasks()  # 返回执行的任务列表
scheduler_loop()  # 主循环
```

**优先级：**
| 级别 | 含义 | 示例 | 间隔 |
|------|------|------|------|
| P0 | 紧急 | emergency | 30s |
| P1 | 重要 | 网络守护 | 5min |
| P2 | 常规 | 监控自愈 | 10min |
| P3 | 后台 | 进化归档 | 30min |

**数据结构：**
```python
_tasks[name] = {
    "func": callable, "priority": int, "interval": int,
    "last_run": float, "depends": [str],
    "run_count": int, "fail_count": int
}
```

**资源感知：** P2/P3 在 CPU>80% 时跳过

**测试用例：**
- [ ] 高优先级先执行
- [ ] 依赖未满足时不执行
- [ ] CPU高时 P2/P3 跳过

---

### 2.3 supervisor.py — 总控

**职责：** 5分钟主循环：监控→分析→自愈→网络守护→场景→进化→记忆→优化

**循环步骤：**
```
1. monitor.get_full_status()
2. analyze() → issues[]
3. healer.run_all_heals()
4. local_net.guard_cycle()      # P1
5. scenarios.run_all_scenarios() # 每3轮
6. evolve.auto_evolve_check()    # 每6轮
7. consolidate()                 # 每12轮
8. optimizer.optimize_all()      # 每10轮
```

**测试用例：**
- [ ] 一轮循环 < 60秒
- [ ] 异常不中断循环（连续5次异常才暂停）

---

### 2.4 emergency.py — 紧急处理

**P0 触发条件：**
| 条件 | 阈值 | 动作 |
|------|------|------|
| 磁盘 | >95% | 紧急清理 |
| 内存 | >97% | 清缓存+记录 |
| 全断网 | 直连✗+代理✗ | 断v2raya |
| supervisor死 | pgrep无 | 重启 |
| CPU温度 | >95°C | 告警 |

**接口：** `emergency.py --check` 单次检查

**测试用例：**
- [ ] 模拟磁盘95% → 触发清理
- [ ] 杀掉supervisor → 30秒内重启

---

### 2.5 monitor.py — 监控

**采集项：**
```python
{
    "cpu_pct": float, "mem_pct": float, "disk_pct": float,
    "temp_c": float, "network": bool,
    "processes": {"name": bool},
    "waydroid": str, "tasks": {...}
}
```

**接口：** `get_full_status()` / `monitor.py --json`

---

### 2.6 healer.py — 自愈

**修复表：**
| 问题 | 动作 |
|------|------|
| 磁盘>90% | apt clean + journal + /tmp |
| Waydroid停 | show-full-ui |
| 内存>90% | 记录Top进程 |

**测试用例：**
- [ ] 修复后记录到 heal_log.json

---

### 2.7 local_net.py — 网络守护

**决策矩阵：**
| 直连 | 代理 | v2raya | 动作 |
|------|------|--------|------|
| ✓ | ✓ | 连 | 保持 |
| ✓ | ✗ | 连 | 断开v2raya |
| ✗ | ✓ | 连 | 保持 |
| ✗ | ✗ | 连 | 断开+告警 |
| ✗ | ✗ | 断 | 等待 |

**接口：**
```
local_net.py --guard       # 一轮检查
local_net.py --auto        # 自动找可用节点
local_net.py --disconnect  # 断开
```

**权限策略：** 修改 v2raya 数据库需 sudo；这是保命操作，自动执行无需确认

---

### 2.8 recorder.py — 记录

**事件格式：**
```json
{"ts": float, "time": str, "module": str, "type": str,
 "level": "info|warning|error|critical",
 "message": str, "data": {}}
```

**接口：** `record(module, type, msg, data, level)` / `query()` / `stats()`

**保留策略：** 30天滚动

---

### 2.9 learner.py — 学习

**技能格式：**
```json
{"pattern": str, "solution": str, "description": str,
 "success_count": int, "fail_count": int, "last_used": str}
```

**进化规则：** 成功→success+1，失败→fail+1，按成功率排序选用

---

### 2.10 scenarios.py — 复杂场景

| 场景 | 触发 | 处理 |
|------|------|------|
| waydroid_stuck | 30秒无进展 | 杀掉重启 |
| disk_full | >85% | 三级清理 |
| high_load | >1.5×CPU数 | 诊断Top |
| service_dead | pgrep无 | 重启 |

---

### 2.11 evolve.py — 自我进化

**流程：** 分析→生成→沙盒测试→评估→纳入/记录

**安全策略：**
- 生成代码先在 sandbox/ 测试
- 语法检查 + 超时60秒
- 一轮最多进化3个（防失控）
- 失败记录教训，不重复试

**测试用例：**
- [ ] "磁盘95%" → 生成可用清理程序
- [ ] 恶意输入不执行危险命令

---

### 2.12 memory.py — 本地记忆

**三类：**
- episodic: 情景记忆（发生的事）
- semantic: 语义记忆（事实）
- procedural: 程序记忆（怎么做）

**机制：**
- 重要度 0-1，新记忆0.5，强化+0.1
- 衰减：重要0.99/中0.97/低0.95 每周期
- 清理：<0.1 且30天未访问则删除

**接口：** `remember()` / `recall()` / `forget()` / `decay()`

---

### 2.13 consolidate.py — 记忆整合

**流程：** recorder事件 → 分类 → 长期记忆 → 衰减

**触发：** supervisor 每12轮

---

### 2.14 optimizer.py — 优化器

**优化项：**
- 日志轮转（>10M压缩）
- 内存整理（drop_caches）
- 磁盘清理
- 后台状态检查

**触发：** supervisor 每10轮

---

### 2.15 verify.py — 验证修复引擎

**流程：** 测试→分析→提方案→执行→确认

**测试注册表：** `TEST_CASES[模块] = {test, expect, desc}`

**测试用例：**
- [ ] 全模块测试通过
- [ ] 模拟失败→自动修复→确认

---

### 2.16 vision.py — 眼睛

**功能：** 截屏 / 找图(模板匹配) / OCR

**状态：** 🟠 degraded（缺mss）

**验收标准：** `vision.py --shot` 返回有效PNG路径

---

### 2.17 brain.py — 大脑

**循环：** 感知→思考→行动→学习

**状态：** ⚪ standby（等vision）

**验收标准：** 能完成设定的多步目标

---

### 2.18 human_input.py — 人类输入

**鼠标：** 贝塞尔曲线 + 变速 + 抖动 + 过冲修正
**键盘：** 高斯间隔 + 词间停顿 + 错字纠正

**反检测原理：** uinput内核级 + 人类化timing

**测试用例：**
- [ ] 移动轨迹非直线
- [ ] 点击间隔随机

---

### 2.19 upgrader.py — 模块升级

**流程：** 备份→替换→验证→重载→失败回滚

**安全：** 保留3个版本

---

### 2.20 arch_manager.py — 架构管理

**接口：** status / validate / register / upgrade / rollback

**版本规则：** 每次变更 minor+1

---

## 3. 数据持久化

| 数据 | 位置 | 格式 |
|------|------|------|
| 架构 | architecture.json | JSON |
| 记忆 | memory.db | SQLite |
| 事件 | logs/events.jsonl | JSONL |
| 技能 | skills/skill_registry.json | JSON |
| 任务 | task-queue/tasks.json | JSON |
| 备份 | arch_backups/ | JSON |

## 4. 权限策略

| 操作 | 权限 | 确认 |
|------|------|------|
| 读状态 | 无 | 自动 |
| 清缓存/日志 | sudo | 自动 |
| 断v2raya（保命） | sudo | 自动 |
| 杀进程 | sudo | P0自动，其他确认 |
| 删文件 | - | 需确认 |
| 对外发送 | - | 需确认 |

## 5. 阶段验收标准

### Phase 1: 可靠闭环 ✅ (已完成)
- [x] 所有模块可独立运行
- [x] supervisor 5分钟循环稳定
- [x] emergency 30秒P0响应
- [x] verify 全模块测试通过

### Phase 2: 感知行动 (进行中)
- [ ] vision 截屏正常
- [ ] brain 认知循环跑通
- [ ] human_input 完成端到端操作

### Phase 3: 智能升级 (待)
- [ ] 本地推理模型接入
- [ ] 任务自动分解
- [ ] 跨应用协作

### Phase 4: 多机协作 (未来)
- [ ] Windows 控制代理
- [ ] 机器间任务分发
- [ ] 联邦记忆

---

## 6. 附录：GPT 咨询工作流（待浏览器就绪）

用户要求：未来系统能自己打开浏览器 → GPT网页 → 提问 → 获取不同视角 → 引入优化。

**前置条件：**
- [ ] vision 截屏正常（眼睛）
- [ ] 浏览器自动化（human_input + vision 配合）
- [ ] ChatGPT 网页可访问（需代理）

**流程设计：**
```
1. 遇到难题 → 构造问题
2. 打开浏览器 → chat.openai.com
3. 人类模拟输入问题
4. 截屏读回答（OCR）
5. 对比本地方案 → 融合优化
6. 记入记忆：gpt_suggestion
```

**状态：** 待 vision + 代理就绪后实现
