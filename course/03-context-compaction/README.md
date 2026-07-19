# Context Compaction | 上下文压缩

## Overview | 概述

This section covers context compaction strategies in `request_builder.rs` (lines 155-210), focusing on how the system manages token usage when the context window approaches capacity.

本节介绍 `request_builder.rs`（第 155-210 行）中的上下文压缩策略，涵盖系统如何在上下文窗口接近容量时管理令牌使用。

---

## Key Concepts | 核心概念

### 1. Pruning Trigger | 修剪触发器

```rust
pub(crate) fn should_prune(total_tokens: u64, context_window: NonZeroU64) -> bool {
    total_tokens > context_window.get() / 2
}
```

**Behavior | 行为:**
- Pruning activates when token usage exceeds **50%** of the context window.
- 当令牌使用量超过上下文窗口的 **50%** 时，触发修剪。

**Why 50%? | 为什么要 50%？**
- Provides early warning before critical threshold.
- Gives room for new messages without immediate re-pruning.
- 在达到临界阈值前提供预警。
- 为新消息留出空间，避免频繁重修剪。

---

### 2. Turn-Based Age Estimation | 基于轮次的年龄估算

The system estimates message age by counting `User` items backward through the conversation:

系统通过向后遍历对话中的 `User` 项来估算消息年龄：

```rust
let mut turn_from_end: usize = 0;
let mut seen_first_user = false;

for i in (0..conversation.len()).rev() {
    if matches!(&conversation[i], ConversationItem::User(_)) {
        if seen_first_user {
            turn_from_end += 1;
        }
        seen_first_user = true;
        continue;
    }
    // ...
}
```

**Key insight | 关键洞察:**
- Each `User` item represents one conversation turn.
- Walking backward counts turns from the most recent.
- 每个 `User` 项代表一轮对话。
- 向后遍历从最近一轮开始计数。

---

### 3. Two-Tier Compaction Strategy | 两级压缩策略

#### Hard Clear (Very Old Results) | 硬清除（非常旧的结果)

```rust
if turn_from_end >= config.hard_clear_age_turns {
    if tool_result.content.as_ref() != HARD_CLEAR_PLACEHOLDER {
        tool_result.content = Arc::<str>::from(HARD_CLEAR_PLACEHOLDER);
    }
    continue;
}
```

| Aspect | Description |
|--------|-------------|
| **When** | Beyond `hard_clear_age_turns` threshold |
| **Action** | Replace content with `[tool result cleared]` |
| **Token savings** | Maximum (content → 1 token) |
| **何时** | 超过 `hard_clear_age_turns` 阈值 |
| **操作** | 替换为 `[tool result cleared]` |
| **令牌节省** | 最大（内容 → 1 令牌） |

#### Soft Trim (Moderately Old, Large Results) | 软裁剪（中等旧的大结果）

```rust
let content_len = tool_result.content.chars().count();
if content_len > config.soft_trim_threshold {
    let head = safe_char_slice(&tool_result.content, 0, config.soft_trim_head);
    let tail = safe_char_slice_tail(&tool_result.content, config.soft_trim_tail);
    tool_result.content = Arc::<str>::from(format!("{head}{SOFT_TRIM_SEPARATOR}{tail}"));
}
```

| Aspect | Description |
|--------|-------------|
| **When** | Content exceeds `soft_trim_threshold` chars |
| **Action** | Keep head + tail, truncate middle |
| **Separator** | `...` between head and tail |
| **何时** | 内容超过 `soft_trim_threshold` 字符 |
| **操作** | 保留头部 + 尾部，截断中间 |
| **分隔符** | `...` 介于头部和尾部之间 |

---

## Configuration | 配置

```rust
struct PruningConfig {
    enabled: bool,
    keep_last_n_turns: usize,        // Never prune recent turns
    hard_clear_age_turns: usize,      // Full clear threshold
    soft_trim_threshold: usize,       // Size for trimming
    soft_trim_head: usize,            // Characters to keep at start
    soft_trim_tail: usize,            // Characters to keep at end
}
```

| Field | Purpose |
|-------|---------|
| `keep_last_n_turns` | Protects recent turns from any compaction |
| `hard_clear_age_turns` | Turns older than this get fully cleared |
| `soft_trim_threshold` | Content size triggers partial trimming |
| `soft_trim_head` | Head portion preserved |
| `soft_trim_tail` | Tail portion preserved |

---

## Visual Flow | 可视化流程

```
Conversation Items (reverse order)
        │
        ▼
┌───────────────────┐
│   Is Pruning      │──No──▶ EXIT (no changes)
│   Enabled?        │
└─────────┬─────────┘
          │ Yes
          ▼
┌───────────────────┐
│  Count turns      │
│  backward from    │
│  most recent User │
└─────────┬─────────┘
          ▼
┌───────────────────────────────┐
│  Is turn < keep_last_n_turns? │──Yes──▶ Skip (preserve)
└───────────────┬───────────────┘
                │ No
                ▼
┌─────────────────────────────────────────┐
│  turn >= hard_clear_age_turns?          │
│  (very old)                             │
└────────┬────────────────────────────────┘
         │Yes                    │No
         ▼                       ▼
┌─────────────────┐    ┌─────────────────────────┐
│ Replace with    │    │ content_len >           │
│ HARD_CLEAR_     │    │ soft_trim_threshold?    │
│ PLACEHOLDER     │    └────────┬────────────────┘
└─────────────────┘             │Yes
                                ▼
                       ┌─────────────────┐
                       │ head + "..." +  │
                       │ tail            │
                       └─────────────────┘
```

---

## Safety Mechanisms | 安全机制

1. **Turn-based protection**: Recent turns are never pruned.
   - 基于轮次的保护：最近的轮次永远不会被修剪。

2. **Idempotent hard clear**: Multiple passes won't re-process already cleared items.
   - 幂等硬清除：多次运行不会重复处理已清除的项。

3. **Character-based trimming**: Uses character count, not byte count, for accurate sizing.
   - 基于字符的裁剪：使用字符数而非字节数进行精确计量。

---

## Key Takeaways | 关键要点

| Point | Description |
|-------|-------------|
| **Proactive** | Starts at 50% capacity, not when full |
| **Tiered** | Different strategies for different ages |
| **Configurable** | All thresholds adjustable via `PruningConfig` |
| **Safe** | Recent turns are always preserved |

| 要点 | 描述 |
|------|------|
| **主动式** | 在 50% 容量时开始，而非满时 |
| **分级** | 不同年龄采用不同策略 |
| **可配置** | 所有阈值可通过 `PruningConfig` 调整 |
| **安全性** | 最近的轮次始终保留 |

---

## Related Files | 相关文件

- `source/crates/codegen/xai-chat-state/src/actor/request_builder.rs` - Implementation
- `source/crates/codegen/xai-chat-state/src/actor/mod.rs` - Module exports