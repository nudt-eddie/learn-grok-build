# Grok Build Extensions System

Grok Build provides a modular extension system composed of six core subsystems. Each subsystem is independently deployable and communicates through well-defined APIs. This document describes the architecture, key structures, APIs, and design decisions for each extension module.

---

## Table of Contents

1. [Extensions Overview](#1-extensions-overview)
2. [MCP (Model Context Protocol)](#2-mcp-model-context-protocol)
3. [Hooks](#3-hooks)
4. [Sandbox](#4-sandbox)
5. [Memory](#5-memory)
6. [TUI (Terminal User Interface)](#6-tui-terminal-user-interface)
7. [Headless Mode](#7-headless-mode)
8. [ACP (Agent Communication Protocol)](#8-acp-agent-communication-protocol)
9. [Cross-Cutting Concerns](#9-cross-cutting-concerns)

---

## 1. Extensions Overview

Grok Build's extension system is designed around three principles:

- **Isolation**: Each subsystem manages its own dependencies, lifecycle, and state. Cross-subsystem communication happens through typed interfaces, not shared mutable state.
- **Composability**: Extensions can be combined arbitrarily. For example, a sandboxed MCP tool call flows through `Sandbox` → `MCP` → `Hooks` in a single call chain.
- **Fail-safe defaults**: Every subsystem defaults to permissive behavior when misconfigured, with explicit opt-in for restrictive policies.

### Extension Subsystem Map

```
Grok Build
├── MCP         Server lifecycle, tool invocation, OAuth, credential storage
├── Hooks       Event-driven command/HTTP handlers for workflow automation
├── Sandbox     OS-level filesystem and network restrictions via kernel primitives
├── Memory      Cross-session semantic persistence with SQLite + vector search
├── TUI         Terminal rendering, input handling, layout engine
├── Headless    Background execution, session recovery, daemon protocol
└── ACP         Inter-process agent communication and reverse channel bridge
```

---

## 2. MCP (Model Context Protocol)

### Module Purpose

`xai-grok-mcp` provides the MCP client implementation. MCP is the protocol by which Grok Build communicates with external tool servers. The crate serves as a dependency isolation layer: it ships its own private copies of `reqwest 0.13` and `rmcp 2.1` to avoid conflicts with other workspace crates that depend on `reqwest 0.12`.

### Core Architecture

```
McpState
├── configs              Vec<McpServer>                Configured server list
├── owned_clients        HashMap<String, McpClient>    Live MCP client instances
├── shared_clients       SharedMcpPool                 Snapshots for subagent inheritance
├── acp_mcp              AcpMcpRegistry                In-process SDK server registry
├── init_progress        InitProgress                  Type-safe initialization state machine
├── mcp_tool_meta        HashMap<String, ToolMetadata> Cached tool metadata per server
├── auth_required        bool                          Whether any server needs OAuth
├── init_failed          bool                          Whether a fatal error occurred
└── generation           u64                           Increment counter for stale initialization
```

### Key State Machines

**InitProgress** replaces the previous three-field pattern (`initialized`, `initializing`, `initializing_servers`):

```rust
enum InitProgress {
    NotStarted,
    Starting { handshaking: HashSet<String> },
    Finished { handshaking: HashSet<String> },
}
```

This eliminates impossible states such as `initialized && initializing`. The `finish_init` call is triggered early so non-MCP work can proceed while per-server handshakes complete in the background. `is_initialized` requires both `InitProgress::Finished` and all per-server handshakes resolved.

**ClientState** manages individual server lifecycle:

```rust
enum ClientState {
    Pending,      // Awaiting initialization
    Initializing, // Handshake in progress
    Ready,        // Fully operational
    Empty,        // Reset, awaiting reconfiguration
}
```

### Key Structures

| Structure | File | Purpose |
|-----------|------|---------|
| `McpState` | `servers.rs` | Unified MCP state container with generation-based stale detection |
| `McpClient` | `servers.rs` | Per-server client wrapper managing lifecycle, liveness, transport |
| `McpConfigDiff` | `servers.rs` | Computed diff: `added`, `removed`, `retained` server lists |
| `SharedMcpPool` | `servers.rs` | Snapshotted client pool for subagent inheritance |
| `AcpMcpRegistry` | `servers.rs` | In-process SDK MCP server registry surviving config reloads |
| `McpCredentialStore` | `credentials.rs` | OAuth credential persistence in `$GROK_HOME/mcp_credentials.json` |
| `McpHttpClient` | `mcp_http_client.rs` | StreamableHttp wrapper with SSE reconnection backoff |
| `TransportLivenessHandle` | `liveness.rs` | RAII handle for transport liveness polling, cancels on drop |
| `AcpBridgeTransport` | `acp_transport.rs` | ACP reverse channel bridge using `DuplexStream` piping |

### Key APIs

#### Configuration Management

```rust
// Differential config update: only reconciles changed servers
pub fn update_configs_diff(&mut self, new_configs: Vec<acp::McpServer>) -> Option<McpConfigDiff>

// Strict initialization completion check
pub fn is_initialized(&self) -> bool

// Install event broadcaster, auto-fanout to all owned clients
pub fn set_client_event_tx(&mut self, tx: Option<UnboundedSender<McpClientEvent>>)

// Build pending ACP clients for registered SDK servers
pub fn build_pending_acp_clients(&self, overrides: &HashMap<String, McpClientTimeoutOverrides>) -> Vec<McpClient>

// Refresh managed clients (e.g., token refresh) without unnecessary reconnects
pub fn refresh_managed_clients<'a, I>(&mut self, fresh_configs: I)
```

#### Transport Liveness

```rust
// Spawn one-shot transport liveness poller; sends TransportClosed event when Ready + transport closed
pub fn spawn_transport_liveness(...) -> TransportLivenessHandle
```

#### Credential Storage

```rust
// Atomic insert-and-save with flock file lock (Unix); reload + merge + save to prevent overwrite
pub fn insert_and_save(&mut self, server_name: &str, server_url: &Url, creds: StoredCredentials) -> Result<()>
```

#### OAuth Authentication

```rust
// Deduplicated OAuth flow: L1 = fs flock (cross-process), L2 = watch channel (intra-process)
pub async fn authenticate_mcp_server_dedup(...) -> Result<(), String>
```

#### ACP Bridge

```rust
// Build rmcp transport from ACP reverse channel via DuplexStream + pump task
pub fn acp_bridge_transport(server_id: String, invoker: Arc<dyn AcpReverseInvoker>, invoke_timeout: Duration) -> AcpBridgeTransport
```

### Design Notes

**Dependency isolation**: `xai-grok-mcp` privately contains `reqwest 0.13` and `rmcp 2.1`. Consumers access `rmcp` types through `xai_grok_mcp::rmcp::*`. This prevents version conflicts with other workspace crates.

**SSE reconnection backoff**: `rmcp 2.1` has a zero-backoff reconnect loop that floods logs when the SSE body dies. `McpHttpClient` implements exponential backoff: a stream alive for `<2` seconds counts as "fast death", and `>=2` consecutive fast deaths trigger backoff (`500ms * 2^n`, cap `30s`). A `WarnBudget` limits log spam to once per hour, shared across rebuilt clients.

**Transport liveness polling**: `rmcp 2.1`'s `RunningService` does not expose a transport-closed signal. `spawn_transport_liveness` polls via `tokio::time::interval` with the first tick fire-immediately. Only fires when the client is `Ready` and the transport is closed.

**Client sharing pool**: `SharedMcpPool` uses snapshots (not live updates) for subagent inheritance. The HashMap clone is cheap since values are `Arc<McpClient>`. Subagents do not inherit the `event_tx` to avoid duplicate event delivery.

**Tool name validation**: Strict cross-provider validation: `^[a-zA-Z_][a-zA-Z0-9_-]{0,63}$`. Must start with letter or underscore (required by Google Gemini), only alphanumeric/underscore/hyphen (Anthropic and OpenAI prohibit dots), max 64 characters.

**ACP bridge half-duplex limitation**: v1 only bridges client-to-server requests and responses. Server-initiated notifications (`Notifications/*`) and server requests (`Sampling`, `Root`, `Elicitation`) are not bridged. Notifications are silently dropped since SDKs tolerate missed ones.

---

## 3. Hooks

### Module Purpose

`xai-grok-hooks` is Grok's event-driven automation framework. Hooks are discovered from `~/.grok/hooks/` and git worktree `.grok/hooks/` directories, loaded from JSON files. They enable third-party integrations, workflow automation, and policy enforcement.

### Hook Discovery

Hooks are loaded from:

1. **Directory sources**: `~/.grok/hooks/*.json` files
2. **Settings files**: `~/.grok/settings.d/` entries with a `hooks` key

Hook files are sorted lexicographically for deterministic ordering. Global hooks (`~/.grok/hooks/`) run before project hooks. Duplicate hooks (same `event`, `command`, `url`, and `matcher`) are deduplicated.

### Event Types

14 event types are supported:

| Event | Type | Blocking | Description |
|-------|------|----------|-------------|
| `SessionStart` | Lifecycle | No | Session begins |
| `SessionEnd` | Lifecycle | No | Session ends normally |
| `Stop` | Lifecycle | No | Session stops (with possible failure) |
| `PreToolUse` | Tool | **Yes** | Before a tool executes. Can `Allow` or `Deny` |
| `PostToolUse` | Tool | No | After a tool executes successfully |
| `PostToolUseFailure` | Tool | No | After a tool fails |
| `PermissionDenied` | Tool | No | When a permission request is denied |
| `UserPromptSubmit` | User | No | When the user submits a prompt |
| `Notification` | User | No | When a notification arrives |
| `SubagentStart` | Subagent | No | When a subagent starts |
| `SubagentStop` | Subagent | No | When a subagent stops |
| `PreCompact` | Compaction | No | Before session compaction |
| `PostCompact` | Compaction | No | After session compaction |

Event name aliases are resolved: `pre_tool_use`, `preToolUse`, and `PreToolUse` are equivalent.

### Key Structures

| Structure | File | Purpose |
|-----------|------|---------|
| `HookSpec` | `config.rs` | Validated hook specification with expanded command/URL paths |
| `HookMatcher` | `matcher.rs` | Tool name matcher supporting `All`, `Exact`, and `Regex` modes |
| `HookEventName` | `event.rs` | 14-type event enum with alias resolution |
| `HookEventEnvelope` | `event.rs` | JSON event payload sent to hook handlers (camelCase wire format) |
| `HookRegistry` | `discovery.rs` | Event-indexed hook snapshot registry |
| `HookDecision` | `result.rs` | Blocking hook result: `Allow` or `Deny { reason, hook_name }` |
| `RunContext` | `runner/mod.rs` | Execution context with `session_id` and `workspace_root` |
| `EnvVarRef` | `env_expand.rs` | Detected environment variable reference with offset and modifier info |

### Key APIs

#### Discovery

```rust
// Load hooks from global and project directories
pub fn load_hooks(global_dir: Option<&Path>, project_dir: Option<&Path>) -> (HookRegistry, Vec<HookError>)

// Parse a JSON hook file
pub fn parse_hook_file(content: &str, file_path: &Path) -> (Vec<HookSpec>, Vec<HookError>)
```

#### Dispatch

```rust
// Dispatch blocking pre_tool_use event; first Deny short-circuits. Fails open on errors.
pub async fn dispatch_pre_tool_use(registry: &HookRegistry, envelope: &HookEventEnvelope, ctx: &RunContext<'_>) -> PreToolUseResult

// Dispatch non-blocking events; collects all results but does not affect control flow
pub async fn dispatch_non_blocking(registry: &HookRegistry, event: HookEventName, envelope: &HookEventEnvelope, ctx: &RunContext<'_>) -> Vec<HookRunResult>
```

#### Execution

```rust
// Execute a command hook via shell or direct exec
pub async fn run_command_hook(spec: &HookSpec, envelope: &HookEventEnvelope, ctx: &RunContext<'_>, is_blocking: bool) -> (HookRunnerResult, Duration)

// Execute an HTTP hook via POST with JSON payload
pub async fn run_http_hook(spec: &HookSpec, envelope: &HookEventEnvelope, _ctx: &RunContext<'_>, is_blocking: bool) -> HookRunOutput
```

#### Environment Expansion

```rust
// Expand env vars at load time; extra_env takes precedence over process env
pub(crate) fn expand_env_vars_with_extra(input: &str, extra: &HashMap<String, String>) -> String
```

#### Security

```rust
// CWE-918 SSRF protection: HTTPS only, resolves DNS and blocks private/link-local/cloud-metadata IPs
async fn validate_hook_url(url: &str) -> Result<(), String>

// Hook enable/disable via $GROK_HOME/disabled-hooks
pub fn is_hook_disabled / disable_hook / enable_hook
```

### Design Notes

**Blocking vs. non-blocking**: Only `PreToolUse` uses blocking semantics (returns `Allow`/`Deny`). All other events are fire-and-forget with results collected for telemetry.

**Matcher design**: Simple form (alphanumeric, `_`, `|`) uses exact matching to avoid regex anchor bugs. For example, `Read|Write` means "exactly Read or exactly Write", not "Read followed by anything or Write". Invalid matchers fail-closed by returning a never-matcher.

**Fail-open by default**: Hook failures (timeout, crash, error output) do not block tool calls. Only `Deny` from a `PreToolUse` hook blocks execution. Failures are recorded for UI display.

**Shell detection**: The runner checks whether the command contains spaces, `|`, `&`, `;`, `>`, `<`, `$`, `~`, or relative paths. If any are present, it runs through `sh -c`. Otherwise it uses direct `exec`. This avoids spawning a shell unnecessarily while ensuring pipes and redirects work when intended.

**Setsid detached**: Command hooks are spawned with `setsid` (Unix) to detach from the controlling terminal. This prevents GPG pinentry-style programs from blocking on `/dev/tty`.

**Environment variable expansion**: Load-time single expansion for command/URL. HTTP runner does runtime re-expansion to support plugin-injected variables. Modifier forms (`${VAR:-default}`) and unresolvable references are preserved verbatim. A sentinel mechanism (randomized PUA character + hex entropy) prevents modifier forms from being accidentally expanded.

**Reserved env keys**: `GROK_HOOK_*`, `GROK_SESSION_ID`, `GROK_WORKSPACE_ROOT`, `GROK_CWD` are stripped from the hook environment before spawning. Any user configuration of these keys is replaced with a warning.

**Raw field separation**: `command_raw` and `url_raw` store the original unexpanded values for display purposes, while `command` and `url` contain the expanded values for execution. This prevents secrets in expanded values from leaking into logs.

**Payload handling**: `toolInput` and `toolResult` are truncated to 128KB to prevent large payloads. Meta-dispatcher tools (`use_tool`, `MCP`) are expanded to their underlying tool names for matcher evaluation.

---

## 4. Sandbox

### Module Purpose

`xai-grok-sandbox` enforces OS-level access control using kernel primitives. On Linux it uses the Landlock LSM via the `nono` crate, augmented by `bwrap` (bubblewrap) for read-deny enforcement. On macOS it uses Seatbelt. The subsystem also provides child process network filtering via seccomp BPF.

### Profile System

Five built-in profiles plus custom TOML profiles:

| Profile | Filesystem | Network | Use Case |
|---------|-----------|---------|----------|
| `workspace` | Read-write on workspace, read-only outside | Unrestricted | Default development |
| `devbox` | Strict isolation including `/data` write-deny | Unrestricted | High-security development |
| `read-only` | Read-only everywhere | Unrestricted | Review-only mode |
| `strict` | Minimal read-write | Minimal | Production simulation |
| `off` | No restrictions | No restrictions | Disabled |

Custom profiles are defined in TOML and can `extends` a built-in profile:

```toml
[profiles.my-profile]
extends = "workspace"
[profiles.my-profile.deny]
paths = ["/etc/secrets"]
```

### Key Structures

| Structure | File | Purpose |
|-----------|------|---------|
| `SandboxManager` | `lib.rs` | Main sandbox manager orchestrating lifecycle |
| `SandboxProfile` | `profiles.rs` | Resolved sandbox configuration with deny lists |
| `ProfileConfig` | `profiles.rs` | TOML-deserialized profile configuration |
| `ProfileName` | `profiles.rs` | Profile name enum: `Workspace`, `Devbox`, `ReadOnly`, `Strict`, `Off`, `Custom(String)` |
| `SandboxConfig` | `profiles.rs` | Container for all profile definitions |
| `SandboxEvent` | `types.rs` | Telemetry event: `ProfileApplied`, `ApplyFailed`, `FsViolation`, `NetViolation` |
| `SandboxMetrics` | `types.rs` | Atomic counters: `fs_violations`, `net_violations`, `bypasses_granted`, `bypasses_denied` |
| `WebsiteOrigin` | `network_policy.rs` | HTTP(S) origin (scheme/hostname/port) |
| `WebsitePolicy` | `network_policy.rs` | Per-website allow/deny rules, deny takes precedence |
| `NetworkPolicySnapshot` | `network_policy.rs` | Versioned network policy with canonical JSON and SHA256 hash |
| `ChildNetworkPolicy` | `network_policy.rs` | Child process network filtering policy |

### Key APIs

#### Lifecycle

```rust
// Create sandbox manager
pub fn new(config: SandboxConfig, profile_name: ProfileName) -> Self

// Apply sandbox to current process (irreversible)
pub fn apply(&self) -> Result<(), SandboxError>

// Install global state after successful apply
pub fn install(self)
```

#### Capability Conversion

```rust
// Convert ProfileName to nono CapabilitySet
pub fn to_capability_set(&self, is_workspace_devbox: bool) -> Result<CapabilitySet, SandboxError>

// Apply deny paths to CapabilitySet
pub fn apply_deny_paths_to_capability_set(&self, caps: &mut CapabilitySet, profile: &SandboxProfile, is_macos: bool)

// Apply deny glob patterns to CapabilitySet
pub fn apply_deny_globs_to_capability_set(&self, caps: &mut CapabilitySet, profile: &SandboxProfile, is_macos: bool)
```

#### Bubblewrap (Linux)

```rust
// Build bwrap re-exec command for bind-over mounts
pub fn bwrap_reexec_command(cmd: Command, profile: &SandboxProfile) -> Command

// Full bwrap re-exec with devbox /data write-deny and custom deny rules
pub fn bwrap_reexec_for_profile(cmd: Command, profile: &SandboxProfile) -> Command
```

#### Configuration

```rust
// Load merged config from ~/.grok/sandbox.toml and workspace .grok/sandbox.toml
pub fn load_sandbox_config(global_dir: Option<&Path>, project_dir: Option<&Path>) -> (SandboxConfig, Vec<SandboxConfigError>)
```

#### Telemetry

```rust
// Log a filesystem or network violation
pub fn log_violation(profile: &str, operation: &str, path: &str, error: Option<&str>)

// Flush metrics to event log
pub fn flush()

// Get current violation metrics
pub fn metrics() -> SandboxMetrics
```

#### Network Filtering

```rust
// Install seccomp BPF filter to block network syscalls in child processes
pub fn install_child_network_filter(policy: &ChildNetworkPolicy, log_violations: bool)
```

### Design Notes

**Fail-closed security**: Any error during sandbox application (path resolution failure, glob expansion failure, mount failure) prevents the sandbox from starting. The system never silently downgrades.

**Dual-layer network isolation**: The parent process retains network access (needed for LLM API calls). Child processes spawned during tool execution have their network syscalls blocked via seccomp BPF.

**Platform differences**: Linux uses Landlock (no read-deny support) + bwrap bind-over mounts for write/read-deny. macOS uses Seatbelt platform rules with regex-based pattern matching.

**Profile inheritance**: Custom profiles can `extends` built-in profiles but cannot extend other custom profiles. Workspace config (`workspace/.grok/sandbox.toml`) is additive-only: it can add new profile names but cannot override global profile definitions.

**Deny path expansion**: On Linux, glob patterns are expanded at startup into concrete paths by `expand_deny_globs`. This converts `**/*.log` to actual matching files. Safety limits (`max_depth`, `max_matches`, `max_entries`) prevent runaway expansion.

**macOS `/private` firmlink**: On macOS, paths like `/tmp` and `/var/folders` have `/private` aliases. Deny rules must cover both forms. `canonicalize` resolves firmlinks but the rule must still specify both variants.

**/devbox special isolation**: `/data` is write-denied via bwrap mount in devbox profile, independent of `profile.deny` to avoid interference from custom profile inheritance.

**Sandbox immutability**: Kernel sandbox (Landlock/Seatbelt) is a one-way operation. After `apply()`, the restrictions cannot be removed. `install()` persists state in `OnceLock` globals for access by subsequent code.

**Event telemetry**: All sandbox events (application, violations, bypass attempts) are written to `~/.grok/sandbox-events.jsonl` for metrics aggregation and replay.

---

## 5. Memory

### Module Purpose

`xai-grok-memory` provides cross-session semantic persistence. It stores conversation summaries and learned facts in Markdown files, backed by an SQLite database with FTS5 full-text search and sqlite-vec vector search. A "Dream" background consolidation process automatically synthesizes session logs into long-term memories.

### Architecture

```
MemoryBackendImpl
├── index       MemoryIndex   SQLite-backed chunk index (chunks/FTS5/vec0 tables)
├── storage     MemoryStorage Filesystem storage (MEMORY.md + session logs)
├── watcher     MemoryFileWatcher  File system watcher for external edits
└── embedding   ApiEmbeddingProvider  OpenAI-compatible embedding API client
```

### Three Memory Sources

| Source | Location | Time Decay | Purpose |
|--------|----------|-----------|---------|
| `global` | `~/.grok/memory/` | None (evergreen) | Cross-project knowledge |
| `workspace` | `{cwd}/.grok/memory/` | None (evergreen) | Project-specific knowledge |
| `session` | `{cwd}/.grok/memory/sessions/` | Exponential decay (configurable half-life) | Recent conversation logs |

### Key Structures

| Structure | File | Purpose |
|-----------|------|---------|
| `MemoryIndex` | `index.rs` | SQLite index managing chunks/FTS5/vec0 tables |
| `MemoryStorage` | `storage.rs` | Filesystem layer for MEMORY.md and session logs |
| `MemoryBackendImpl` | `backend.rs` | Backend trait implementation with hybrid search |
| `SearchResult` | `search.rs` | Search result with chunk_id, path, score, snippet, source |
| `DreamLock` | `dream_lock.rs` | PID-based lock file for background consolidation coordination |
| `MemoryFileWatcher` | `watcher.rs` | Lock-free file system watcher using `ArcSwap` |
| `Chunk` | `chunker.rs` | Markdown block with text, start_line, end_line |
| `ChunkRecord` | `index.rs` | SQLite record: rowid, id, path, hash, source, access_count |
| `DreamGate` | `dream.rs` | Consolidation trigger conditions: enabled, time, session count |
| `ApiEmbeddingProvider` | `embedding.rs` | OpenAI-compatible embedding client with retry and backoff |
| `EndpointScopedCredentials` | `backend.rs` | Credentials scoped to trusted endpoints only |
| `MemoryBackendParams` | `backend.rs` | Factory parameter bundle for backend creation |

### Key APIs

#### Index Operations

```rust
// Open or create SQLite index with FTS5 and sqlite-vec
pub fn open_or_create(db_path: &Path, storage: MemoryStorage, config: MemoryIndexConfig, dimensions: usize) -> Result<Self, rusqlite::Error>

// Re-index a file based on hash comparison
pub fn reindex_file(&mut self, path: &Path, source: &str) -> Result<ReindexResult, rusqlite::Error>

// FTS5 BM25 search with stopword filtering
pub fn search_fts(&self, query: &str, limit: usize) -> Result<Vec<FtsResult>, rusqlite::Error>

// sqlite-vec KNN vector search
pub fn vector_search(&self, query_embedding: &[f32], k: usize) -> Result<Vec<(String, f32)>, rusqlite::Error>
```

#### Hybrid Search

```rust
// Main search entry: FTS first, then embed query, then merge
pub async fn hybrid_search(index: &MemoryIndex, embedding_provider: Option<&dyn EmbeddingProvider>, query: &str, config: &MemorySearchConfig) -> Result<Vec<SearchResult>, Box<dyn std::error::Error>>

// Synchronous merge: normalize scores, apply time decay, source weight, access boost, MMR rerank
pub(super) fn hybrid_search_merge(index: &MemoryIndex, fts_results: Vec<FtsResult>, query_embedding: Option<&[f32]>, config: &MemorySearchConfig) -> Result<Vec<SearchResult>, Box<dyn std::error::Error>>
```

#### Storage

```rust
// Create storage instance; workspace dir named {slug}-{hash8}; detects temp directories
pub fn new(cwd: &Path, root_override: Option<&Path>) -> Self

// Write daily session log with timestamp separators
pub fn write_daily_log(&self, date: &str, slug: &str, session_id: &str, content: &str, append: bool) -> std::io::Result<PathBuf>
```

#### Dream Consolidation

```rust
// Check dream trigger conditions
pub fn check_dream_gates(config: &MemoryDreamConfig, lock: &DreamLock, sessions_dir: &Path, current_session_sid8: Option<&str>) -> DreamGate

// Execute consolidation: acquire lock, process response, write MEMORY.md, cleanup session files
pub fn execute_dream(lock: &DreamLock, storage: &MemoryStorage, response: &str, sessions_eligible: usize, stale_lock_secs: u64, sessions_dir: &Path, processed_stems: &[String]) -> DreamResult
```

#### Chunking and Embedding

```rust
// Intelligent Markdown chunking by ## headers; overflow splits by paragraphs; adds ancestor context
pub fn chunk_markdown(content: &str, config: &MemoryIndexConfig) -> Vec<Chunk>

// Async embedding of un-embedded chunks; batches of 32
pub async fn embed_missing_chunks(index: &MemoryIndex, provider: &dyn EmbeddingProvider) -> usize
```

### Design Notes

**Two-layer search**: `hybrid_search` first runs FTS5 BM25 keyword search, then embeds the query, then merges results by normalized score weighting. Chunks without vectors are not penalized. The merge applies: time decay (session only), source weighting (global > workspace > session), access frequency boost (`ln(1 + count)`), and MMR (Maximal Marginal Relevance) diversity reranking.

**Send+Sync safety**: `MemoryIndex` is `!Sync`. All `&index` borrows happen in the synchronous merge phase. `.await` points are outside borrow ranges, ensuring the borrow is released before suspension.

**Graceful degradation**: If sqlite-vec is unavailable, the system falls back to FTS-only search. Missing configuration uses sensible defaults. Operations are idempotent: `reindex_file` compares hashes to skip unchanged files, `delete_path` returns 0 for unindexed paths.

**Transaction boundaries**: `reindex_file` and `delete_path` update all three tables (chunks, FTS5, vec0) within a single transaction. The `meta.reindex_claim` field (PID:timestamp) uses atomic `UPDATE` to ensure only one process wins the reindex race.

**Dream lock coordination**: The `.dream-lock` file stores PID and mtime. `is_process_alive` (cross-platform) detects stale locks. On rollback, prior mtime is restored to avoid a fresh lock being incorrectly marked stale.

**Search quality**: Stopword filtering (100+ words) in `query_expansion::extract_keywords` preserves 2-character meaningful terms. MMR reranking uses Jaccard token overlap (`O(n^2)` but n is small). "Evergreen supplement" adds global and workspace results to the top of FTS results to prevent session volume from drowning out long-term memory.

**Security**: `EndpointScopedCredentials` only stores auth tokens for endpoints that pass `is_trusted(endpoint)`. URL matching uses exact comparison. `read_file` uses `canonicalize` for double-validation (TOCTOU protection). API key refresh uses `current_api_key_async` instead of sync to avoid OIDC expiry causing 401 errors.

**Garbage collection**: `tmp*` directories: empty directories deleted unconditionally; non-empty directories deleted after 7 days. Empty workspaces: deleted when `sessions/` is empty and older than `max_age_days` (default 30). Non-empty workspaces are never deleted.

---

## 6. TUI (Terminal User Interface)

### Module Purpose

The TUI subsystem renders the interactive terminal interface, handles keyboard and mouse input, manages layout, and coordinates with the headless backend. It is responsible for the user-facing rendering pipeline that displays prompts, tool results, status bars, and diff views.

### Architecture

The TUI is structured around a rendering loop that:

1. Receives state updates from the backend (headless or foreground process)
2. Computes the visible layout from the scrollback buffer and viewport position
3. Renders the terminal output using a cross-platform terminal library
4. Handles input events and forwards them to the appropriate handler

### Key Components

| Component | Responsibility |
|-----------|---------------|
| **Rendering Engine** | Converts internal state to terminal escape sequences |
| **Layout Manager** | Computes visible regions, handles scrolling, manages panels |
| **Input Handler** | Keyboard shortcuts, mouse events, line editing |
| **Status Bar** | Model indicator, token count, connection status, sandbox profile |
| **Diff Viewer** | Side-by-side or unified diff rendering for file changes |
| **Scrollback Buffer** | Stores and retrieves historical output for scrollback and search |

### Key Design Points

- **Double-buffered rendering**: Updates are computed in a background buffer and atomically swapped to avoid flicker.
- **Incremental rendering**: Only changed regions are re-rendered, not the entire screen.
- **Unicode and box-drawing**: Full UTF-8 support with box-drawing characters for borders and separators.
- **Mouse support**: Terminal mouse protocol for clickable links, selectable text, and panel resizing.
- **Accessible**: Screen reader mode for accessibility, supporting ANSI escape code navigation.

---

## 7. Headless Mode

### Module Purpose

Headless mode allows Grok Build to run as a background daemon without a terminal. It enables:

- **Background execution**: Long-running tasks continue after terminal disconnection
- **Session recovery**: Sessions can be detached and reattached
- **Daemon protocol**: JSON-RPC or HTTP-based communication with the headless instance
- **Persistent state**: Maintains in-memory state across process forks

### Session Model

In headless mode, a session is a persistent execution context. The session survives terminal disconnects and can be recovered by reconnecting to the daemon. State includes:

- Conversation history and context
- MCP client connections
- Sandbox state
- Memory index handles
- Hook event handlers

### Daemon Protocol

The headless daemon exposes a local socket or HTTP endpoint for client connections:

```
Grok Build Client  →  Unix Socket / HTTP  →  Grok Headless Daemon
                     (daemon protocol)
```

The protocol supports:
- Session creation and management
- Message streaming (stdio replacement)
- State queries
- Graceful shutdown

### Key Design Points

- **Process isolation**: The daemon runs as a separate process, isolated from the client's lifecycle.
- **Signal handling**: SIGTERM initiates graceful shutdown with session persistence.
- **Session persistence**: Sessions are serialized to disk for recovery after daemon restart.
- **Socket activation**: The daemon can be socket-activated by systemd or launched directly.

---

## 8. ACP (Agent Communication Protocol)

### Module Purpose

ACP defines how Grok Build agents communicate with each other and with external MCP servers. It encompasses:

- **Protocol constants**: Wire format, message types, and version negotiation
- **Reverse channel**: Server-initiated callbacks to the client
- **ACP-MCP bridge**: Transparent proxy between ACP and MCP protocols

### Protocol Constants

ACP defines standardized constants for:

```rust
// Message type IDs
const INITIALIZE: u32 = 0;
const HANDSHAKE_REQUEST: u32 = 1;
const HANDSHAKE_RESPONSE: u32 = 2;
const INVOKE: u32 = 3;
const INVOKE_RESPONSE: u32 = 4;
const NOTIFICATION: u32 = 5;
```

### ACP-MCP Bridge

The bridge enables MCP servers registered via ACP to be used as if they were native MCP clients:

```
ACP Client  ↔  AcpBridgeTransport  ↔  DuplexStream  ↔  ACP Reverse Channel  ↔  MCP Server
```

- **DuplexStream** creates a bidirectional pipe for JSON-RPC messages
- A **pump task** reads from one direction and writes to the other
- Notifications (which have no `id` in JSON-RPC) are silently dropped
- The bridge handles concurrent calls without head-of-line blocking

### ACP in xai-grok-mcp

The `AcpMcpRegistry` tracks SDK MCP servers registered within the process:

```rust
struct AcpMcpRegistry {
    servers: Vec<AcpServerEntry>,       // Registered server list
    shared_invoker: Arc<dyn AcpReverseInvoker>,  // Shared reverse invoker
}
```

`build_pending_acp_clients` creates `McpClient` instances for each registered ACP server, which then participate in the standard handshake pipeline alongside HTTP and stdio clients.

### Key Design Points

**Half-duplex bridge limitation**: The v1 bridge only supports client-to-server request/response. Server-initiated requests (Sampling, Root, Elicitation) and notifications are not bridged.

**Cancel safety**: The bridge's `read_line` is not cancel-safe and cannot race with `reap`. It uses `try_join_next` to synchronously reclaim completed tasks, maintaining `read_line` atomicity and avoiding JSON-RPC desynchronization from partial reads.

**JoinSet ownership**: All invoke tasks are owned by a `JoinSet`. On teardown, the `JoinSet` is dropped which aborts all remaining tasks.

---

## 9. Cross-Cutting Concerns

### Dependency Management

Extensions use `cargo.metadata` for dependency introspection. The isolation strategy:

```
xai-grok-mcp
└── Private: reqwest 0.13 + rmcp 2.1
    Public: re-exports via xai_grok_mcp::rmcp::*

Other workspace crates
└── reqwest 0.12 (no conflict)
```

### Security Model

| Concern | Mechanism |
|---------|-----------|
| SSRF in hooks | HTTPS enforcement + DNS resolution + private IP blocklist |
| Credential storage | 0600 file permissions, atomic save, flock locking |
| Sandbox bypass | Kernel-level enforcement (Landlock/Seatbelt), fail-closed errors |
| OAuth token exposure | Endpoint-scoped credentials, no token in error messages |
| Shell injection | Shell detection (space, pipe, redirect detection), setsid detached |
| Path traversal | `canonicalize` double-validation, deny glob expansion |

### Telemetry Pipeline

All subsystems emit structured events to `~/.grok/`:

| File | Subsystem | Format |
|------|-----------|--------|
| `sandbox-events.jsonl` | Sandbox | JSONL: `ProfileApplied`, `FsViolation`, `NetViolation` |
| `hook-events.jsonl` | Hooks | JSONL: hook runs, decisions, errors |
| `mcp-events.jsonl` | MCP | JSONL: connection state, tool calls, OAuth flows |

### Lifecycle Phases

1. **Configuration loading**: Each subsystem loads its config from `$GROK_HOME` and workspace overrides.
2. **Initialization**: Subsystems initialize in dependency order (Sandbox → MCP → Hooks → Memory).
3. **Runtime**: Subsystems operate independently, communicating through typed interfaces.
4. **Shutdown**: Graceful teardown with state persistence (Memory writes MEMORY.md, Credentials saved atomically).
5. **Telemetry flush**: All buffered events flushed to disk on exit.

### Error Handling Strategy

| Subsystem | Strategy |
|-----------|----------|
| MCP | Partial degradation: failed servers isolated, others continue |
| Hooks | Fail-open: errors do not block execution |
| Sandbox | Fail-closed: errors prevent sandbox activation |
| Memory | Graceful degradation: vector search unavailable → FTS-only |
| ACP Bridge | Fail-silent: unhandled server messages dropped, errors logged |