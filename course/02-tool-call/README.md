# Tool Call System / 工具调用系统

## Overview / 概述

The tool call system is the core mechanism enabling the AI to interact with the external world. It provides a unified `Tool` trait for all tool implementations and a `ToolDispatch` interface for runtime routing.

工具调用系统是 AI 与外部世界交互的核心机制。它提供了统一的 `Tool` trait 用于所有工具实现，以及 `ToolDispatch` 接口用于运行时路由。

---

## Core Traits / 核心 Trait

### `Tool` Trait

The central trait for all tool implementations:

所有工具实现的核心 trait：

```rust
pub trait Tool: Send + Sync {
    type Args: for<'de> Deserialize<'de> + JsonSchema + Send + 'static;
    type Output: Serialize + ToolOutput + Send + 'static;

    fn id(&self) -> ToolId;
    fn description(&self, _ctx: &ListToolsContext) -> ToolDescription;
    fn capabilities(&self) -> ToolCapabilities;
    fn has_dynamic_description(&self) -> bool;
    fn should_list(&self, _ctx: &ListToolsContext) -> bool;

    fn execute(&self, ctx: ToolCallContext, args: Self::Args) -> impl Future<Output = ToolStream<Self::Output>> + Send;
    fn run(&self, ctx: ToolCallContext, args: Self::Args) -> impl Future<Output = Result<Self::Output, ToolError>> + Send;
}
```

**Two execution paths / 两种执行路径：**

- `execute()` - Streaming entry point. Returns `ToolStream<T>` with zero or more `Progress` items followed by exactly one `Terminal`.
- `run()` - Blocking convenience. Override this for simple tools; `execute()` wraps it automatically.

- `execute()` - 流式入口。返回 `ToolStream<T>`，包含零个或多个 `Progress` 项，最后是唯一的 `Terminal`。
- `run()` - 阻塞式便捷入口。简单工具重写此方法；`execute()` 会自动包装它。

---

### `ToolDispatch` Trait

Object-safe dispatch interface:

面向对象的调度接口：

```rust
#[async_trait]
pub trait ToolDispatch: Send + Sync {
    async fn call(&self, tool_id: ToolId, args: Value, ctx: ToolCallContext) -> ToolStream<TypedToolOutput>;
    async fn call_terminal(&self, tool_id: ToolId, args: Value, ctx: ToolCallContext) -> Result<TypedToolOutput, ToolError>;
}
```

- `call()` - Streaming dispatch, preserves progress chunks
- `call_terminal()` - Convenience that drains the stream and returns only the final result

- `call()` - 流式调度，保留进度块
- `call_terminal()` - 便捷方法，排空流并只返回最终结果

---

## Stream Model / 流模型

```rust
pub type ToolStream<T> = Pin<Box<dyn Stream<Item = ToolStreamItem<T>> + Send>>;

pub enum ToolStreamItem<T> {
    Progress(ToolProgress),        // Zero or more
    Terminal(Result<T, ToolError>), // Exactly one, always last
}
```

**`ToolProgress` variants / 变体：**

```rust
pub enum ToolProgress {
    Text { text: String },
    Content { blocks: Vec<ContentBlock> },
    Custom { subkind: String, payload: Value },
}
```

**Helper functions / 辅助函数：**

```rust
// Simple terminal-only result
terminal_only(result: Result<T, ToolError>) -> ToolStream<T>

// Stream with progress items
with_progress(progress: P, terminal: F) -> ToolStream<T>
```

---

## Content Blocks / 内容块

Rich content output via `ContentBlock`:

通过 `ContentBlock` 输出富内容：

```rust
pub enum ContentBlock {
    Text { text: String },
    Image { mime_type: String, data: String, media_id: Option<String>, ... },
    Resource { uri: String, mime_type: Option<String>, text: Option<String> },
}
```

---

## Tool Taxonomy / 工具分类

### `ToolNamespace` - Toolset classification

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

### `ToolKind` - Functional categorization

```rust
pub enum ToolKind {
    Read, Edit, Delete, ListDir, Write, Move, Search,
    Lsp, Execute, Plan, WebSearch, WebFetch,
    BackgroundTaskAction, WaitTasksAction, KillTaskAction,
    List, Skill, MemorySearch, MemoryGet, Task,
    EnterPlan, ExitPlan, AskUser,
    ImageGen, VideoGen, ImageToVideo, ReferenceToVideo,
    DeployApp, SearchTool, UseTool, Monitor, GoalUpdate,
    Other,
}
```

---

## Reminder System / 提醒系统

Post-execution reminders fire after tool completion:

工具执行完成后的提醒机制：

```rust
#[async_trait]
pub trait Reminder {
    fn requires_expr(&self) -> Expr<ToolRequirement>;
    async fn collect_reminders(&self, _resources: SharedResources, _tool_output: &ToolOutput) -> Vec<String>;
}
```

- **Per-tool reminders** - Defined on tool structs
- **Cross-cutting reminders** - Standalone structs reacting to any tool call

- **工具级提醒** - 在工具结构体上定义
- **跨切面提醒** - 独立结构体，响应任何工具调用

---

## Tool Families / 工具家族

Tools that share one `ToolId` but route to different implementations:

共享一个 `ToolId` 但路由到不同实现的工具：

```rust
pub trait ToolFamily: Send + Sync {
    fn id(&self) -> ToolId;
    fn get_tool(&self, variant: &ToolVariant) -> Option<ArcTool>;
    fn variants(&self) -> Vec<ToolVariant>;
    fn default_variant_name(&self) -> Option<&'static str>;
}

pub enum ToolVariant {
    Default,
    Variant(String),
}
```

---

## RPC Protocol / RPC 协议

```rust
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ToolRequest {
    Call(ToolCallArgs),
    Definitions,
}

pub struct ToolCallArgs {
    pub session: SessionId,
    pub tool_name: String,
    pub input_json: String,
    pub call_id: ToolCallId,
}
```

---

## Key Files / 关键文件

- `xai-tool-runtime/src/tool.rs` - Core `Tool` trait and stream types
- `xai-tool-runtime/src/dispatch.rs` - `ToolDispatch` interface
- `xai-grok-tools/src/types/tool.rs` - `ToolNamespace`, `ToolKind`, `Reminder`
- `xai-grok-workspace-types/src/requests/tool.rs` - RPC protocol types

---

## Implementation Flow / 实现流程

```
ToolCallArgs (RPC)
    ↓
ToolDispatch::call()
    ↓
Tool::execute() → ToolStream<T>
    ↓
ToolStreamItem::Terminal(TypedToolOutput)
    ↓
TypedToolOutput { tool_id, value, model_output, chat_completion_output }
```