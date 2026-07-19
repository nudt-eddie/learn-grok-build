# Chapter 6: Skills, Plugins, and Hooks Extension System

## Learning Objectives

By the end of this chapter, you will understand:

1. **Skills System**: How Grok discovers, prioritizes, and injects skills from multiple sources
2. **Plugin System**: The plugin discovery mechanism, scope model, and trust architecture
3. **Plugin Manifest**: Parsing plugin manifest files and resolving component paths
4. **Hooks System**: Lifecycle hook registration, dispatch, and execution mechanisms

---

## 1. Skills System

### 1.1 Core Data Structures

The core types for Skills are defined in the `xai-grok-tools` crate and re-exported for use in the agent:

```rust
// source/crates/codegen/xai-grok-agent/src/prompt/skills.rs:12
pub use xai_grok_tools::implementations::skills::types::{SkillInfo, SkillScope};
```

#### SkillInfo Structure

```rust
// source/crates/codegen/xai-grok-tools/src/implementations/skills/types.rs
#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
pub struct SkillInfo {
    pub name: String,                          // Skill name
    pub display_name: Option<String>,          // Display name
    pub description: String,                   // Description
    pub when_to_use: Option<String>,           // When to use
    pub short_description: Option<String>,     // Short description
    pub author: Option<String>,                // Author
    pub argument_hint: Option<String>,         // Argument hint
    
    pub path: String,                          // SKILL.md file path
    pub scope: SkillScope,                     // Scope
    pub config_source: Option<ConfigSource>,   // Config source
    
    // Plugin-related fields
    pub plugin_name: Option<String>,           // Plugin name
    pub plugin_version: Option<String>,        // Plugin version
    pub plugin_root: Option<String>,           // Plugin root directory
    pub plugin_data: Option<String>,           // Plugin data directory
    
    // Tools and license
    pub allowed_tools: Option<Vec<String>>,    // Allowed tools
    pub license: Option<String>,               // License
    pub compatibility: Option<String>,         // Compatibility
    
    pub model: Option<String>,                 // Recommended model
    pub effort: Option<String>,                // Expected effort
    pub user_invocable: bool,                  // User-invocable flag
    pub disable_model_invocation: bool,        // Disable model invocation flag
    
    pub paths: Option<Vec<String>>,            // Nested paths
    pub enabled: bool,                         // Whether enabled
    pub body: Option<String>,                  // Skill body content
}
```

#### SkillScope Enum

```rust
// source/crates/codegen/xai-grok-tools/src/implementations/skills/types.rs
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SkillScope {
    /// Local skill: located in cwd/.grok/skills/
    Local = 0,
    /// Repo skill: located in repo_root/.grok/skills/
    Repo = 1,
    /// User skill: located in ~/.grok/skills/
    User = 2,
    /// Server skill: synced from server
    Server = 3,
    /// Bundled skill: built-in skill
    Bundled = 4,
    /// Plugin skill: from plugins
    Plugin = 5,
}
```

### 1.2 Core Implementation: list_skills Function

```rust
// source/crates/codegen/xai-grok-agent/src/prompt/skills.rs:64-70
/// List all discovered skills with their metadata.
///
/// Priority order:
/// Local (cwd/.grok/skills, cwd/.agents/skills, cwd/.claude/skills) 
/// → Repo (repo_root/.grok/skills, ...) → User (~/.grok/skills, ...)
/// → additional paths from `config.paths`
/// → Server (injected `config.server_skill_dirs`)
/// → Bundled (injected `config.bundled_skill_dirs` + `~/.grok/bundled`)
pub async fn list_skills(
    working_directory: Option<&str>,
    config: &SkillsConfig,
    compat: CompatConfig,
) -> Vec<SkillInfo> {
    list_skills_with_plugins(working_directory, config, None, compat).await
}
```

#### Skills List with Plugin Support

```rust
// source/crates/codegen/xai-grok-agent/src/prompt/skills.rs:79-136
pub async fn list_skills_with_plugins(
    working_directory: Option<&str>,
    config: &SkillsConfig,
    plugins: Option<&crate::plugins::PluginRegistry>,
    compat: CompatConfig,
) -> Vec<SkillInfo> {
    let _skill_discovery_timer = crate::timing::timer("skill_discovery");
    let workspace_user_dir = crate::prompt::workspace_user::optional_workspace_user_dir();

    // 1. Collect skills from local, repo, and user directories
    let mut skills = list_skills_with_options(
        working_directory,
        workspace_user_dir.as_deref(),
        &xai_grok_tools::util::grok_home::grok_home(),
        compat,
    ).await;

    // 2. Resolve git root for path resolution
    let git_root = working_directory.and_then(|wd| {
        git2::Repository::discover(wd)
            .ok()
            .and_then(|repo| repo.workdir().map(|p| p.to_path_buf()))
    });

    // 3. Collect skills from configured paths
    skills.extend(collect_config_skills(&config.paths, git_root.as_deref()));

    // 4. Collect injected Server and Bundled skills
    skills.extend(collect_injected_skills(&config.server_skill_dirs, SkillScope::Server));
    skills.extend(collect_injected_skills(&config.bundled_skill_dirs, SkillScope::Bundled));

    // 5. Apply ignore filters and sort
    let mut skills = filter_skills(skills, &config.ignore);
    skills.sort_by_key(|s| s.scope);

    // 6. Collect and merge plugin skills
    let plugin_skills = if let Some(registry) = plugins {
        collect_plugin_skills(registry)
    } else {
        vec![]
    };
    let mut merged = merge_skills_with_plugins(skills, plugin_skills);

    // 7. Mark disabled skills
    if !config.disabled.is_empty() {
        let disabled_set: HashSet<&str> = config.disabled.iter().map(|s| s.as_str()).collect();
        for skill in &mut merged {
            if disabled_set.contains(skill.name.as_str()) {
                skill.enabled = false;
            }
        }
    }

    merged
}
```

### 1.3 Priority and Deduplication

#### Priority Order

```
Local (highest) → Repo → User → Config Paths → Server → Bundled (lowest)
```

#### Deduplication Logic

```rust
// source/crates/codegen/xai-grok-agent/src/prompt/skills.rs:424-502
fn dedupe_skills(skills: Vec<SkillInfo>) -> Vec<SkillInfo> {
    let mut seen_paths: HashMap<PathBuf, usize> = HashMap::new();
    let mut seen_names: HashMap<String, (SkillScope, usize)> = HashMap::new();
    let mut deduped: Vec<SkillInfo> = Vec::with_capacity(skills.len());

    for mut skill in skills {
        let canonical_path = dunce::canonicalize(&skill.path)
            .unwrap_or_else(|_| PathBuf::from(&skill.path));

        // Path deduplication: same file from multiple sources
        if let Some(&kept_idx) = seen_paths.get(&canonical_path) {
            // Keep existing entry, inherit config_source from duplicate
            let kept = &mut deduped[kept_idx];
            if kept.config_source.is_none() && skill.config_source.is_some() {
                kept.config_source = skill.config_source;
            }
            continue;
        }

        // Name deduplication: higher priority source wins
        if let Some(&(winner_scope, winner_idx)) = seen_names.get(&skill.name) {
            // Same scope same name: rekey to directory basename
            if winner_scope == skill.scope
                && !matches!(skill.scope, SkillScope::Server | SkillScope::Bundled) 
            {
                if rekey_to_dir_basename(&mut skill, &mut seen_names, deduped.len()) {
                    // Rekey successful, add it
                    seen_paths.insert(canonical_path, deduped.len());
                    deduped.push(skill);
                    continue;
                }
                // ... more handling logic
            }
            continue; // Shadowed by same-name skill
        }

        seen_names.insert(skill.name.clone(), (skill.scope, deduped.len()));
        seen_paths.insert(canonical_path, deduped.len());
        deduped.push(skill);
    }

    deduped
}
```

### 1.4 Plugin Skills Collection

```rust
// source/crates/codegen/xai-grok-agent/src/prompt/skills.rs:565-598
fn collect_plugin_skills(registry: &crate::plugins::PluginRegistry) -> Vec<SkillInfo> {
    let mut skills = Vec::new();

    for plugin in registry.enabled_plugins() {
        let mut paths: Vec<(PathBuf, SkillScope)> = Vec::new();

        // Collect from plugin skill_dirs
        for skill_dir in &plugin.skill_dirs {
            if !skill_dir.is_dir() {
                continue;
            }
            paths.extend(
                find_skill_md_paths(skill_dir)
                    .into_iter()
                    .map(|p| (p, SkillScope::Repo)),
            );
        }

        // Collect from plugin command_dirs (.md files)
        for cmd_dir in &plugin.command_dirs {
            paths.extend(
                scan_md_files(cmd_dir)
                    .into_iter()
                    .map(|p| (p, SkillScope::Repo)),
            );
        }

        let mut parsed = parse_skill_files(paths);
        stamp_plugin_fields(&mut parsed, plugin); // Inject plugin metadata
        skills.extend(parsed);
    }

    skills
}
```

### 1.5 Skills Configuration

```rust
// source/crates/codegen/xai-grok-agent/src/prompt/skills.rs:22-47
#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
pub struct SkillsConfig {
    /// Additional skill locations
    pub paths: Vec<String>,
    
    /// Paths to exclude (prefixes)
    pub ignore: Vec<String>,
    
    /// Disabled skill names
    pub disabled: Vec<String>,
    
    /// Server-synced skill directories
    pub server_skill_dirs: Vec<String>,
    
    /// Bundled skill directories
    pub bundled_skill_dirs: Vec<String>,
}
```

---

## 2. Plugin System

### 2.1 Core Data Structures

#### PluginScope Enum

```rust
// source/crates/codegen/xai-grok-agent/src/plugins/discovery.rs:27-37
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PluginScope {
    /// CLI --plugin-dir (highest priority, always trusted)
    CliOverride = 0,
    /// Project plugin: .grok/plugins/ or .claude/plugins/
    Project = 1,
    /// User plugin: ~/.grok/plugins/ or ~/.claude/plugins/
    User = 2,
    /// Config path: [plugins].paths
    ConfigPath = 3,
}
```

#### DiscoveredPlugin Structure

```rust
// source/crates/codegen/xai-grok-agent/src/plugins/discovery.rs:132-161
#[derive(Debug, Clone)]
pub struct DiscoveredPlugin {
    /// Parsed manifest (synthesized for convention plugins)
    pub manifest: PluginManifest,
    
    /// Stable internal identifier
    pub id: PluginId,
    
    /// Absolute path to plugin root
    pub root: PathBuf,
    
    /// Canonicalized root path (resolves symlinks)
    pub canonical_root: PathBuf,
    
    /// Scope of discovery source
    pub scope: PluginScope,
    
    /// Specific discovery origin
    pub origin: PluginOrigin,
    
    /// Whether trusted (can execute operations)
    pub trusted: bool,
    
    /// Resolved skill directories
    pub skill_dirs: Vec<PathBuf>,
    pub command_dirs: Vec<PathBuf>,
    
    /// Resolved agent directories
    pub agent_dirs: Vec<PathBuf>,
    
    /// Resolved hooks file path
    pub hooks_path: Option<PathBuf>,
    
    /// Resolved MCP config file path
    pub mcp_config_path: Option<PathBuf>,
    
    /// Resolved LSP config file path
    pub lsp_config_path: Option<PathBuf>,
    
    /// Name conflict warning message
    pub conflict: Option<String>,
}
```

#### PluginId Structure

```rust
// source/crates/codegen/xai-grok-agent/src/plugins/discovery.rs:102-123
/// Stable internal identity for a plugin.
/// Format: <scope>/<hex8>/<name>
/// - <scope>: lowercase scope string (cli, project, user, config)
/// - <hex8>: first 8 hex chars of SHA-256 of the canonical plugin root path
/// - <name>: the plugin_name
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct PluginId(pub String);

impl PluginId {
    pub fn new(scope: PluginScope, canonical_root: &Path, name: &str) -> Self {
        let path_str = canonical_root.to_string_lossy();
        let mut hasher = Sha256::new();
        hasher.update(path_str.as_bytes());
        let hash = hasher.finalize();
        let hex8 = format!("{:02x}{:02x}{:02x}{:02x}", hash[0], hash[1], hash[2], hash[3]);
        Self(format!("{}/{}/{}", scope.id_label(), hex8, name))
    }
}
```

### 2.2 Core Implementation: discover_plugins Function

```rust
// source/crates/codegen/xai-grok-agent/src/plugins/discovery.rs:274-486
/// Discover all plugins from the filesystem.
///
/// cwd is used to find the git worktree root for project-scope plugins.
/// project_trusted is the folder-trust verdict for cwd; it gates Project-scope plugins.
pub fn discover_plugins(
    cwd: Option<&Path>,
    config: &DiscoveryConfig,
    trust_store: &TrustStore,
    project_trusted: bool,
) -> Vec<DiscoveredPlugin> {
    let _plugin_discovery_timer = crate::timing::timer("plugin_discovery");
    let mut seen_paths: HashSet<PathBuf> = HashSet::new();
    let mut candidates: Vec<DiscoveredPlugin> = Vec::new();

    // 1. CLI --plugin-dir paths (highest priority)
    for dir in &config.cli_plugin_dirs {
        if dir.is_dir() {
            collect_plugin(dir, PluginScope::CliOverride, ...);
        }
    }

    // 2-3. Project plugins (.grok/plugins/, .claude/plugins/)
    if let Some(cwd) = cwd {
        let (project_dirs, git_root) = project_plugin_dirs(Some(cwd));
        for plugins_dir in project_dirs {
            scan_plugin_dir(&plugins_dir, PluginScope::Project, ...);
        }
    }

    // 4-5. User plugins: $GROK_HOME/plugins, ~/.claude/plugins
    let grok = xai_grok_config::user_grok_home();
    let plugin_dirs = user_plugin_dirs(dirs::home_dir().as_deref(), grok.as_deref());
    for (plugins_dir, origin) in plugin_dirs {
        if plugins_dir.is_dir() {
            scan_plugin_dir(&plugins_dir, PluginScope::User, ...);
        }
    }

    // 6. Config path plugins
    for dir in &config.config_paths {
        if dir.is_dir() {
            collect_plugin(dir, PluginScope::ConfigPath, ...);
        }
    }

    // Resolve name conflicts: same name, higher priority scope wins
    resolve_name_conflicts(&mut candidates);

    candidates
}
```

### 2.3 Plugin Discovery Flow

```
Discovery Priority (high → low):
┌──────────────────────────────────────────────────────────────┐
│ 1. CLI --plugin-dir paths (CliOverride)                      │
│    - Always trusted                                         │
│    - Highest priority                                       │
├──────────────────────────────────────────────────────────────┤
│ 2. Project plugins (Project)                                 │
│    - .grok/plugins/<name>/                                  │
│    - .claude/plugins/<name>/                                │
│    - Requires folder-trust authorization                    │
├──────────────────────────────────────────────────────────────┤
│ 3. Marketplace plugins (Marketplace)                         │
│    - Resolved from known marketplace                        │
│    - User scope                                             │
├──────────────────────────────────────────────────────────────┤
│ 4. User plugins (User)                                       │
│    - ~/.grok/plugins/<name>/                                │
│    - Always trusted                                         │
├──────────────────────────────────────────────────────────────┤
│ 5. Installed plugins (Installed)                             │
│    - Loaded from installation registry                      │
│    - User scope                                             │
├──────────────────────────────────────────────────────────────┤
│ 6. Config paths (ConfigPath)                                 │
│    - [plugins].paths configuration                          │
│    - Trust depends on location                              │
└──────────────────────────────────────────────────────────────┘
```

### 2.4 Name Conflict Resolution

```rust
// source/crates/codegen/xai-grok-agent/src/plugins/discovery.rs:732-794
/// Resolve plugin_name conflicts across scopes.
/// Within each name group, keep only the highest-priority candidate
/// (lowest scope ordinal).
fn resolve_name_conflicts(candidates: &mut Vec<DiscoveredPlugin>) {
    let mut name_map: HashMap<String, usize> = HashMap::new();
    let mut to_remove: Vec<usize> = Vec::new();

    for (idx, candidate) in candidates.iter().enumerate() {
        let name = candidate.manifest.name.clone();
        match name_map.get(&name) {
            Some(&existing_idx) => {
                let existing = &candidates[existing_idx];
                // Lower scope ordinal = higher priority
                if (candidate.scope as u8) < (existing.scope as u8) {
                    // New candidate wins
                    to_remove.push(existing_idx);
                    name_map.insert(name, idx);
                } else {
                    // Existing wins
                    to_remove.push(idx);
                }
            }
            None => {
                name_map.insert(name, idx);
            }
        }
    }

    // Remove losers
    to_remove.sort_unstable();
    to_remove.dedup();
    for idx in to_remove.into_iter().rev() {
        candidates.remove(idx);
    }
}
```

### 2.5 Trust Model

```rust
// source/crates/codegen/xai-grok-agent/src/plugins/discovery.rs:687-697
/// Determine trust status. Exhaustive match forces compile error on new scopes.
let trusted = match scope {
    PluginScope::CliOverride | PluginScope::User => true,
    PluginScope::ConfigPath => {
        TrustStore::is_config_path_auto_trusted(plugin_root)
            || trust_store.is_trusted(plugin_root)
    }
    // Project trust comes from folder-trust (passed by caller)
    PluginScope::Project => project_trusted,
};
```

---

## 3. Plugin Manifest

### 3.1 Core Data Structures

#### PathOrInline Enum

```rust
// source/crates/codegen/xai-grok-agent/src/plugins/manifest.rs:125-130
/// A value that can be either a file path (string) or an inline JSON object.
#[derive(Debug, Clone, Deserialize)]
#[serde(untagged)]
pub enum PathOrInline {
    Path(String),
    Inline(serde_json::Value),
}
```

#### PluginManifest Structure

```rust
// source/crates/codegen/xai-grok-agent/src/plugins/manifest.rs:132-170
/// Parsed plugin manifest from plugin.json.
/// Forward-compatible: unknown fields are silently ignored.
#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PluginManifest {
    // Basic info
    pub name: String,                         // Required: plugin namespace (kebab-case)
    pub version: Option<String>,              // Semver version
    pub description: Option<String>,
    pub author: Option<Author>,
    pub homepage: Option<String>,
    pub repository: Option<String>,
    pub license: Option<String>,
    pub keywords: Vec<String>,

    // Component path overrides
    pub skills: Option<PathOrPaths>,
    pub commands: Option<PathOrPaths>,
    pub agents: Option<PathOrPaths>,
    pub hooks: Option<PathOrInline>,
    pub mcp_servers: Option<PathOrInline>,
    pub lsp_servers: Option<PathOrInline>,
}
```

### 3.2 Manifest Loading

```rust
// source/crates/codegen/xai-grok-agent/src/plugins/manifest.rs:292-333
/// Manifest search order within a plugin directory.
const MANIFEST_PATHS: &[&str] = &[
    "plugin.json",
    ".grok-plugin/plugin.json",
    ".claude-plugin/plugin.json",
];

/// Load a plugin manifest from the given plugin root directory.
pub fn load_manifest(plugin_root: &Path) -> Result<ManifestLoadResult, ManifestError> {
    for rel_path in MANIFEST_PATHS {
        let manifest_path = plugin_root.join(rel_path);
        if manifest_path.is_file() {
            let content = std::fs::read_to_string(&manifest_path)
                .map_err(|e| ManifestError::IoError { path: manifest_path.clone(), source: e })?;
            let manifest: PluginManifest = serde_json::from_str(&content)
                .map_err(|e| ManifestError::ParseError { path: manifest_path.clone(), message: e.to_string() })?;
            manifest.validate()?;
            manifest.warn_unsupported_features(&manifest.name);
            return Ok(ManifestLoadResult::Found(Box::new(manifest)));
        }
    }
    Ok(ManifestLoadResult::NotFound)
}
```

### 3.3 Component Path Resolution

```rust
// source/crates/codegen/xai-grok-agent/src/plugins/manifest.rs:97-122
/// Resolve a plugin component path (hooks, MCP, LSP) from a manifest field.
fn resolve_component_path(
    field: &Option<PathOrInline>,
    plugin_root: &Path,
    default_file: &str,
    label: &str,
) -> Option<PathBuf> {
    match field {
        Some(PathOrInline::Path(p)) => {
            let resolved = plugin_root.join(p);
            // Path escape check
            if !is_path_contained(&resolved, plugin_root) {
                tracing::warn!("{label} path escapes plugin root; skipping");
                return None;
            }
            resolved.is_file().then_some(resolved)
        }
        Some(PathOrInline::Inline(_)) => None, // Caller reads inline value directly
        None => {
            let default = plugin_root.join(default_file);
            default.is_file().then_some(default)
        }
    }
}

/// Check whether a resolved path stays within the plugin root.
fn is_path_contained(resolved: &Path, plugin_root: &Path) -> bool {
    let canonical_root = dunce::canonicalize(plugin_root)
        .unwrap_or_else(|_| plugin_root.to_path_buf());
    let canonical_resolved = dunce::canonicalize(resolved)
        .unwrap_or_else(|_| resolved.to_path_buf());
    canonical_resolved.starts_with(&canonical_root)
}
```

### 3.4 Inline Configuration Support

```rust
// source/crates/codegen/xai-grok-agent/src/plugins/manifest.rs:213-235
/// Get inline hooks JSON value, if the manifest uses inline hooks.
pub fn inline_hooks(&self) -> Option<&serde_json::Value> {
    match &self.hooks {
        Some(PathOrInline::Inline(v)) => Some(v),
        _ => None,
    }
}

/// Get inline MCP servers JSON value.
pub fn inline_mcp_servers(&self) -> Option<&serde_json::Value> {
    match &self.mcp_servers {
        Some(PathOrInline::Inline(v)) => Some(v),
        _ => None,
    }
}
```

### 3.5 Manifest Validation

```rust
// source/crates/codegen/xai-grok-agent/src/plugins/manifest.rs:23-31
/// Regex pattern for valid plugin names: lowercase alphanumeric + hyphens.
fn is_valid_plugin_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= MAX_PLUGIN_NAME_LEN
        && name.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
        && !name.starts_with('-')
        && !name.ends_with('-')
}

impl PluginManifest {
    pub fn validate(&self) -> Result<(), ManifestError> {
        if !is_valid_plugin_name(&self.name) {
            return Err(ManifestError::InvalidName { ... });
        }
        Ok(())
    }
}
```

---

## 4. Hooks System

### 4.1 Core Data Structures

#### HookEventName Enum

```rust
// source/crates/codegen/xai-grok-hooks/src/event.rs:11-49
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum HookEventName {
    // Session lifecycle
    SessionStart,
    SessionEnd,
    Stop,           // Agent turn ends
    StopFailure,    // Stop caused by API error

    // Tool events
    PreToolUse,     // Before tool call (blocking)
    PostToolUse,    // After tool call
    PostToolUseFailure, // Tool call failed
    PermissionDenied,   // Permission denied

    // User/notification events
    UserPromptSubmit,   // User submitted prompt
    Notification,       // Notification sent

    // Subagent events
    SubagentStart,
    SubagentStop,
    SubagentEnd,    // Alias for SubagentStop

    // Compaction events
    PreCompact,     // Before context compaction
    PostCompact,    // After context compaction
}
```

### 4.2 Event Envelope

```rust
// source/crates/codegen/xai-grok-hooks/src/event.rs:152-172
/// The normalized event envelope sent to hook commands on stdin as JSON.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HookEventEnvelope {
    pub hook_event_name: HookEventName,
    pub session_id: String,
    pub cwd: String,
    pub workspace_root: String,
    pub timestamp: String,
    pub transcript_path: Option<String>,
    pub client_identifier: Option<String>,
    pub prompt_id: Option<String>,
    #[serde(flatten)]
    pub payload: HookPayload,
}
```

### 4.3 Core Dispatch: dispatch_pre_tool_use

```rust
// source/crates/codegen/xai-grok-hooks/src/dispatcher.rs:31-160
/// Dispatch a pre_tool_use event against all matching hooks.
/// Runs hooks sequentially in config order. Only an explicit deny decision
/// stops the chain and blocks the tool call.
/// Hook failures are **fail-open**: the failure is logged and surfaced in
/// results for UI scrollback, but the tool call continues.
pub async fn dispatch_pre_tool_use(
    registry: &HookRegistry,
    envelope: &HookEventEnvelope,
    ctx: &RunContext<'_>,
) -> PreToolUseResult {
    let hooks = registry.hooks_for(HookEventName::PreToolUse);
    if hooks.is_empty() {
        return PreToolUseResult { decision: HookDecision::Allow, results: Vec::new() };
    }

    let mut run_results = Vec::new();

    for spec in hooks {
        // Check if disabled
        if !spec.enabled || crate::trust::is_hook_disabled(&spec.name) {
            run_results.push(HookRunResult::Skipped { hook_name: spec.name.clone() });
            continue;
        }

        // Check matcher
        if let Some(ref matcher) = spec.matcher
            && let Some(ref name) = tool_name
            && !matcher.is_match(name)
        {
            continue;
        }

        // Run hook
        let (result, elapsed, http_info) = runner::run_hook(spec, envelope, ctx, true).await;

        match result {
            HookRunnerResult::Decision(HookDecision::Deny { reason, .. }) => {
                // First deny wins, block tool call
                run_results.push(HookRunResult::Failed { ... });
                return PreToolUseResult {
                    decision: HookDecision::Deny { reason, hook_name: spec.name.clone() },
                    results: run_results,
                };
            }
            HookRunnerResult::Decision(HookDecision::Allow) => {
                run_results.push(HookRunResult::Success { ... });
            }
            HookRunnerResult::Failed(err) => {
                // Fail-open: failure doesn't block tool call
                tracing::warn!("hook failed; ignoring (fail-open)");
                run_results.push(HookRunResult::Failed { ... });
            }
            _ => {}
        }
    }

    PreToolUseResult { decision: HookDecision::Allow, results: run_results }
}
```

### 4.4 Non-Blocking Dispatch

```rust
// source/crates/codegen/xai-grok-hooks/src/dispatcher.rs:167-265
/// Dispatch a non-blocking event (session_start, post_tool_use, session_end)
/// against all matching hooks.
/// Runs hooks sequentially, collects results. Never denies.
pub async fn dispatch_non_blocking(
    registry: &HookRegistry,
    event: HookEventName,
    envelope: &HookEventEnvelope,
    ctx: &RunContext<'_>,
) -> Vec<HookRunResult> {
    let hooks = registry.hooks_for(event);
    if hooks.is_empty() {
        return Vec::new();
    }

    let mut results = Vec::with_capacity(hooks.len());

    for spec in hooks {
        // ... check disabled and matcher ...

        let (result, elapsed, http_info) = runner::run_hook(spec, envelope, ctx, false).await;

        match result {
            HookRunnerResult::Success => {
                results.push(HookRunResult::Success { ... });
            }
            HookRunnerResult::Failed(err) => {
                // Non-blocking: failure doesn't stop chain
                results.push(HookRunResult::Failed { ... });
            }
            HookRunnerResult::Decision(_) => {
                // Non-blocking events shouldn't return decisions
                results.push(HookRunResult::Success { ... });
            }
        }
    }

    results
}
```

### 4.5 Hooks System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Hooks Execution Architecture                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐     ┌─────────────────┐                   │
│  │  HookRegistry   │────▶│  HookEventName  │                   │
│  │  (hook specs)   │     │  (event types)  │                   │
│  └────────┬────────┘     └─────────────────┘                   │
│           │                                                     │
│           ▼                                                     │
│  ┌────────────────────────────────────────┐                    │
│  │         Dispatcher                     │                    │
│  │  ┌──────────────────────────────────┐  │                    │
│  │  │  dispatch_pre_tool_use          │  │  // blocking       │
│  │  │  (return decision)              │  │                    │
│  │  └──────────────────────────────────┘  │                    │
│  │  ┌──────────────────────────────────┐  │                    │
│  │  │  dispatch_non_blocking          │  │  // non-blocking   │
│  │  │  (return results)               │  │                    │
│  │  └──────────────────────────────────┘  │                    │
│  └────────────────┬───────────────────────┘                    │
│                   │                                              │
│                   ▼                                              │
│  ┌────────────────────────────────────────┐                    │
│  │           HookRunner                   │                    │
│  │  ┌─────────────┐  ┌─────────────────┐  │                    │
│  │  │ CommandRunner│  │ HttpRunner      │  │                    │
│  │  │ (subprocess)│  │ (HTTP request)  │  │                    │
│  │  └─────────────┘  └─────────────────┘  │                    │
│  └────────────────┬───────────────────────┘                    │
│                   │                                              │
│                   ▼                                              │
│  ┌────────────────────────────────────────┐                    │
│  │         HookDecision                    │                    │
│  │   Allow / Deny { reason, hook_name }   │                    │
│  └────────────────────────────────────────┘                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.6 Blocking Semantics

```rust
// source/crates/codegen/xai-grok-hooks/src/event.rs:138-141
impl HookEventName {
    /// Returns true if this event type uses blocking (deny/allow) semantics.
    pub fn is_blocking(&self) -> bool {
        matches!(self, Self::PreToolUse)
    }

    /// Events that don't support matcher patterns.
    pub fn is_lifecycle(&self) -> bool {
        matches!(self, Self::SessionStart | Self::SessionEnd | Self::Stop | Self::UserPromptSubmit)
    }
}
```

### 4.7 Fail-Open Strategy

```rust
// source/crates/codegen/xai-grok-hooks/src/dispatcher.rs:16-30
/// Hook failures (timeouts, crashes, command-not-found, env-var
/// pre-spawn refusals, malformed output) are **fail-open**:
/// the failure is logged and surfaced in the per-hook results for 
/// the UI scrollback, but the tool call continues as if the hook 
/// had allowed it.
/// 
/// Grok runs in protected environments where induced-failure bypass 
/// of security hooks is not part of the threat model; the previous
/// fail-closed posture over-blocked innocent tool calls when hooks
/// timed out or had unrelated configuration errors.
```

---

## 5. Exercises

### Exercise 1: Implement Custom Skill Discoverer

**Task**: Extend the Skills system to load skills from a database.

**Hints**:
- Reference the structure of `list_skills_with_plugins`
- Consider using `SkillInfo::config_source` to mark database-sourced skills
- Implement deduplication logic for same-name skills

**Acceptance Criteria**:
- Skills can be discovered and injected into system prompts
- Same-name skills correctly handle priority

### Exercise 2: Implement Custom Plugin Discovery Source

**Task**: Add support for loading plugins from a remote URL.

**Hints**:
- Reference the discovery flow in `discover_plugins`
- Implement path validation and trust checks
- Consider incremental update mechanisms

**Acceptance Criteria**:
- Remote plugins can be correctly discovered and loaded
- Security checks (path escape, trust evaluation) work correctly

### Exercise 3: Implement Hook Filtering Rules

**Task**: Add condition-based filtering for Hooks.

**Hints**:
- Reference the matcher check logic in `dispatch_pre_tool_use`
- Support multi-condition combinations (AND/OR)
- Consider performance impact

**Acceptance Criteria**:
- Hooks are correctly skipped when conditions don't match
- Filter decisions are logged

### Exercise 4: Analyze Name Collision Scenarios

**Task**: Analyze and resolve the following collision scenarios.

**Scenario A**: Two same-name skills in the same scope
- Location 1: `~/.grok/skills/deploy/SKILL.md` (name: deploy)
- Location 2: `~/.grok/skills/deploy-v2/SKILL.md` (name: deploy)

**Scenario B**: Same-name skills in different scopes
- Location 1: `~/.grok/skills/git/SKILL.md` (User scope)
- Location 2: `repo/.grok/skills/git/SKILL.md` (Repo scope)

**Scenario C**: Plugin skill and local skill with same name
- Local: `~/.grok/skills/lint/SKILL.md`
- Plugin: `my-linter/skills/lint/SKILL.md`

### Exercise 5: Extend Hook Payload

**Task**: Add a new payload field to `PreToolUse`.

**Hints**:
- Modify `HookPayload::PreToolUse` variant
- Update serialization format
- Add test cases

**Acceptance Criteria**:
- New field is correctly serialized and deserialized
- Backward compatibility is maintained

---

## Summary

In this chapter, we thoroughly analyzed Grok Build's three major extension systems:

| System | Core Mechanism | Key Features |
|--------|----------------|--------------|
| **Skills** | Priority-driven multi-source discovery | Scope model, name deduplication, front-matter parsing |
| **Plugins** | Layered scope discovery | Trust model, path validation, name conflict resolution |
| **Hooks** | Event-driven lifecycle hooks | Blocking/non-blocking semantics, fail-open strategy, matcher filtering |

These three systems together form Grok Build's extension ecosystem, enabling users to deeply customize agent behavior through skills, plugins, and hooks.

---

## Source Code Index

| File | Line Numbers | Content |
|------|-------------|---------|
| `xai-grok-agent/src/prompt/skills.rs` | 64-136 | `list_skills` main function |
| `xai-grok-agent/src/prompt/skills.rs` | 79-136 | `list_skills_with_plugins` |
| `xai-grok-agent/src/prompt/skills.rs` | 424-502 | `dedupe_skills` deduplication logic |
| `xai-grok-agent/src/prompt/skills.rs` | 565-598 | `collect_plugin_skills` |
| `xai-grok-agent/src/plugins/discovery.rs` | 27-37 | `PluginScope` enum |
| `xai-grok-agent/src/plugins/discovery.rs` | 102-123 | `PluginId` struct |
| `xai-grok-agent/src/plugins/discovery.rs` | 132-161 | `DiscoveredPlugin` struct |
| `xai-grok-agent/src/plugins/discovery.rs` | 274-486 | `discover_plugins` main function |
| `xai-grok-agent/src/plugins/discovery.rs` | 732-794 | `resolve_name_conflicts` |
| `xai-grok-agent/src/plugins/manifest.rs` | 125-130 | `PathOrInline` enum |
| `xai-grok-agent/src/plugins/manifest.rs` | 132-170 | `PluginManifest` struct |
| `xai-grok-agent/src/plugins/manifest.rs` | 292-333 | `load_manifest` function |
| `xai-grok-hooks/src/event.rs` | 11-49 | `HookEventName` enum |
| `xai-grok-hooks/src/event.rs` | 152-172 | `HookEventEnvelope` struct |
| `xai-grok-hooks/src/dispatcher.rs` | 31-160 | `dispatch_pre_tool_use` |
| `xai-grok-hooks/src/dispatcher.rs` | 167-265 | `dispatch_non_blocking` |
| `xai-grok-hooks/src/lib.rs` | 1-51 | Module documentation and overview |

---

*[Previous: Context Compaction System](../05-context-compaction/README.md)* | *[Next: Sandbox and Security Isolation](../07-sandbox-security/README.md)*