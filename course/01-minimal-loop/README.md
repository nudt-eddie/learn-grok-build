# Chapter 01: Minimal Actor Loop / 第一章：最小 Actor 循环

## 本章目标 / Chapter Objectives

- 理解 Actor 模式的基本概念与 Rust 实现 / Understand the fundamental Actor pattern and its Rust implementation
- 掌握 `ChatStateActor` 的核心结构与消息循环 / Master the core structure and message loop of `ChatStateActor`
- 学会使用 channel 进行异步通信 / Learn asynchronous communication using channels
- 实现一个最小化的 Python actor 对比理解 / Implement a minimal Python actor for comparative understanding

---

## 源码分析 / Source Code Analysis

### 1. Actor 模式概述 / Overview of Actor Pattern

Actor 模式是一种并发编程模型，每个 Actor 是一个独立的执行单元，通过消息传递进行通信。`ChatStateActor` 是 Grok 对话系统的核心组件，运行在独立的 tokio 任务中，拥有和管理所有对话状态。

The Actor pattern is a concurrency model where each Actor is an independent execution unit communicating via message passing. `ChatStateActor` is the core component of Grok's chat system, running in a dedicated tokio task and owning all chat state.

### 2. 核心数据结构 / Core Data Structures

https://github.com/xai-org/grok-build/blob/7cfcb20/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L28-L43

```rust
pub struct ChatStateActor {
    /// Internal state — conversation, tokens, config, etc.
    state: ChatState,
    /// Pruning configuration for tool-result trimming.
    pruning_config: PruningConfig,
    /// Persistence implementation — owned exclusively
    persistence: Box<dyn ChatPersistence>,
    /// Channel to receive commands from handles.
    cmd_rx: mpsc::UnboundedReceiver<ChatStateCommand>,
    /// Channel to send events to the session main loop.
    event_tx: mpsc::UnboundedSender<ChatStateEvent>,
    /// Cancellation token for graceful shutdown.
    cancellation_token: tokio_util::sync::CancellationToken,
}
```

**设计要点 / Design Notes:**
- `state`: 内部状态，封装对话历史、token 计数、配置等 / Internal state encapsulating conversation history, token counts, config
- `persistence`: 使用 trait object 实现持久化抽象 / Uses trait object for persistence abstraction
- `cmd_rx`: 无界通道接收器，用于接收命令 / Unbounded channel receiver for receiving commands
- `event_tx`: 无界通道发送器，用于发送事件 / Unbounded channel sender for emitting events

### 3. Actor 的 Spawn 模式 / Actor Spawn Pattern

https://github.com/xai-org/grok-build/blob/7cfcb20/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L53-L94

```rust
pub fn spawn(
    initial_conversation: Vec<ConversationItem>,
    sampling_config: SamplingConfig,
    persistence: Box<dyn ChatPersistence>,
    event_tx: mpsc::UnboundedSender<ChatStateEvent>,
    cancellation_token: tokio_util::sync::CancellationToken,
) -> ChatStateHandle {
    Self::spawn_with_pruning(
        initial_conversation,
        sampling_config,
        PruningConfig::default(),
        persistence,
        event_tx,
        cancellation_token,
    )
}

pub fn spawn_with_pruning(...) -> ChatStateHandle {
    let (cmd_tx, cmd_rx) = mpsc::unbounded_channel();

    let actor = ChatStateActor {
        state: ChatState::new(initial_conversation, sampling_config),
        pruning_config,
        persistence,
        cmd_rx,
        event_tx,
        cancellation_token,
    };

    tokio::spawn(actor.run());

    ChatStateHandle::new(cmd_tx)
}
```

**关键观察 / Key Observations:**
- 使用 `mpsc::unbounded_channel()` 创建命令通道 / Creates command channel using `mpsc::unbounded_channel()`
- 返回 `ChatStateHandle` 供外部调用者使用 / Returns `ChatStateHandle` for external callers
- Actor 在新任务中通过 `tokio::spawn(actor.run())` 启动 / Actor starts in new task via `tokio::spawn(actor.run())`

---

## 核心实现 / Core Implementation

### 主循环：事件驱动的消息处理 / Main Loop: Event-Driven Message Processing

https://github.com/xai-org/grok-build/blob/7cfcb20/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L96-L114

```rust
/// Main actor loop — processes commands until shutdown or cancellation.
async fn run(mut self) {
    loop {
        tokio::select! {
            biased;
            _ = self.cancellation_token.cancelled() => {
                debug!("ChatStateActor shutting down via cancellation");
                break;
            }
            cmd = self.cmd_rx.recv() => {
                let Some(cmd) = cmd else {
                    debug!("ChatStateActor shutting down: all handles dropped");
                    break;
                };
                self.handle_command(cmd);
            }
        }
    }
}
```

**循环设计要点 / Loop Design Notes:**

| 特性 / Feature | 说明 / Description |
|----------------|-------------------|
| `tokio::select!` | 同时监听多个异步操作 / Listens to multiple async operations simultaneously |
| `biased` | 优先处理取消信号 / Prioritizes cancellation signal |
| `cancellation_token.cancelled()` | 优雅关闭机制 / Graceful shutdown mechanism |
| `cmd_rx.recv()` | 阻塞等待命令 / Blocks waiting for commands |
| `None` 检查 | 所有 handle 丢弃时退出 / Exits when all handles are dropped |

### 命令分发：模式匹配 / Command Dispatch: Pattern Matching

https://github.com/xai-org/grok-build/blob/7cfcb20/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L116-L390

Actor 使用 Rust 的 `match` 表达式将命令分发给不同的处理函数：

```rust
fn handle_command(&mut self, cmd: ChatStateCommand) {
    match cmd {
        // ═══ Mutations ═══
        ChatStateCommand::PushUserMessage { item } => {
            self.push_user_message(item);
        }
        ChatStateCommand::GetConversation { reply } => {
            // Query handlers return data via channel
            let _ = reply.send(self.state.conversation.clone());
        }
        // ... many more commands
    }
}
```

**命令类型 / Command Types:**
- **Mutations**: 修改状态的操作 (如 `PushUserMessage`, `ReplaceConversation`) / Operations that modify state
- **Queries**: 只读查询 (如 `GetConversation`, `Snapshot`) / Read-only queries

### 事件发送 / Event Sending

https://github.com/xai-org/grok-build/blob/7cfcb20/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L45-L51

```rust
fn send_event(&self, event: ChatStateEvent) {
    if self.event_tx.send(event).is_err() {
        debug!("ChatState event channel closed, event dropped");
    }
}
```

---

## Python 实现 / Python Implementation

以下是一个最小化的 Actor 实现，展示了相同的设计理念：

Below is a minimal Actor implementation demonstrating the same design principles:

```python
"""
Minimal Actor Loop - Python Implementation
最小 Actor 循环 - Python 实现

Based on xai-chat-state/src/actor/mod.rs
"""

import asyncio
from enum import Enum, auto
from typing import Any, Callable, Generic, TypeVar
from dataclasses import dataclass, field
from collections import deque

T = TypeVar('T')


class StopReason(Enum):
    """Actor 停止原因 / Actor stop reasons"""
    CANCELLATION = auto()
    HANDLES_DROPPED = auto()


@dataclass
class ActorState:
    """Actor 内部状态 / Actor internal state"""
    messages: list = field(default_factory=list)
    count: int = 0


class Command(Enum):
    """命令类型 / Command types"""
    PUSH_MESSAGE = auto()
    GET_STATE = auto()
    STOP = auto()


@dataclass
class PushMessageCmd:
    """推送消息命令 / Push message command"""
    content: str


@dataclass
class GetStateCmd:
    """获取状态命令 / Get state command"""
    reply: asyncio.Queue


class MinimalActor:
    """
    最小化 Actor 实现
    
    Design principles from Rust version:
    - Sequential command processing (no concurrent state access)
    - Event-driven loop using asyncio
    - Graceful shutdown via cancellation
    """
    
    def __init__(self):
        self.state = ActorState()
        self.command_queue: asyncio.Queue = asyncio.Queue()
        self.event_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
    
    async def handle_command(self, cmd: Command) -> Any:
        """命令处理分发 / Command dispatch handler"""
        if isinstance(cmd, PushMessageCmd):
            self.state.messages.append(cmd.content)
            self.state.count += 1
            print(f"[Actor] Received: {cmd.content}")
            await self._send_event(f"message_added:{cmd.content}")
            return None
            
        elif isinstance(cmd, GetStateCmd):
            await cmd.reply.put({
                "messages": list(self.state.messages),
                "count": self.state.count
            })
            return None
            
        elif cmd == Command.STOP:
            return StopReason.HANDLES_DROPPED
        
        return None
    
    async def _send_event(self, event: str):
        """发送事件到订阅者 / Send event to subscribers"""
        try:
            self.event_queue.put_nowait(event)
        except asyncio.QueueFull:
            print("[Actor] Event queue full, dropping event")
    
    async def run(self):
        """主循环 / Main loop"""
        self._running = True
        print("[Actor] Started")
        
        while self._running:
            try:
                # 使用 asyncio.wait_for 实现取消支持
                # Use asyncio.wait_for for cancellation support
                cmd = await asyncio.wait_for(
                    self.command_queue.get(),
                    timeout=0.1  # 短超时以允许定期检查
                )
                
                result = await self.handle_command(cmd)
                
                if result == StopReason.HANDLES_DROPPED:
                    print("[Actor] All handles dropped, stopping")
                    break
                    
            except asyncio.TimeoutError:
                # 继续循环，允许检查运行状态
                # Continue loop, allow checking running status
                continue
            except asyncio.CancelledError:
                print("[Actor] Cancelled, shutting down gracefully")
                break
        
        self._running = False
        print("[Actor] Stopped")
    
    async def stop(self):
        """停止 Actor / Stop the actor"""
        self._running = False


class ActorHandle:
    """
    Actor 句柄，用于与 Actor 通信
    
    Actor Handle - used to communicate with the actor
    """
    
    def __init__(self, command_queue: asyncio.Queue):
        self._cmd_queue = command_queue
    
    async def push_message(self, content: str):
        """推送消息到 Actor / Push message to actor"""
        await self._cmd_queue.put(PushMessageCmd(content))
    
    async def get_state(self) -> dict:
        """获取 Actor 状态 / Get actor state"""
        reply_queue: asyncio.Queue = asyncio.Queue()
        await self._cmd_queue.put(GetStateCmd(reply_queue))
        return await reply_queue.get()


async def spawn_actor() -> tuple:
    """
    Spawn actor and return handle
    
    启动 Actor 并返回句柄
    
    Pattern from: xai-chat-state/src/actor/mod.rs#L53-L94
    """
    actor = MinimalActor()
    
    # 在独立任务中运行 actor
    # Run actor in a separate task
    task = asyncio.create_task(actor.run())
    
    return actor, ActorHandle(actor.command_queue), task


async def main():
    """演示 / Demonstration"""
    print("=== Minimal Actor Demo ===\n")
    
    # Spawn actor
    # 启动 Actor
    actor, handle, task = await spawn_actor()
    
    try:
        # Push some messages
        # 推送消息
        await handle.push_message("Hello")
        await handle.push_message("World")
        
        # Get state
        # 获取状态
        state = await handle.get_state()
        print(f"\n[Main] State: {state}")
        
    finally:
        # Clean shutdown
        # 清理关闭
        await actor.stop()
        await task


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 练习 / Exercises

### 练习 1: 添加新的命令类型 / Exercise 1: Add a New Command Type

为 `MinimalActor` 添加一个 `GetMessageCountCmd` 命令，返回消息数量。

Add a `GetMessageCountCmd` command to `MinimalActor` that returns the message count.

**提示 / Hint:** 参考 `GetStateCmd` 的实现模式。/ Refer to the `GetStateCmd` implementation pattern.

### 练习 2: 实现取消令牌 / Exercise 2: Implement Cancellation Token

在 Python 实现中添加取消令牌功能，模仿 Rust 版本的 `cancellation_token.cancelled()` 模式。

Add cancellation token functionality to the Python implementation, mimicking the Rust version's `cancellation_token.cancelled()` pattern.

### 练习 3: 分析 Rust 代码 / Exercise 3: Analyze Rust Code

阅读 https://github.com/xai-org/grok-build/blob/7cfcb20/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L243-L268 中的查询命令实现，说明为什么查询命令在读取引用时不需要锁。

Read the query command implementation in https://github.com/xai-org/grok-build/blob/7cfcb20/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L243-L268 and explain why query commands don't need locks when reading references.

### 练习 4: 扩展持久化 / Exercise 4: Extend Persistence

为 Python Actor 添加一个简单的文件持久化机制，保存和恢复对话状态。

Add a simple file persistence mechanism to the Python Actor to save and restore conversation state.

---

## 总结 / Summary

本章我们学习了 Actor 模式的核心概念：

In this chapter, we learned the core concepts of the Actor pattern:

1. **状态封装**: Actor 拥有自己的内部状态，外部无法直接访问 / **State encapsulation**: Actor owns its internal state, inaccessible from outside
2. **消息驱动**: 通过 channel 传递命令，Actor 按顺序处理 / **Message-driven**: Commands passed via channel, processed sequentially
3. **事件通知**: Actor 可以向订阅者发送事件通知 / **Event notification**: Actor can send events to subscribers
4. **优雅关闭**: 支持通过取消令牌实现优雅关闭 / **Graceful shutdown**: Supports graceful shutdown via cancellation token

下一章我们将深入分析状态管理 mutations 模块。

In the next chapter, we will dive deep into the state management mutations module.

---

**参考来源 / References:**
- https://github.com/xai-org/grok-build/blob/7cfcb20/source/crates/codegen/xai-chat-state/src/actor/mod.rs (L1-L392)
- https://github.com/xai-org/grok-build/blob/7cfcb20/source/crates/codegen/xai-chat-state/src/actor/state.rs
- https://github.com/xai-org/grok-build/blob/7cfcb20/source/crates/codegen/xai-chat-state/src/commands.rs
- https://github.com/xai-org/grok-build/blob/7cfcb20/source/crates/codegen/xai-chat-state/src/events.rs