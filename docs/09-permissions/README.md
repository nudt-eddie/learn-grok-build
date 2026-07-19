# 权限和沙箱机制

本文档分析 Grok Build 的权限模型、沙箱隔离、文件访问控制及信任等级设计。

## 1. 权限模型

### 1.1 CapabilityMode 能力模式

系统定义了四种能力模式，形成偏序关系 (`is_subset_of`)：

```rust
pub enum CapabilityMode {
    ReadOnly,   // 只读：搜索、读取、列表
    ReadWrite,  // 读写：+ 编辑、写入、删除、移动
    Execute,    // 执行：+ Shell/后台任务
    All,        // 全部权限
}
```

**权限层级关系：**
- `ReadOnly` ⊆ `ReadWrite`，`ReadOnly` ⊆ `Execute`
- `ReadWrite` 与 `Execute` 不可比较（互不包含）
- `fork_session` 强制子会话能力 ≤ 父会话能力

### 1.2 ToolKind 工具分类

系统支持 27 种工具类型，分为多个类别：

| 类别 | 工具类型 | ReadOnly | ReadWrite | Execute | All |
|------|----------|----------|-----------|---------|-----|
| 元工具 | Plan, AskUser, Skill 等 | ✓ | ✓ | ✓ | ✓ |
| 读取类 | Read, MemoryGet, MemorySearch | ✓ | ✓ | ✓ | ✓ |
| 搜索类 | Search, WebSearch, WebFetch | ✓ | ✓ | ✓ | ✓ |
| 检视类 | Lsp, ListDir, List | ✓ | ✓ | ✓ | ✓ |
| 编辑类 | Edit, Write, Delete, Move, ImageGen 等 | ✗ | ✓ | ✗ | ✓ |
| 执行类 | Execute (Shell) | ✗ | ✗ | ✓ | ✓ |
| 进程控制 | BackgroundTaskAction, Task, Monitor | ✗ | ✗ | ✓ | ✓ |

### 1.3 AccessKind 访问类型

工具调用映射到访问类型：

```rust
pub enum AccessKind {
    Read(Option<String>),           // 文件读取
    Grep { path, glob },            // 内容搜索
    Edit(String),                   // 文件编辑
    Bash(String),                   // Shell 执行
    MCPTool { name, input },        // MCP 工具调用
    WebFetch(String),               // 网页抓取
    WebSearch(String),              // 网络搜索
}
```

### 1.4 权限决策流程

```
ToolCall → AccessKind → Policy Rules → Decision
                                    ├─ Allow
                                    ├─ Ask → User Prompt
                                    ├─ Reject
                                    └─ PolicyDeny
```

**决策类型：**
- `Allow`: 允许执行
- `Ask`: 触发用户交互提示
- `FollowupMessage`: 用户取消时返回的消息
- `Reject`: 用户拒绝
- `PolicyDeny`: 策略规则拒绝
- `Cancelled`: 用户取消整个 Turn

## 2. 沙箱隔离机制

### 2.1 SandboxMode 沙箱模式

```rust
pub enum SandboxMode {
    Invalid,          // 无效
    Agent,            // Agent 模式
    WorkspaceServer,  // 工作区服务器模式
    Bare,             // 裸模式（无沙箱）
}
```

### 2.2 沙箱 API 类型

**沙箱会话管理：**
```rust
pub struct SandboxForkRequest {
    pub source_sandbox_id: String,  // 源沙箱 ID
    pub copies: Option<u32>,        // 副本数量
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

**环境配置：**
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

### 2.3 安全约束

**CWE-284 防护：** 用户提供的 `snapshotBucket` 参数被接受但不转发到后端服务，服务器始终使用配置的默认存储桶。

```rust
// SECURITY: snapshot_bucket from user input must never control GCS access
pub struct SandboxForkRequest {
    pub source_sandbox_id: String,
    #[serde(default)]
    pub snapshot_bucket: Option<String>,  // 忽略，服务器端强制
}
```

## 3. 文件访问控制

### 3.1 文件操作权限

不同文件操作对应不同权限级别：

| 操作 | CapabilityMode | AccessKind |
|------|----------------|------------|
| ReadFile | ReadOnly+ | Read |
| ListDir | ReadOnly+ | Read |
| Grep | ReadOnly+ | Grep |
| SearchReplace | ReadWrite | Edit |
| Write | ReadWrite | Edit |
| Delete | ReadWrite | Edit |
| Move | ReadWrite | Edit |

### 3.2 文件路径上下文

```rust
pub struct EditPathContext {
    pub real_cwd: std::path::PathBuf,        // 实际工作目录
    pub display_cwd: Option<std::path::PathBuf>,  // 显示用工作目录
}
```

### 3.3 WorkspaceOps 双模式

**本地模式 (Local)：** 扩展直接通过 `WorkspaceHandle` 分发，工具调用通过会话的 `FinalizedToolset` 执行。

**代理模式 (Proxy)：** 所有操作通过 Hub WebSocket 路由到远程工作区服务器。

```rust
pub enum WorkspaceOps {
    Local { handle: WorkspaceHandle },
    Proxy { client: WorkspaceClient },
}
```

## 4. 信任等级

### 4.1 TrustStore 文件夹信任

持久化存储：`~/.grok/trusted_folders.toml`

```rust
pub struct FolderTrust {
    pub trusted: bool,        // 是否信任
    pub decided_at: Option<i64>,  // Unix 时间戳
}
```

### 4.2 信任级联规则

**最特定匹配优先：** 多个匹配的文件夹中，路径最深（最长前缀）的记录生效。

**级联行为：**
- 受信任的父文件夹级联信任其所有子目录
- 子文件夹的显式不信任可覆盖父级的信任
- 信任决策持久化到磁盘（0600 权限）

### 4.3 Workspace Key 计算

```
工作区信任 Key 计算流程：
1. 若为 grok 管理的 worktree → 回退到源仓库的 git root
2. 若为 linked git worktree → 使用主 checkout 的 root
3. 否则 → 使用当前工作目录
```

**不安全根目录拒绝：**
- 相对路径
- 文件系统根 (`/`)
- 用户主目录 (`$HOME`)

```rust
pub fn is_unsafe_trust_root(key: &Path) -> bool {
    !key.is_absolute() || key.parent().is_none() || is_home_dir(key)
}
```

### 4.4 持久化安全

- **原子写入：** 使用唯一临时文件 + fsync + rename
- **文件权限：** 0600 (仅所有者读写)
- **跨进程锁：** Advisory lock (`.toml.lock`) 防止并发写入冲突
- **无 home 环境：** 在无法解析用户 home 时，返回空 store，不写入 cwd-relative 文件

## 5. 权限提示与自动模式

### 5.1 PromptOutcome 结果类型

```rust
pub enum PromptOutcome {
    AllowOnce,                    // 允许一次
    AllowAlways,                  // 永久允许
    AllowEditsForSession,         // 会话内允许编辑
    AllowAlwaysBashCommand(String),   // 永久允许特定命令
    AllowAlwaysDomain(String),        // 永久允许特定域名
    AllowAlwaysMcpServer(String),     // 永久允许特定 MCP 服务器
    AllowAlwaysMcpTool(String),       // 永久允许特定 MCP 工具
    RejectOnce,                   // 拒绝一次
    RejectAlwaysBashCommand(String),  // 永久拒绝特定命令
    FollowupMessage(String),      // 返回后续消息
    Cancelled,                    // 已取消
    Error(String),                // 错误
}
```

### 5.2 HITL (Human-in-the-Loop) 实时权限

通过 `GROK_HITL_PERMISSION_LIVE` 环境变量启用：

```rust
pub fn hitl_permission_live_enabled() -> bool {
    match std::env::var("GROK_HITL_PERMISSION_LIVE") {
        Ok(v) => matches!(v.trim().to_ascii_lowercase().as_str(),
                         "1" | "true" | "yes" | "on"),
        Err(_) => false,
    }
}
```

### 5.3 权限请求超时

- **回退超时：** 600 秒（10 分钟）
- **Prometheus 指标：** `grok_workspace_permission_reply_seconds`

## 6. 权限策略配置

### 6.1 PermissionConfig

```rust
pub struct PermissionConfig {
    pub rules: Vec<PermissionRule>,
    pub prompt_policy: PromptPolicy,  // 默认行为
}

pub enum PromptPolicy {
    Ask,   // 提示用户（默认）
    Deny,  // 直接拒绝
    Auto,  // 使用自动分类器
}
```

### 6.2 PermissionRule 规则

```rust
pub struct PermissionRule {
    pub action: RuleAction,   // Allow | Deny | Ask
    pub tool: ToolFilter,     // 工具过滤器
    pub pattern: Option<String>,
    pub pattern_mode: PatternMode,  // Glob | Domain
}

pub enum ToolFilter {
    Any, Bash, Edit, Read, Grep, Mcp, WebFetch, WebSearch
}
```

### 6.3 决策原因 (DecisionReason)

| 原因 | 说明 |
|------|------|
| `yolo` | YOLO 模式自动批准 |
| `policy_allow` | 策略规则允许 |
| `policy_deny` | 策略规则拒绝 |
| `policy_ask` | 策略规则触发提示 |
| `auto_classifier_allow` | 自动分类器允许 |
| `auto_classifier_block` | 自动分类器阻止 |
| `sandbox_auto` | 沙箱自动决策 |
| `persisted_grant` | 持久化授权 |
| `session_grant` | 会话授权 |
| `session_deny` | 会话拒绝 |

## 7. 权限事件遥测

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

## 8. 客户端类型识别

```rust
pub enum ClientType {
    Generic,      // 通用客户端
    GrokTUI,      // TUI 终端界面
    GrokWeb,      // Web 界面
    Nebula,       // Nebula 客户端
    Extension,    // VS Code 扩展
    GrokPager,    // TUI 分页器
    Desktop,      // Electron 桌面客户端
}
```

不同客户端类型会影响：
- 权限 UI 选项展示方式
- Bash 命令高亮和交互选择
- 遥测归因标签