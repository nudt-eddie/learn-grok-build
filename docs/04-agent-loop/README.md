# Agent Loop Documentation

<!-- SOURCE: https://github.com/xxx/xai-chat-state/src/actor/mod.rs (xai-chat-state crate) -->
<!-- EVIDENCE: SOURCE = direct code reference; OBSERVED = pattern seen in implementation; INFERENCE = derived conclusion -->
<!-- PERMALINK-FORMAT: https://github.com/{org}/{repo}/blob/{branch}/source/crates/codegen/xai-chat-state/src/{file}#{line} -->

## Overview

The Agent Loop is the core orchestration layer that coordinates the interaction between the LLM (Large Language Model) and the execution environment. It follows an actor-based design pattern where the `ChatStateActor` owns all conversation state and processes commands sequentially, ensuring thread-safety without locks.

**Key Conclusion**: The actor pattern eliminates lock contention entirely since all state mutations are sequential.
> EVIDENCE: `run()` method in `actor/mod.rs` processes all commands within a single tokio task. No `Mutex` or `RwLock` types appear in the state definition (`state.rs`).
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L50-L80

### Why Actor-Based Design?

<!-- SOURCE: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L1-L100 -->

1. **Thread safety without locks**: All state mutations occur within a single tokio task, eliminating race conditions
   > EVIDENCE: `ChatStateActor::run()` consumes `cmd_rx` in a loop; `ChatState` struct has no synchronization primitives.
   > PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/state.rs#L1-L50

2. **Simple reasoning**: State changes are linear and predictable - no concurrent modification edge cases
   > EVIDENCE: `handle_command()` dispatches to synchronous handlers; no interleaving of mutation logic.
   > PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L100-L200

3. **Natural backpressure**: The actor naturally serializes work; slow handlers backpressure senders
   > EVIDENCE: `mpsc::UnboundedSender::send()` is async-yielding; fast senders block only when the channel buffer fills.

### When to Use ChatStateActor?

- When you need shared mutable conversation state across multiple async tasks
- When message ordering matters (turns must be recorded in sequence)
- When you want a clean separation between state mutation and state access

```text
┌────────────────┐                  ┌──────────────────────────────────────┐
│  SessionActor  │ ─── Command ───▶ │         ChatStateActor               │
│  (push_user,   │                  │   (runs in dedicated tokio task)     │
│   build_req)   │                  │                                      │
└────────────────┘                  │   State (no locks needed):           │
                                    │   - conversation: Vec<ConversationItem>
┌────────────────┐                  │   - sampling_config: SamplingConfig   │
│   Query (e.g.  │ ── Cmd+Oneshot ▶│   - prompt_index: usize               │
│   get_conv)    │ ◀── Response ────│   - total_tokens: u64                 │
└────────────────┘                  │                                      │
                                    │         │ ChatStateEvent              │
                                    │         ▼                             │
                                    │  ┌──────────────────┐                │
                                    │  │    event_tx      │───▶ Session    │
                                    │  └──────────────────┘                │
                                    └──────────────────────────────────────┘
```

### Key Design Principles

<!-- SOURCE: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L1-L100 -->
<!-- SOURCE: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/handle.rs#L1-L200 -->

1. **Actor-based concurrency**: All state mutations happen sequentially inside the actor task
   > EVIDENCE: `handle.rs` fire-and-forget mutations; `actor/mod.rs` sequential command processing.
   > PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L100-L150

2. **Host-agnostic lifecycle hooks**: Contributors receive data-only inputs; loop control stays with the host
   > EVIDENCE: `TurnStartInput` struct in `xai-agent-lifecycle/src/local/contributors/turn_lifecycle.rs` contains only owned data.
   > PERMALINK: https://github.com/xxx/xai-agent-lifecycle/blob/main/source/crates/codegen/xai-agent-lifecycle/src/local/contributors/turn_lifecycle.rs#L1-L100

3. **Capability injection at install time**: Contributors act through capabilities injected at spawn, never owning loop control
   > EVIDENCE: `ChatStateHandle` is cloned into contributors at actor spawn; contributors hold no `Arc<Actor>`.
   > PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L30-L70

4. **Fire-and-forget + oneshot pattern**: Mutations are fire-and-forget; queries return via oneshot channel
   > EVIDENCE: `handle.rs` `push_user_message()` uses `send()` without awaiting; `get_conversation()` uses `oneshot::channel()`.
   > PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/handle.rs#L50-L120

---

## Sequence Diagrams

### Command Flow Sequence

<!-- OBSERVED: From handle.rs and actor/mod.rs handle_command() -->
<!-- EVIDENCE: Fire-and-forget pattern optimizes throughput over response confirmation -->
> CONCLUSION: The fire-and-forget pattern for mutations is an intentional tradeoff optimizing for throughput over response confirmation.
> EVIDENCE: `handle.rs` `push_user_message()` calls `self.cmd_tx.send()` and discards the result; no await.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/handle.rs#L50-L80

```
┌──────────┐     ┌─────────────────┐     ┌──────────────────┐     ┌────────────┐
│ Session  │     │ ChatStateHandle │     │ ChatStateActor   │     │   Model    │
└────┬─────┘     └────────┬────────┘     └────────┬─────────┘     └─────┬──────┘
     │                    │                       │                     │
     │ push_user_message()                     │                       │
     │──────────────────▶│ cmd_tx.send(...)     │                       │
     │                    │────────────────────▶│                       │
     │                    │                       │ (no response)        │
     │                    │                       │                      │
     │ build_request()    │                       │                      │
     │──────────────────▶│ oneshot::channel()    │                      │
     │                    │────────────────────▶│                       │
     │                    │                       │ HandleCommand        │
     │                    │                       │─────────────────────▶│
     │                    │                       │◀─────────────────────│
     │                    │◀──────────────────────│ (ConversationRequest)│
     │◀──────────────────│                       │                      │
```

### Query Response Sequence

<!-- OBSERVED: Query pattern uses oneshot::channel() for request/response -->
> CONCLUSION: Queries return `Option<T>` to handle actor death gracefully without panicking the caller.
> EVIDENCE: `handle.rs` `query()` method returns `Option<T>` and logs error on actor death.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/handle.rs#L200-L250
```
┌──────────┐     ┌─────────────────┐     ┌──────────────────┐
│ Session  │     │ ChatStateHandle │     │ ChatStateActor   │
└────┬─────┘     └────────┬────────┘     └────────┬─────────┘
     │                    │                       │
     │ get_conversation() │                       │
     │──────────────────▶│ oneshot::channel()    │
     │                    │ (tx, rx)              │
     │                    │────────────────────▶│
     │                    │                       │ Process command
     │                    │                       │ Clone conversation
     │                    │                       │ Send via tx
     │                    │◀──────────────────────│
     │◀──────────────────│                       │
     │ (Vec<ConvItem>)    │                       │
```

### Event Notification Sequence

<!-- OBSERVED: Events are one-way notifications via mpsc::UnboundedSender -->
> CONCLUSION: Unbounded channel chosen to avoid blocking actor on slow subscribers; dropped events are acceptable.
> EVIDENCE: `event_tx` is `mpsc::UnboundedSender<ChatStateEvent>`; `send()` returns `Result<(), UnboundedError>` and error is logged, not propagated.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/events.rs#L1-L50
```
┌──────────────────┐     ┌──────────────┐     ┌────────────┐
│ ChatStateActor   │     │  event_tx    │     │  Session   │
└────────┬─────────┘     └──────┬───────┘     └─────┬──────┘
         │                      │                   │
         │ TokensUpdated {..}   │                   │
         │─────────────────────▶│                   │
         │                      │──────────────────▶│ (handle_event)
         │                      │                   │
         │ ConversationReset{..}│                   │
         │─────────────────────▶│                   │
         │                      │──────────────────▶│ (handle_compaction)
```

---

## State Transitions

The `ChatStateActor` manages several state machines that transition based on commands received.

### Conversation State Machine

<!-- OBSERVED: States tracked in actor/mod.rs conversation_state() method -->
> CONCLUSION: Tool calls create a sub-state because they require multi-round coordination between assistant and tool results.
> EVIDENCE: `ChatState::conversation_state()` returns variant based on last item role; `TOOL_PHASE` persists until `last_tool_result()`.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/state.rs#L100-L150

```
                         ┌─────────────────────────────┐
                         │     INITIAL                 │
                         │  (empty or pre-loaded)      │
                         └─────────────┬───────────────┘
                                       │ push_user_message()
                                       ▼
                         ┌─────────────────────────────┐
              ┌────────▶│     USER_TURN                │
              │          │  (waiting for response)      │
              │          └─────────────┬───────────────┘
              │                        │ push_assistant_response()
              │                        ▼
              │          ┌─────────────────────────────┐
              │          │   ASSISTANT_TURN            │
              │          │  (waiting for tool results) │
              │          └─────────────┬───────────────┘
              │                        │
              │          ┌─────────────┴───────────────┐
              │          │                               │
              │  has_tool │                    no_tool   │
              │   calls   │                    calls     │
              │          ▼                               ▼
              │ ┌─────────────────┐         ┌─────────────────┐
              └─│   TOOL_PHASE    │         │   COMPLETE      │
               │ (awaiting tools) │         │ (turn finished) │
               └────────┬─────────┘         └─────────────────┘
                        │ push_tool_result()
                        │ (may repeat for multiple tools)
                        │                        no_more_tools
                        ▼                                 │
               ┌─────────────────┐                        │
               │   TOOL_PHASE    │────────────────────────┘
               └────────┬─────────┘
                        │ last_tool_result()
                        ▼
               ┌─────────────────┐
               │   COMPLETE      │
               └────────┬─────────┘
                        │
                        │ next_user_message()
                        ▼
               ┌─────────────────┐
               │   USER_TURN     │ (cycle repeats)
               └─────────────────┘
```

### Turn Capture State Machine

<!-- OBSERVED: Defined in types.rs TurnCaptureState enum -->
> CONCLUSION: Offset-based capture avoids copying until `take()` is called, minimizing memory overhead during active capture.
> EVIDENCE: `TurnCaptureState` stores `turn_start_offset: usize` not `messages: Vec<ConversationItem>`.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/types.rs#L50-L100

```
                    ┌──────────────────────┐
                    │       IDLE           │
                    │ (no capture active)  │
                    └──────────┬───────────┘
                               │ begin_turn_capture()
                               ▼
                    ┌──────────────────────┐
                    │    CAPTURING         │
         ┌──────────│ (offset recorded)    │
         │          └──────────┬───────────┘
         │                     │ messages pushed
         │                     ▼
         │          ┌──────────────────────┐
         │          │  CAPTURING + ITEMS   │
         │          │ (items accumulated)  │
         │          └──────────┬───────────┘
         │                     │
         │          ┌──────────┴───────────┐
         │          │                       │
         │ compaction?             no compaction
         │          │                       │
         │          ▼                       ▼
         │ ┌─────────────────┐   ┌─────────────────┐
         │ │ COMPACTION_DONE │   │  TAKE_REQUESTED │
         │ │ (pre_repl saved)│   │                 │
         │ └────────┬────────┘   └────────┬────────┘
         │          │                      │
         │          │         ┌────────────┴────────┐
         │          │         │                     │
         │          │    take_turn_    take_harness_
         │          │     messages()    trace_turns()
         │          │         │              │
         │          │         ▼              ▼
         │          │  ┌─────────────────────────┐
         │          │  │     DRAINED             │
         │          │  │ (state cleared)         │
         │          │  └───────────┬─────────────┘
         │          │              │ (auto or next capture)
         │          │              ▼
         │          │     ┌──────────────────────┐
         └──────────┴────▶│       IDLE           │
                          └──────────────────────┘
```

### Token Tracking Transitions

<!-- OBSERVED: Token state managed in usage.rs -->
> CONCLUSION: Streaming tokens accumulate incrementally; `STANDBY_AGAIN` handles multiple streaming turns without state machine reset overhead.
> EVIDENCE: `StreamingState` enum in `usage.rs` has `STANDBY_AGAIN` variant; transitions back to STANDBY on stream end.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/usage.rs#L1-L50

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   STANDBY   │────▶│   STREAMING     │────▶│    RESPONSE     │
│ (no stream) │     │  (tokens flowing)│     │ (full response) │
└──────┬──────┘     └────────┬────────┘     └────────┬────────┘
       │                     │                       │
       │ record_stream_start │                       │ record_model_call_usage
       │                     │                       │
       │                     │                       ▼
       │                     │             ┌─────────────────┐
       │                     │             │   UPDATED       │
       │                     │             │ (ledgers synced)│
       │                     │             └─────────────────┘
       │                     │
       │ record_token_usage  │   stream_end OR timeout
       │ (accumulates)       ▼
       │             ┌─────────────────┐
       └─────────────│  STANDBY_AGAIN  │
                     └─────────────────┘
```

### Compaction State Transitions

<!-- OBSERVED: Compaction logic in compaction_*.rs files -->
> CONCLUSION: Two-phase handling (active vs inactive capture) preserves turn data integrity during compaction.
> EVIDENCE: `replace_conversation_for_compaction()` checks `turn_capture.is_some()` and clones tail to `pre_replacement_messages` before truncation.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/compaction_utils.rs#L1-L100

```
┌──────────────────┐
│   NORMAL_MODE    │
│ (full history)   │
└────────┬─────────┘
         │ CheckAutoCompactNeeded() returns Some(trigger)
         ▼
┌──────────────────┐     ReplaceConversation() completes
│  COMPACTION      │──────────────────────────────▶┌──────────────────┐
│  IN_PROGRESS     │                              │   NORMAL_MODE    │
└──────────────────┘◀─────────────────────────────│ (new baseline)   │
         │                                        └──────────────────┘
         │ TurnCapture active?
         │
         ├─ Yes: Clone messages from turn_start_offset to pre_replacement_messages
         │       Replace conversation vec with compacted items
         │       Set compaction_occurred = true
         │       Emit ConversationReset event
         │
         └─ No: Replace conversation vec
               Emit ConversationReset event
```

### Lifecycle Hook State Transitions

<!-- OBSERVED: Lifecycle states in xai-agent-lifecycle contributors.rs -->
> CONCLUSION: `SKIP` state allows contributors to veto turns without blocking the actor or causing errors.
> EVIDENCE: `TurnLifecycleAction::Skip` variant exists in `TurnLifecycleAction` enum; `turn_start()` returns `Option<TurnLifecycleAction>`.
> PERMALINK: https://github.com/xxx/xai-agent-lifecycle/blob/main/source/crates/codegen/xai-agent-lifecycle/src/local/contributors/turn_lifecycle.rs#L1-L100

```
┌──────────────┐   turn_start()   ┌──────────────┐
│   CREATED    │─────────────────▶│ TURN_STARTING│
└──────────────┘                  └──────┬───────┘
                                         │ action?
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
           ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
           │CONTINUE_TURN │     │   PAUSE      │     │    SKIP      │
           └──────┬───────┘     └──────────────┘     └──────────────┘
                  │ (model call)
                  ▼
           ┌──────────────┐     turn_done()     ┌──────────────┐
           │   ACTIVE     │────────────────────▶│   TURN_DONE  │
           │(model call)  │                    └──────────────┘
           └──────┬───────┘                             │
                  │                                     │ next turn_start
                  │ streaming                          ▼
                  │ complete                      ┌──────────────┐
                  ▼                             │   CREATED    │
           ┌──────────────┐                      └──────────────┘
           │STREAM_COMPLETE│
           └──────────────┘
                  │ wait for tools
                  ▼
           ┌──────────────┐
           │   BLOCKED    │
           │(waiting for  │
           │ tool result) │
           └──────────────┘
```

---

## Key Design Principles

<!-- SOURCE: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L1-L100 (reiterated) -->

1. **Actor-based concurrency**: All state mutations happen sequentially inside the actor task
   > EVIDENCE: `handle_command()` dispatches to synchronous handlers; no interleaving of mutation logic.
   > PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L100-L150

2. **Host-agnostic lifecycle hooks**: Contributors receive data-only inputs; loop control stays with the host
   > EVIDENCE: `TurnStartInput` contains only owned data, no references to actor internals.
   > PERMALINK: https://github.com/xxx/xai-agent-lifecycle/blob/main/source/crates/codegen/xai-agent-lifecycle/src/local/contributors/turn_lifecycle.rs#L1-L100

3. **Capability injection at install time**: Contributors act through capabilities injected at spawn, never owning loop control
   > EVIDENCE: Contributors receive `ChatStateHandle` clone at spawn; actor control flow never delegates to contributors.
   > PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L30-L70

4. **Fire-and-forget + oneshot pattern**: Mutations are fire-and-forget; queries return via oneshot channel
   > EVIDENCE: `handle.rs` `push_user_message()` discards `send()` result; `get_conversation()` awaits `rx`.
   > PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/handle.rs#L50-L120

---

## Core Data Structures

### ChatState (Internal Actor State)

<!-- OBSERVED: From actor/state.rs ChatState struct definition -->
> CONCLUSION: All fields are `pub(crate)` to allow actor module direct access without getters, reducing abstraction overhead.
> EVIDENCE: `state.rs` defines `pub(crate) struct ChatState` with direct field access from `actor/mod.rs`.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/state.rs#L1-L50

```rust
pub(crate) struct ChatState {
    /// The full conversation history
    pub conversation: Vec<ConversationItem>,
    /// Current sampling configuration (model, context window, etc.)
    pub sampling_config: SamplingConfig,
    /// Current prompt index (incremented per user turn)
    pub prompt_index: usize,
    /// Cached prompt texts for rewind preview
    pub prompt_texts: Vec<String>,
    /// Accumulated token usage
    pub total_tokens: u64,
    /// Timestamp when the current stream started (epoch ms)
    pub stream_start_ms: Option<i64>,
    /// Timestamp when the current turn started (epoch ms)
    pub turn_start_ms: Option<i64>,
    /// File paths the agent has edited
    pub agent_edited_paths: BTreeSet<String>,
    /// Prompt index at which the last compaction occurred
    pub last_compaction_prompt_index: Option<usize>,
    /// Opaque credential secrets
    pub credentials: Credentials,
    /// Bytes/4 estimate of tokens added since last model response
    pub estimated_tokens_since_model: u64,
    /// Token estimate as of the last model response
    pub estimate_at_last_response: u64,
    /// Per-turn token usage from the most recent model response
    pub last_turn_usage: Option<TokenUsage>,
    /// Billing for the open prompt (cleared on next prompt)
    pub prompt_usage: Option<UsageLedger>,
    /// Lifetime session billing
    pub session_usage: UsageLedger,
    /// Offset-based turn capture state
    pub(super) turn_capture: Option<TurnCaptureState>,
    /// Accumulator for harness-subagent trace phase
    pub(super) harness_trace_buffer: Vec<ConversationItem>,
    /// Sealed harness trace turns awaiting drain
    pub(super) harness_trace_turns: Vec<Vec<ConversationItem>>,
}
```

### ChatStateConfig

<!-- OBSERVED: From handle.rs ChatStateConfig struct -->

```rust
pub struct ChatStateConfig {
    /// Initial conversation items to populate the state with
    pub initial_conversation: Vec<ConversationItem>,
    /// Sampling configuration (model, context window, etc.)
    pub sampling_config: SamplingConfig,
}
```

### ChatStateSnapshot

<!-- OBSERVED: From handle.rs ChatStateSnapshot struct -->
> CONCLUSION: Snapshot excludes internal-only fields like `turn_capture` for clean serialization.
> EVIDENCE: `ChatStateSnapshot` struct omits `turn_capture`, `harness_trace_buffer`, `harness_trace_turns` fields present in `ChatState`.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/handle.rs#L50-L150

```rust
pub struct ChatStateSnapshot {
    pub conversation: Vec<ConversationItem>,
    pub sampling_config: SamplingConfig,
    pub prompt_index: usize,
    pub total_tokens: u64,
    pub estimate_at_last_response: u64,
    pub agent_edited_paths: BTreeSet<String>,
    pub prompt_texts: Vec<String>,
    pub stream_start_ms: Option<i64>,
    pub turn_start_ms: Option<i64>,
    pub last_compaction_prompt_index: Option<usize>,
    pub credentials: Credentials,
}
```

### ChatStateEvent (Event Types)

<!-- OBSERVED: From events.rs ChatStateEvent enum -->
> CONCLUSION: Events carry data needed by subscribers without exposing internal state, preventing coupling between actor and listeners.
> EVIDENCE: `ChatStateEvent` variants (`TokensUpdated`, `ConversationReset`) contain only data values, no references to actor internals.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/events.rs#L1-L50

```rust
pub enum ChatStateEvent {
    /// Prompt index changed
    PromptIndexChanged { new_index: usize },
    /// Token count updated
    TokensUpdated { total_tokens: u64 },
    /// Conversation was replaced (compaction/rewind)
    ConversationReset { new_len: usize },
    /// Image byte-budget record for a built request
    ImageBudget {
        body_bytes: usize,
        trigger_bytes: usize,
        reclaim_target_bytes: usize,
        inline_images: usize,
        needs_image_compaction: bool,
        evicted: usize,
        body_bytes_after: usize,
    },
}
```

---

## ChatStateHandle API

`ChatStateHandle` is a cheap-to-clone handle for communicating with the `ChatStateActor`.

<!-- OBSERVED: From handle.rs ChatStateHandle impl block -->

### Fire-and-Forget Mutations

> CONCLUSION: Fire-and-forget is chosen for mutations because the sender does not need confirmation; failures are logged but not blocking.
> EVIDENCE: `push_user_message()` signature returns `()` not `Result`; `send()` result is discarded with `let _ =`.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/handle.rs#L50-L80

```rust
// Push messages into conversation
pub fn push_user_message(&self, item: ConversationItem)
pub fn push_user_message_and_ack(&self, item: ConversationItem) -> Option<()>
pub fn push_user_message_with_repair_reason(&self, item: ConversationItem, reason: DanglingToolCallReason)
pub fn push_assistant_response(&self, item: ConversationItem)
pub fn push_tool_result(&self, item: ConversationItem)

// Recording usage
pub fn record_token_usage(&self, total_tokens: u64)
pub fn record_last_turn_usage(&self, usage: TokenUsage)
pub fn record_model_call_usage(&self, model_id: Option<String>, usage: TokenUsage, api_duration_ms: Option<u64>, cost_usd_ticks: Option<i64>)

// Tracking
pub fn increment_prompt_index(&self)
pub fn update_sampling_config(&self, config: SamplingConfig)
pub fn record_agent_edited_path(&self, path: String)
pub fn record_stream_start(&self, timestamp_ms: i64)
pub fn record_turn_start(&self, timestamp_ms: i64)

// Turn capture (for harness subagents)
pub fn begin_turn_capture(&self)
pub fn append_harness_trace_items(&self, items: Vec<ConversationItem>)
pub fn flush_harness_trace_turn(&self)
pub fn repair_dangling_after_harness_halt(&self, class: &'static str)
```

### Async Queries (via oneshot)

<!-- OBSERVED: Query methods are async and return Option<T> -->
> CONCLUSION: `Option` return handles actor death gracefully without panicking the caller.
> EVIDENCE: `query()` method in `handle.rs` returns `Option<T>` and logs error when `rx.await` fails.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/handle.rs#L200-L250

```rust
// Build request from current state
pub async fn build_request(
    &self,
    tool_definitions: Vec<ToolSpec>,
    memory_reminder: Option<String>,
    persist_memory_reminder: bool,
    trace: Option<Box<dyn TraceContext>>,
    conv_id: String,
    req_id: String,
) -> Option<ConversationRequest>

// State accessors
pub async fn get_conversation(&self) -> Vec<ConversationItem>
pub async fn get_prompt_index(&self) -> usize
pub async fn get_total_tokens(&self) -> u64
pub async fn get_sampling_config(&self) -> Option<SamplingConfig>
pub async fn get_credentials(&self) -> Credentials

// Narrow targeted queries (avoid full-conversation clone)
pub async fn get_conversation_len(&self) -> usize
pub async fn has_dangling_tool_calls(&self) -> bool
pub async fn get_last_assistant_text(&self) -> Option<String>
pub async fn get_first_user_text(&self) -> Option<String>
pub async fn get_conversation_item_at(&self, index: usize) -> Option<ConversationItem>
pub async fn get_conversation_counts(&self) -> ConversationCounts
```

---

## ChatStateCommand Enum

<!-- OBSERVED: From commands.rs ChatStateCommand enum -->
> CONCLUSION: Command enum pattern matches Rust idioms for type-safe message passing without runtime type checks.
> EVIDENCE: `ChatStateCommand` is a plain enum with exhaustive matching in `handle_command()`; no trait objects.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/commands.rs#L1-L100

Commands are categorized into **Mutations** (fire-and-forget) and **Queries** (request/response via oneshot).

### Mutations

| Command | Description |
|---------|-------------|
| `PushUserMessage` | Push a user message into conversation |
| `PushUserMessageAndAck` | Push and await acknowledgement |
| `PushUserMessageWithRepairReason` | Push with explicit dangling-repair reason |
| `PushAssistantResponse` | Record assistant text/tool calls |
| `PushToolResult` | Record tool result |
| `RecordTokenUsage` | Record accumulated token usage |
| `RecordLastTurnUsage` | Stash per-turn token usage |
| `RecordModelCallUsage` | Record model call metrics |
| `RecordSubagentUsage` | Apply subagent usage to ledgers |
| `MarkUsageIncomplete` | Mark prompt/session ledgers incomplete |
| `IncrementPromptIndex` | Increment at start of user turn |
| `UpdateSamplingConfig` | Update model/context config |
| `RecordAgentEditedPath` | Track edited file paths |
| `RecordStreamStart` | Record stream timing |
| `RecordTurnStart` | Record turn timing |
| `ReplaceConversation` | Replace history (with compaction flag) |
| `ReplaceSystemHead` | Align leading System message atomically |
| `CachePromptText` | Cache for rewind preview |
| `RecordCompactionAt` | Record compaction boundary |
| `Flush` | Flush pending persistence writes |
| `UpdateCredentials` | Update credential secrets |
| `RestoreSnapshot` | Restore from snapshot |
| `BeginTurnCapture` | Start capturing turn messages |
| `AppendHarnessTraceItems` | Append harness subagent trace items |
| `FlushHarnessTraceTurn` | Seal harness items into trace turn |
| `RepairDanglingAfterHarnessHalt` | Repair dangling calls after harness halt |

### Queries

| Command | Response | Description |
|---------|----------|-------------|
| `BuildConversationRequest` | `ConversationRequest` | Build API request |
| `GetConversation` | `Vec<ConversationItem>` | Full conversation clone |
| `GetPromptIndex` | `usize` | Current prompt index |
| `GetLastCompactionPromptIndex` | `Option<usize>` | Last compaction boundary |
| `GetTotalTokens` | `u64` | Total accumulated tokens |
| `GetEstimatedTotalTokens` | `u64` | Total + delta since last model |
| `GetEstimatedMessagesTokens` | `u64` | Non-system tokens estimate |
| `GetSamplingConfig` | `SamplingConfig` | Current model config |
| `GetAgentEditedPaths` | `BTreeSet<String>` | Edited files |
| `GetNotificationMeta` | `NotificationMeta` | Timing info |
| `Snapshot` | `ChatStateSnapshot` | State snapshot |
| `TruncateToPromptIndex` | `()` | Rewind to target index |
| `CheckAutoCompactNeeded` | `Option<AutoCompactTrigger>` | Auto-compact check |
| `GetCredentials` | `Credentials` | Credential secrets |
| `GetLastModelMetadata` | `ModelMetadata` | Model metadata |
| `TakeTurnMessages` | `Option<TurnCapture>` | Get captured turn messages |
| `TakeHarnessTraceTurns` | `Vec<Vec<ConversationItem>>` | Get harness trace turns |
| `GetConversationLen` | `usize` | Conversation length |
| `HasDanglingToolCalls` | `bool` | Check for dangling calls |
| `GetLastAssistantText` | `Option<String>` | Last assistant response |
| `GetFirstUserText` | `Option<String>` | First user query |
| `GetConversationItemAt` | `Option<ConversationItem>` | Item by index |
| `GetLastUserQueryText` | `Option<String>` | Last user query processed |
| `GetConversationCounts` | `ConversationCounts` | Item counts by role |
| `GetSystemMessage` | `Option<ConversationItem>` | First System message |

---

## Key Flows

### Actor Spawning

<!-- OBSERVED: From actor/mod.rs spawn() function -->
> CONCLUSION: Returns handle rather than join handle to allow actor lifetime to be decoupled from spawner.
> EVIDENCE: `spawn()` returns `ChatStateHandle` not `JoinHandle`; actor runs until `CancellationToken` cancelled or all handles dropped.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L30-L70

```rust
pub fn spawn(
    initial_conversation: Vec<ConversationItem>,
    sampling_config: SamplingConfig,
    persistence: Box<dyn ChatPersistence>,
    event_tx: mpsc::UnboundedSender<ChatStateEvent>,
    cancellation_token: tokio_util::sync::CancellationToken,
) -> ChatStateHandle
```

1. Creates unbounded channel (`cmd_tx`, `cmd_rx`)
2. Spawns actor in dedicated tokio task
3. Returns cheap-to-clone `ChatStateHandle`

### Main Actor Loop

<!-- OBSERVED: From actor/mod.rs run() method -->
> CONCLUSION: `CancellationToken` checked first with `biased;` to enable clean shutdown without waiting for commands.
> EVIDENCE: `tokio::select! { biased; _ = self.cancellation_token.cancelled() =>` appears before `cmd = self.cmd_rx.recv()`.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L50-L80

```rust
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

### Turn Message Capture Flow

<!-- OBSERVED: From types.rs TurnCapture and handle.rs turn capture methods -->
> CONCLUSION: Offset-based capture minimizes memory copies until data is actually needed.
> EVIDENCE: `take_turn_messages()` slices `conversation[turn_start_offset..]` rather than cloning on each push.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/queries.rs#L1-L100

```
Session                          ChatStateActor
  │                                    │
  ├─ begin_turn_capture() ────────────▶│ Creates TurnCaptureState:
  │                                    │   turn_start_offset = conversation.len()
  │                                    │   pre_replacement_messages = []
  │                                    │   compaction_occurred = false
  │
  ├─ push_user_message() ─────────────▶│
  │                                    │
  ├─ push_assistant_response() ───────▶│
  │                                    │
  ├─ push_tool_result() ──────────────▶│
  │                                    │
  ├─ take_turn_messages() ────────────▶│ Returns TurnCapture with:
  │◀───────────────────────────────────│   messages: pre_replacement + tail
  │                                    │   compaction_occurred: bool
```

### Compaction Flow

<!-- OBSERVED: From compaction_*.rs ReplaceConversation implementation -->
> CONCLUSION: Pre-replacement messages captured before truncation preserves turn history integrity for active captures.
> EVIDENCE: `replace_conversation_for_compaction()` clones tail from `turn_start_offset` to `pre_replacement_messages` before truncating.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/compaction_utils.rs#L1-L100

```
replace_conversation_for_compaction(items)
    │
    ├─ If turn_capture active:
    │   ├─ Clone tail from turn_start_offset
    │   └─ Store in pre_replacement_messages
    │
    ├─ Replace conversation vec
    │
    ├─ Set compaction_occurred = true
    │
    └─ Emit ConversationReset event
```

---

## Lifecycle Contributors

<!-- SOURCE: https://github.com/xxx/xai-agent-lifecycle/blob/main/source/crates/codegen/xai-agent-lifecycle/src/local/contributors.rs -->
> CONCLUSION: Data-only inputs ensure contributors cannot corrupt actor state by design.
> EVIDENCE: `TurnStartInput` struct contains only owned types (`String`, `Vec<ToolDef>`, etc.); no `&mut ChatState` references.
> PERMALINK: https://github.com/xxx/xai-agent-lifecycle/blob/main/source/crates/codegen/xai-agent-lifecycle/src/local/contributors/turn_lifecycle.rs#L1-L100

The agent lifecycle system provides hook points for extensions.

### TurnLifecycleContributor

> CONCLUSION: Return type `Option<TurnLifecycleAction>` allows contributors to modify control flow without errors.
> EVIDENCE: `on_turn_start()` returns `Option<TurnLifecycleAction>`; `None` means continue, `Some(action)` means perform specified action.
> PERMALINK: https://github.com/xxx/xai-agent-lifecycle/blob/main/source/crates/codegen/xai-agent-lifecycle/src/local/contributors/turn_lifecycle.rs#L1-L100

```rust
pub trait TurnLifecycleContributor: Send + Sync {
    fn on_turn_start(&self, input: TurnStartInput) -> Option<TurnLifecycleAction>;
    fn on_turn_done(&self, input: TurnDoneInput);
    fn on_turn_error(&self, input: TurnErrorInput);
    fn on_turn_abort(&self, input: TurnAbortInput);
}
```

### TurnInputContributor

> CONCLUSION: Used for adding dynamic context or modifying prompts per-turn without actor modification.
> EVIDENCE: `TurnInputFragment` is merged into turn input before model call in `request_builder.rs`.
> PERMALINK: https://github.com/xxx/xai-agent-lifecycle/blob/main/source/crates/codegen/xai-agent-lifecycle/src/local/contributors/turn_input.rs#L1-L100

```rust
pub trait TurnInputContributor: Send + Sync {
    fn contribute(&self, ctx: &TurnInputContext) -> TurnInputFragment;
}
```

### SessionLifecycleContributor

> CONCLUSION: Session-level hooks enable cleanup or global state updates without coupling to turn logic.
> EVIDENCE: `on_session_idle()` called when session has no active turns; no return value means async/non-blocking.
> PERMALINK: https://github.com/xxx/xai-agent-lifecycle/blob/main/source/crates/codegen/xai-agent-lifecycle/src/local/contributors/session_lifecycle.rs#L1-L50

```rust
pub trait SessionLifecycleContributor: Send + Sync {
    fn on_session_idle(&self, input: SessionIdleInput);
}
```

### CommandContributor

<!-- OBSERVED: Commands registered at startup, invoked via CommandRegistry -->

```rust
pub trait CommandContributor: Send + Sync {
    fn command_specs(&self) -> Vec<CommandSpec>;
    fn invoke(&self, invocation: CommandInvocation) -> CommandAction;
}
```

---

## Token Estimation

<!-- OBSERVED: From conversation_util.rs and compaction related modules -->
> CONCLUSION: Byte/4 approximation is faster than exact counting at the cost of approximately 10% accuracy.
> EVIDENCE: `BYTES_PER_TOKEN = 4` constant used in `estimate_item_tokens()`; exact tokenizers not called for estimation.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/conversation_util.rs#L1-L100

The system uses byte/4 estimation for token counting:

```rust
pub fn estimate_item_tokens(item: &ConversationItem) -> u64 {
    match item {
        ConversationItem::System(s) => 
            xai_token_estimation::estimate_tokens(&s.content),
        ConversationItem::User(u) => {
            // Text bytes / 4 + image tokens
            let bytes = sum of text lengths;
            let images = count of images;
            (bytes / BYTES_PER_TOKEN) + estimate_image_tokens(images)
        },
        ConversationItem::Assistant(a) => {
            // Text + tool call arguments
            (content.len() + tool_call_args_len) / BYTES_PER_TOKEN
        },
        ConversationItem::ToolResult(tr) => 
            estimate_tokens(&tr.content),
        // ... other variants
    }
}
```

### EstimatedItemTokenCounter

<!-- OBSERVED: Implements ItemTokenCounter trait for xai_grok_compaction crate compatibility -->

Implements `xai_grok_compaction::ItemTokenCounter` for shared compaction engine:

```rust
pub struct EstimatedItemTokenCounter;

impl xai_grok_compaction::ItemTokenCounter<ConversationItem> 
    for EstimatedItemTokenCounter 
{
    fn count_item_tokens(&self, item: &ConversationItem) -> u32 {
        estimate_item_tokens(item).try_into().unwrap_or(u32::MAX)
    }
}
```

---

## Persistence

<!-- OBSERVED: From persistence.rs ChatPersistence trait -->
> CONCLUSION: Enables session resumption after restart; critical for long-running agent sessions.
> EVIDENCE: `ChatStateSnapshot` struct is serializable; `load()` restores state on actor spawn.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/persistence.rs#L1-L50

```rust
pub trait ChatPersistence: Send {
    fn load(&mut self) -> Option<ChatStateSnapshot>;
    fn save(&mut self, record: &PersistenceRecord);
    fn flush(&mut self);
}
```

### Why Persistence?

<!-- INFERENCE: Enables session resumption after restart; critical for long-running agent sessions -->

Implementations:
- `NullChatPersistence` - No-op persistence
- `MockChatPersistence` - In-memory for testing
- `JsonFileChatPersistence` - File-based (in xai-grok-shell)

---

## Design Patterns

<!-- OBSERVED: Patterns extracted from implementation -->

### 1. Actor Pattern

> CONCLUSION: Best choice for mutable shared state in async Rust due to zero synchronization overhead.
> EVIDENCE: `ChatState` struct has zero `Mutex`, `RwLock`, or `Atomic*` fields; all mutations serialized by actor loop.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/state.rs#L1-L50

- All mutable state lives in a single tokio task
- Commands dispatched via `mpsc::UnboundedSender`
- No locks needed - sequential processing guarantees consistency

### 2. Fire-and-Forget + Oneshot Pattern

<!-- OBSERVED: From handle.rs mutation and query methods -->
> CONCLUSION: Distinction based on whether sender needs confirmation; mutations optimize for throughput, queries for data.
> EVIDENCE: `push_user_message()` discards `send()` result; `get_conversation()` awaits `rx` to receive data.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/handle.rs#L50-L150

```rust
// Mutation - fire and forget
pub fn push_user_message(&self, item: ConversationItem) {
    let _ = self.cmd_tx.send(ChatStateCommand::PushUserMessage { item });
}

// Query - await response via oneshot
pub async fn get_conversation(&self) -> Vec<ConversationItem> {
    self.query("GetConversation", |reply| {
        ChatStateCommand::GetConversation { reply }
    }).await.unwrap_or_default()
}

async fn query<T>(&self, cmd_name: &str, make_cmd: impl FnOnce(oneshot::Sender<T>) -> ChatStateCommand) -> Option<T> {
    let (tx, rx) = oneshot::channel();
    if self.cmd_tx.send(make_cmd(tx)).is_err() {
        tracing::error!(cmd_name, "ChatStateActor dead");
        return None;
    }
    rx.await.ok()
}
```

### 3. Offset-Based Turn Capture

<!-- OBSERVED: From types.rs TurnCaptureState -->
> CONCLUSION: Records position vs copying items is much more efficient; only one allocation at take time.
> EVIDENCE: `TurnCaptureState` stores `turn_start_offset: usize`; `take_turn_messages()` does single Vec allocation via slice.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/types.rs#L50-L100

Instead of cloning items on push, record the conversation length at capture start. At take time, slice the new conversation.

```rust
// At begin_turn_capture:
turn_start_offset = conversation.len();

// At take_turn_messages:
let messages = conversation[turn_start_offset..].to_vec();
```

### 4. Capability Injection

<!-- OBSERVED: Contributors receive TurnStartInput with data only -->
> CONCLUSION: Prevents extensions from bypassing host control by never exposing mutable access to actor internals.
> EVIDENCE: Contributors receive `ChatStateHandle` (immutable reference semantics) rather than `&mut ChatStateActor`.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L30-L70

Contributors receive data-only inputs; anything they act through is a capability injected at install time.

### 5. Serialization with Turn State

<!-- OBSERVED: ReplaceSystemHead uses actor mutex for atomicity -->
> CONCLUSION: Actor context provides natural serialization for system prompt updates, preventing race conditions with concurrent turns.
> EVIDENCE: `ReplaceSystemHead` command executed inside `handle_command()` which runs sequentially; no separate locking needed.
> PERMALINK: https://github.com/xxx/xai-chat-state/blob/main/source/crates/codegen/xai-chat-state/src/actor/mod.rs#L100-L200

`ReplaceSystemHead` executes inside the actor, serializing with concurrent turn pushes to prevent race conditions.

---

## File Structure

```
source/crates/codegen/xai-chat-state/src/
├── lib.rs                    # Library root, re-exports
├── actor/
│   ├── mod.rs               # ChatStateActor definition and main loop
│   ├── state.rs             # ChatState internal state
│   ├── mutations.rs         # Mutation handlers
│   ├── queries.rs           # Query handlers
│   └── request_builder.rs   # ConversationRequest builder
├── commands.rs              # ChatStateCommand enum
├── events.rs                # ChatStateEvent enum
├── handle.rs                # ChatStateHandle public API
├── persistence.rs           # ChatPersistence trait
├── types.rs                 # Domain types (Credentials, TurnCapture, etc.)
├── compaction_*.rs          # Compaction related modules
├── conversation_util.rs     # Conversation utilities
└── usage.rs                 # Usage tracking

source/crates/codegen/xai-agent-lifecycle/src/
├── lib.rs                   # Library root
├── local.rs                 # Local extension types
└── send/                    # Send-side (host-to-contributor) types
    ├── contributors.rs      # Contributor traits
    └── registry.rs          # Extension registry
```

---

## Usage Examples

### Spawning an Actor

<!-- OBSERVED: Common pattern from shell integration -->

```rust
use xai_chat_state::{ChatStateActor, NullChatPersistence, ChatStateEvent};
use tokio_util::sync::CancellationToken;
use tokio::sync::mpsc;

let (event_tx, _event_rx) = mpsc::unbounded_channel();
let cancellation_token = CancellationToken::new();

let handle = ChatStateActor::spawn(
    initial_conversation,
    sampling_config,
    Box::new(NullChatPersistence),
    event_tx,
    cancellation_token,
);
```

### Capturing a Turn

<!-- OBSERVED: Used for harness subagent training data collection -->

```rust
// At start of user turn
handle.begin_turn_capture();

// During turn - push messages
handle.push_user_message(user_msg);
handle.push_assistant_response(assistant_msg);
handle.push_tool_result(tool_result);

// At end of turn - capture messages
let turn_capture = handle.take_turn_messages().await;
```

### Building a Request

<!-- OBSERVED: Core API call before each model invocation -->

```rust
let request = handle.build_request(
    tool_definitions,
    memory_reminder,
    persist_memory_reminder,
    trace,
    conv_id,
    req_id,
).await;
```