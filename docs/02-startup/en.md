# Grok Build Startup Flow Analysis

## 1. Entry Point

### 1.1 Main Entry: xai-grok-pager-bin

**Path**: `source/crates/codegen/xai-grok-pager-bin/src/main.rs`

```rust
fn main() {
    // Initialize jemalloc memory allocator
    xai_grok_pager_minimal::install();
    
    // Initialize memory tracing
    xai_grok_pager::memory_trace::start(...);
    
    // TokiO multi-threaded runtime
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .unwrap();
    
    let result = run_and_shutdown(runtime, async_main(), RUNTIME_SHUTDOWN_GRACE);
}
```

**Key Initialization Steps**:
1. Install jemalloc allocator (optional)
2. Install crash handler
3. Check version requirements
4. Initialize Sentry monitoring
5. Build Tokio multi-threaded runtime

### 1.2 Async Main Function: async_main()

```rust
async fn async_main() -> Result<()> {
    let mut args = PagerArgs::parse_and_apply_cwd()?;
    
    // Command routing
    match command {
        Command::Agent(agent_args) => run_agent_command(...),
        Command::Setup { .. } => run_setup_command(...).await,
        Command::Workspace(..) => run_workspace_mgmt(...).await,
        Command::Login { .. } => run_cli_login(...).await,
        // ...other commands
    }
}
```

## 2. Configuration Loading

### 2.1 Configuration Layers

**Source**: `xai-grok-shell/src/config/mod.rs`

Configurations are loaded in order of increasing priority:

```
1. System Managed Config
2. Managed Config - server-provided
3. User Config - ~/.grok/config.toml
4. Project Config - .grok/config.toml
5. CLI Overrides
```

### 2.2 Configuration Loading Functions

```rust
// Load merged effective configuration
pub fn load_effective_config() -> Result<toml::Value> {
    // Load each layer and deep merge
}

// Load AgentConfig
AgentConfig::new_from_toml_cfg(&raw_config)
```

### 2.3 Configuration Application Flow

```rust
// 1. Load base configuration
let raw_config = xai_grok_shell::config::load_effective_config()?;

// 2. Create AgentConfig
let mut agent_config = AgentConfig::new_from_toml_cfg(&raw_config)?;

// 3. Apply CLI overrides
apply_agent_endpoint_args(&agent_args, &mut agent_config);

// 4. Apply sandbox configuration
xai_grok_shell::config::apply_sandbox(None, sandbox_profile_arg, cwd);

// 5. Resolve runtime fields
agent_config.resolve_runtime_fields(&RuntimeResolutionContext {
    raw_config: &raw_config,
    remote_settings: remote_settings.as_ref(),
    is_headless: !is_leader,
    // ...
});
```

## 3. Component Initialization

### 3.1 Tokio Runtime

```rust
// Main program uses multi-threaded runtime
let runtime = tokio::runtime::Builder::new_multi_thread()
    .enable_all()
    .build()?;
```

### 3.2 Telemetry Initialization

```rust
fn init_tracing_simple(app_entrypoint: &'static str) {
    let registry = tracing_subscriber::registry()
        .with(fmt_layer.with_filter(env_filter))
        .with(xai_grok_telemetry::sampling_log::layer())
        .with(xai_grok_telemetry::instrumentation::layer())
        .with(xai_grok_telemetry::hooks_log::layer())
        .with(xai_grok_telemetry::otel_layer::build_otel_layer(...));
    
    xai_grok_telemetry::external::init(...);
}
```

### 3.3 Sentry Monitoring

```rust
let _sentry_guard = xai_grok_telemetry::sentry::init(
    xai_grok_telemetry::sentry::Config {
        client: "grok-pager",
        client_version: PAGER_CLIENT_VERSION,
        release: env!("VERSION_WITH_COMMIT"),
        disabled: is_error_reporting_disabled_sync(),
    }
);
```

### 3.4 AuthManager Initialization

```rust
// Create authentication manager
let auth_manager = Arc::new(agent_config.create_auth_manager());

// Start proactive refresh
auth_manager.start_proactive_refresh(cancel.clone());

// System power listener (pause refresh)
auth_manager.start_system_power_listener();
```

## 4. Service Startup Flow

### 4.1 Run Modes

```
┌─────────────────────────────────────────────────────┐
│                      Run Modes                       │
├─────────────┬─────────────┬─────────────┬───────────┤
│  Pager TUI  │   Stdio     │  Headless   │   Leader  │
│ (Interactive)│ (IDE Plugin) │ (No Browser)│(Multi-Client)│
└─────────────┴─────────────┴─────────────┴───────────┘
```

### 4.2 Pager TUI Mode

**Entry**: `xai_grok_pager::app::run(args, bg_update_rx)`

```rust
// 1. Parse arguments
let args = PagerArgs::parse_and_apply_cwd()?;

// 2. Check for auto updates
if should_check_for_updates(args.no_auto_update) {
    tokio::spawn(auto_update::check_update_background(...));
}

// 3. Run Pager application
xai_grok_pager::app::run(args, bg_update_rx).await
```

### 4.3 Stdio Agent Mode

**Entry**: `xai_grok_shell::agent::app::run_stdio_agent()`

```rust
pub async fn run_stdio_agent(...) -> anyhow::Result<()> {
    // 1. Register filesystem watch runtime
    register_fs_watch_runtime();
    
    // 2. Set unified log version
    xai_grok_telemetry::unified_log::set_version(...);
    
    // 3. Clean orphaned temporary files
    xai_file_utils::queue::cleanup_orphaned_uploads(...);
    
    // 4. Prefetch model list
    let prefetched_models = prefetch_models(agent_config).await;
    
    // 5. Create ACP simplex stream
    let (acp_incoming_rx, acp_incoming_tx) = simplex(MAX_BUFFER_SIZE);
    
    // 6. Start stdin->ACP bridge
    let mut stdin_lines = xai_acp_lib::spawn_stdin_line_reader();
    
    // 7. Create LocalSet and run Agent
    let local_set = tokio::task::LocalSet::new();
    local_set.run_until(async {
        let auth_manager = Arc::new(agent_config.create_auth_manager());
        spawn_agent_local(agent_config, auth_manager, ...).await
    }).await
}
```

### 4.4 Headless Mode

**Entry**: `xai_grok_shell::agent::app::run_headless()`

```rust
pub async fn run_headless(...) -> anyhow::Result<()> {
    // 1. Register runtime
    register_fs_watch_runtime();
    
    // 2. Auth flow (no browser)
    let auth = if no_browser {
        // Use cached credentials only
        auth_manager.current()
    } else {
        // Execute OAuth flow
        run_auth_flow(...).await?
    };
    
    // 3. Prefetch models
    let prefetched_models = tokio::task::spawn_blocking(move || {
        prefetch_models_blocking(...)
    }).await?;
    
    // 4. Establish Relay connection
    spawn_relay_connection_with_callback(...);
    
    // 5. Run Agent in LocalSet
    local_set.run_until(async {
        // Agent task
        tokio::task::spawn_local(async {
            let agent = MvpAgent::new(...);
            acp::AgentSideConnection::new(agent, ...).await
        });
        
        // WebSocket->Agent bridge
        // Agent->Relay bridge
    }).await
}
```

### 4.5 Leader Mode

**Entry**: `xai_grok_shell::agent::app::run_leader()`

**Startup Sequence**:

```
Phase 1: Lock acquisition check
    └─ LeaderLock::new(ws_url)
    └─ lock.try_acquire()
    
Phase 2: Socket cleanup
    └─ lock.cleanup_socket()
    
Phase 3: IPC server startup (before auth)
    └─ run_leader_server(socket_path, ...)
    
Phase 4: Wait for socket ready
    
Phase 5: Lock handover
    
Phase 6: Auth + Model prefetch
    └─ try_ensure_session_noninteractive()
    └─ prefetch_models_and_settings_blocking()
    
Phase 7: Send ready signal
    └─ ready_tx.send(true)
    
Phase 8: LocalSet run
    └─ Agent + IPC bridge + WS bridge + Relay + Config listener
```

```rust
pub async fn run_leader(...) -> anyhow::Result<()> {
    // Lock acquisition
    let lock = LeaderLock::new(ws_url);
    let lock_already_held = lock.try_acquire()?;
    
    // IPC server (started before auth)
    let ipc_handle = tokio::spawn(async move {
        run_leader_server(
            socket_path,
            ipc_to_agent_tx,
            agent_to_ipc_rx,
            ipc_server_cancel,
            // ...
        ).await
    });
    
    // Wait for socket ready
    while !crate::leader::listener_is_ready(&socket_path) { ... }
    
    // Auth
    let auth = crate::auth::try_ensure_session_noninteractive(ctx).await;
    
    // Model prefetch
    let (prefetched_models, remote_settings) = 
        spawn_blocking(prefetch_models_and_settings_blocking).await?;
    
    // Send ready signal
    ready_tx.send(true);
    
    // LocalSet run
    local_set.run_until(async {
        // Agent
        tokio::task::spawn_local(async {
            let agent = MvpAgent::with_models(...);
        });
        
        // IPC bridge
        tokio::task::spawn_local(async { ... });
        
        // WS bridge
        tokio::task::spawn_local(async { ... });
        
        // Agent->WS+IPC bridge
        tokio::task::spawn_local(async { ... });
        
        // Relay connection
        spawn_leader_relay(...);
        
        // Config hot-reload listener
        crate::config::watcher::ConfigFileWatcher::start(...);
    }).await
}
```

## 5. Agent Core Components

### 5.1 MvpAgent Initialization

```rust
let agent = MvpAgent::new(gateway, &agent_config, auth_manager, prefetched_models)
    .unwrap_or_else(exit_on_config_error);
```

### 5.2 ACP Connection Establishment

```rust
// ACP (Agent Client Protocol) connection
let (conn, handle_io) = acp::AgentSideConnection::new(
    agent,           // Agent handler
    outgoing,        // ACP output stream
    incoming,        // ACP input stream
    |fut| tokio::task::spawn_local(fut)  // Local task spawn
);

// Gateway receiver
tokio::task::spawn_local(
    GatewayReceiver::new(gw_rx, conn).run()
);
```

## 6. Startup Flow Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                        main()                                │
│  ├─ xai_grok_pager_minimal::install()                       │
│  ├─ xai_grok_pager::memory_trace::start()                   │
│  ├─ xai_grok_config::validate_requirements()                │
│  ├─ xai_grok_telemetry::sentry::init()                      │
│  ├─ xai_crash_handler::install()                            │
│  ├─ tokio::runtime::Builder::new_multi_thread()             │
│  └─ run_and_shutdown(runtime, async_main())                 │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                      async_main()                            │
│  ├─ PagerArgs::parse_and_apply_cwd()                        │
│  ├─ Parse command type                                      │
│  └─ Command routing                                         │
└──────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│    Agent Mode   │ │  Pager TUI Mode │ │   Other Cmds    │
│ (run_agent_cmd) │ │   (run pager)   │ │  (login, etc.)  │
└─────────────────┘ └─────────────────┘ └─────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────────┐
│                    run_agent_command()                       │
│  ├─ init_tracing_simple()                                   │
│  ├─ Create AuthManager                                      │
│  ├─ start_proactive_refresh()                               │
│  ├─ load_effective_config()                                 │
│  ├─ Create AgentConfig                                      │
│  ├─ resolve_use_leader()                                    │
│  └─ Route to specific mode                                  │
└──────────────────────────────────────────────────────────────┘
          │
          ├──────────────┬──────────────┬──────────────┐
          ▼              ▼              ▼              ▼
    ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
    │  Stdio   │  │ Headless │  │  Leader  │  │  Serve   │
    │  Agent   │  │  Agent   │  │  Agent   │  │  Agent   │
    └──────────┘  └──────────┘  └──────────┘  └──────────┘
          │              │              │              │
          └──────────────┴──────────────┴──────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    LocalSet::run_until()                     │
│  ├─ Register FS watch runtime                               │
│  ├─ Create ACP simplex stream                               │
│  ├─ Start stdin/WS bridge                                   │
│  ├─ Create and start MvpAgent                               │
│  ├─ Establish ACP connection (AgentSideConnection)          │
│  └─ Start GatewayReceiver                                   │
└──────────────────────────────────────────────────────────────┘
```

## 7. Key Configuration Items

### 7.1 Memory Configuration

```rust
pub struct MemoryConfig {
    pub enabled: bool,
    pub index: MemoryIndexConfig,
    pub embedding: MemoryEmbeddingConfig,
    pub search: MemorySearchConfig,
    pub initial_injection: MemoryInitialInjectionConfig,
    pub session: MemorySessionConfig,
    pub watcher: MemoryWatcherConfig,
    pub gc: MemoryGcConfig,
}
```

### 7.2 Plugins Configuration

```rust
pub struct PluginsConfig {
    pub paths: Vec<String>,      // Plugin directories
    pub disabled: Vec<String>,   // Disabled plugins
    pub enabled: Vec<String>,    // Enabled plugins
}
```

### 7.3 Model Configuration

```rust
pub struct ModelOverrideConfig {
    pub web_search: String,                // Web search model
    pub session_summary: Option<String>,   // Session summary model
    pub image_description: Option<String>, // Image description model
}
```

## 8. Key Module Dependencies

```
┌─────────────────────────────────────────────────────────────┐
│                    xai-grok-pager-bin                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     xai-grok-shell                          │
│  ├─ agent/app.rs      - Agent startup entry                 │
│  ├─ agent/mvp_agent/ - MVP Agent implementation             │
│  ├─ auth/            - Authentication management            │
│  ├─ config/          - Configuration loading                │
│  ├─ leader/          - Leader mode                          │
│  └─ agent/relay/     - Relay connection                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     xai-grok-agent                          │
│  ├─ Agent definition and parsing                            │
│  ├─ Tool system                                             │
│  ├─ System prompt assembly                                  │
│  └─ Compression strategy                                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     xai-chat-state                          │
│  ├─ Conversation state management                           │
│  ├─ Session persistence                                     │
│  └─ Compression transcription                               │
└─────────────────────────────────────────────────────────────┘
```