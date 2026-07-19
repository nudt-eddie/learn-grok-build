# Mini Grok - 精简版 Coding Agent 实现

用 Python 复刻 Grok Build 核心功能，对照源码进行讲解。

## 设计目标

参考 Grok Build 架构，实现一个最小可用的 Coding Agent：

```python
# 核心架构
User Input → Agent Loop (Actor) → Model → Tool Call → Execute → Response
                ↓
         Session State (Actor)
                ↓
         Context Assembly
```

## 核心模块

| 模块 | 源码对应 | 说明 |
|------|----------|------|
| `agent_loop.py` | xai-chat-state/actor | Actor 模型的会话状态管理 |
| `tool_system.py` | xai-grok-tools | 工具注册和调用 |
| `context.py` | xai-chat-state | 上下文组装和 Token 管理 |
| `session.py` | xai-grok-shell | 会话生命周期 |
| `compaction.py` | xai-chat-state/compaction | 上下文压缩 |

## 对照源码

每个 Python 实现都标注对应的 Go/Rust 源码位置：
- `[SOURCE]` - 直接对应源码实现
- `[OBSERVED]` - 从源码观察到的模式
- `[INFERENCE]` - 基于源码的推断

## 运行

```bash
cd mini-grok
pip install -e .
python examples/minimal_loop.py
```
