# Terminology

This document defines the core architectural terms used throughout the Grok Build codebase.

---

## Orchestration Loop

**In `xai-grok-shell`**

**Definition**

The `run_session` async function in `xai-grok-shell/src/agent/mvp_agent/acp_agent.rs`. This is the top-level event loop that drives a `SessionActor`. It uses `tokio::select!` to multiplex across:

- Idle flush timers (memory persistence)
- Dream check timers (memory synthesis)
- Model switch watch channels
- Chat state event stream (`chat_state_event_rx`)
- Session command channel (`cmd_rx`)
- Session event stream (`event_rx`)
- Completion notifications (`completion_rx`)

The orchestration loop is the **dispatch hub** for a session. It does not own any state directly — all state lives in either `SessionActor` (for scheduling/task state) or `ChatStateActor` (for conversation state). The loop only coordinates: it receives commands, forwards them to the appropriate actor, and drives the idle/timer arms that trigger background work (memory flush, dream checks, model-switch reactions).

**Code Location**

`source/crates/codegen/xai-grok-shell/src/agent/mvp_agent/acp_agent.rs` — the main agent loop entry point.

---

## Conversation State Actor

**In `xai-chat-state`**

**Definition**

An alternate name for `ChatStateActor` used in documentation and the crate-level doc comment in `xai-chat-state/src/lib.rs`. It denotes the actor that owns all conversation state (messages, tokens, prompt index, sampling config, pruning settings, credentials).

The crate-level architecture diagram shows the relationship explicitly:

```
SessionActor (push_user, build_req) --> ChatStateActor (runs in dedicated tokio task)
```

**Responsibility Boundary**

The Conversation State Actor owns all chat history and conversation-level metadata. It does NOT own:

- Task scheduling or turn lifecycle (that is `SessionActor`)
- Tool execution
- MCP connections
- File system state (except via tools)

It provides a sequential, mutation-safe API via `ChatStateCommand` messages and emits `ChatStateEvent` events for consumers like the memory system.

---

## Agent Builder

**In `xai-grok-agent`**

**Definition**

The `AgentBuilder` struct in `xai-grok-agent/src/builder.rs`. A fluent builder API that constructs an `Agent` instance from an `AgentDefinition`, session context, tool registry, and various feature flags.

Two main construction flows:

```rust
// 1. From a definition file
let def = AgentDefinition::from_file("agents/code-reviewer.md")?;
let agent = AgentBuilder::new(cwd, None, notification_handle)
    .from_definition(def)
    .build()
    .await?;

// 2. Programmatic (no file)
let agent = AgentBuilder::new(cwd, None, notification_handle)
    .with_name("my-agent")
    .with_tools(vec!["read_file".into(), "grep".into()])
    .build()
    .await?;
```

**Responsibility Boundary**

Agent Builder is responsible for assembling the complete `Agent` at session spawn or subagent creation time. This includes:

- Resolving the agent definition (file-based via `.grok/agents/*.md` or programmatic)
- Building the `ToolBridge` with the configured toolset
- Discovering and injecting skills from `.grok/skills`, `AGENTS.md`, and plugins
- Rendering the system prompt via `PromptContext`
- Configuring compaction and reminder policies
- Setting up memory backend, web search, LSP, and other feature flags

Agent Builder is a **one-shot constructor** — it produces an `Agent` and then its lifetime ends. It does not participate in the session loop.

---

## Agent Definition

**In `xai-grok-agent`**

**Definition**

The `AgentDefinition` struct in `xai-grok-agent/src/config.rs`. A parsed representation of an agent's configuration, loaded from `.grok/agents/*.md` files or created programmatically.

An agent definition contains:

- `name`: Human-readable agent name
- `description`: Brief description shown in UI
- `tools`: Tool allowlist/denylist for this agent
- `system_prompt`: Custom system prompt or template override
- `compaction_policy`: How and when to compact conversation history
- `reminder_policy`: System reminder injection settings
- `preset`: Named toolset preset to use

**Code Location**

`source/crates/codegen/xai-grok-agent/src/config.rs`

---

## Session Actor

**In `xai-grok-shell`**

**Definition**

The primary actor that owns a session's runtime in `xai-grok-shell`. It manages: command handling, prompt queue, turn lifecycle, tool dispatch, MCP state, memory, goal orchestration, compaction, and file watching.

`SessionActor` is not a single struct but rather the **coordinating concept** across `MvpAgent` and related modules. The session lifecycle is managed in `mvp_agent/session_lifecycle.rs`, while the main event processing happens in the agent's `tokio::select!` loop.

**Code Location**

- Session lifecycle: `source/crates/codegen/xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs`
- Session spawning: `source/crates/codegen/xai-grok-shell/src/session/`

**Responsibility Boundary**

Session Actor / `MvpAgent` is the central coordinator for a session. It owns:

- The scheduling state (`running_task`, `pending_inputs`, `pending_notifications`)
- The `ChatStateActor` handle (via `chat_state_handle`) and sends it commands
- Turn lifecycle (via submodules `turn.rs`, `turn_end.rs`)
- Tool dispatch coordination (`tool_dispatch.rs`)
- Goal mode orchestration (`goal.rs`)
- Compaction triggers (`compaction.rs`)
- MCP server lifecycle (`mcp.rs`, `mcp_snapshot.rs`)
- Memory state (`memory_state.rs`)
- Permission handling

It delegates conversation state storage to `ChatStateActor` and tool execution to the `ToolBridge` inside `Agent`.

---

## ChatStateActor

**In `xai-chat-state`**

**Definition**

The concrete struct `ChatStateActor` in `xai-chat-state/src/actor/mod.rs`. Runs in a dedicated tokio task and owns all chat state (conversation messages, token counts, prompt index, sampling config, pruning config, persistence layer). Processes commands sequentially from an unbounded mpsc channel.

**Code Location**

`source/crates/codegen/xai-chat-state/src/actor/mod.rs` — the `ChatStateActor` struct and its `run()` method.

**Responsibility Boundary**

ChatStateActor is the **single authoritative owner of conversation state**. It:

- Stores and mutates the `conversation: Vec<ConversationItem>` without locks
- Tracks token usage (`total_tokens`, `prompt_usage`, `session_usage`)
- Maintains prompt index and compaction markers
- Handles pruning (tool result trimming) via `PruningConfig`
- Provides read-only query API (`BuildConversationRequest`, `GetConversation`, `Snapshot`, etc.)
- Flushes state to `ChatPersistence` on command

It does NOT:

- Execute tools or route tool calls
- Manage session lifecycle or scheduling
- Handle MCP connections
- Directly emit user-facing events (it emits `ChatStateEvent` which `SessionActor` may transform)

The `ChatStateHandle` type (in `xai-chat-state/src/handle.rs`) is the `Clone + Send` proxy that callers (including `SessionActor`) use to send commands to this actor.

---

## Responsibility Boundaries Summary

| Component | Owns | Does NOT Own |
|-----------|------|--------------|
| **Orchestration Loop** | Event multiplexing, timer arms | Any state directly |
| **SessionActor / MvpAgent** | Session lifecycle, scheduling, tool dispatch, MCP | Conversation messages |
| **ChatStateActor** | Conversation messages, tokens, pruning, sampling config | Tool execution, session scheduling |
| **AgentBuilder** | Agent construction at spawn time | Runtime session state |
| **AgentDefinition** | Static agent configuration | Runtime behavior |

**Command Flow**

```
Client Request
    │
    ▼
MvpAgent (orchestration loop)
    │
    ├──▶ ChatStateActor (via ChatStateHandle)
    │        - Push messages
    │        - Build conversation
    │        - Record tokens
    │
    ├──▶ ToolBridge (inside Agent)
    │        - Execute tools
    │        - MCP connections
    │
    └──▶ Memory / Compaction subsystems
             - Flush to disk
             - Synthesize context
```