# Agent Loop Documentation

## Overview

The Agent Loop is the core orchestration layer that coordinates the interaction between the LLM (Large Language Model) and the execution environment. It follows an actor-based design pattern where the `ChatStateActor` owns all conversation state and processes commands sequentially, ensuring thread-safety without locks.

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

1. **Actor-based concurrency**: All state mutations happen sequentially inside the actor task
2. **Host-agnostic lifecycle hooks**: Contributors receive data-only inputs; loop control stays with the host
3. **Capability injection at install time**: Contributors act through capabilities injected at spawn, never owning loop control
4. **Fire-and-forget + oneshot pattern**: Mutations are fire-and-forget; queries return via oneshot channel

---

## Core Data Structures

### ChatState (Internal Actor State)

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

```rust
pub struct ChatStateConfig {
    /// Initial conversation items to populate the state with
    pub initial_conversation: Vec<ConversationItem>,
    /// Sampling configuration (model, context window, etc.)
    pub sampling_config: SamplingConfig,
}
```

### ChatStateSnapshot

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

### Fire-and-Forget Mutations

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

The agent lifecycle system provides hook points for extensions.

### TurnLifecycleContributor

```rust
pub trait TurnLifecycleContributor: Send + Sync {
    fn on_turn_start(&self, input: TurnStartInput) -> Option<TurnLifecycleAction>;
    fn on_turn_done(&self, input: TurnDoneInput);
    fn on_turn_error(&self, input: TurnErrorInput);
    fn on_turn_abort(&self, input: TurnAbortInput);
}
```

### TurnInputContributor

```rust
pub trait TurnInputContributor: Send + Sync {
    fn contribute(&self, ctx: &TurnInputContext) -> TurnInputFragment;
}
```

### SessionLifecycleContributor

```rust
pub trait SessionLifecycleContributor: Send + Sync {
    fn on_session_idle(&self, input: SessionIdleInput);
}
```

### CommandContributor

```rust
pub trait CommandContributor: Send + Sync {
    fn command_specs(&self) -> Vec<CommandSpec>;
    fn invoke(&self, invocation: CommandInvocation) -> CommandAction;
}
```

---

## Token Estimation

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

```rust
pub trait ChatPersistence: Send {
    fn load(&mut self) -> Option<ChatStateSnapshot>;
    fn save(&mut self, record: &PersistenceRecord);
    fn flush(&mut self);
}
```

Implementations:
- `NullChatPersistence` - No-op persistence
- `MockChatPersistence` - In-memory for testing
- `JsonFileChatPersistence` - File-based (in xai-grok-shell)

---

## Design Patterns

### 1. Actor Pattern
- All mutable state lives in a single tokio task
- Commands dispatched via `mpsc::UnboundedSender`
- No locks needed - sequential processing guarantees consistency

### 2. Fire-and-Forget + Oneshot Pattern
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
Instead of cloning items on push, record the conversation length at capture start. At take time, slice the new conversation.

```rust
// At begin_turn_capture:
turn_start_offset = conversation.len();

// At take_turn_messages:
let messages = conversation[turn_start_offset..].to_vec();
```

### 4. Capability Injection
Contributors receive data-only inputs; anything they act through is a capability injected at install time.

### 5. Serialization with Turn State
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