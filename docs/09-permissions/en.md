# Permissions and Sandbox Mechanism

This document analyzes Grok Build's permission model, sandbox isolation, file access control, and trust level design.

## 1. Permission Model

### 1.1 CapabilityMode

The system defines four capability modes forming a partial ordering relationship (`is_subset_of`):

```rust
pub enum CapabilityMode {
    ReadOnly,   // Read-only: search, read, list
    ReadWrite,  // Read-write: + edit, write, delete, move
    Execute,    // Execute: + shell/background tasks
    All,        // All permissions
}
```

**Permission hierarchy:**
- `ReadOnly` ⊆ `ReadWrite`, `ReadOnly` ⊆ `Execute`
- `ReadWrite` and `Execute` are incomparable (neither includes the other)
- `fork_session` enforces child session capability ≤ parent session capability

### 1.2 ToolKind Tool Classification

The system supports 27 tool types, divided into multiple categories:

| Category | Tool Types | ReadOnly | ReadWrite | Execute | All |
|----------|------------|----------|-----------|---------|-----|
| Meta tools | Plan, AskUser, Skill, etc. | ✓ | ✓ | ✓ | ✓ |
| Read tools | Read, MemoryGet, MemorySearch | ✓ | ✓ | ✓ | ✓ |
| Search tools | Search, WebSearch, WebFetch | ✓ | ✓ | ✓ | ✓ |
| Inspection tools | Lsp, ListDir, List | ✓ | ✓ | ✓ | ✓ |
| Edit tools | Edit, Write, Delete, Move, ImageGen, etc. | ✗ | ✓ | ✗ | ✓ |
| Execute tools | Execute (Shell) | ✗ | ✗ | ✓ | ✓ |
| Process control | BackgroundTaskAction, Task, Monitor | ✗ | ✗ | ✓ | ✓ |

### 1.3 AccessKind Access Types

Tool calls are mapped to access types:

```rust
pub enum AccessKind {
    Read(Option<String>),           // File read
    Grep { path, glob },            // Content search
    Edit(String),                   // File edit
    Bash(String),                   // Shell execution
    MCPTool { name, input },        // MCP tool call
    WebFetch(String),               // Web fetch
    WebSearch(String),              // Web search
}
```

### 1.4 Permission Decision Flow

```
ToolCall → AccessKind → Policy Rules → Decision
                                    ├─ Allow
                                    ├─ Ask → User Prompt
                                    ├─ Reject
                                    └─ PolicyDeny
```

**Decision types:**
- `Allow`: Execution permitted
- `Ask`: Triggers user interaction prompt
- `FollowupMessage`: Message returned when user cancels
- `Reject`: User denied
- `PolicyDeny`: Rejected by policy rules
- `Cancelled`: User cancelled entire Turn

## 2. Sandbox Isolation Mechanism

### 2.1 SandboxMode

```rust
pub enum SandboxMode {
    Invalid,          // Invalid
    Agent,            // Agent mode
    WorkspaceServer,  // Workspace server mode
    Bare,             // Bare mode (no sandbox)
}
```

### 2.2 Sandbox API Types

**Sandbox session management:**
```rust
pub struct SandboxForkRequest {
    pub source_sandbox_id: String,  // Source sandbox ID
    pub copies: Option<u32>,        // Number of copies
}

pub struct SandboxStartRequest {
    pub environment_id: Option<String>,
    pub repository: Option<String>,
    pub branch: Option<String>,
    pub memory_limit_bytes: Option<String>,
    pub cpus: Option<u32>,
    pub gpus: Option<u32>,
    pub env_vars: HashMap<String, String>,
    pub mode: SandboxMode,
}
```

**Environment configuration:**
```rust
pub struct SandboxEnvironment {
    pub environment_id: Option<String>,
    pub repository: Option<String>,
    pub container_image: Option<String>,
    pub caching_enabled: Option<bool>,
    pub internet_enabled: Option<bool>,
    pub domain_allowlist_preset: Option<String>,
    pub preinstalled_packages: HashMap<String, String>,
    pub requested_cpus: Option<u32>,
    pub requested_memory_bytes: Option<String>,
}
```

### 2.3 Security Constraints

**CWE-284 Protection:** User-provided `snapshotBucket` parameter is accepted but not forwarded to the backend service; the server always uses the configured default bucket.

```rust
// SECURITY: snapshot_bucket from user input must never control GCS access
pub struct SandboxForkRequest {
    pub source_sandbox_id: String,
    #[serde(default)]
    pub snapshot_bucket: Option<String>,  // Ignored, server-enforced
}
```

## 3. File Access Control

### 3.1 File Operation Permissions

Different file operations correspond to different permission levels:

| Operation | CapabilityMode | AccessKind |
|-----------|----------------|------------|
| ReadFile | ReadOnly+ | Read |
| ListDir | ReadOnly+ | Read |
| Grep | ReadOnly+ | Grep |
| SearchReplace | ReadWrite | Edit |
| Write | ReadWrite | Edit |
| Delete | ReadWrite | Edit |
| Move | ReadWrite | Edit |

### 3.2 File Path Context

```rust
pub struct EditPathContext {
    pub real_cwd: std::path::PathBuf,        // Actual working directory
    pub display_cwd: Option<std::path::PathBuf>,  // Display working directory
}
```

### 3.3 WorkspaceOps Dual Mode

**Local mode:** Extensions are dispatched directly via `WorkspaceHandle`, and tool calls are executed through the session's `FinalizedToolset`.

**Proxy mode:** All operations are routed to remote workspace server via Hub WebSocket.

```rust
pub enum WorkspaceOps {
    Local { handle: WorkspaceHandle },
    Proxy { client: WorkspaceClient },
}
```

## 4. Trust Levels

### 4.1 TrustStore Folder Trust

Persistent storage: `~/.grok/trusted_folders.toml`

```rust
pub struct FolderTrust {
    pub trusted: bool,        // Whether trusted
    pub decided_at: Option<i64>,  // Unix timestamp
}
```

### 4.2 Trust Cascading Rules

**Most specific match wins:** Among multiple matching folders, the record with the deepest path (longest prefix) takes effect.

**Cascading behavior:**
- Trusted parent folders cascade trust to all subdirectories
- Subfolder's explicit distrust can override parent's trust
- Trust decisions are persisted to disk (0600 permissions)

### 4.3 Workspace Key Calculation

```
Workspace Trust Key Calculation Flow:
1. If grok-managed worktree → fall back to source repo's git root
2. If linked git worktree → use main checkout's root
3. Otherwise → use current working directory
```

**Unsafe root rejection:**
- Relative paths
- Filesystem root (`/`)
- User home directory (`$HOME`)

```rust
pub fn is_unsafe_trust_root(key: &Path) -> bool {
    !key.is_absolute() || key.parent().is_none() || is_home_dir(key)
}
```

### 4.4 Persistence Security

- **Atomic writes:** Use unique temporary file + fsync + rename
- **File permissions:** 0600 (owner read/write only)
- **Cross-process locking:** Advisory lock (`.toml.lock`) prevents concurrent write conflicts
- **No home environment:** When unable to resolve user home, return empty store without writing cwd-relative files

## 5. Permission Prompts and Auto Mode

### 5.1 PromptOutcome Result Types

```rust
pub enum PromptOutcome {
    AllowOnce,                    // Allow once
    AllowAlways,                  // Always allow
    AllowEditsForSession,         // Allow edits for session
    AllowAlwaysBashCommand(String),   // Always allow specific command
    AllowAlwaysDomain(String),        // Always allow specific domain
    AllowAlwaysMcpServer(String),     // Always allow specific MCP server
    AllowAlwaysMcpTool(String),       // Always allow specific MCP tool
    RejectOnce,                   // Reject once
    RejectAlwaysBashCommand(String),  // Always reject specific command
    FollowupMessage(String),      // Return follow-up message
    Cancelled,                    // Cancelled
    Error(String),                // Error
}
```

### 5.2 HITL (Human-in-the-Loop) Real-time Permissions

Enabled via `GROK_HITL_PERMISSION_LIVE` environment variable:

```rust
pub fn hitl_permission_live_enabled() -> bool {
    match std::env::var("GROK_HITL_PERMISSION_LIVE") {
        Ok(v) => matches!(v.trim().to_ascii_lowercase().as_str(),
                         "1" | "true" | "yes" | "on"),
        Err(_) => false,
    }
}
```

### 5.3 Permission Request Timeout

- **Fallback timeout:** 600 seconds (10 minutes)
- **Prometheus metrics:** `grok_workspace_permission_reply_seconds`

## 6. Permission Policy Configuration

### 6.1 PermissionConfig

```rust
pub struct PermissionConfig {
    pub rules: Vec<PermissionRule>,
    pub prompt_policy: PromptPolicy,  // Default behavior
}

pub enum PromptPolicy {
    Ask,   // Prompt user (default)
    Deny,  // Direct deny
    Auto,  // Use auto classifier
}
```

### 6.2 PermissionRule Rules

```rust
pub struct PermissionRule {
    pub action: RuleAction,   // Allow | Deny | Ask
    pub tool: ToolFilter,     // Tool filter
    pub pattern: Option<String>,
    pub pattern_mode: PatternMode,  // Glob | Domain
}

pub enum ToolFilter {
    Any, Bash, Edit, Read, Grep, Mcp, WebFetch, WebSearch
}
```

### 6.3 DecisionReason

| Reason | Description |
|--------|-------------|
| `yolo` | YOLO mode auto-approved |
| `policy_allow` | Policy rule allowed |
| `policy_deny` | Policy rule denied |
| `policy_ask` | Policy rule triggered prompt |
| `auto_classifier_allow` | Auto classifier allowed |
| `auto_classifier_block` | Auto classifier blocked |
| `sandbox_auto` | Sandbox auto decision |
| `persisted_grant` | Persisted grant |
| `session_grant` | Session grant |
| `session_deny` | Session deny |

## 7. Permission Event Telemetry

```rust
pub struct PermissionEvent {
    pub tool_id: String,
    pub tool_name: String,
    pub access_kind: String,
    pub access_detail: Option<String>,
    pub yolo_mode: bool,
    pub auto_approved: bool,
    pub user_prompted: bool,
    pub decision: String,
    pub prompt_outcome: Option<String>,
    pub reject_reason: Option<String>,
    pub timestamp: DateTime<Utc>,
    pub subagent_session_id: Option<String>,
    pub subagent_type: Option<String>,
    pub permission_mode: Option<String>,
    pub decision_reason: Option<String>,
    pub wait_ms: Option<u64>,
    pub queue_depth: Option<u32>,
}
```

## 8. Client Type Identification

```rust
pub enum ClientType {
    Generic,      // Generic client
    GrokTUI,      // TUI terminal interface
    GrokWeb,      // Web interface
    Nebula,       // Nebula client
    Extension,    // VS Code extension
    GrokPager,    // TUI pager
    Desktop,      // Electron desktop client
}
```

Different client types affect:
- Permission UI option display
- Bash command highlighting and interactive selection
- Telemetry attribution labels