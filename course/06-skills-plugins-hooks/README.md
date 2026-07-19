# 第六章：Skills、Plugins、Hooks 扩展系统
# Chapter 6: Skills, Plugins, and Hooks Extension System

---

## 本章目标 / Learning Objectives

通过本章学习，你将掌握：

1. **Skills 系统**：了解 Grok 如何从多个来源发现、优先级排序和注入技能
2. **Plugin 系统**：理解插件的发现机制、作用域模型和信任体系
3. **Plugin Manifest**：掌握插件清单文件的解析和组件路径解析
4. **Hooks 系统**：理解生命周期钩子的注册、分发和执行机制

By the end of this chapter, you will understand:

1. **Skills System**: How Grok discovers, prioritizes, and injects skills from multiple sources
2. **Plugin System**: The plugin discovery mechanism, scope model, and trust architecture
3. **Plugin Manifest**: Parsing plugin manifest files and resolving component paths
4. **Hooks System**: Lifecycle hook registration, dispatch, and execution mechanisms

---

## 一、Skills 系统 / Skills System

### 1.1 核心数据结构 / Core Data Structures

Skills 的核心类型定义在 `xai-grok-tools` crate 中，通过 re-export 在 agent 中使用：

```rust
// source/crates/codegen/xai-grok-agent/src/prompt/skills.rs:12
pub use xai_grok_tools::implementations::skills::types::{SkillInfo, SkillScope};
```

#### SkillInfo 结构体 / SkillInfo Structure

```rust
// source/crates/codegen/xai-grok-tools/src/implementations/skills/types.rs
#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
pub struct SkillInfo {
    pub name: String,                          // 技能名称
    pub display_name: Option<String>,          // 显示名称
    pub description: String,                   // 描述
    pub when_to_use: Option<String>,           // 使用时机
    pub short_description: Option<String>,     // 短描述
    pub author: Option<String>,                // 作者
    pub argument_hint: Option<String>,         // 参数提示
    
    pub path: String,                          // SKILL.md 文件路径
    pub scope: SkillScope,                     // 作用域
    pub config_source: Option<ConfigSource>,   // 配置来源
    
    // Plugin 关联字段
    pub plugin_name: Option<String>,           // 插件名称
    pub plugin_version: Option<String>,        // 插件版本
    pub plugin_root: Option<String>,           // 插件根目录
    pub plugin_data: Option<String>,           // 插件数据目录
    
    // 工具与许可
    pub allowed_tools: Option<Vec<String>>,    // 允许的工具
    pub license: Option<String>,               // 许可证
    pub compatibility: Option<String>,         // 兼容性
    
    pub model: Option<String>,                 // 推荐模型
    pub effort: Option<String>,                // 预期工作量
    pub user_invocable: bool,                  // 可用户调用
    pub disable_model_invocation: bool,        // 禁用模型调用
    
    pub paths: Option<Vec<String>>,            // 嵌套路径
    pub enabled: bool,                         // 是否启用
    pub body: Option<String>,                  // 技能正文内容
}
```

#### SkillScope 枚举 / SkillScope Enum

```rust
// source/crates/codegen/xai-grok-tools/src/implementations/skills/types.rs
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SkillScope {
    /// 本地技能：位于 cwd/.grok/skills/
    Local = 0,
    /// Repo 技能：位于 repo_root/.grok/skills/
    Repo = 1,
    /// 用户技能：位于 ~/.grok/skills/
    User = 2,
    /// Server 技能：服务端同步的技能
    Server = 3,
    /// Bundled 技能：内置技能
    Bundled = 4,
    /// Plugin 技能：来自插件
    Plugin = 5,
}
```

### 1.2 核心实现：list_skills 函数 / Core Implementation: list_skills Function

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

#### 带插件支持的技能列表 / Skills List with Plugin Support

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

    // 1. 从本地、repo、用户目录收集技能
    let mut skills = list_skills_with_options(
        working_directory,
        workspace_user_dir.as_deref(),
        &xai_grok_tools::util::grok_home::grok_home(),
        compat,
    ).await;

    // 2. 解析 git root 用于路径判断
    let git_root = working_directory.and_then(|wd| {
        git2::Repository::discover(wd)
            .ok()
            .and_then(|repo| repo.workdir().map(|p| p.to_path_buf()))
    });

    // 3. 收集配置中指定的技能路径
    skills.extend(collect_config_skills(&config.paths, git_root.as_deref()));

    // 4. 收集注入的 Server 和 Bundled 技能
    skills.extend(collect_injected_skills(&config.server_skill_dirs, SkillScope::Server));
    skills.extend(collect_injected_skills(&config.bundled_skill_dirs, SkillScope::Bundled));

    // 5. 应用 ignore 过滤器并排序
    let mut skills = filter_skills(skills, &config.ignore);
    skills.sort_by_key(|s| s.scope);

    // 6. 收集并合并插件技能
    let plugin_skills = if let Some(registry) = plugins {
        collect_plugin_skills(registry)
    } else {
        vec![]
    };
    let mut merged = merge_skills_with_plugins(skills, plugin_skills);

    // 7. 标记禁用技能
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

### 1.3 优先级与去重 / Priority and Deduplication

#### 优先级顺序 / Priority Order

```
Local (最高) → Repo → User → Config Paths → Server → Bundled (最低)
```

#### 去重逻辑 / Deduplication Logic

```rust
// source/crates/codegen/xai-grok-agent/src/prompt/skills.rs:424-502
fn dedupe_skills(skills: Vec<SkillInfo>) -> Vec<SkillInfo> {
    let mut seen_paths: HashMap<PathBuf, usize> = HashMap::new();
    let mut seen_names: HashMap<String, (SkillScope, usize)> = HashMap::new();
    let mut deduped: Vec<SkillInfo> = Vec::with_capacity(skills.len());

    for mut skill in skills {
        let canonical_path = dunce::canonicalize(&skill.path)
            .unwrap_or_else(|_| PathBuf::from(&skill.path));

        // 路径去重：同一文件多个来源
        if let Some(&kept_idx) = seen_paths.get(&canonical_path) {
            // 保留已有条目，从重复条目继承 config_source
            let kept = &mut deduped[kept_idx];
            if kept.config_source.is_none() && skill.config_source.is_some() {
                kept.config_source = skill.config_source;
            }
            continue;
        }

        // 名称去重：更高优先级的来源获胜
        if let Some(&(winner_scope, winner_idx)) = seen_names.get(&skill.name) {
            // 同作用域的同名技能：重新键名为目录名
            if winner_scope == skill.scope
                && !matches!(skill.scope, SkillScope::Server | SkillScope::Bundled) 
            {
                if rekey_to_dir_basename(&mut skill, &mut seen_names, deduped.len()) {
                    // 重新键名成功，添加
                    seen_paths.insert(canonical_path, deduped.len());
                    deduped.push(skill);
                    continue;
                }
                // ...更多处理逻辑
            }
            continue; // 被同名技能遮蔽
        }

        seen_names.insert(skill.name.clone(), (skill.scope, deduped.len()));
        seen_paths.insert(canonical_path, deduped.len());
        deduped.push(skill);
    }

    deduped
}
```

### 1.4 插件技能收集 / Plugin Skills Collection

```rust
// source/crates/codegen/xai-grok-agent/src/prompt/skills.rs:565-598
fn collect_plugin_skills(registry: &crate::plugins::PluginRegistry) -> Vec<SkillInfo> {
    let mut skills = Vec::new();

    for plugin in registry.enabled_plugins() {
        let mut paths: Vec<(PathBuf, SkillScope)> = Vec::new();

        // 从插件 skill_dirs 收集
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

        // 从插件 command_dirs 收集（.md 文件）
        for cmd_dir in &plugin.command_dirs {
            paths.extend(
                scan_md_files(cmd_dir)
                    .into_iter()
                    .map(|p| (p, SkillScope::Repo)),
            );
        }

        let mut parsed = parse_skill_files(paths);
        stamp_plugin_fields(&mut parsed, plugin); // 注入插件元数据
        skills.extend(parsed);
    }

    skills
}
```

### 1.5 技能配置 / Skills Configuration

```rust
// source/crates/codegen/xai-grok-agent/src/prompt/skills.rs:22-47
#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
pub struct SkillsConfig {
    /// 额外技能位置
    pub paths: Vec<String>,
    
    /// 排除的路径前缀
    pub ignore: Vec<String>,
    
    /// 禁用的技能名称
    pub disabled: Vec<String>,
    
    /// 服务端同步的技能目录
    pub server_skill_dirs: Vec<String>,
    
    /// 内置技能目录
    pub bundled_skill_dirs: Vec<String>,
}
```

---

## 二、Plugin 系统 / Plugin System

### 2.1 核心数据结构 / Core Data Structures

#### PluginScope 枚举 / PluginScope Enum

```rust
// source/crates/codegen/xai-grok-agent/src/plugins/discovery.rs:27-37
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PluginScope {
    /// CLI --plugin-dir（最高优先级，始终受信任）
    CliOverride = 0,
    /// 项目插件：.grok/plugins/ 或 .claude/plugins/
    Project = 1,
    /// 用户插件：~/.grok/plugins/ 或 ~/.claude/plugins/
    User = 2,
    /// 配置路径：[plugins].paths
    ConfigPath = 3,
}
```

#### DiscoveredPlugin 结构体 / DiscoveredPlugin Structure

```rust
// source/crates/codegen/xai-grok-agent/src/plugins/discovery.rs:132-161
#[derive(Debug, Clone)]
pub struct DiscoveredPlugin {
    /// 解析的清单（惯例插件为合成的）
    pub manifest: PluginManifest,
    
    /// 稳定内部标识
    pub id: PluginId,
    
    /// 插件根目录绝对路径
    pub root: PathBuf,
    
    /// 规范化的根路径（解析符号链接）
    pub canonical_root: PathBuf,
    
    /// 发现来源的作用域
    pub scope: PluginScope,
    
    /// 具体发现来源
    pub origin: PluginOrigin,
    
    /// 是否受信任（可执行操作）
    pub trusted: bool,
    
    /// 解析的技能目录
    pub skill_dirs: Vec<PathBuf>,
    pub command_dirs: Vec<PathBuf>,
    
    /// 解析的智能体目录
    pub agent_dirs: Vec<PathBuf>,
    
    /// 解析的 hooks 文件路径
    pub hooks_path: Option<PathBuf>,
    
    /// 解析的 MCP 配置文件路径
    pub mcp_config_path: Option<PathBuf>,
    
    /// 解析的 LSP 配置文件路径
    pub lsp_config_path: Option<PathBuf>,
    
    /// 名称冲突警告信息
    pub conflict: Option<String>,
}
```

#### PluginId 结构体 / PluginId Structure

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

### 2.2 核心实现：discover_plugins 函数 / Core Implementation: discover_plugins Function

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

    // 1. CLI --plugin-dir paths (最高优先级)
    for dir in &config.cli_plugin_dirs {
        if dir.is_dir() {
            collect_plugin(dir, PluginScope::CliOverride, ...);
        }
    }

    // 2-3. 项目插件 (.grok/plugins/, .claude/plugins/)
    if let Some(cwd) = cwd {
        let (project_dirs, git_root) = project_plugin_dirs(Some(cwd));
        for plugins_dir in project_dirs {
            scan_plugin_dir(&plugins_dir, PluginScope::Project, ...);
        }
    }

    // 4-5. 用户插件: $GROK_HOME/plugins, ~/.claude/plugins
    let grok = xai_grok_config::user_grok_home();
    let plugin_dirs = user_plugin_dirs(dirs::home_dir().as_deref(), grok.as_deref());
    for (plugins_dir, origin) in plugin_dirs {
        if plugins_dir.is_dir() {
            scan_plugin_dir(&plugins_dir, PluginScope::User, ...);
        }
    }

    // 6. 配置路径插件
    for dir in &config.config_paths {
        if dir.is_dir() {
            collect_plugin(dir, PluginScope::ConfigPath, ...);
        }
    }

    // 解决名称冲突：同名称时，高优先级作用域获胜
    resolve_name_conflicts(&mut candidates);

    candidates
}
```

### 2.3 插件发现流程 / Plugin Discovery Flow

```
发现优先级 (高 → 低):
┌──────────────────────────────────────────────────────────────┐
│ 1. CLI --plugin-dir 路径 (CliOverride)                       │
│    - 始终受信任                                              │
│    - 最高优先级                                              │
├──────────────────────────────────────────────────────────────┤
│ 2. 项目插件 (Project)                                        │
│    - .grok/plugins/<name>/                                  │
│    - .claude/plugins/<name>/                                │
│    - 需要 folder-trust 授权                                  │
├──────────────────────────────────────────────────────────────┤
│ 3. 市场插件 (Marketplace)                                    │
│    - 从已知市场解析                                          │
│    - User 作用域                                             │
├──────────────────────────────────────────────────────────────┤
│ 4. 用户插件 (User)                                           │
│    - ~/.grok/plugins/<name>/                                │
│    - 始终受信任                                              │
├──────────────────────────────────────────────────────────────┤
│ 5. 已安装插件 (Installed)                                    │
│    - 从安装注册表加载                                        │
│    - User 作用域                                             │
├──────────────────────────────────────────────────────────────┤
│ 6. 配置路径 (ConfigPath)                                     │
│    - [plugins].paths 配置                                    │
│    - 信任取决于位置                                          │
└──────────────────────────────────────────────────────────────┘
```

### 2.4 名称冲突解决 / Name Conflict Resolution

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
                    // 新候选者获胜
                    to_remove.push(existing_idx);
                    name_map.insert(name, idx);
                } else {
                    // 现有者获胜
                    to_remove.push(idx);
                }
            }
            None => {
                name_map.insert(name, idx);
            }
        }
    }

    // 移除失败者
    to_remove.sort_unstable();
    to_remove.dedup();
    for idx in to_remove.into_iter().rev() {
        candidates.remove(idx);
    }
}
```

### 2.5 信任模型 / Trust Model

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

## 三、Plugin Manifest / Plugin Manifest

### 3.1 核心数据结构 / Core Data Structures

#### PathOrInline 枚举 / PathOrInline Enum

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

#### PluginManifest 结构体 / PluginManifest Structure

```rust
// source/crates/codegen/xai-grok-agent/src/plugins/manifest.rs:132-170
/// Parsed plugin manifest from plugin.json.
/// Forward-compatible: unknown fields are silently ignored.
#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PluginManifest {
    // 基本信息
    pub name: String,                         // 必需：插件命名空间（kebab-case）
    pub version: Option<String>,              // Semver 版本
    pub description: Option<String>,
    pub author: Option<Author>,
    pub homepage: Option<String>,
    pub repository: Option<String>,
    pub license: Option<String>,
    pub keywords: Vec<String>,

    // 组件路径覆盖
    pub skills: Option<PathOrPaths>,
    pub commands: Option<PathOrPaths>,
    pub agents: Option<PathOrPaths>,
    pub hooks: Option<PathOrInline>,
    pub mcp_servers: Option<PathOrInline>,
    pub lsp_servers: Option<PathOrInline>,
}
```

### 3.2 清单加载 / Manifest Loading

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

### 3.3 组件路径解析 / Component Path Resolution

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
            // 路径逃逸检查
            if !is_path_contained(&resolved, plugin_root) {
                tracing::warn!("{label} path escapes plugin root; skipping");
                return None;
            }
            resolved.is_file().then_some(resolved)
        }
        Some(PathOrInline::Inline(_)) => None, // 调用方直接读取内联值
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

### 3.4 内联配置支持 / Inline Configuration Support

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

### 3.5 清单验证 / Manifest Validation

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

## 四、Hooks 系统 / Hooks System

### 4.1 核心数据结构 / Core Data Structures

#### HookEventName 枚举 / HookEventName Enum

```rust
// source/crates/codegen/xai-grok-hooks/src/event.rs:11-49
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum HookEventName {
    // 会话生命周期
    SessionStart,
    SessionEnd,
    Stop,           // Agent turn 结束
    StopFailure,    // API 错误导致的停止

    // 工具事件
    PreToolUse,     // 工具调用前（阻塞）
    PostToolUse,    // 工具调用后
    PostToolUseFailure, // 工具调用失败
    PermissionDenied,   // 权限被拒绝

    // 用户/通知事件
    UserPromptSubmit,   // 用户提交提示词
    Notification,       // 通知发送

    // 子智能体事件
    SubagentStart,
    SubagentStop,
    SubagentEnd,    // SubagentStop 的别名

    // 压缩事件
    PreCompact,     // 上下文压缩前
    PostCompact,    // 上下文压缩后
}
```

### 4.2 事件信封 / Event Envelope

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

### 4.3 核心分发：dispatch_pre_tool_use / Core Dispatch: dispatch_pre_tool_use

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
        // 检查是否禁用
        if !spec.enabled || crate::trust::is_hook_disabled(&spec.name) {
            run_results.push(HookRunResult::Skipped { hook_name: spec.name.clone() });
            continue;
        }

        // 检查 matcher
        if let Some(ref matcher) = spec.matcher
            && let Some(ref name) = tool_name
            && !matcher.is_match(name)
        {
            continue;
        }

        // 运行 hook
        let (result, elapsed, http_info) = runner::run_hook(spec, envelope, ctx, true).await;

        match result {
            HookRunnerResult::Decision(HookDecision::Deny { reason, .. }) => {
                // 第一个 deny 获胜，阻止工具调用
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
                // Fail-open: 失败不阻止工具调用
                tracing::warn!("hook failed; ignoring (fail-open)");
                run_results.push(HookRunResult::Failed { ... });
            }
            _ => {}
        }
    }

    PreToolUseResult { decision: HookDecision::Allow, results: run_results }
}
```

### 4.4 非阻塞分发 / Non-Blocking Dispatch

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
        // ... 检查禁用和 matcher ...

        let (result, elapsed, http_info) = runner::run_hook(spec, envelope, ctx, false).await;

        match result {
            HookRunnerResult::Success => {
                results.push(HookRunResult::Success { ... });
            }
            HookRunnerResult::Failed(err) => {
                // 非阻塞事件：失败不停止链
                results.push(HookRunResult::Failed { ... });
            }
            HookRunnerResult::Decision(_) => {
                // 非阻塞事件不应返回决策
                results.push(HookRunResult::Success { ... });
            }
        }
    }

    results
}
```

### 4.5 Hooks 系统架构 / Hooks System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Hooks 执行架构                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐     ┌─────────────────┐                   │
│  │  HookRegistry   │────▶│  HookEventName  │                   │
│  │  (hook specs)   │     │  (事件类型)      │                   │
│  └────────┬────────┘     └─────────────────┘                   │
│           │                                                     │
│           ▼                                                     │
│  ┌────────────────────────────────────────┐                    │
│  │         Dispatcher                     │                    │
│  │  ┌──────────────────────────────────┐  │                    │
│  │  │  dispatch_pre_tool_use          │  │  // 阻塞           │
│  │  │  (return decision)              │  │                    │
│  │  └──────────────────────────────────┘  │                    │
│  │  ┌──────────────────────────────────┐  │                    │
│  │  │  dispatch_non_blocking          │  │  // 非阻塞         │
│  │  │  (return results)               │  │                    │
│  │  └──────────────────────────────────┘  │                    │
│  └────────────────┬───────────────────────┘                    │
│                   │                                              │
│                   ▼                                              │
│  ┌────────────────────────────────────────┐                    │
│  │           HookRunner                   │                    │
│  │  ┌─────────────┐  ┌─────────────────┐  │                    │
│  │  │ CommandRunner│  │ HttpRunner      │  │                    │
│  │  │ (子进程执行) │  │ (HTTP 请求)     │  │                    │
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

### 4.6 阻塞语义 / Blocking Semantics

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

### 4.7 Fail-Open 策略 / Fail-Open Strategy

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

## 五、Python 对照 / Python Comparison

### 5.1 Skills 系统对比 / Skills System Comparison

```python
# Python (LangChain Agent 风格)
class Skill:
    def __init__(self, name: str, description: str, 
                 tools: List[str] = None, prompt: str = ""):
        self.name = name
        self.description = description
        self.tools = tools or []
        self.prompt = prompt

class SkillRegistry:
    def __init__(self):
        self._skills: Dict[str, Skill] = {}
    
    def register(self, skill: Skill):
        self._skills[skill.name] = skill
    
    def list_skills(self, scope: str = "all") -> List[Skill]:
        if scope == "all":
            return list(self._skills.values())
        return [s for s in self._skills.values() if s.scope == scope]

# Rust 实现的关键区别：
# 1. 优先级通过 SkillScope 枚举实现
# 2. 路径规范化和符号链接解析
# 3. 前端-matter 解析和正文截断
# 4. 同名冲突通过目录名重新键名解决
```

### 5.2 Plugin 系统对比 / Plugin System Comparison

```python
# Python (简易插件系统)
import importlib.util
from pathlib import Path
from typing import Protocol, List

class Plugin(Protocol):
    name: str
    version: str
    def initialize(self, app): ...

class PluginManager:
    def __init__(self, plugin_dirs: List[Path]):
        self._plugins: Dict[str, Plugin] = {}
        self.discover_plugins(plugin_dirs)
    
    def discover_plugins(self, dirs: List[Path]):
        for dir in dirs:
            for plugin_dir in dir.iterdir():
                manifest = self._load_manifest(plugin_dir)
                if self._validate_manifest(manifest):
                    plugin = self._load_plugin(plugin_dir, manifest)
                    self._plugins[manifest['name']] = plugin

# Rust 实现的关键区别：
# 1. PluginScope 枚举管理发现优先级
# 2. SHA-256 哈希生成稳定 PluginId
# 3. 路径逃逸检查防止安全风险
# 4. 名称冲突通过作用域优先级解决
```

### 5.3 Hooks 系统对比 / Hooks System Comparison

```python
# Python (FastAPI 生命周期钩子风格)
from enum import Enum
from typing import Callable, List, Optional
import json

class HookEvent(Enum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    SESSION_START = "session_start"
    SESSION_END = "session_end"

class Hook:
    def __init__(self, name: str, event: HookEvent, 
                 handler: Callable, matcher: Optional[str] = None):
        self.name = name
        self.event = event
        self.handler = handler
        self.matcher = matcher  # glob pattern

class HookDispatcher:
    def __init__(self):
        self._hooks: Dict[HookEvent, List[Hook]] = {}
    
    async def dispatch_pre_tool_use(self, tool_name: str, 
                                     tool_input: dict) -> "Decision":
        hooks = self._hooks.get(HookEvent.PRE_TOOL_USE, [])
        for hook in hooks:
            if hook.matcher and not self._matches(hook.matcher, tool_name):
                continue
            result = await hook.handler(tool_name, tool_input)
            if result.decision == "deny":
                return result  # 短路：返回第一个 deny
        return Decision("allow")
    
    async def dispatch_non_blocking(self, event: HookEvent, 
                                     context: dict) -> List["HookResult"]:
        hooks = self._hooks.get(event, [])
        results = []
        for hook in hooks:
            result = await hook.handler(context)
            results.append(result)  # 不短路
        return results

# Rust 实现的关键区别：
# 1. 严格的类型系统（HookEventName 枚举 + HookPayload 联合类型）
# 2. JSON 信封通过 serde 序列化
# 3. Fail-open 策略而非 fail-closed
# 4. 命令执行通过子进程而非直接函数调用
# 5. HTTP hook 支持（扩展性）
```

---

## 六、练习 / Exercises

### 练习 1：实现自定义 Skill 发现器 / Exercise 1: Implement Custom Skill Discoverer

**任务**：扩展 Skills 系统，支持从数据库加载技能。

**提示**：
- 参考 `list_skills_with_plugins` 的结构
- 考虑使用 `SkillInfo::config_source` 标记数据库来源
- 实现去重逻辑处理同名技能

**验收标准**：
- 技能可以被发现并注入到系统提示词
- 同名技能正确处理优先级

### 练习 2：实现自定义 Plugin 发现源 / Exercise 2: Implement Custom Plugin Discovery Source

**任务**：添加从远程 URL 加载插件的支持。

**提示**：
- 参考 `discover_plugins` 的发现流程
- 实现路径验证和信任检查
- 考虑增量更新机制

**验收标准**：
- 远程插件可以被正确发现和加载
- 安全检查（路径逃逸、信任评估）正常工作

### 练习 3：实现 Hook 过滤规则 / Exercise 3: Implement Hook Filtering Rules

**任务**：为 Hook 添加基于条件的过滤功能。

**提示**：
- 参考 `dispatch_pre_tool_use` 的 matcher 检查逻辑
- 支持多条件组合（AND/OR）
- 考虑性能影响

**验收标准**：
- 条件不匹配时 hook 被正确跳过
- 日志记录过滤决策

### 练习 4：分析名称冲突场景 / Exercise 4: Analyze Name Collision Scenarios

**任务**：分析并解决以下冲突场景。

**场景 A**：同一作用域有两个同名技能
- 位置 1: `~/.grok/skills/deploy/SKILL.md` (name: deploy)
- 位置 2: `~/.grok/skills/deploy-v2/SKILL.md` (name: deploy)

**场景 B**：不同作用域有同名技能
- 位置 1: `~/.grok/skills/git/SKILL.md` (User scope)
- 位置 2: `repo/.grok/skills/git/SKILL.md` (Repo scope)

**场景 C**：插件技能与本地技能同名
- 本地: `~/.grok/skills/lint/SKILL.md`
- 插件: `my-linter/skills/lint/SKILL.md`

### 练习 5：扩展 Hook Payload / Exercise 5: Extend Hook Payload

**任务**：为 `PreToolUse` 添加新的 payload 字段。

**提示**：
- 修改 `HookPayload::PreToolUse` 变体
- 更新序列化格式
- 添加测试用例

**验收标准**：
- 新字段被正确序列化和反序列化
- 向后兼容性保持

---

## 总结 / Summary

本章我们深入分析了 Grok Build 的三大扩展系统：

| 系统 | 核心机制 | 关键特性 |
|------|----------|----------|
| **Skills** | 优先级驱动的多源发现 | 作用域模型、名称去重、前端-matter 解析 |
| **Plugins** | 分层作用域发现 | 信任模型、路径验证、名称冲突解决 |
| **Hooks** | 事件驱动的生命周期钩子 | 阻塞/非阻塞语义、Fail-open 策略、Matcher 过滤 |

这三个系统共同构成了 Grok Build 的扩展生态，使得用户可以通过技能、插件和钩子来深度定制 Agent 的行为。

---

## 源码索引 / Source Code Index

| 文件 | 行号 | 内容 |
|------|------|------|
| `xai-grok-agent/src/prompt/skills.rs` | 64-136 | `list_skills` 主函数 |
| `xai-grok-agent/src/prompt/skills.rs` | 79-136 | `list_skills_with_plugins` |
| `xai-grok-agent/src/prompt/skills.rs` | 424-502 | `dedupe_skills` 去重逻辑 |
| `xai-grok-agent/src/prompt/skills.rs` | 565-598 | `collect_plugin_skills` |
| `xai-grok-agent/src/plugins/discovery.rs` | 27-37 | `PluginScope` 枚举 |
| `xai-grok-agent/src/plugins/discovery.rs` | 102-123 | `PluginId` 结构体 |
| `xai-grok-agent/src/plugins/discovery.rs` | 132-161 | `DiscoveredPlugin` 结构体 |
| `xai-grok-agent/src/plugins/discovery.rs` | 274-486 | `discover_plugins` 主函数 |
| `xai-grok-agent/src/plugins/discovery.rs` | 732-794 | `resolve_name_conflicts` |
| `xai-grok-agent/src/plugins/manifest.rs` | 125-130 | `PathOrInline` 枚举 |
| `xai-grok-agent/src/plugins/manifest.rs` | 132-170 | `PluginManifest` 结构体 |
| `xai-grok-agent/src/plugins/manifest.rs` | 292-333 | `load_manifest` 函数 |
| `xai-grok-hooks/src/event.rs` | 11-49 | `HookEventName` 枚举 |
| `xai-grok-hooks/src/event.rs` | 152-172 | `HookEventEnvelope` 结构体 |
| `xai-grok-hooks/src/dispatcher.rs` | 31-160 | `dispatch_pre_tool_use` |
| `xai-grok-hooks/src/dispatcher.rs` | 167-265 | `dispatch_non_blocking` |
| `xai-grok-hooks/src/lib.rs` | 1-51 | 模块文档和概览 |

---

*[上一章：上下文压缩系统](../05-context-compaction/README.md)* | *[下一章：沙箱与安全隔离](../07-sandbox-security/README.md)*

*[Previous: Context Compaction System](../05-context-compaction/README.md)* | *[Next: Sandbox and Security Isolation](../07-sandbox-security/README.md)*