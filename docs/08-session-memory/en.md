# Session and State Management

This document details the session and state management architecture in the `xai-chat-state` crate, including core data structures, key flows, API interfaces, and design patterns.

## Overview

`xai-chat-state` is a session state management module extracted from `xai-grok-shell`'s `acp_session.rs`, running as an Actor in a dedicated tokio task. It manages conversation history, token counting, sampling configuration, credentials, and other core states, coordinating with the main session loop via an event channel.

### Architecture Diagram

```
┌────────────────┐                  ┌──────────────────────────────────────┐
│ SessionActor   │ ─── Command ───▶ │        ChatStateActor                │
│  (push_user,   │                  │  (runs in dedicated tokio task)      │
│   build_req)   │                  │                                      │
└────────────────┘                  │  State (no locks needed):            │
                                    │  - conversation: Vec<ConversationItem>│
┌────────────────┐                  │  - sampling_config: SamplingConfig   │
│   Query (e.g.  │ ── Cmd+Oneshot ─▶│  - prompt_index: usize              │
│  get_conv)     │ ◀── Response ────│  - total_tokens: u64                │
└────────────────┘                  │                                      │
                                    │         │ ChatStateEvent             │
                                    │         ▼                            │
                                    │  ┌──────────────────┐               │
                                    │  │ event_tx         │───▶ Session   │
                                    │  └──────────────────┘               │
                                    └──────────────────────────────────────┘
```

## Core Data Structures

### ChatStateConfig

Configuration parameters for initializing the ChatStateActor:

```rust
pub struct ChatStateConfig {
    /// Initial conversation items
    pub initial_conversation: Vec<ConversationItem>,
    /// Sampling config (model, context window, etc.)
    pub sampling_config: SamplingConfig,
}
```

### ChatStateSnapshot

Immutable snapshot of Actor state, used for session forking and rewinding:

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatStateSnapshot {
    /// Full conversation history
    pub conversation: Vec<ConversationItem>,
    /// Current sampling config
    pub sampling_config: SamplingConfig,
    /// Current prompt index (increments per user turn)
    pub prompt_index: usize,
    /// Cumulative token usage
    pub total_tokens: u64,
    /// Estimated value at last response (for re-estimation after compaction)
    pub estimate_at_last_response: u64,
    /// File paths edited by the agent
    pub agent_edited_paths: BTreeSet<String>,
    /// Cached prompt text for rewind preview
    pub prompt_texts: Vec<String>,
    /// Timestamp when current stream started (milliseconds)
    pub stream_start_ms: Option<i64>,
    /// Timestamp when current turn started (milliseconds)
    pub turn_start_ms: Option<i64>,
    /// Prompt index at last compaction
    pub last_compaction_prompt_index: Option<usize>,
    /// Credential keys
    pub credentials: Credentials,
}
```

### ChatState

Internal mutable state, exclusively owned by the Actor, no locks needed:

```rust
pub(crate) struct ChatState {
    /// Full conversation history
    pub conversation: Vec<ConversationItem>,
    /// Current sampling config
    pub sampling_config: SamplingConfig,
    /// Current prompt index
    pub prompt_index: usize,
    /// Cached prompt texts
    pub prompt_texts: Vec<String>,
    /// Cumulative token usage
    pub total_tokens: u64,
    /// Current stream start timestamp
    pub stream_start_ms: Option<i64>,
    /// Current turn start timestamp
    pub turn_start_ms: Option<i64>,
    /// File paths edited by the agent
    pub agent_edited_paths: BTreeSet<String>,
    /// Prompt index at last compaction
    pub last_compaction_prompt_index: Option<usize>,
    /// Credential keys (API key, optional extra auth, client version)
    pub credentials: Credentials,
    /// Estimated new tokens since last record_token_usage
    pub estimated_tokens_since_model: u64,
    /// Conversation estimate at last response
    pub estimate_at_last_response: u64,
    /// Token usage for the most recent model response turn
    pub last_turn_usage: Option<TokenUsage>,
    /// Billing for current prompt (cleared at next prompt)
    pub prompt_usage: Option<UsageLedger>,
    /// Session lifecycle billing (not persisted)
    pub session_usage: UsageLedger,
    /// Offset-based turn capture state
    pub turn_capture: Option<TurnCaptureState>,
    /// Tool chain trace buffer
    pub harness_trace_buffer: Vec<ConversationItem>,
    /// Sealed tool chain trace turns
    pub harness_trace_turns: Vec<Vec<ConversationItem>>,
}
```

### TurnCaptureState

Tracks which conversation item the current turn belongs to, without cloning each pushed item:

```rust
pub(super) struct TurnCaptureState {
    /// Index where this turn's messages start in the conversation
    pub turn_start_offset: usize,
    /// Messages saved before conversation replacement
    pub pre_replacement_messages: Vec<ConversationItem>,
    /// Whether compaction occurred this turn
    pub compaction_occurred: bool,
}
```

### Credentials

Keys stored in the Actor for use by the request builder:

```rust
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Credentials {
    /// API key
    pub api_key: Option<String>,
    /// Auth type (session token vs API key)
    pub auth_type: AuthType,
    /// Optional extra auth material
    pub alpha_test_key: Option<String>,
    /// Client version string
    pub client_version: Option<String>,
}

pub enum AuthType {
    /// From AuthManager (grok login, OIDC, external binary)
    SessionToken,
    /// From user config or environment variable
    ApiKey,
}
```

### PruningConfig

Tool result pruning configuration for freeing context space:

```rust
pub struct PruningConfig {
    /// Whether pruning is enabled
    pub enabled: bool,
    /// Never prune tool results from the last N turns
    pub keep_last_n_turns: usize,
    /// Character threshold for soft pruning of old tool results
    pub soft_trim_threshold: usize,
    /// Characters to keep from the start during soft pruning
    pub soft_trim_head: usize,
    /// Characters to keep from the end during soft pruning
    pub soft_trim_tail: usize,
    /// Turn age at which tool results are hard cleared (replaced with placeholder)
    pub hard_clear_age_turns: usize,
}
```

## Key Flows

### Actor Lifecycle

1. **Spawn**: Create Actor and Handle via `ChatStateActor::spawn()`
2. **Run Loop**: Actor runs in a dedicated tokio task, processing commands
3. **Shutdown**: Triggered via cancellation token or when all handles are dropped

```rust
impl ChatStateActor {
    pub fn spawn(
        initial_conversation: Vec<ConversationItem>,
        sampling_config: SamplingConfig,
        persistence: Box<dyn ChatPersistence>,
        event_tx: mpsc::UnboundedSender<ChatStateEvent>,
        cancellation_token: CancellationToken,
    ) -> ChatStateHandle
}
```

### Command Processing Loop

```rust
async fn run(mut self) {
    loop {
        tokio::select! {
            biased;
            _ = self.cancellation_token.cancelled() => break,
            cmd = self.cmd_rx.recv() => {
                let Some(cmd) = cmd else { break; };
                self.handle_command(cmd);
            }
        }
    }
}
```

### User Message Push Flow

```
push_user_message(item)
    │
    ├─► ensure_conversation_integrity()  // Fix dangling tool calls
    │
    ├─► Estimate new tokens
    │
    ├─► persistence.persist_message(&item)
    │
    ├─► self.state.conversation.push(item)
    │
    └─► prune_retained_conversation()  // Proactive cleanup of old tool results
```

### Session Rewind Flow

```
truncate_to_prompt_index(target)
    │
    ├─► Find position of Nth User message
    │
    ├─► Truncate conversation to that position
    │
    ├─► Re-estimate token count
    │
    ├─► persistence.replace_history()
    │
    └─► Send ConversationReset event
```

### State Snapshot and Restore

```rust
// Snapshot
pub(super) fn snapshot(&self) -> ChatStateSnapshot {
    ChatStateSnapshot {
        conversation: self.state.conversation.clone(),
        sampling_config: self.state.sampling_config.clone(),
        prompt_index: self.state.prompt_index,
        total_tokens: self.state.total_tokens,
        // ... other fields
    }
}

// Restore
pub(super) fn restore_snapshot(&mut self, snap: ChatStateSnapshot) {
    self.snapshot_turn_slice();
    self.state.conversation = snap.conversation;
    self.state.sampling_config = snap.sampling_config;
    self.state.prompt_index = snap.prompt_index;
    // ... restore other fields
}
```

## API Interface

### ChatStateHandle

Handle for communicating with the Actor, safely cloneable and shareable across tasks.

#### Mutation Commands (fire-and-forget)

```rust
impl ChatStateHandle {
    /// Push user message
    pub fn push_user_message(&self, item: ConversationItem);

    /// Push assistant response
    pub fn push_assistant_response(&self, item: ConversationItem);

    /// Push tool result
    pub fn push_tool_result(&self, item: ConversationItem);

    /// Record token usage
    pub fn record_token_usage(&self, total_tokens: u64);

    /// Increment prompt index
    pub fn increment_prompt_index(&self);

    /// Replace conversation history
    pub fn replace_conversation(&self, items: Vec<ConversationItem>);

    /// Replace conversation history (for compaction)
    pub fn replace_conversation_for_compaction(&self, items: Vec<ConversationItem>);

    /// Begin capturing turn messages
    pub fn begin_turn_capture(&self);

    /// Flush persistence writes
    pub fn flush(&self);
}
```

#### Async Query Commands

```rust
impl ChatStateHandle {
    /// Build API request
    pub async fn build_request(
        &self,
        tool_definitions: Vec<ToolSpec>,
        memory_reminder: Option<String>,
        persist_memory_reminder: bool,
        trace: Option<Box<dyn TraceContext>>,
        conv_id: String,
        req_id: String,
    ) -> Option<ConversationRequest>;

    /// Get full conversation
    pub async fn get_conversation(&self) -> Vec<ConversationItem>;

    /// Get current prompt index
    pub async fn get_prompt_index(&self) -> usize;

    /// Get total token count
    pub async fn get_total_tokens(&self) -> u64;

    /// Get sampling config
    pub async fn get_sampling_config(&self) -> Option<SamplingConfig>;

    /// State snapshot
    pub async fn snapshot(&self) -> Option<ChatStateSnapshot>;

    /// Truncate to specified prompt index
    pub async fn truncate_to_prompt_index(&self, target: usize);

    /// Check if auto compaction is needed
    pub async fn check_auto_compact_needed(&self, threshold_percent: u8) -> Option<AutoCompactTrigger>;
}
```

#### Precise Queries (avoid full clones)

```rust
impl ChatStateHandle {
    /// Get conversation length (no clone needed)
    pub async fn get_conversation_len(&self) -> usize;

    /// Has dangling tool calls
    pub async fn has_dangling_tool_calls(&self) -> bool;

    /// Get last assistant text
    pub async fn get_last_assistant_text(&self) -> Option<String>;

    /// Get first user text
    pub async fn get_first_user_text(&self) -> Option<String>;

    /// Get conversation item counts
    pub async fn get_conversation_counts(&self) -> ConversationCounts;

    /// Get first system message
    pub async fn get_system_message(&self) -> Option<ConversationItem>;
}
```

## Event System

The Actor sends events to the session main loop via an event channel:

```rust
pub enum ChatStateEvent {
    /// Prompt index changed
    PromptIndexChanged { new_index: usize },

    /// Token count updated
    TokensUpdated { total_tokens: u64 },

    /// Conversation replaced (compaction/rewind)
    ConversationReset { new_len: usize },

    /// Image budget info
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

## Persistence Interface

```rust
pub trait ChatPersistence: Send + 'static {
    /// Persist a single conversation item
    fn persist_message(&mut self, item: &ConversationItem);

    /// Replace entire conversation history
    fn replace_history(&mut self, items: &[ConversationItem]);

    /// Flush pending writes to disk
    fn flush(&mut self);
}
```

### Implementation Variants

- **MockChatPersistence**: Channel implementation for testing
- **NullChatPersistence**: No-op implementation (for benchmarking)

## Design Patterns

### 1. Actor Pattern

- Actor runs in a dedicated tokio task
- All state is exclusively owned by the Actor, no locks needed
- Receives commands via mpsc channel
- Returns query responses via oneshot channel

### 2. Command Pattern

```rust
pub enum ChatStateCommand {
    // Mutation commands
    PushUserMessage { item: ConversationItem },
    ReplaceConversation { items: Vec<ConversationItem>, is_compaction: bool },
    // ...
    
    // Query commands
    GetConversation { reply: oneshot::Sender<Vec<ConversationItem>> },
    Snapshot { reply: oneshot::Sender<ChatStateSnapshot> },
    // ...
}
```

### 3. Write Boundary Integrity Repair

Integrity repair is only called at write boundaries:

- `ChatState::new()` - At startup
- `push_user_message()` - At start of new turn
- `BuildConversationRequest` - Before building request

Not called in read handlers to avoid misidentifying in-flight tool calls as dangling.

### 4. Turn Capture Pattern

Uses offsets instead of copying each item:

```rust
pub(super) struct TurnCaptureState {
    turn_start_offset: usize,  // Conversation length at capture start
    pre_replacement_messages: Vec<ConversationItem>,  // Messages saved before replacement
    compaction_occurred: bool,
}
```

### 5. Token Estimation

Uses bytes/4 estimation, no real tokenization needed:

```rust
pub fn estimate_item_tokens(item: &ConversationItem) -> u64 {
    // Images count as fixed constant
    // Text counts as bytes/4
    // ...
}
```

### 6. Opaque Credential Storage

Actor stores credentials but never interprets them:

```rust
pub struct Credentials {
    pub api_key: Option<String>,
    pub auth_type: AuthType,
    pub alpha_test_key: Option<String>,
    pub client_version: Option<String>,
}
```

## Compaction Mode

### CompactionMode

Defines how the model accesses historical details after compaction:

```rust
pub enum CompactionMode {
    /// Summary only (default)
    Summary,
    /// Summary + pointer to full original updates.jsonl
    Transcript,
    /// Summary + segmented markdown in compaction folder
    Segments(CompactionDetail),
}

pub enum CompactionDetail {
    None,      // Statistics only
    Minimal,   // One line of tool signature per turn
    Balanced,  // Tool calls + truncated responses
    Verbose,   // Complete verbatim turns
}
```

### Compaction Context

Session state captured during compaction:

```rust
pub struct CompactionStateContext {
    /// Messages since last real user turn
    pub recent_messages: Vec<ConversationItem>,
    /// Last real user query text
    pub last_user_query: Option<String>,
    /// Files edited by agent
    pub agent_edited_paths: Vec<String>,
    /// Running background tasks
    pub running_tasks: Vec<BackgroundTaskSummary>,
    /// Subagents still running
    pub running_subagents: Vec<RunningSubagentSummary>,
    /// Connected MCP servers
    pub connected_mcp_servers: Vec<CompactionServerSummary>,
    /// Todo list
    pub todos: Vec<TodoSummary>,
}
```

## Usage System

### UsageLedger

Tracks billing by prompt and session:

```rust
pub struct UsageTotals {
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub cached_read_tokens: u64,
    pub reasoning_tokens: u64,
    pub model_calls: u64,
    pub api_duration_ms: u64,
    pub cost_usd_ticks: Option<i64>,
    pub cost_missing_calls: u64,
}

pub struct UsageLedger {
    pub totals: UsageTotals,
    pub by_model: IndexMap<String, UsageTotals>,
    pub main_loop_model_calls: u64,
    pub incomplete: bool,  // Billing may be incomplete
}
```

### Completeness Ownership

- `UsageLedger.incomplete`: Persisted on billing snapshot
- Sticky flag: Report-level signal only
- Foreground live IDs: Collapse may still occur
- Background live: Never wait, mark incomplete immediately

## Real User Identification

Distinguishes real user turns from synthetic injections:

```rust
pub fn is_real_user_turn(item: &ConversationItem) -> bool {
    match item {
        ConversationItem::User(u) => {
            // non-empty synthetic_reason = not real
            if u.synthetic_reason.is_some() {
                return false;
            }
            // has images = real
            if has_images { return true; }
            // Is extracted query text synthetic?
            !is_synthetic_extracted_query(&extracted)
        }
        _ => false,
    }
}
```

Synthetic turns include:
- System reminders
- Auto-continue prompts
- Bootstrap messages with metadata only

## File Structure

```
xai-chat-state/src/
├── lib.rs              # Module exports and public API
├── actor/
│   ├── mod.rs          # ChatStateActor main module
│   ├── state.rs        # ChatState internal state
│   ├── mutations.rs    # State mutation handling
│   ├── queries.rs      # Read-only query handling
│   ├── request_builder.rs  # Request building logic
│   └── tests.rs        # Actor tests
├── commands.rs         # ChatStateCommand enum
├── events.rs           # ChatStateEvent enum
├── handle.rs           # ChatStateHandle implementation
├── persistence.rs      # ChatPersistence trait and implementations
├── types.rs            # Shared domain types
├── compaction_mode.rs  # Compaction mode definitions
├── compaction_transcript.rs  # Segmented markdown rendering
├── compaction_utils.rs # Compaction utilities
├── conversation_util.rs # Conversation utilities
└── usage.rs            # Usage ledger
```

## Usage Examples

### Creating an Actor

```rust
let (event_tx, _event_rx) = mpsc::unbounded_channel();
let cancellation_token = CancellationToken::new();
let persistence = Box::new(MockChatPersistence::new());

let handle = ChatStateActor::spawn(
    initial_conversation,
    sampling_config,
    persistence,
    event_tx,
    cancellation_token,
);
```

### Pushing Messages

```rust
handle.push_user_message(ConversationItem::user("Hello!"));
handle.increment_prompt_index();
handle.push_assistant_response(ConversationItem::assistant("Hi there!"));
handle.push_tool_result(ConversationItem::tool_result("call-1", "result"));
```

### Building Requests

```rust
let request = handle
    .build_request(
        tool_definitions,
        memory_reminder,
        false,
        None,
        conv_id,
        req_id,
    )
    .await;
```

### Session Rewind

```rust
handle.truncate_to_prompt_index(2).await;
```

### State Snapshot and Restore

```rust
let snapshot = handle.snapshot().await.unwrap();
handle.restore_snapshot(snapshot);
```

## Thread Safety

- `ChatStateHandle` is `Clone + Send + 'static`
- Safely shareable across multiple tasks
- Actor runs in a dedicated task, processing all commands sequentially
- No external synchronization needed

## Error Handling

- Command send failure (Actor dead) returns `None` or `Err(())`
- Query response lost (Actor dead) returns `None`
- Integrity repair rejection (turn in progress) returns `RepairHistoryBlocked`

```rust
pub struct RepairHistoryBlocked;

impl std::fmt::Display for RepairHistoryBlocked {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "cannot repair history while a turn is in flight")
    }
}
```

## Testing

The module includes comprehensive unit tests:

- Command variant construction tests
- State default initialization tests
- Token estimation tests
- Compaction summary format tests
- Real user identification tests
- Persistence mock tests

Run tests:

```bash
cargo test -p xai-chat-state
```