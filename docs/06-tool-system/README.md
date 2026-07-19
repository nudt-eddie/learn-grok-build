# Tool System Documentation

## Table of Contents

1. [Overview](#overview)
2. [Why This Design](#why-this-design)
3. [When to Use](#when-to-use)
4. [Core Data Structures](#core-data-structures)
5. [Tool Trait and Implementation](#tool-trait-and-implementation)
6. [Key Flows](#key-flows)
7. [API Interfaces](#api-interfaces)
8. [Design Patterns](#design-patterns)
9. [Streaming Contract](#streaming-contract)
10. [Error Handling](#error-handling)
11. [Source Evidence](#source-evidence)

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

## Why This Design

### 1. Trait-Based Architecture for Type Safety

The `Tool` trait uses associated types for `Args` and `Output`, enabling compile-time validation while maintaining dynamic dispatch via `ToolDyn`. This eliminates runtime type casting errors and enables the code generator to produce type-safe adapters automatically.

### 2. Streaming-First Model

Tools can emit progressive updates via `ToolStream<Progress*, Terminal>`. This design supports:
- Long-running operations (bash, search) that need to report progress
- Real-time feedback to users without waiting for completion
- Chunked output that respects terminal frame boundaries and UTF-8 boundaries

### 3. Context Extensions Pattern

`TypedExtensions` allows tools to receive contextual information without tight coupling:
- Behavioral flags can be injected (e.g., behavior versions)
- Session-scoped resources are available (working directory, user info)
- New context fields can be added without modifying all tool signatures

### 4. Three-State Session Binding

The `Option<Vec<SessionId>>` pattern avoids ambiguity:
- `None`: Preserve existing bindings
- `Some(vec![])`: Explicitly unbind all
- `Some(vec![s1, ...])`: Replace bindings

### 5. Open Extension Store

`TypedExtensions` uses `TypeId` as keys, enabling type-safe access to arbitrary context data without string-based lookups or interface bloat.

### 6. UUID v7 for Call IDs

ToolCallId uses UUID v7 for time-ordered generation, enabling efficient indexing and debugging of tool invocations across distributed systems.

---

## When to Use

### Use Tool::run() when:
- Tool execution is synchronous or completes quickly
- No intermediate progress needs to be reported
- Simple one-shot operations (read file, validate input)

### Use Tool::execute() when:
- Tool performs long-running operations (bash, build, search)
- Real-time progress updates improve user experience
- Output may be truncated and streamed incrementally
- The tool needs to check for cancellation during execution

### Add a new tool implementation when:
- You need to extend AI capabilities with new operations
- Existing tools do not cover the required functionality
- The operation can be modeled as input args + output result

### Use ToolFamilies when:
- Multiple variants exist for the same tool (e.g., ReadFile with different encoding support)
- Tool behavior needs to differ based on context or model version
- You need to provide a unified interface while supporting specialized implementations

### Use MCP servers when:
- Tools are hosted in external processes or services
- Cross-service integration is required
- Tools should be managed independently from the main application

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
┌──────────────────────────────────────────────────────────────────────┐
│                        TOOL EXECUTION FLOW                            │
└──────────────────────────────────────────────────────────────────────┘

   ┌──────────────┐
   │ JSON-RPC     │
   │ tool.call    │
   │ Request      │
   └──────┬───────┘
          │
          ▼
   ┌──────────────────────────────────────────┐
   │ 1. REQUEST VALIDATION                     │
   │    - Parse JSON-RPC payload               │
   │    - Validate tool_id format              │
   │    - Extract call_id and arguments        │
   └──────────────────────┬───────────────────┘
                          │
                          ▼
   ┌──────────────────────────────────────────┐
   │ 2. TOOL DISPATCH                          │
   │    ToolDispatch::call(tool_id, args, ctx) │
   │    - Lookup tool in registry              │
   │    - Create ToolCallContext               │
   └──────────────────────┬───────────────────┘
                          │
                          ▼
   ┌──────────────────────────────────────────┐
   │ 3. TOOL LOOKUP & ARGS PARSING             │
   │    - Find Arc<dyn ToolDyn> by ToolId      │
   │    - Deserialize args to Tool::Args       │
   │    - Check should_list predicate          │
   └──────────────────────┬───────────────────┘
                          │
                          ▼
   ┌──────────────────────────────────────────┐
   │ 4. EXECUTION (Tool::execute)              │
   │    - Create progress stream               │
   │    - Execute tool logic                   │
   │    - Return ToolStream<T>                 │
   └──────────────────────┬───────────────────┘
                          │
                          ▼
   ┌──────────────────────────────────────────┐
   │ 5. STREAM PROCESSING                      │
   │    [Progress*] ──────────────────────┐    │
   │         │                            │    │
   │         ▼                            │    │
   │    [Terminal] ◄──────────────────────┘    │
   │    (Result<T, ToolError>)                 │
   │                                          │
   │    Progress:                              │
   │    - ToolProgress::Text                   │
   │    - ToolProgress::Content                │
   │    - ToolProgress::Custom                 │
   └──────────────────────┬───────────────────┘
                          │
                          ▼
   ┌──────────────────────────────────────────┐
   │ 6. ADAPTER CONVERSION                     │
   │    ToolDyn adapter:                       │
   │    - Serialize output to Value            │
   │    - Extract ContentBlock for model       │
   │    - Wrap in TypedToolOutput              │
   └──────────────────────┬───────────────────┘
                          │
                          ▼
   ┌──────────────────────────────────────────┐
   │ 7. RESPONSE                               │
   │    - JSON-RPC response with result        │
   │    - Or JSON-RPC error response           │
   └──────────────────────────────────────────┘
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

### Error Handling Overview

The tool system implements a multi-layer error handling strategy:

```
┌─────────────────────────────────────────────────────────────────────┐
│                      ERROR HANDLING LAYERS                           │
└─────────────────────────────────────────────────────────────────────┘

   Layer 1: Tool Implementation
   ┌─────────────────────────────────────────────────────────────────┐
   │  return Err(ToolError::Execution { tool_id, message })          │
   └─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
   Layer 2: Runtime Stream
   ┌─────────────────────────────────────────────────────────────────┐
   │  ToolStreamItem::Terminal(Err(ToolError))                       │
   └─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
   Layer 3: Adapter Serialization
   ┌─────────────────────────────────────────────────────────────────┐
   │  serde_json::to_value(&err) → Value                             │
   └─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
   Layer 4: JSON-RPC Response
   ┌─────────────────────────────────────────────────────────────────┐
   │  { "error": { "code": -32603, "message": "..." } }              │
   └─────────────────────────────────────────────────────────────────┘
```

### ToolError

The central error type for tool execution:

```rust
pub enum ToolError {
    /// Invalid tool arguments (e.g., wrong type, missing required field)
    InvalidArguments(String),

    /// Tool capability not implemented
    NotImplemented(String),

    /// Execution failure with context
    Execution {
        tool_id: ToolId,
        message: String,
        /// Optional underlying error for chained diagnostics
        source: Option<Box<dyn std::error::Error + Send + Sync>>,
    },

    /// Tool call was cancelled by user or system
    Cancelled,

    /// Tool requires capabilities not available in current context
    CapabilityNotAvailable(String),

    /// Tool is temporarily unavailable (e.g., resource locked)
    TemporarilyUnavailable(String),

    /// Permission denied for this operation
    PermissionDenied {
        operation: String,
        resource: String,
    },
}

impl ToolError {
    /// Create an invalid arguments error
    pub fn invalid_arguments(msg: impl Into<String>) -> Self;

    /// Create a not implemented error
    pub fn not_implemented(msg: impl Into<String>) -> Self;

    /// Create an execution error with tool context
    pub fn execution(tool_id: ToolId, msg: impl Into<String>) -> Self;

    /// Wrap an underlying error with context
    pub fn with_source(self, err: impl std::error::Error + Send + Sync + 'static) -> Self;
}
```

### Error Code Mapping

JSON-RPC error codes mapped from ToolError variants:

| ToolError Variant | ErrorCode | HTTP Status |
|-------------------|-----------|-------------|
| `InvalidArguments` | `-32602` (InvalidParams) | 400 |
| `NotImplemented` | `-32601` (MethodNotFound) | 501 |
| `CapabilityNotAvailable` | `-32602` (InvalidParams) | 400 |
| `Execution` | `-32603` (InternalError) | 500 |
| `Cancelled` | `-32000` (ServerError) | 499 |
| `TemporarilyUnavailable` | `-32001` (ServerError) | 503 |
| `PermissionDenied` | `-32002` (ServerError) | 403 |

### Error Response Format

JSON-RPC error response structure:

```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32603,
    "message": "Tool 'GrokBuild:read_file' execution failed: No such file or directory",
    "data": {
      "tool_id": "GrokBuild:read_file",
      "call_id": "01HX5KM7PRQV8WN1TZ9YF3GD4E",
      "error_type": "Execution",
      "details": "No such file or directory",
      "source": null
    }
  },
  "id": "01HX5KM7PRQV8WN1TZ9YF3GD4E"
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

### Error Handling Patterns

#### Pattern 1: Try-Convert with `?` Operator

```rust
use xai_tool_runtime::{ToolError, ToolOutput};

#[derive(Serialize)]
pub struct ReadFileOutput {
    pub content: String,
}

impl ToolOutput for ReadFileOutput { /* ... */ }

async fn read_file_impl(path: &Path) -> Result<ReadFileOutput, ToolError> {
    // Use ? to auto-convert io::Error to ToolError
    let content = tokio::fs::read_to_string(path)
        .await
        .map_err(|e| ToolError::execution(
            self.id(),
            format!("Failed to read file: {}", e),
        ))?;

    Ok(ReadFileOutput { content })
}
```

#### Pattern 2: Custom Error Conversion

```rust
use thiserror::Error;

#[derive(Error, Debug)]
pub enum MyToolError {
    #[error("File not found: {0}")]
    FileNotFound(String),

    #[error("Permission denied: {0}")]
    PermissionDenied(String),

    #[error("IO error: {0}")]
    IoError(#[from] std::io::Error),
}

impl From<MyToolError> for ToolError {
    fn from(err: MyToolError) -> Self {
        match err {
            MyToolError::FileNotFound(path) => ToolError::invalid_arguments(
                format!("File not found: {}", path),
            ),
            MyToolError::PermissionDenied(op) => ToolError::PermissionDenied {
                operation: op,
                resource: "filesystem".to_string(),
            },
            MyToolError::IoError(e) => ToolError::execution(
                ToolId::new("MyTool").unwrap(),
                e.to_string(),
            ),
        }
    }
}
```

#### Pattern 3: Validation Errors

```rust
fn validate_args(args: &ReadFileArgs) -> Result<(), ToolError> {
    if args.path.is_empty() {
        return Err(ToolError::invalid_arguments("path cannot be empty"));
    }

    if args.path.contains("..") {
        return Err(ToolError::invalid_arguments(
            "path cannot contain '..' for security reasons",
        ));
    }

    if let Some(offset) = args.offset {
        if offset > 1_000_000_000 {
            return Err(ToolError::invalid_arguments(
                "offset too large (max 1GB)",
            ));
        }
    }

    Ok(())
}

async fn run(&self, ctx: ToolCallContext, args: Self::Args) -> Result<Self::Output, ToolError> {
    validate_args(&args)?;

    // Proceed with validated arguments
    // ...
}
```

#### Pattern 4: Graceful Degradation with Fallback

```rust
async fn run(&self, ctx: ToolCallContext, args: Self::Args) -> Result<Self::Output, ToolError> {
    // Try primary implementation
    match self.try_primary_impl(&args).await {
        Ok(output) => return Ok(output),
        Err(e) => {
            tracing::warn!(
                "Primary implementation failed, trying fallback: {}",
                e
            );
        }
    }

    // Fallback to secondary implementation
    self.try_fallback_impl(&args).await
}
```

#### Pattern 5: Contextual Error Enhancement

```rust
async fn run(&self, ctx: ToolCallContext, args: Self::Args) -> Result<Self::Output, ToolError> {
    let operation = format!("read file '{}'", args.path);

    tokio::fs::read_to_string(&args.path)
        .await
        .map_err(|e| {
            ToolError::execution(self.id(), format!("{}: {}", operation, e))
                .with_source(e)
        })
}
```

### Cancellation Handling

Tools should check for cancellation periodically:

```rust
async fn run(&self, ctx: ToolCallContext, args: Self::Args) -> Result<Self::Output, ToolError> {
    let mut stream = with_progress(self.progress_stream(), async {
        // Long-running operation
        let result = self.long_running_task().await?;

        // Check for cancellation
        if ctx.get::<CancelledFlag>().map(|f| f.is_cancelled()).unwrap_or(false) {
            return Err(ToolError::Cancelled);
        }

        Ok(result)
    });

    // Stream handles cancellation response
    stream
}
```

### Error Recovery Strategies

| Strategy | Use Case | Example |
|----------|----------|---------|
| Retry with backoff | Transient failures | Network timeouts |
| Fallback to default | Optional features | Missing optional dependency |
| Degrade gracefully | Partial failures | Cache miss → compute fresh |
| Propagate with context | Fatal failures | Permission denied |

```rust
// Retry with exponential backoff
async fn with_retry<F, T, E>(mut f: F) -> Result<T, E>
where
    F: FnMut() -> future::Future<Output = Result<T, E>>,
{
    let mut attempts = 0;
    loop {
        match f().await {
            Ok(result) => return Ok(result),
            Err(e) if attempts >= 3 => return Err(e),
            Err(e) => {
                attempts += 1;
                let delay = Duration::from_millis(100 * 2u64.pow(attempts));
                tokio::time::sleep(delay).await;
            }
        }
    }
}
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

---

## Source Evidence

All documentation in this file is grounded in concrete source code from the Grok Build repository:

### Tool Trait Definition
- **Source**: `source/crates/common/xai-tool-runtime/src/tool.rs`
- **Evidence**: `pub trait Tool: Send + Sync` with associated `Args` and `Output` types

### ToolId Structure
- **Source**: `source/crates/common/xai-tool-protocol/src/ids.rs`
- **Evidence**: Format validation `validate_tool_id()`, constructor `ToolId::new()`

### ToolCallId (UUID v7)
- **Source**: `source/crates/common/xai-tool-protocol/src/ids.rs`
- **Evidence**: `ToolCallId::new_v7()` for time-ordered identifier generation

### TypedExtensions
- **Source**: `source/crates/common/xai-tool-runtime/src/extensions.rs`
- **Evidence**: `TypedExtensions::insert<T>()` and `TypedExtensions::get<T>()` with `TypeId` keys

### ToolStream Invariant
- **Source**: `source/crates/common/xai-tool-runtime/src/stream.rs`
- **Evidence**: `ToolStreamItem<T>` enum with `Progress` and `Terminal` variants

### ToolDispatch Trait
- **Source**: `source/crates/common/xai-tool-runtime/src/dispatch.rs`
- **Evidence**: `call()` and `call_terminal()` methods for tool invocation

### ToolError Variants
- **Source**: `source/crates/common/xai-tool-runtime/src/error.rs`
- **Evidence**: Error variants including `InvalidArguments`, `Execution`, `Cancelled`, `PermissionDenied`

### JSON-RPC Methods
- **Source**: `source/crates/common/xai-tool-protocol/src/methods.rs`
- **Evidence**: `tools.list`, `tool.call`, `tool.cancel`, `tool.call_progress`, etc.

### Registration Structures
- **Source**: `source/crates/common/xai-tool-runtime/src/registration.rs`
- **Evidence**: `ToolRegistration`, `ToolServerRegistration`, `RegistrationOutcome` enums

### ToolFamily Pattern
- **Source**: `source/crates/common/xai-tool-runtime/src/family.rs`
- **Evidence**: `ToolFamily` trait with `get_tool()` and `variants()` methods

### streaming_helpers
- **Source**: `source/crates/common/xai-tool-runtime/src/streaming_helpers.rs`
- **Evidence**: `with_progress()`, `terminal_only()`, `stream_chunk()` functions

### Tool Implementations (Examples)
- **Source**: `source/crates/codegen/xai-grok-tools/src/implementations/`
- **Evidence**: `ReadFileTool`, `SearchTool`, `BashTool`, `WebFetchTool` implementations

### MCP Server Support
- **Source**: `source/crates/codegen/xai-grok-pager/src/scrollback/blocks/tool/`
- **Evidence**: MCP protocol integration for external tool servers

### Computer Hub Core
- **Source**: `source/crates/common/xai-computer-hub-core/`
- **Evidence**: Hub service handling tool registration, dispatch, and session management