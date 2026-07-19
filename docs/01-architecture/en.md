# Grok Build Architecture Documentation

## Project Overview

Grok Build is a high-performance AI code assistant infrastructure developed by xAI, implemented in Rust. Its core design philosophy is **modular code generation** and **secure sandbox execution**. The system uses the Actor model for conversation state management, Tree-sitter for code graph indexing, supports Btrfs snapshots for O(1) worktree creation, and implements bidirectional client-server communication via the Agent-Client Protocol (ACP).

### Design Goals

- **High Performance**: Full-chain Rust implementation, no GC pauses, ensures low-latency tool invocations
- **Secure Isolation**: Workspaces run in remote sandboxes with capability mode permission restrictions
- **Extensibility**: Plugin system supports dynamic registration of tools, agents, and skills
- **Traceability**: Hunk tracking supports conversation rewind and snapshot restore

---

## Technology Stack

### Core Dependencies

| Dependency | Purpose |
|------------|---------|
| `tokio` | Async runtime, all I/O operations based on async/await |
| `tree-sitter` | Multi-language code parsing, building code graph index |
| `serde` | Serialization/deserialization (config, snapshots, RPC messages) |
| `minijinja` | System prompt template rendering |
| `git2` | Git repository operations |
| `portable_pty` | Cross-platform pseudo-terminal control |

### Internal Crate Ecosystem

```
xai-chat-state          Conversation state management (Actor pattern)
xai-agent-lifecycle     Agent lifecycle hooks (Contributor pattern)
xai-codebase-graph      Code graph indexing and navigation
xai-acp-lib             Agent-Client Protocol communication framework
xai-fast-worktree       Fast Git worktrees (Btrfs snapshots)
xai-crash-handler       Cross-platform crash capture
xai-grok-agent          Agent building and discovery
xai-grok-tools          Tool registration and scheduling
xai-grok-workspace      Remote sandbox Workspace ToolServer
ptyctl                  PTY control service
```

---

## Crate Architecture Map

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            Grok Build Architecture                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    xai-grok-agent (codegen)                     │   │
│  │  AgentBuilder │ AgentDefinition │ Toolset Presets │ Discovery   │   │
│  └──────────────┬──────────────────────────────────────────────────┘   │
│                 │                                                        │
│                 ▼                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     xai-grok-tools (codegen)                    │   │
│  │  FinalizedToolset │ ToolBridge │ TerminalBackend │ Resources    │   │
│  └──────┬──────────────────────┬────────────────────────────────────┘   │
│         │                      │                                         │
│         ▼                      ▼                                         │
│  ┌─────────────┐        ┌─────────────┐                                 │
│  │  Implement- │        │  Implement- │                                 │
│  │  ations:    │        │  ations:    │                                 │
│  │  GrokBuild  │        │  Codex      │                                 │
│  │  OpenCode   │        │  GrokBuild- │                                 │
│  │  Explore    │        │  Concise    │                                 │
│  └─────────────┘        └─────────────┘                                 │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                   xai-grok-workspace (server)                   │   │
│  │  WorkspaceHandle │ Session │ CapabilityMode │ Hub Connection    │   │
│  └───────────────────────────┬─────────────────────────────────────┘   │
│                              │                                          │
│                              ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                       codegen (core library)                     │   │
│  │  ┌───────────────┐  ┌──────────────────┐  ┌────────────────┐    │   │
│  │  │ xai-chat-state│  │ xai-agent-       │  │ xai-codebase-  │    │   │
│  │  │ (Actor mode)  │  │ lifecycle        │  │ graph          │    │   │
│  │  │               │  │ (Contributor)    │  │ (Tree-sitter)  │    │   │
│  │  └───────────────┘  └──────────────────┘  └────────────────┘    │   │
│  │  ┌───────────────┐  ┌──────────────────┐  ┌────────────────┐    │   │
│  │  │ xai-acp-lib   │  │ xai-fast-worktree│  │ xai-crash-     │    │   │
│  │  │ (Protocol)    │  │ (Btrfs snapshot) │  │ handler        │    │   │
│  │  └───────────────┘  └──────────────────┘  └────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Module Dependencies

```
xai-chat-state ← xai-agent-lifecycle  (lifecycle hooks)
xai-chat-state ← xai-acp-lib          (message types)
xai-chat-state → xai-grok-sampling-types
xai-chat-state → xai-grok-compaction

xai-grok-agent → xai-grok-hooks
xai-grok-agent → xai-grok-tools       (ToolBridge, ToolRegistry)
xai-grok-agent → xai-grok-config
xai-grok-agent → xai-tool-types

xai-grok-tools → xai-grok-sampling-types
xai-grok-tools → xai-tool-runtime
xai-grok-tools → xai-computer-hub-core/sdk

xai-grok-workspace → xai-grok-tools   (toolset)
xai-grok-workspace → xai-computer-hub-sdk (HubConnectionPool)
xai-grok-workspace → xai-grok-sandbox (sandbox config)
xai-grok-workspace → xai-hunk-tracker (change tracking)
```

---

## Three Operation Modes

### 1. Local Mode (Embedded)

Agent and Workspace run in the same process, tools directly invoke the local filesystem.

```
┌─────────────────────────────┐
│         Grok Shell          │
│  ┌─────────────────────────┐│
│  │  Agent (xai-grok-agent) ││
│  └──────────┬──────────────┘│
│             │                │
│             ▼                │
│  ┌─────────────────────────┐│
│  │  Tools (xai-grok-tools) ││
│  │  - BashTool             ││
│  │  - ReadFileTool         ││
│  │  - SearchReplaceTool    ││
│  │  ...                    ││
│  └──────────┬──────────────┘│
│             │                │
│             ▼                │
│  ┌─────────────────────────┐│
│  │  LocalFileSystem        ││
│  │  LocalTerminalBackend   ││
│  └─────────────────────────┘│
└─────────────────────────────┘
```

**Use Cases**: Development debugging, single-user local development

### 2. Workspace Server Mode (Remote Sandbox)

Workspace runs as an independent service, connecting to Hub via WebSocket. Agent proxies tool calls through Hub.

```
┌──────────────────┐         ┌──────────────────────┐         ┌──────────────────┐
│   Grok Shell     │         │    Computer Hub      │         │   Workspace      │
│   (xai-grok-     │◄───────►│    (Tool Router)     │◄───────►│   Server         │
│   agent)         │  WS     │                      │  WS     │   (xai-grok-     │
│                  │         │  ┌───────────────┐   │         │   workspace)     │
│  ToolBridge ─────┼────────►│  │ session.bind  │   │         │                  │
│  (Client side)   │         │  │ tool_call     │   │         │  FinalizedToolset│
│                  │         │  └───────────────┘   │         │  TerminalBackend │
└──────────────────┘         └──────────────────────┘         │  HunkTracker     │
                                                              │  LocalFileSystem  │
                                                              └──────────────────┘
```

**Use Cases**: Secure isolation, multi-tenant, compute-intensive tasks

### 3. Proxy Mode (Hybrid)

WorkspaceOps supports both Local and Proxy modes, forwarding via WebSocket to remote Workspace Server.

```
┌─────────────────────────┐         ┌──────────────────────┐
│    Workspace Client     │         │   Workspace Server   │
│   (xai-grok-workspace-  │◄───────►│   (Remote)           │
│   client)               │  WS     │                      │
│                         │         │  Actual file ops     │
│  WorkspaceOps::execute  │         │  on remote FS        │
│  (Local or Proxy path)  │         │                      │
└─────────────────────────┘         └──────────────────────┘
```

**Use Cases**: Need to connect to remote sandbox while maintaining local development experience

---

## Core Component Descriptions

### 1. xai-chat-state — Conversation State Management

**Core Pattern**: Actor Pattern

ChatState runs using the Tokio Actor pattern. All state modifications execute serially in a single task, no locks needed.

**Key Structures**:

| Structure | Responsibility |
|-----------|----------------|
| `ChatState` | Actor internal state: conversation, token counting, turn capture |
| `ChatStateActor` | Actor running in Tokio task, main loop processes commands |
| `ChatStateHandle` | Client handle, sends commands via mpsc |
| `ChatStateSnapshot` | State snapshot, supports serialization for fork/rewind |

**Key APIs**:

```rust
// Spawn Actor
ChatStateActor::spawn(initial_conversation, sampling_config, ...) -> ChatStateHandle

// Message operations
handle.push_user_message(item)           // Push user message
handle.push_assistant_response(item)     // Push assistant response
handle.push_tool_result(item)            // Push tool result

// State queries
handle.build_conversation_request(...)   // Build API request
handle.snapshot()                        // Get state snapshot
handle.truncate_to_prompt_index(target)  // Rewind to specified turn
```

**Key Features**:

- **Turn Capture**: Preserves turn tail items during mid-turn conversation replacement
- **Token Estimation**: bytes/4 model, estimated_tokens_since_model tracks overflow risk
- **Image Compression**: 47MB triggers gate, 25MB recovery target, oldest-first eviction
- **Tool Completeness Fix**: dedup duplicate ToolResults, repair dangling tool calls

### 2. xai-agent-lifecycle — Lifecycle Hooks

**Core Pattern**: Contributor Pattern

Supports Turn, Session, and Command lifecycle hooks.

**Key Structures**:

| Structure | Responsibility |
|-----------|----------------|
| `TurnLifecycleContributor` | Turn lifecycle hook interface (on_turn_start/done/abort/error) |
| `SessionLifecycleContributor` | Session hook (on_session_idle) |
| `CommandContributor` | Command contributor (registers command specs) |
| `ExtensionRegistry` | Contributor registry, supports Builder pattern |

**Key APIs**:

```rust
// Register hooks
ExtensionRegistry::register_turn_lifecycle(contributor)
ExtensionRegistry::register_session_lifecycle(contributor)

// Lifecycle callbacks
.on_turn_start(ctx)   // Called when turn starts
.on_turn_done(ctx)    // Called when turn completes
.on_turn_abort(ctx)   // Called when turn is aborted
.on_turn_error(ctx)   // Called when turn encounters error
```

**Key Features**:

- **Send/Local Dual Versions**: `LocalExtensionRegistryBuilder` for Rc/RefCell in TUI environments
- **Lock-free Design**: Hooks trigger via immutable snapshots, avoiding deadlocks

### 3. xai-codebase-graph — Code Graph Index

**Core Pattern**: Navigator Pattern

Multi-language code parsing and symbol navigation based on Tree-sitter.

**Key Structures**:

| Structure | Responsibility |
|-----------|----------------|
| `ScopeGraph` | Single-file symbol graph (definitions/references/imports) |
| `ScopeGraphIndex` | Global index, Navigator core |
| `Navigator` | Location-based navigation (Goto definition/reference) |
| `IndexManager` | Incremental index manager, responds to fsnotify events |
| `IndexBuilder` | Full index builder |

**Key APIs**:

```rust
// Index operations
IndexBuilder::build()                           // Full index build
IndexManager::spawn()                           // Create manager

// Navigation operations
IndexManagerHandle::goto_definition_blocking()  // Navigate to definition
Navigator::goto_definition()                    // Location navigation

// Caching
load_index() / save_index()                     // Index serialization
```

**Key Features**:

- **Memory Mapping Optimization**: Uses memmap2 for large codebases
- **Incremental Indexing**: IndexManager listens to fsnotify events, partial index updates
- **Multi-language Support**: tree-sitter-<lang> plugins support 30+ languages

### 4. xai-acp-lib — Agent-Client Protocol

**Core Pattern**: Channel + Gateway Pattern

Bidirectional communication framework, supports message routing and channel management.

**Key Structures**:

| Structure | Responsibility |
|-----------|----------------|
| `AcpAgentMessage` | Messages received by Agent enum |
| `AcpClientMessage` | Messages received by Client enum |
| `AcpArgs<T>` | Wrapper for request + response channel |
| `AcpChannel` | Bidirectional communication channel |

**Key APIs**:

```rust
// Create communication
acp_channel()    // Create bidirectional channel
acp_gateway()    // Create gateway

// Message routing
AcpAgentMessage::route_to_agent()  // Route message to handler
```

### 5. xai-fast-worktree — Fast Worktree

**Core Pattern**: Builder Pattern + Delegate Pattern

Fast Git worktree creation, supports Btrfs snapshots and CoW copying.

**Key Structures**:

| Structure | Responsibility |
|-----------|----------------|
| `WorktreeBuilder` | Worktree creation Builder, chainable configuration |
| `WorktreePlan` | Execution plan parameter encapsulation |
| `BtrfsDelegate` | Privileged btrfs operation delegate trait (sandbox environment) |

**Key APIs**:

```rust
// Create worktree
WorktreeBuilder::new().create()   // Create worktree

// Cleanup operations
remove_worktree()                 // O(1) btrfs deletion
cleanup_worktrees_in()            // Batch cleanup
gc::gc_worktrees()                // Garbage collect expired worktrees
```

**Key Features**:

- **Btrfs Snapshots**: O(1) creation time achievable
- **Privilege Delegation**: BtrfsDelegate trait solves CAP_SYS_ADMIN absence in sandbox environments
- **GC Mechanism**: Regular cleanup of expired worktrees

### 6. xai-grok-agent — Agent Building and Discovery

**Core Pattern**: Builder Pattern + Registry Pattern

Agent constructor, supports parsing definitions from Markdown files, dynamic discovery of Agents, Skills, and Plugins.

**Key Structures**:

| Structure | Responsibility |
|-----------|----------------|
| `Agent` | Immutable Agent instance, bundles tools, prompts, policies |
| `AgentBuilder` | 10-step async build process, fluent API |
| `AgentDefinition` | Portable definition parsed from Markdown YAML frontmatter |
| `BuiltinAgentName` | 11 built-in Agent name enums |
| `PluginRegistry` | Plugin registry, manages discovery, trust, installation |

**Key APIs**:

```rust
// Build process
AgentBuilder::new(cwd, terminal_backend, notification_handle)
    .from_definition(def)
    .build()                                     // 10-step async build

// Discovery mechanism
discover(cwd)                                    // Discover all agents
by_name_in_cwd(name, cwd)                        // Find by name (priority: project > built-in > user > bundled)
all_subagents(cwd, toggle)                       // Build complete subagent list
```

**Toolset Presets**:

| Preset | Toolset |
|--------|---------|
| `grok-build` | Read, Glob, Grep, GrepSymbols, GrepPath, GrepDir, GrepWeb, Bash, Write, NotebookEdit, MultiEdit, SearchReplace, ApplyPatch, TODO, Revert, ReadNoContext, ReadRelocated |
| `grok-build-plan` | Same as grok-build + PlanMode tools |
| `codex` | ReadFile, ListDir, GrepFiles, ApplyPatch |
| `explore` | Read, Glob, Grep, GrepWeb, Bash |
| `plan` | Read, Glob, Grep |

### 7. xai-grok-tools — Tool Registration and Scheduling

**Core Pattern**: Registry Pattern + Trait-based Architecture

Tool implementation decoupled from runtime, unified management via FinalizedToolset.

**Key Structures**:

| Structure | Responsibility |
|-----------|----------------|
| `FinalizedToolset` | Toolset core, tools RwLock, reminders, resources |
| `ToolRegistryBuilder` | Tool builder, pre-registers built-in tools |
| `SessionContext` | Session context: terminal, fs, cwd, skills |
| `ToolBridge` | Connects ToolRegistry to session layer |
| `ToolEntry` | Tool entry: type-erased dispatch handle, metadata, validator |
| `TerminalBackend` | Terminal execution abstraction trait (Local/ACP two implementations) |

**Key APIs**:

```rust
// Build toolset
ToolRegistryBuilder::new()
    .finalize(config, ctx)              // Validate and finalize

// Tool invocation
FinalizedToolset::call(tool_name, args, call_id, cwd_override) -> ToolRunResult

// Bridge layer
ToolBridge::finalize_builder(builder, config, ctx) -> Self
```

**Key Features**:

- **Version Management**: behavior_preset (current/legacy-0.4.10) implements backward compatibility
- **Dynamic Registration**: MCP tools support runtime registration
- **Capability Filtering**: CapabilityMode enum (ReadOnly/ReadWrite/Execute/All)

### 8. xai-grok-workspace — Remote Sandbox Workspace

**Core Pattern**: Session Multiplexing + Hub Connection

Multiplexed sessions, independent CWD/shell state/toolset, supports fork/bind/unbind.

**Key Structures**:

| Structure | Responsibility |
|-----------|----------------|
| `WorkspaceHandle` | Main entry, manages sessions, Hub connection, ActivityTracker |
| `WorkspaceSession` | Independent state container per Hub session |
| `HubConfig` | Hub connection config: WebSocket URL, AuthProvider |
| `HubHandle` | Hub connection holder, 7 background tasks |
| `WorkspaceOps` | Dual-mode operation handle (Local/Proxy) |
| `CapabilityMode` | Session capability mode: ReadOnly/ReadWrite/Execute/All |
| `FileStateTracker` | Tracks file state within session, supports rewind points |

**Key APIs**:

```rust
// Workspace Server lifecycle
WorkspaceHandle::connect_local_workspace()  // Connect to hub
.handle().two_phase_drain()                  // Two-phase graceful shutdown

// Session management
WorkspaceHandle::bind_session(config)        // Create session
WorkspaceHandle::fork_session(parent_id)     // Fork session
WorkspaceHandle::drop_session(session_id)    // Destroy session

// Toolset update
WorkspaceSession::update_tool_config(config) // Hot-reload toolset
```

**Key Features**:

- **Sandbox Support**: bwrap/namespace isolation, restrict_network_at_known_linux_launches
- **Hunk Tracking**: Tracks file changes, supports session rewind/snapshot/restore
- **OIDC Authentication**: ~/.grok/auth.json configures authentication info
- **Diagnostic Endpoints**: /ready, /statusz, /logs HTTP server

### 9. ptyctl — PTY Control Service

Cross-platform PTY control, provides HTTP REST API.

**Key Structures**:

| Structure | Responsibility |
|-----------|----------------|
| `PtyConfig` | PTY session config: command/cwd/env/rows/cols |
| `PtyHandle` | Running PTY session handle |

---

## Design Pattern Summary

### 1. Actor Pattern

**Application**: `xai-chat-state`

All state modifications execute serially in a single tokio task, no Mutex needed.

```rust
// ChatStateActor runs an independent task
tokio::spawn(actor.run());  // cmd_rx processes all state changes

// ChatStateHandle sends commands via mpsc
handle.push_user_message(item);  // fire-and-forget
```

### 2. Builder Pattern

**Application**: `AgentBuilder`, `WorktreeBuilder`, `ToolRegistryBuilder`

Chainable configuration, 10-step async build process.

```rust
AgentBuilder::new(cwd, backend, notification)
    .from_definition(def)
    .with_tool_config(config)
    .with_skills(skills)
    .build()                    // Async finalization
```

### 3. Registry Pattern

**Application**: `ToolRegistry`, `PluginRegistry`, `ExtensionRegistry`

Centralized registration and lookup, supports dynamic extension.

```rust
ToolRegistryBuilder::new()  // Pre-register all built-in tools
    .finalize(config, ctx)   // Finalize after config filtering
```

### 4. Trait-based Abstraction

**Application**: `TerminalBackend`, `AsyncFileSystem`, `ChatPersistence`

Supports multiple backend implementations (Local/ACP, Fs/ObjectStorage).

```rust
trait TerminalBackend {
    async fn run(&self, request: TerminalRunRequest) -> Result<TerminalRunResult>;
    async fn run_background(&self, request: TerminalRunRequest) -> Result<BackgroundHandle>;
}
```

### 5. Contributor Pattern

**Application**: `xai-agent-lifecycle`

Lifecycle hook registration, supports Send/Local dual versions.

```rust
trait TurnLifecycleContributor: Send + Sync {
    fn on_turn_start(&self, ctx: TurnStartCtx);
    fn on_turn_done(&self, ctx: TurnDoneCtx);
}
```

### 6. Channel + Gateway Pattern

**Application**: `xai-acp-lib`

Bidirectional communication, routes messages via method_name.

```rust
acp_channel()   // Create bidirectional channel
acp_gateway()   // Create gateway
```

### 7. Snapshot + Rewind Pattern

**Application**: `xai-chat-state`, `xai-grok-workspace`

Supports state snapshots and history rollback.

```rust
handle.snapshot()                      // Get snapshot
handle.truncate_to_prompt_index(idx)   // Rewind to specified turn
```

### 8. Session Multiplexing

**Application**: `xai-grok-workspace`

Multiple concurrent sessions share Workspace, each session has independent state.

```rust
WorkspaceHandle::bind_session(config)    // Create session
WorkspaceHandle::fork_session(parent)    // Fork session
WorkspaceHandle::drop_session(id)        // Destroy session
```

---

## Key Process Details

### Session Creation Flow (Session Bind)

```
┌──────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│   Hub        │────►│  session.bind   │────►│  WorkspaceHandle    │
│  (Router)    │     │  notification   │     │  .bind_session()    │
└──────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                        │
                                                        ▼
                                            ┌───────────────────────┐
                                            │  WorkspaceSession     │
                                            │  - session_id         │
                                            │  - capability_mode    │
                                            │  - FinalizedToolset   │
                                            │  - HunkTracker        │
                                            └───────────────────────┘
```

### Tool Invocation Flow

```
┌──────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│   Agent      │────►│  ToolCall       │────►│  FinalizedToolset   │
│  (LLM)       │     │  Request        │     │  .call()            │
└──────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                        │
                                                        ▼
                                            ┌───────────────────────┐
                                            │  Tool Implementation  │
                                            │  (Bash/Read/Write...) │
                                            └───────────────────────┘
```

### Conversation Compaction Flow

```
┌──────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│   Threshold  │────►│  AutoCompact    │────►│  Replace History    │
│   Reached    │     │  Trigger        │     │  (Summary/Transcript│
│   (>50%)     │     │                 │     │  /Segments)         │
└──────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                        │
                                                        ▼
                                            ┌───────────────────────┐
                                            │  ChatState Actor      │
                                            │  - dedup & repair     │
                                            │  - token recalc       │
                                            │  - emit events        │
                                            └───────────────────────┘
```

---

## Important Design Decisions

| Decision | Description |
|----------|-------------|
| **Actor Pattern Instead of Locks** | ChatState all state modifications execute serially in a single tokio task, no Mutex needed |
| **Send/Local Dual Versions** | AgentLifecycle distinguishes Send and Local Contributor types, Local for Rc/RefCell TUI environments |
| **Memory Mapping Optimization** | CodebaseGraph uses memmap2 for large codebase indexes |
| **Btrfs Delegation** | FastWorktree's BtrfsDelegate trait solves CAP_SYS_ADMIN absence in sandbox environments |
| **Crash Handler Timing** | CrashHandler must be installed before async runtime starts to capture startup crashes |
| **Compaction Mode Separation** | Summary/Transcript/Segments modes control post-compaction history recovery granularity |
| **Turn Capture Efficient Implementation** | Records conversation length instead of cloning, implements efficient single-turn message capture |
| **Capability Partial Order** | CapabilityMode.is_subset_of() ensures capabilities don't expand during fork |
| **Duplex Communication Separation** | Workspace Server Provider (exposes tools) and Consumer (proxies tools) direction separation |

---

*Document Version: 1.0.0*  
*来源: Grok Build 源码分析*