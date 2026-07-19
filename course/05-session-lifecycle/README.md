# Session Lifecycle / 会话生命周期

## Overview / 概述

Source file: `source/crates/codegen/xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs`

This module implements the complete session lifecycle management for `MvpAgent`, including session shutdown, finalization, roster management, idle-session supervision, and health monitoring.

本模块实现了 `MvpAgent` 的完整会话生命周期管理，包括会话关闭、最终化、花名册管理、空闲会话监控和健康监控。

---

## Core Concepts / 核心概念

### Session State / 会话状态

```rust
pub enum SessionLiveState {
    Completed,  // Session ended explicitly / 会话显式结束
    DeadFailed, // Actor crashed unexpectedly / Actor 意外崩溃
    Dormant,    // Idle-unloaded, resumable / 空闲卸载，可恢复
}
```

### Three-Layer Activity Check / 三层活动检查

The `session_has_live_work()` method checks if a session has pending work before idle-unloading:

`session_has_live_work()` 方法在空闲卸载前检查会话是否有待处理工作：

1. **Fast path (sync):** Check `current_prompt_id` - set while turn is running
   - 快速路径（同步）：检查 `current_prompt_id` - 轮次运行时设置

2. **Parked plan-approval (sync):** Check `pending_interactions` for parked resume
   - 停放的计划审批（同步）：检查 `pending_interactions` 中的停放恢复

3. **Queue check (async):** Ask actor if `pending_inputs` is non-empty
   - 队列检查（异步）：询问 actor 的 `pending_inputs` 是否非空

---

## Key Functions / 关键函数

### Session Shutdown & Removal / 会话关闭与移除

| Function | Description | Finalize? |
|----------|-------------|-----------|
| `request_session_shutdown(id)` | Send `Shutdown` to live actor | No |
| `finalize_session_replica(id)` | Mark session done upstream (Hook 4) | Yes - cloud only |
| `remove_session(id)` | Remove from all maps, keep on disk | No |
| `close_session_explicit(id)` | Explicit terminal close | Yes - both |
| `reap_dead_session(id)` | Actor crashed unexpectedly | No |

### Roster Management / 花名册管理

```rust
// Broadcast x.ai/sessions/changed with removed session
pub fn record_roster_delta(&self, id: &SessionId, final_state: SessionLiveState)

// Broadcast x.ai/sessions/changed with upserted session (for activity transitions)
pub fn push_roster_delta_upserted(&self, id: &SessionId)

// Build roster: resident actors + on-disk Dormant sessions
pub async fn build_roster(&self) -> Vec<RosterEntry>
```

### Idle Session Supervisor / 空闲会话监控器

The supervisor runs a periodic sweep (`SESSION_SUPERVISOR_TICK`) to reap dead actor threads:

监控器定期扫描（`SESSION_SUPERVISOR_TICK`）来回收死亡的 actor 线程：

```rust
pub fn ensure_session_supervisor(&self)  // Idempotent - starts once
pub fn sweep_dead_sessions(&self)        // Reap finished threads
```

**Critical distinction in `sweep_dead_sessions`:**

`sweep_dead_sessions` 中的关键区别：

- **Still resident:** Actor exited unexpectedly → `DeadFailed`
  - 仍在内存中：Actor 意外退出 → `DeadFailed`

- **Not resident:** Clean exit expected → just cleanup, no roster delta
  - 不在内存中：预期的干净退出 → 仅清理，不发送花名册变更

---

## Registry Snapshot / 注册表快照

Debug endpoint for health monitoring:

健康监控的调试端点：

```rust
pub fn registry_snapshot(&self) -> RegistrySnapshot

pub struct RegistrySnapshot {
    pub sessions: usize,
    pub session_threads: usize,
    pub dispatch_locks: usize,
    pub session_turn_numbers: usize,
    pub permission_event_receivers: usize,
    pub model_unavailable_sessions: usize,
    pub session_live_state: usize,
    pub session_index_claims: usize,
    pub require_gateway_sessions: usize,
    pub subagent_pending: usize,
    pub subagent_active: usize,
    pub subagent_completed: usize,
    pub workspace_bindings: Option<usize>,
}
```

---

## Design Patterns / 设计模式

### Fire-and-Forget Finalization / 异步最终化

```rust
pub(super) fn finalize_session_replica(&self, id: &SessionId) {
    if let Some(client) = self.session_registry_client() {
        let sid = id.0.to_string();
        tokio::spawn(async move {
            if let Err(e) = client.finalize(&sid).await {
                tracing::warn!(error = %e, "session registry finalize failed");
            }
        });
    }
}
```

### Idempotent Supervisor / 幂等监控器

```rust
pub(super) fn ensure_session_supervisor(&self) {
    if self.supervisor_started.replace(true) {  // Atomic check-and-set
        return;
    }
    // ... spawn supervisor task
}
```

### Panic-Safe Sweep / 崩溃安全的扫描

```rust
let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
    agent_ref.get().sweep_dead_sessions();
}));
if result.is_err() {
    tracing::error!("session supervisor sweep panicked; continuing supervision");
}
```

---

## Key Invariants / 关键不变量

1. **Finalize only on genuine session end** - NOT on client disconnect or dead-actor reap
   - 仅在真正的会话结束时最终化 - 客户端断开或 actor 回收时不执行

2. **Dormant sessions stay resumable** - Remove without finalize preserves disk state
   - 休眠会话保持可恢复 - 移除但不最终化保留磁盘状态

3. **One supervisor per agent** - `AtomicBool::replace` ensures idempotency
   - 每个 agent 一个监控器 - `AtomicBool::replace` 保证幂等性

4. **Resident wins on roster collision** - Local actors override on-disk summaries
   - 花名册冲突时内存优先 - 本地 actor 覆盖磁盘摘要

---

## Related Files / 相关文件

- `source/crates/codegen/xai-grok-shell/src/agent/mod.rs` - `MvpAgent` definition
- `source/crates/codegen/xai-grok-shell/src/session/acp_session_impl/session_mode.rs` - Session modes
- `source/crates/codegen/xai-grok-shell/src/agent/roster.rs` - Roster types
- `source/crates/codegen/xai-grok-shell/src/session/persistence.rs` - On-disk session storage