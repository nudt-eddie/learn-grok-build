# Tool Call System

> This section analyzes the tool registration, discovery, dispatch, and execution lifecycle in Grok Build.

## 1. Overview

The Tool Call system is the core execution engine of the Grok Build Agent. It handles:

- **Registration**: Tools are registered at startup via `ToolRegistryBuilder`
- **Discovery**: Tool definitions are sent to the model for tool selection
- **Dispatch**: The Agent calls tools based on model responses
- **Execution**: Tools run with proper context and return results
- **Post-processing**: Reminders, persistence, and prompt formatting

## 2. Architecture

```
ToolCall System Architecture
─────────────────────────────────────────────
                                             │
┌──────────────────────────────────────────┐ │
│           ToolRegistryBuilder             │ │
│  ┌────────────────────────────────────┐  │ │
│  │ register_with_params::<T, P>()     │  │ │
│  │   - Tool metadata                  │  │ │
│  │   - Output converter               │  │ │
│  │   - Params validator               │  │ │
│  │   - LocalRegistry registration     │  │ │
│  └────────────────────────────────────┘  │ │
└────────────────────┬─────────────────────┘ │
                     │ finalize()            │
                     ▼                       │
┌──────────────────────────────────────────┐ │
│           FinalizedToolset               │ │
│  ┌────────────────────────────────────┐  │ │
│  │  tools: RwLock<Vec<FinalizedTool>> │  │ │
│  │  resources: SharedResources        │  │ │
│  │  local_registry: LocalRegistry     │  │ │
│  │  renderer: TemplateRenderer        │  │ │
│  └────────────────────────────────────┘  │ │
└────────────────────┬─────────────────────┘ │
                     │ call()                │
                     ▼                       │
┌──────────────────────────────────────────┐ │
│           Tool Execution                 │ │
│  ┌────────────────────────────────────┐  │ │
│  │  prepare_dispatch()                │  │ │
│  │    - Lookup tool entry             │  │ │
│  │    - Remap client params           │  │ │
│  │    - Build ToolCallContext         │  │ │
│  │    - Find LocalRegistry handle     │  │ │
│  └────────────────────────────────────┘  │ │
│  ┌────────────────────────────────────┐  │ │
│  │  lr_handle.execute(ctx, params)    │  │ │
│  │    - Run tool with context         │  │ │
│  │    - Stream progress/results       │  │ │
│  └────────────────────────────────────┘  │ │
│  ┌────────────────────────────────────┐  │ │
│  │  finalize_output()                 │  │ │
│  │    - Convert output                │  │ │
│  │    - Collect reminders             │  │ │
│  │    - Persist state                 │  │ │
│  │    - Build ToolRunResult           │  │ │
│  └────────────────────────────────────┘  │ │
└──────────────────────────────────────────┘ │
```

## 3. Tool Registration

### 3.1 ToolEntry Structure

Each registered tool stores type-erased metadata and handlers:

```rust
struct ToolEntry {
    namespace: String,
    id: String,
    kind: ToolKind,
    requires: Expr<ToolRequirement>,
    default_params: serde_json::Value,
    input_schema: serde_json::Value,
    metadata: Box<dyn ToolMetadata>,
    output_converter: Box<...>,
    validate_params: Box<...>,
    apply_params: Box<...>,
    register_params: Box<...>,
    parse_input: Box<...>,
    register_in_local: Box<...>,
}
```

### 3.2 Registration Process

Tools are registered in `ToolRegistryBuilder::new()`:

```rust
pub fn new() -> Self {
    let mut b = Self { tools: HashMap::new(), reminders: Vec::new(), ... };
    
    // Built-in Grok Build tools
    b.register_with_params::<grok_build::BashTool, bash::BashParams>();
    b.register_with_params::<grok_build::ReadFileTool, read_file::ReadFileParams>();
    b.register_with_params::<grok_build::SearchReplaceTool, search_replace::SearchReplaceParams>();
    // ... 30+ more tools
    
    // Codex tools (legacy file operations)
    b.register::<codex::apply_patch::ApplyPatchTool>();
    
    // Reminders
    b.register_reminder(crate::reminders::LspDiagnosticsReminder);
    
    // Out-of-tree tool packs
    for pack in tool_packs().lock().iter() {
        pack(&mut b);
    }
    b
}
```

### 3.3 Tool Requirements

Tools can declare requirements that must be satisfied:

```rust
impl<T> ToolMetadata for ReadFileTool {
    fn requires_expr(&self) -> Expr<ToolRequirement> {
        Expr::Not(Box::new(Expr::ToolPresent(ToolKind::Edit)))
    }
}
```

Example: `search_replace` requires a Read tool when `skip_read_before_edit=false`.

## 4. Tool Discovery

### 4.1 Tool Definitions

Tool definitions (schemas) are generated from Rust types using `schemars`:

```rust
pub fn generate_schema<T: schemars::JsonSchema>() -> serde_json::Value {
    let settings = schemars::generate::SchemaSettings::draft07().with(|s| {
        s.inline_subschemas = true;
    });
    let generator = settings.into_generator();
    generator.into_root_schema_for::<T>()
}
```

### 4.2 Sending Definitions to Model

The `FinalizedToolset::tool_definitions()` returns all tool schemas:

```rust
pub fn tool_definitions(&self) -> Vec<ToolDefinition> {
    self.tools.read().iter().map(|t| t.definition.clone()).collect()
}
```

## 5. Tool Dispatch

### 5.1 Dispatch Flow

```
call(tool_name, args, tool_call_id, cwd_override)
    │
    ▼
prepare_dispatch()
    ├── Lookup FinalizedTool by client_name
    ├── Remap client params → canonical params
    ├── Build ToolCallContext
    │   ├── Insert resources
    │   ├── Insert renderer
    │   ├── Insert InnerDispatch
    │   └── Insert workspace_viewer_ctx
    └── Find LocalRegistry handle
            │
            ▼
lr_handle.execute(ctx, params)
    │
    ▼
finalize_output()
    ├── Convert value → ToolOutput
    ├── Collect reminders
    ├── Persist resources state
    └── Build ToolRunResult
```

### 5.2 Param Remapping

Client-facing param names can differ from canonical names:

```rust
// Client sends: { "file": "path", "text": "content" }
// Canonical expects: { "file_path": "path", "old_string": "content" }

let reverse_params: HashMap<String, String> = param_map
    .iter()
    .map(|(canonical, client)| (client.clone(), canonical.clone()))
    .collect();
```

### 5.3 Inner Dispatch

`use_tool` delegates to other tools via `InnerDispatch`:

```rust
struct InnerDispatchForToolset {
    toolset: Arc<FinalizedToolset>,
}

impl xai_tool_runtime::ToolDispatch for InnerDispatchForToolset {
    async fn call(&self, tool_id, args, ctx) -> ToolStream<TypedToolOutput> {
        let result = self.toolset.call_raw(tool_id.as_str(), args, ctx).await
            .and_then(|output| {
                let value = serde_json::to_value(&output)?;
                Ok(TypedToolOutput::from_value(tool_id.clone(), value))
            });
        xai_tool_runtime::terminal_only(result)
    }
}
```

## 6. SessionContext

Resources are injected via `SessionContext`:

```rust
pub struct SessionContext {
    pub backend: Arc<dyn TerminalBackend>,       // Shell execution
    pub fs: Arc<dyn AsyncFileSystem>,            // File operations
    pub cwd: PathBuf,                            // Working directory
    pub session_folder: PathBuf,                 // Session logs
    pub session_env: Arc<HashMap<String, String>>, // Environment
    pub notification_handle: ToolNotificationHandle,
    pub owner_session_id: Option<String>,
    pub parent_scheduler_handle: Option<SchedulerHandle>,
    pub skills: Vec<SkillInfo>,
    pub state_path: PathBuf,
    pub memory_backend: Option<Arc<dyn MemoryBackend>>,
    pub web_search_config: WebSearchConfig,
    pub web_fetch_config: WebFetchConfig,
    pub lsp: Option<Arc<dyn LspBackend>>,
    pub image_gen_config: ImageGenConfig,
    pub video_gen_config: VideoGenConfig,
    pub api_key_provider: Option<SharedApiKeyProvider>,
    pub auth_provider: Option<SharedAuthProvider>,
    pub attribution_callback: Option<SharedAttributionCallback>,
}
```

## 7. Tool Types

### 7.1 ToolKind Taxonomy

```rust
pub enum ToolKind {
    Read,
    Edit,
    Bash,
    BackgroundTaskAction,
    KillTaskAction,
    Memory,
    Search,
    Skill,
    AgentSpawn,
    AgentKill,
    AgentResult,
    Web,
    ImageGeneration,
    VideoGeneration,
    Other,
}
```

### 7.2 Built-in Tools

| Tool | Kind | Description |
|------|------|-------------|
| `read_file` | Read | Read file contents with offset/limit |
| `search_replace` | Edit | Edit files using old/new string matching |
| `grep` | Search | Search files with regex patterns |
| `list_dir` | Read | List directory contents |
| `run_terminal_cmd` | Bash | Execute shell commands |
| `task` | AgentSpawn | Spawn background subagent |
| `get_task_output` | AgentResult | Get subagent output |
| `kill_task` | KillTaskAction | Kill running task |
| `web_search` | Web | Search the web |
| `web_fetch` | Web | Fetch web pages |
| `image_gen` | ImageGeneration | Generate images |
| `scheduler_*` | BackgroundTaskAction | Schedule recurring tasks |

## 8. Reminders

Reminders fire after tool execution to inject additional context:

```rust
pub struct LspDiagnosticsReminder;
pub struct TaskCompletionReminder;
pub struct SkillDiscoveryReminder;
```

## 9. Key Source Files

| File | Purpose |
|------|---------|
| `xai-grok-tools/src/lib.rs` | Main entry, exports |
| `xai-grok-tools/src/registry/mod.rs` | Tool registry builder |
| `xai-grok-tools/src/types/tool_metadata.rs` | Tool metadata trait |
| `xai-grok-tools/src/types/output.rs` | Output types |
| `xai-tool-types/src/types.rs` | Core tool types |
| `xai-tool-types/src/task.rs` | Task/tool input types |
| `xai-tool-runtime/src/lib.rs` | Tool runtime traits |

## 10. Summary

The Tool Call system provides:

1. **Type-safe registration**: Compile-time checking of tool names and types
2. **Flexible configuration**: Per-tool params, name overrides, behavior versions
3. **Requirements validation**: Ensures tool dependencies are satisfied
4. **Streaming execution**: Progress updates during long operations
5. **Context injection**: Resources like filesystem, terminal, memory
6. **Post-processing pipeline**: Reminders, persistence, prompt formatting