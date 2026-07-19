# Workspace System Documentation

## Overview

The workspace system (`xai-grok-workspace`) is the core Rust crate that provides filesystem operations, version control (Git/JJ), permissions management, tool configuration, and subsystem orchestration for the xAI Grok development environment.

**Key Characteristics:**
- Asynchronous architecture using Tokio runtime
- Session-multiplexed: multiple concurrent sessions per workspace
- Remote-capable: works both locally and via Hub server connection
- Zero-copy toolset management with atomic swaps
- Comprehensive permission and trust system

---

## Core Data Structures

### 1. WorkspaceHandle

The main public handle to a workspace instance, providing all workspace operations.

```rust
// From: crate::handle::WorkspaceHandle
pub struct WorkspaceHandle {
    shared: Arc<WorkspaceShared>,
    local_session: Option<Arc<WorkspaceSession>>,
}
```

**Key Responsibilities:**
- Session lifecycle management (create, fork, bind, drop)
- Toolset resolution and dynamic swapping
- Hub server connection management
- Checkpoint capture and restore (rewind)
- File system operations delegation

### 2. WorkspaceSession

Per-session state container, isolated per `session_id`.

```rust
// From: crate::session::WorkspaceSession
pub struct WorkspaceSession {
    pub(crate) session_id: String,
    pub(crate) cwd: PathBuf,
    pub(crate) session_env: Arc<HashMap<String, String>>,
    pub(crate) capability_mode: CapabilityMode,
    pub(crate) depth: u32,
    pub(crate) fork_budget: u32,
    pub(crate) hunk_tracker: HunkTrackerHandle,
    pub(crate) file_state_tracker: Arc<FileStateTracker>,
    pub(crate) hunk_checkpoints: Arc<Mutex<HashMap<usize, HunkTurnDelta>>>,
    pub(crate) git_checkpoints: GitCheckpointStore,
    pub(crate) checkpoint_store: CheckpointStore,
    pub(crate) async_fs: AsyncFsWrapper,
    inner: RwLock<WorkspaceSessionInner>,
    pub(crate) update_lock: Mutex<()>,
    pub(crate) mcp_state: Arc<Mutex<McpState>>,
    pub(crate) terminal_backend: SessionTerminalBackend,
    pub(crate) viewer_ctx: Option<WorkspaceViewerContext>,
    pub(crate) yolo_mode: AtomicBool,
}
```

**Key Fields:**
| Field | Type | Purpose |
|-------|------|---------|
| `session_id` | String | Unique session identifier |
| `cwd` | PathBuf | Current working directory |
| `capability_mode` | CapabilityMode | Access control level (All, ReadWrite, ReadOnly, etc.) |
| `hunk_tracker` | HunkTrackerHandle | Tracks file hunk-level changes |
| `file_state_tracker` | FileStateTracker | Tracks file open/edit state |
| `checkpoint_store` | CheckpointStore | Durable storage for rewind checkpoints |
| `update_lock` | Mutex | Serializes toolset updates |

### 3. WorkspaceShared

Workspace-wide shared state across all sessions.

```rust
pub struct WorkspaceShared {
    pub(crate) root_cwd: PathBuf,
    pub(crate) sessions: RwLock<HashMap<String, Arc<WorkspaceSession>>>,
    pub(crate) default_tool_config: ToolServerConfig,
    pub(crate) mcp_tools_snapshot: ArcSwap<Vec<ToolConfig>>,
    pub(crate) hub_tools_snapshot: ArcSwap<Vec<ToolConfig>>,
    pub(crate) events: broadcast::Sender<WorkspaceEvent>,
    pub(crate) hub_handle: Mutex<Option<HubHandle>>,
    pub(crate) session_factory: Arc<dyn SessionContextFactory>,
    pub(crate) workspace_home: PathBuf,
    pub(crate) activity_tracker: Arc<ActivityTracker>,
    pub(crate) fuzzy_searches: Arc<Mutex<FuzzySearchManager>>,
    pub(crate) lsp: Option<Arc<dyn LspBackend>>,
}
```

**Key Features:**
- Session registry with thread-safe access
- ArcSwap for lock-free tool config snapshots
- Broadcast channel for workspace events
- Activity tracking for status reporting

### 4. SessionTerminalBackend

Session-lifetime terminal backend that survives toolset swaps.

```rust
pub struct SessionTerminalBackend {
    backend: Arc<dyn TerminalBackend>,
    shutdown: Arc<dyn Fn() + Send + Sync>,
}
```

### 5. CapabilityMode

Access control levels for sessions.

```rust
pub enum CapabilityMode {
    All,           // Full access
    ReadWrite,     // Read + write, no shell execution
    ReadOnly,      // Read-only filesystem
    // ...
}
```

---

## Key Modules

### Module Hierarchy

```
xai-grok-workspace/
├── lib.rs                 # Public exports and metrics initialization
├── handle.rs              # WorkspaceHandle implementation
├── session/
│   ├── mod.rs            # WorkspaceSession, WorkspaceShared
│   ├── tool_config.rs    # Toolset resolution
│   ├── git.rs            # Git checkpoint store
│   ├── checkpoint_store.rs
│   └── file_state.rs     # FileStateTracker
├── worktree/
│   └── mod.rs            # Git worktree operations
├── hub.rs                # HubConfig, HubHandle
├── permission/
│   ├── manager.rs        # PermissionManager (actor)
│   ├── auto_mode.rs      # LLM-based permission classifier
│   ├── policy.rs         # Compiled permission policies
│   └── state.rs          # Permission state persistence
├── file_system/
│   ├── mod.rs            # AsyncFsWrapper, FileHashMemo
│   ├── index.rs          # Codebase indexing
│   └── content.rs        # Content fetching
├── workspace_ops.rs      # File operations (GetFile, PutFile)
├── mcp.rs                # MCP server integration
├── discovery.rs          # Skills and plugins discovery
└── config.rs             # WorkspaceConfig, SessionContextFactory
```

---

## Key Flows

### 1. Session Lifecycle

```
┌─────────────┐     bind      ┌──────────────┐     tool_call     ┌─────────────┐
│   Client    │ ────────────> │  HubServer   │ ───────────────> │  Workspace  │
│             │               │  (xai-grok-  │                  │   Session   │
│             │ <───────────  │   workspace) │                  │             │
│             │   session.bind│              │ <──────────────  │             │
└─────────────┘   response    └──────────────┘   tool.stream     └─────────────┘
```

**Session Creation Flow:**
1. Client sends `session.bind` via Hub
2. `HubServer::on_session_bind()` receives notification
3. `WorkspaceHandle::bind_session()` creates `WorkspaceSession`
4. Toolset is resolved via `resolve_session_toolset()`
5. Session stored in `WorkspaceShared::sessions`
6. Response sent back to client

### 2. Toolset Resolution & Swap

```rust
// Toolset resolution happens on:
// 1. Session creation (bind)
// 2. Tool config update (update_tool_config)
// 3. MCP snapshot change
// 4. Hub tools change

pub async fn resolve_and_swap_session_toolset(
    session: &Arc<WorkspaceSession>,
    config: ToolServerConfig,
    // ... resolve with MCP and hub tools
) -> Result<(ToolServerConfig, Arc<FinalizedToolset>)>
```

**Swap Policy:**
- `SwapDecision::Apply` - Rebuild toolset
- `SwapDecision::Skip` - Skip (e.g., externally owned terminal)
- `SwapDecision::Defer` - Defer to next turn

### 3. Worktree Creation

```
Client ──> create_worktree_async ──> claim_worktree_in_progress
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    │                         ▼                         │
                    │              WorktreeBuilder::create()            │
                    │              (btrfs copy / rsync)                 │
                    │                         │                         │
                    │     ┌───────────────────┴───────────────────┐     │
                    │     ▼                                       ▼     │
                    │  Success                                 Failure │
                    │     │                                       │     │
                    │     ▼                                       ▼     │
                    │  Register worktree                     Error   │
                    │  in worktrees.db                       status  │
                    │     │                                       │     │
                    │     ▼                                       │     │
                    │  Emit WorktreeStatus::Created              │     │
                    │     │                                       │     │
                    │     ▼                                       │     │
                    │  Background copy (optional)                 │     │
                    └─────┴───────────────────────────────────────┴─────┘
                                              │
                                              ▼
                              mark_worktree_complete()
```

### 4. Permission Request Flow

```
Tool Call ──> PermissionManager::request()
                     │
         ┌───────────┼───────────┐
         ▼           ▼           ▼
    YOLO mode    Auto mode    Ask mode
    (allow)      (LLM eval)   (user prompt)
         │           │           │
         └───────────┴───────────┘
                     │
                     ▼
              Decision::Allow/Deny
```

**Permission Sources (in priority order):**
1. YOLO mode (always allow)
2. Policy deny/allow rules
3. Auto classifier decision
4. Persisted grants (session or durable)
5. Static allowlist (safe commands)
6. User prompt
7. Fallback deny

### 5. Rewind (Checkpoint/Restore)

```
Turn End (on_before_turn)
         │
         ▼
┌─────────────────┐
│ Capture Checkpoint │
│  - FS diff      │
│  - Hunk delta   │
│  - Git HEAD     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Finalize Checkpoint │
│ (on_after_turn)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Persist to disk  │ (workspace_rewind_durable)
└─────────────────┘

User Request (rewind_to)
         │
         ▼
┌─────────────────┐
│ Restore Domain  │
│  - Fs restore   │
│  - Hunk replay  │
│  - Git reset    │
└─────────────────┘
```

---

## API Interface

### RPC Methods

All workspace RPC methods implement the `WorkspaceRpc` trait:

```rust
pub trait WorkspaceRpc: Serialize + DeserializeOwned {
    const METHOD: &'static str;
    type Response: Serialize + DeserializeOwned;
}
```

#### Session Management

| Method | Request | Response | Description |
|--------|---------|----------|-------------|
| `workspace.bind` | `BindSessionReq` | `BindSessionResponse` | Bind/create session |
| `workspace.drop_session` | `DropSessionReq` | `Value` | Drop session |
| `workspace.update_tool_config` | `UpdateToolConfigReq` | `Value` | Update session toolset |

#### File Operations

| Method | Request | Response | Description |
|--------|---------|----------|-------------|
| `workspace.get_file` | `GetFileReq` | `GetFileResult` | Read file content |
| `workspace.put_file` | `PutFileReq` | `PutFileResult` | Write file content |
| `workspace.get_files` | `GetFilesReq` | `GetFilesRes` | Batch read files |
| `workspace.put_files` | `PutFilesReq` | `PutFilesRes` | Batch write files |
| `workspace.list_dir` | `ListDirReq` | `ListDirResponse` | List directory |
| `workspace.create_dir` | `CreateDirReq` | `Value` | Create directory |

#### Worktree Operations

| Method | Description |
|--------|-------------|
| `workspace.create_worktree` | Create Git worktree |
| `workspace.remove_worktree` | Remove worktree |
| `workspace.apply_worktree` | Apply changes from worktree |

#### Configuration

| Method | Request | Response | Description |
|--------|---------|----------|-------------|
| `workspace.info` | `WorkspaceInfoReq` | `WorkspaceInfo` | Workspace info |
| `workspace.load_project_config` | `LoadProjectConfigReq` | `Value` | Load .xai/config |
| `workspace.load_permissions` | `LoadPermissionsReq` | `Value` | Load permission state |
| `workspace.load_envrc` | `LoadEnvrcReq` | `Value` | Load .envrc |

#### MCP Management

| Method | Request | Response | Description |
|--------|---------|----------|-------------|
| `workspace.configure_mcp` | `ConfigureMcpReq` | `Value` | Configure MCP servers |
| `workspace.refresh_plugins` | `RefreshPluginsReq` | `Value` | Refresh plugins |

#### Status/Snapshot

| Method | Request | Response | Description |
|--------|---------|----------|-------------|
| `workspace.list_background_tasks` | `ListBackgroundTasksReq` | `ListBackgroundTasksResponse` | List bg tasks |
| `workspace.tasks_snapshot` | `TasksSnapshotReq` | `TasksSnapshotResponse` | Full task snapshot |
| `workspace.list_todos` | `ListTodosReq` | `ListTodosResponse` | List TODO items |

---

## Design Patterns

### 1. Actor Pattern (Permission Manager)

```rust
#[derive(Clone)]
pub enum PermissionHandle {
    Actor {
        cmd_tx: mpsc::UnboundedSender<PermissionCommand>,
        yolo_state: Arc<AtomicBool>,
        auto_state: Arc<AtomicBool>,
        // ...
    },
    AllowAll,
}

// Messages
pub enum PermissionCommand {
    Request { /* ... */ },
    Grant { /* ... */ },
    Revoke { /* ... */ },
    // ...
}
```

### 2. RAII Guard Pattern

```rust
// CallCompletedGuard - tracks tool call lifecycle
struct CallCompletedGuard {
    tracker: Arc<ActivityTracker>,
    call_id: String,
    outcome: ToolOutcome,
}

impl Drop for CallCompletedGuard {
    fn drop(&mut self) {
        self.tracker.tool_call_completed(&self.call_id, self.outcome);
    }
}
```

### 3. ArcSwap for Lock-Free Snapshots

```rust
pub struct WorkspaceShared {
    pub(crate) mcp_tools_snapshot: arc_swap::ArcSwap<Vec<ToolConfig>>,
    pub(crate) hub_tools_snapshot: arc_swap::ArcSwap<Vec<ToolConfig>>,
}

// Reading (lock-free)
let mcp_tools = self.mcp_tools_snapshot.load_full();

// Updating (atomic swap)
self.mcp_tools_snapshot.store(Arc::new(new_tools));
```

### 4. Session Context Factory (Dependency Injection)

```rust
pub trait SessionContextFactory: Send + Sync {
    fn build_session_context(
        &self,
        session_id: &str,
        cwd: PathBuf,
        session_env: Arc<HashMap<String, String>>,
        backend: Arc<dyn TerminalBackend>,
    ) -> SessionContext;

    fn build_terminal_backend(&self) -> SessionTerminalBackend;
    fn registry_builder(&self) -> ToolRegistryBuilder;
}
```

### 5. Broadcast Channel for Events

```rust
pub struct WorkspaceShared {
    pub(crate) events: tokio::sync::broadcast::Sender<WorkspaceEvent>,
}

pub enum WorkspaceEvent {
    SessionBound { session_id: String },
    SessionDropped { session_id: String },
    ToolsChanged { session_id: String },
    // ...
}
```

### 6. Atomic Counter for In-Flight Tracking

```rust
struct InFlightGuard(Arc<AtomicUsize>);

impl InFlightGuard {
    fn new(counter: &Arc<AtomicUsize>) -> Self {
        counter.fetch_add(1, Ordering::Relaxed);
        Self(counter.clone())
    }
}

impl Drop for InFlightGuard {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::Relaxed);
    }
}
```

### 7. Worktree In-Progress Tracking

```rust
static WORKTREE_IN_PROGRESS: OnceLock<TokioMutex<HashSet<String>>> = OnceLock::new();

pub async fn claim_worktree_in_progress(session_id: &str) -> bool {
    worktree_registry()
        .lock()
        .await
        .insert(session_id.to_string())
}

pub async fn mark_worktree_complete(session_id: &str) {
    worktree_registry().lock().await.remove(session_id);
}
```

---

## Configuration

### WorkspaceConfig

```rust
pub struct WorkspaceConfig {
    pub root_cwd: PathBuf,
    pub default_tool_config: ToolServerConfig,
    pub hub_config: Option<HubConfig>,
    pub require_explicit_toolset: bool,
    pub memory_config: Option<MemoryConfig>,
    pub workspace_home: Option<PathBuf>,
    pub hook_source_config: HookSourceConfig,
    pub workspace_rewind_all_outcomes: bool,
    // ...
}
```

### HubConfig

```rust
pub struct HubConfig {
    pub url: Url,
    pub auth: Arc<dyn AuthProvider>,
    pub activity_tracker: Option<Arc<ActivityTracker>>,
    pub server_id: Option<String>,
    pub alpha_test_key: Option<String>,
    pub allow_insecure_ws: bool,
    pub diag: Option<DiagHandle>,
}
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GROK_WORKSPACE_HOME` | `~/.grok/workspace` | Workspace state root |
| `GROK_WORKSPACE_EVENTS_ENABLED` | `false` | Enable events.jsonl |
| `GROK_WORKSPACE_TOOL_DEFS_ENABLED` | `false` | Enable tool defs |
| `GROK_WORKSPACE_TERMINATION_GRACE_MS` | `45000` | Drain timeout |
| `GROK_HITL_PERMISSION_LIVE` | `false` | Live HITL permission |

---

## Security Model

### Trust Levels

1. **Trusted** - Full access, no prompts
2. **Untrusted** - All actions require explicit permission
3. **Ask** - Prompt before each action
4. **Auto** - LLM-based classification

### Permission Decision Sources

```rust
pub enum Decision {
    Allow,    // Permit the action
    Deny,     // Block the action
    Ask,      // Require user interaction
}
```

**Priority Order:**
1. YOLO mode
2. Policy static rules (deny > allow)
3. Auto classifier
4. Sandbox auto-mode
5. Persisted/session grants
6. Safe command list
7. User prompt

---

## Metrics

Key Prometheus metrics exported:

| Metric | Type | Description |
|--------|------|-------------|
| `grok_workspace_drain_started_total` | Counter | Drains by trigger |
| `grok_workspace_drain_duration_seconds` | Histogram | Drain duration |
| `grok_workspace_toolset_swap_rejected_total` | Counter | Swap rejections |
| `grok_workspace_bind_advertised_tools` | Histogram | Tools per bind |
| `grok_workspace_rewind_checkpoint_capture_total` | Counter | Checkpoint captures |
| `grok_workspace_rewind_restore_total` | Counter | Restore operations |
| `grok_workspace_permission_timeout_total` | Counter | Permission timeouts |
| `grok_workspace_env_capture_panic_total` | Counter | Env capture panics |

---

## File Structure

```
~/.grok/workspace/
├── sessions/
│   └── {session_id}/
│       └── events.jsonl         # Session event log
├── uploads/                      # Upload queue
│   └── pending/
└── workspace_environment.json   # Environment capture

~/.grok/worktrees/
└── {repo_slug}/
    └── {worktree_label}/        # Git worktree directories
```

---

## Key Dependencies

| Crate | Purpose |
|-------|---------|
| `tokio` | Async runtime |
| `git2` | Git operations |
| `serde` | Serialization |
| `arc_swap` | Lock-free atomic Arc swap |
| `parking_lot` | Fast RwLock |
| `xai-grok-tools` | Tool implementations |
| `xai-grok-workspace-types` | Shared types |
| `xai-computer-hub-sdk` | Hub communication |
| `xai-fast-worktree` | Fast worktree operations |
| `xai-hunk-tracker` | Hunk-level file tracking |

---

## Extension Points

### 1. Custom SessionContextFactory

```rust
impl SessionContextFactory for MyFactory {
    fn build_session_context(...) -> SessionContext { /* ... */ }
    fn build_terminal_backend(...) -> SessionTerminalBackend { /* ... */ }
    fn registry_builder(...) -> ToolRegistryBuilder { /* ... */ }
}
```

### 2. Custom BtrfsDelegate

```rust
// For rootless hosts requiring privileged snapshot helpers
pub trait BtrfsDelegate: Send + Sync {
    fn snapshot(&self, source: &Path, dest: &Path) -> Result<()>;
    fn delete(&self, path: &Path) -> Result<()>;
}

// Register at startup
set_btrfs_delegate_factory(|| Some(Arc::new(MyBtrfsDelegate::new())));
```

### 3. MCP Server Integration

```rust
// Via workspace.configure_mcp RPC
pub struct ConfigureMcpReq {
    pub mcp_servers: Value,  // ACP McpServer list
}
```