# Tool System Documentation

## Table of Contents

1. [Overview](#overview)
2. [Core Data Structures](#core-data-structures)
3. [Tool Trait and Implementation](#tool-trait-and-implementation)
4. [Key Flows](#key-flows)
5. [API Interfaces](#api-interfaces)
6. [Design Patterns](#design-patterns)
7. [Streaming Contract](#streaming-contract)
8. [Error Handling](#error-handling)

---

## Overview

The Grok Build tool system is a modular framework for executing AI agent tools via the Computer Hub protocol. It provides:

- **Unified Tool Interface**: A trait-based system (`Tool`) that abstract tool implementations
- **Protocol Layer**: JSON-RPC based communication via `xai-tool-protocol`
- **Runtime Engine**: Execution engine in `xai-tool-runtime` for streaming, dispatch, and error handling
- **Tool Registry**: Centralized registration and discovery in `xai-grok-tools`

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Computer Hub (Service)                    │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐ │
│  │   Tool      │  │   Tool      │  │   Tool Dispatch      │ │
│  │   Registry  │  │   Search    │  │   (ToolDispatch)     │ │
│  └─────────────┘  └─────────────┘  └──────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐│
│  │              xai-tool-runtime (Runtime Engine)          ││
│  │  ┌────────────┐  ┌────────────┐  ┌───────────────────┐  ││
│  │  │Tool Stream │  │  Context   │  │    Render/Output  │  ││
│  │  └────────────┘  └────────────┘  └───────────────────┘  ││
│  └─────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐│
│  │              xai-tool-protocol (Wire Protocol)          ││
│  │  ┌───────────┐  ┌────────────┐  ┌────────────────────┐  ││
│  │  │ Methods   │  │  Frames    │  │  IDs (ToolId, etc) │  ││
│  │  └───────────┘  └────────────┘  └────────────────────┘  ││
│  └─────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐│
│  │              xai-grok-tools (Implementations)           ││
│  │  ┌─────────────────────────────────────────────────┐   ││
│  │  │  File tools, Search tools, Bash, Web tools...    │   ││
│  │  └─────────────────────────────────────────────────┘   ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

---

## Core Data Structures

### ToolId

Unique identifier for each tool, defined in `xai-tool-protocol/src/ids.rs`.

```rust
// Format: `{namespace}:{name}` or `{name}`
// Each segment must match `[a-zA-Z0-9_-]+`
pub struct ToolId(String);
```

**Construction:**
```rust
ToolId::new("GrokBuild:read_file")  // Ok
ToolId::new("read_file")            // Ok
ToolId::new("")                     // Err(IdError::Empty)
ToolId::new("GrokBuild:")           // Err(IdError::InvalidFormat)
```

### ToolCallId

End-to-end identifier for a single tool invocation. Uses UUID v7.

```rust
ToolCallId::new_v7()  // Generates fresh UUID v7
```

### ToolCallContext

Per-call context passed to every tool execution.

```rust
pub struct ToolCallContext {
    pub call_id: ToolCallId,       // Unique call identifier
    pub extensions: TypedExtensions, // Type-safe extension store
}

impl ToolCallContext {
    pub fn new(call_id: ToolCallId) -> Self;
    pub fn insert<T>(&mut self, value: T) -> &mut Self;  // Add extension
    pub fn get<T>(&self) -> Option<Arc<T>>;              // Get extension
}
```

### TypedExtensions

Open typed-extension store keyed by `TypeId`.

```rust
pub struct TypedExtensions {
    map: HashMap<TypeId, Arc<dyn Any + Send + Sync>>,
}

impl TypedExtensions {
    pub fn insert<T: Send + Sync + 'static>(&mut self, value: T) -> &mut Self;
    pub fn get<T: Send + Sync + 'static>(&self) -> Option<Arc<T>>;
    pub fn contains<T: Send + Sync + 'static>(&bool;
    pub fn merge_defaults(&mut self, defaults: &TypedExtensions);
}
```

### ListToolsContext

Context consumed by `Tool::should_list` for per-turn listing predicate.

```rust
pub struct ListToolsContext {
    pub extensions: TypedExtensions,
}
```

### ToolNamespace

Toolset classification.

```rust
pub enum ToolNamespace {
    GrokBuild,
    GrokBuildConcise,
    GrokBuildHashline,
    Codex,
    OpenCode,
    MCP,
}
```

### ToolKind

High-level tool categorization.

```rust
pub enum ToolKind {
    Read,
    Edit,
    Delete,
    ListDir,
    Write,
    Move,
    Search,
    Lsp,
    Execute,
    Plan,
    WebSearch,
    WebFetch,
    BackgroundTaskAction,
    Task,
    Skill,
    MemorySearch,
    ImageGen,
    // ... and more
    Other,
}
```

### TransportKind

Whether a tool runs in-process or remote.

```rust
pub enum TransportKind {
    Local,
    Remote,
}
```

---

## Tool Trait and Implementation

### The Tool Trait

Located in `xai-tool-runtime/src/tool.rs`, the core trait for tool implementations:

```rust
pub trait Tool: Send + Sync {
    type Args: for<'de> Deserialize<'de> + JsonSchema + Send + 'static;
    type Output: Serialize + ToolOutput + Send + 'static;

    fn id(&self) -> ToolId;
    fn description(&self, _ctx: &ListToolsContext) -> ToolDescription;
    fn capabilities(&self) -> ToolCapabilities;
    fn has_dynamic_description(&self) -> bool { false }
    fn should_list(&self, _ctx: &ListToolsContext) -> bool { true }

    fn execute(
        &self,
        ctx: ToolCallContext,
        args: Self::Args,
    ) -> impl Future<Output = ToolStream<Self::Output>> + Send;

    fn run(
        &self,
        ctx: ToolCallContext,
        args: Self::Args,
    ) -> impl Future<Output = Result<Self::Output, ToolError>> + Send;
}
```

### Tool Implementation Pattern

```rust
use async_trait::async_trait;
use xai_tool_runtime::{Tool, ToolOutput, terminal_only, ToolStream};
use xai_tool_protocol::ToolId;

pub struct ReadFileTool;

#[derive(serde::Deserialize, schemars::JsonSchema)]
pub struct ReadFileArgs {
    pub path: String,
    #[serde(default)]
    pub offset: Option<u64>,
}

#[derive(serde::Serialize)]
pub struct ReadFileOutput {
    pub content: String,
    pub bytes_read: u64,
}

impl ToolOutput for ReadFileOutput {
    fn model_output(&self) -> Vec<ContentBlock> {
        vec![ContentBlock::Text { text: self.content.clone() }]
    }

    fn chat_completion_output(&self) -> Option<ToolChatCompletionResponse> {
        None
    }
}

#[async_trait]
impl Tool for ReadFileTool {
    type Args = ReadFileArgs;
    type Output = ReadFileOutput;

    fn id(&self) -> ToolId {
        ToolId::new("GrokBuild:read_file").unwrap()
    }

    fn description(&self, _ctx: &ListToolsContext) -> ToolDescription {
        ToolDescription {
            name: "read_file".into(),
            description: "Read file contents".into(),
            namespace: Some("GrokBuild".into()),
            // ...
        }
    }

    async fn run(
        &self,
        _ctx: ToolCallContext,
        args: Self::Args,
    ) -> Result<Self::Output, ToolError> {
        // Implementation
        let content = tokio::fs::read_to_string(&args.path).await
            .map_err(|e| ToolError::execution(self.id(), e.to_string()))?;

        Ok(ReadFileOutput {
            content,
            bytes_read: content.len() as u64,
        })
    }
}
```

### ToolDyn (Type-Erased Tool)

Auto-generated blanket implementation for dynamic dispatch:

```rust
#[async_trait]
pub trait ToolDyn: Send + Sync {
    fn id(&self) -> ToolId;
    fn description(&self, ctx: &ListToolsContext) -> ToolDescription;
    fn capabilities(&self) -> ToolCapabilities;
    async fn execute(&self, ctx: ToolCallContext, args: Value) -> ToolStream<TypedToolOutput>;
}

pub type ArcTool = Arc<dyn ToolDyn>;
```

---

## Key Flows

### Tool Execution Flow

```
1. Hub receives tool.call request
          │
          ▼
2. ToolDispatch::call(tool_id, args, ctx)
          │
          ▼
3. Route to concrete tool implementation
          │
          ▼
4. Tool::execute(ctx, args) → ToolStream<T>
          │
          ▼
5. Stream: [Progress*, Terminal(Result<T, ToolError>)]
          │
          ▼
6. ToolDyn adapter serializes and extracts ContentBlock
          │
          ▼
7. TypedToolOutput returned to hub
```

### Tool Registration Flow

```
1. Tool Server sends register_tool or register_server
          │
          ▼
2. Hub validates ToolId derivation
          │
          ▼
3. Registry stores: (connection_id, tool_id) → tool
          │
          ▼
4. Session bindings applied (sessions field)
          │
          ▼
5. RegistrationOutcome returned
          │
          ▼
6. If tool set changed: tools_changed notification sent
```

### Streaming Tool Flow

```rust
// Tool declares streaming capability
fn capabilities(&self) -> ToolCapabilities {
    ToolCapabilities {
        streaming: Some(StreamingSpec {
            subkind: "bash_output".into(),
            max_delta_bytes: Some(16 * 1024),
        }),
        ..Default::default()
    }
}

// Tool implementation uses with_progress
fn execute(&self, ctx: ToolCallContext, args: Self::Args) -> impl Future<Output = ToolStream<Self::Output>> + Send {
    let progress_stream = self.stream_output(ctx.clone());
    let final_result = self.run_bash(ctx, args);
    with_progress(progress_stream, final_result)
}
```

---

## API Interfaces

### JSON-RPC Methods

Defined in `xai-tool-protocol/src/methods.rs`:

| Method | Direction | Description |
|--------|-----------|-------------|
| `session_open` | harness → service | Open a new session |
| `session_close` | harness → service | Close a session |
| `session_bind_server` | harness → service | Bind server to session |
| `tools.list` | harness → service | List available tools |
| `tools.search` | harness → service | Search tools |
| `tool.call` | harness → service | Execute a tool |
| `tool.cancel` | harness → service | Cancel a tool call |
| `tool.call_progress` | tool_server → service | Streaming progress |
| `tool.notification` | tool_server → service | Tool notification |
| `tools_changed` | service → harness | Tools changed notification |
| `serve` | server → hub | Serve session with tools |
| `session.bind` | hub → server | Start serving session |

### ToolDispatch Trait

Object-safe dispatch interface in `xai-tool-runtime/src/dispatch.rs`:

```rust
#[async_trait]
pub trait ToolDispatch: Send + Sync {
    async fn call(
        &self,
        tool_id: ToolId,
        args: Value,
        ctx: ToolCallContext,
    ) -> ToolStream<TypedToolOutput>;

    async fn call_terminal(
        &self,
        tool_id: ToolId,
        args: Value,
        ctx: ToolCallContext,
    ) -> Result<TypedToolOutput, ToolError> {
        // Default: drain stream, return terminal result
    }
}
```

### Registration Structures

```rust
// Single tool registration
pub struct ToolRegistration {
    pub tool_id: ToolId,
    pub sessions: Option<Vec<SessionId>>,
    pub user_id: UserId,
    pub description: ToolDescription,
    pub input_schema: Option<serde_json::Value>,
    pub capabilities: Option<ToolCapabilities>,
    pub transport_kind: TransportKind,
    pub if_match_generation: Option<u64>,
}

// Server registration (batch)
pub struct ToolServerRegistration {
    pub server_id: ServerId,
    pub sessions: Option<Vec<SessionId>>,
    pub user_id: UserId,
    pub tools: Vec<ToolDescriptionWithSchema>,
    pub hooks: Vec<HookKind>,
    // ...
}

// Registration outcome
pub enum RegistrationOutcome {
    Registered { tool_id: ToolId, generation: u64 },
    Updated { tool_id: ToolId, generation: u64 },
    Shadowed { tool_id: ToolId, reason: String },
    Rejected { tool_id: ToolId, code: String, message: String },
}
```

---

## Design Patterns

### 1. Trait Object Pattern (ToolDyn)

Tools use typed `Tool` trait but dispatch uses type-erased `ToolDyn`:

```rust
// Registry stores Arc<dyn ToolDyn>
pub struct ToolRegistry {
    tools: HashMap<ToolId, Arc<dyn ToolDyn>>,
}

impl ToolDispatch for ToolRegistry {
    async fn call(&self, tool_id: ToolId, args: Value, ctx: ToolCallContext) -> ToolStream<TypedToolOutput> {
        let tool = self.tools.get(&tool_id)?;
        tool.execute(ctx, args).await
    }
}
```

### 2. Builder Pattern (Context Extensions)

```rust
let mut ctx = ToolCallContext::default();
ctx.insert(Cwd(std::path::PathBuf::from("/workspace")));
ctx.insert(BehaviorVersion("v2".to_string()));
```

### 3. Streaming Helpers

```rust
// Blocking tool: wraps result in terminal_only
terminal_only(result)

// Streaming tool: combines progress + terminal
with_progress(progress_stream, final_result)
```

### 4. Newtype ID Pattern

Prevent ID mixing via opaque newtypes:

```rust
opaque_id!(SessionId);
opaque_id!(ToolId, extra_validator = validate_tool_id);
opaque_id!(ToolCallId);
opaque_id!(ServerId, extra_validator = validate_server_id);
```

### 5. Three-State Semantics

Sessions field uses three-state pattern:

```rust
// None: "no change" - preserve existing bindings
// Some(vec![]): "unbind all"
// Some(vec![s1, ...]): "replace with these"
pub sessions: Option<Vec<SessionId>>,
```

### 6. Tool Family Pattern

Support multiple implementations under one ToolId:

```rust
pub trait ToolFamily: Send + Sync {
    fn id(&self) -> ToolId;
    fn get_tool(&self, variant: &ToolVariant) -> Option<ArcTool>;
    fn variants(&self) -> Vec<ToolVariant>;
}

pub enum ToolVariant {
    Default,
    Variant(String),
}
```

---

## Streaming Contract

### ToolStream Invariant

Streams must follow: `[Progress(_)*, Terminal(Result<T, ToolError>)]`

- Zero or more `Progress` items
- Exactly one `Terminal` item (always last)

### ToolStreamItem

```rust
pub enum ToolStreamItem<T> {
    Progress(ToolProgress),
    Terminal(Result<T, ToolError>),
}
```

### ToolProgress Variants

```rust
pub enum ToolProgress {
    Text { text: String },
    Content { blocks: Vec<ContentBlock> },
    Custom { subkind: String, payload: Value },
}
```

### ContentBlock Types

```rust
pub enum ContentBlock {
    Text { text: String },
    Image {
        mime_type: String,
        data: String,
        media_id: Option<String>,
        filename: Option<String>,
        path: Option<String>,
        metadata: HashMap<String, String>,
    },
    Resource {
        uri: String,
        mime_type: Option<String>,
        text: Option<String>,
    },
}
```

### PartialResultPayload

Canonical streaming payload for chunked output:

```rust
pub struct PartialResultPayload {
    pub delta: String,           // New content since last tick
    pub total_bytes: u64,        // Total bytes so far
    pub truncated: bool,         // Cumulative upstream truncation
    pub gap: bool,               // Per-tick gap (bytes dropped)
}
```

### UTF-8 Safe Streaming

The `stream_chunk` function ensures:
- Deltas never split multi-byte UTF-8 sequences
- Oversized deltas are paced to frame cap
- Gap detection for dropped content

---

## Error Handling

### ToolError

```rust
pub enum ToolError {
    InvalidArguments(String),
    NotImplemented(String),
    Execution { tool_id: ToolId, message: String },
    Cancelled,
    // ...
}

impl ToolError {
    pub fn invalid_arguments(msg: impl Into<String>) -> Self;
    pub fn not_implemented(msg: impl Into<String>) -> Self;
    pub fn execution(tool_id: ToolId, msg: impl Into<String>) -> Self;
}
```

### Error Codes

```rust
pub enum ErrorCode {
    ParseError,
    InvalidRequest,
    MethodNotFound,
    InvalidArguments,
    InternalError,
}
```

### Error Flow

```
1. Tool returns Err(ToolError)
          │
          ▼
2. Wrapped in ToolStreamItem::Terminal(Err(...))
          │
          ▼
3. ToolDyn adapter: serde_json::to_value(&err) → Value
          │
          ▼
4. Terminal carries TypedToolOutput with error Value
          │
          ▼
5. Hub responds with JSON-RPC error response
```

---

## Module Reference

| Module | Location | Purpose |
|--------|----------|---------|
| `xai-tool-types` | `crates/common/` | Tool description types |
| `xai-tool-protocol` | `crates/common/` | Wire protocol |
| `xai-tool-runtime` | `crates/common/` | Execution engine |
| `xai-grok-tools` | `crates/codegen/` | Tool implementations |
| `xai-grok-workspace` | `crates/codegen/` | Workspace tools |
| `xai-computer-hub-core` | `crates/common/` | Hub core logic |
| `xai-computer-hub-sdk` | `crates/common/` | SDK for tool servers |