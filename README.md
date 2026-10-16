# 自主 AI 系统 (Autonomous AI System)

> 运行在本地的完全自主 AI：能上网、写程序、玩游戏，像人类一样操作电脑，自己进化自己。

## 设计哲学

```
人能做的，机器都能做。
机器不会的，机器自己学。
学不会的，机器自己写程序来学。
```

## 系统架构

```
                    ┌──────────────┐
                    │  supervisor  │ ← 总控 (5分钟循环)
                    └──────┬───────┘
        ┌──────────────────┼──────────────────┐
   ┌────▼────┐       ┌────▼────┐       ┌────▼────┐
   │ monitor │       │ healer  │       │local_net│
   └─────────┘       └─────────┘       └─────────┘
   ┌────▼────┐       ┌────▼────┐       ┌────▼────┐
   │recorder │       │learner  │       │scenarios│
   └─────────┘       └─────────┘       └─────────┘
                    ┌──────▼───────┐
                    │    evolve    │ ← 自我进化引擎
                    └──────────────┘
```

## 模块

| 模块 | 功能 | 状态 |
|------|------|------|
| supervisor | 总调度 | 🟢 |
| monitor | 系统监控 | 🟢 |
| healer | 自愈 | 🟢 |
| local_net | 网络守护 | 🟢 |
| recorder | 事件记录 | 🟢 |
| learner | 技能库 | 🟢 |
| scenarios | 复杂场景 | 🟢 |
| evolve | 自我进化 | 🟢 |
| vision | 截屏/OCR | 🟠 |
| brain | 认知循环 | ⚪ |
| human_input | 人类模拟输入 | 🟡 |

## 人类行为模拟

基于 Linux uinput 内核级模拟，应用视为真实硬件：
- **鼠标**：贝塞尔曲线、变速、抖动、过冲修正
- **键盘**：高斯按键间隔、词间停顿、错字纠正

```python
from human_input import HumanInput
hi = HumanInput()
hi.click(500, 300)              # 人类点击
hi.type("hello world")          # 人类打字
hi.click_and_type(500,300,"hi") # 点输入框+打字
```

## 自我进化

```bash
python3 evolve.py "磁盘空间不足"  # 自动分析→生成→测试→纳入
python3 evolve.py --auto           # 扫描未解决问题并进化
```

## 架构管理

```bash
python3 arch_manager.py              # 状态
python3 arch_manager.py --validate   # 验证
python3 arch_manager.py --upgrade    # 升级检查
```

## 文档

- [整体架构](ARCHITECTURE.md)
- [开发日志](docs/DEV_LOG.md) — 全过程记录：问题→解决

## 许可证

MIT
