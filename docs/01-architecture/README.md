# Grok Build 总体架构文档

## 项目概述

Grok Build 是 xAI 开发的高性能 AI 代码助手基础设施，采用 Rust 实现，核心设计理念是**模块化代码生成**与**安全沙箱执行**。系统通过 Actor 模型管理对话状态，基于 Tree-sitter 构建代码图索引，支持 Btrfs 快照实现 O(1) 工作树创建，并通过 Agent-Client Protocol (ACP) 实现客户端-服务器双向通信。

### 设计目标

![Architecture](../figures/architecture.mmd)

- **高性能**: 全链路 Rust 实现，避免 GC 停顿，确保低延迟工具调用
- **安全隔离**: Workspace 运行在远程沙箱，通过 capability mode 限制权限
- **可扩展**: 插件系统支持动态注册工具、Agent、Skills
- **可追溯**: Hunk 追踪支持对话 rewind 和快照恢复

---

## 技术栈

### 核心依赖

| 依赖 | 用途 |
|------|------|
| `tokio` | 异步运行时，所有 I/O 操作基于 async/await |
| `tree-sitter` | 多语言代码解析，构建代码图索引 |
| `serde` | 序列化/反序列化（配置、快照、RPC 消息） |
| `minijinja` | 系统提示模板渲染 |
| `git2` | Git 仓库操作 |
| `portable_pty` | 跨平台伪终端控制 |

### 内部 Crate 生态

```
xai-chat-state          对话状态管理（Actor 模式）
xai-agent-lifecycle     Agent 生命周期钩子（Contributor 模式）
xai-codebase-graph      代码图索引与导航
xai-acp-lib             Agent-Client Protocol 通信框架
xai-fast-worktree       快速 Git 工作树（Btrfs 快照）
xai-crash-handler       跨平台崩溃捕获
xai-grok-agent          Agent 构建与发现
xai-grok-tools          工具注册与调度
xai-grok-workspace      远程沙箱 Workspace ToolServer
ptyctl                  PTY 控制服务
```

---

## Crate 架构地图

![Architecture](../figures/architecture.mmd)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            Grok Build 架构                               │
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
│  │                       codegen (核心库)                           │   │
│  │  ┌───────────────┐  ┌──────────────────┐  ┌────────────────┐    │   │
│  │  │ xai-chat-state│  │ xai-agent-       │  │ xai-codebase-  │    │   │
│  │  │ (Actor模式)   │  │ lifecycle        │  │ graph          │    │   │
│  │  │               │  │ (Contributor)   │  │ (Tree-sitter)  │    │   │
│  │  └───────────────┘  └──────────────────┘  └────────────────┘    │   │
│  │  ┌───────────────┐  ┌──────────────────┐  ┌────────────────┐    │   │
│  │  │ xai-acp-lib   │  │ xai-fast-worktree│  │ xai-crash-     │    │   │
│  │  │ (Protocol)   │  │ (Btrfs快照)      │  │ handler        │    │   │
│  │  └───────────────┘  └──────────────────┘  └────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 模块依赖关系

```
xai-chat-state ← xai-agent-lifecycle  (生命周期钩子)
xai-chat-state ← xai-acp-lib          (消息类型)
xai-chat-state → xai-grok-sampling-types
xai-chat-state → xai-grok-compaction

xai-grok-agent → xai-grok-hooks
xai-grok-agent → xai-grok-tools       (ToolBridge, ToolRegistry)
xai-grok-agent → xai-grok-config
xai-grok-agent → xai-tool-types

xai-grok-tools → xai-grok-sampling-types
xai-grok-tools → xai-tool-runtime
xai-grok-tools → xai-computer-hub-core/sdk

xai-grok-workspace → xai-grok-tools   (工具集)
xai-grok-workspace → xai-computer-hub-sdk (HubConnectionPool)
xai-grok-workspace → xai-grok-sandbox (沙箱配置)
xai-grok-workspace → xai-hunk-tracker (变更追踪)
```

---

## 三种运行模式

### 1. Local 模式（嵌入式）

Agent 和 Workspace 运行在同一个进程内，工具直接调用本地文件系统。

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

**适用场景**: 开发调试、单用户本地开发

### 2. Workspace Server 模式（远程沙箱）

Workspace 作为独立服务运行，通过 WebSocket 连接到 Hub，Agent 通过 Hub 代理工具调用。

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

**适用场景**: 安全隔离、多租户、计算密集任务

### 3. Proxy 模式（混合）

WorkspaceOps 同时支持 Local 和 Proxy 模式，通过 WebSocket 代理到远程 Workspace Server。

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

**适用场景**: 需要连接远程沙箱但保持本地开发体验

---

## 核心组件描述

### 1. xai-chat-state — 对话状态管理

**核心模式**: Actor 模式

ChatState 采用 Tokio Actor 模式运行，所有状态修改在独立任务中串行执行，无需锁。

**关键结构**:

| 结构 | 职责 |
|------|------|
| `ChatState` | Actor 内部状态：conversation、token 计数、turn capture |
| `ChatStateActor` | Tokio 任务中的 Actor，运行主循环处理命令 |
| `ChatStateHandle` | 客户端句柄，通过 mpsc 发送命令 |
| `ChatStateSnapshot` | 状态快照，支持序列化用于 fork/rewind |

**关键 API**:

```rust
// 启动 Actor
ChatStateActor::spawn(initial_conversation, sampling_config, ...) -> ChatStateHandle

// 消息操作
handle.push_user_message(item)           // 推送用户消息
handle.push_assistant_response(item)     // 推送助手响应
handle.push_tool_result(item)            // 推送工具结果

// 状态查询
handle.build_conversation_request(...)   // 构建 API 请求
handle.snapshot()                        // 获取状态快照
handle.truncate_to_prompt_index(target)  // Rewind 到指定轮次
```

**关键特性**:

- **Turn Capture**: 支持 mid-turn conversation replacement 时保留 turn tail items
- **Token 估算**: bytes/4 模型，estimated_tokens_since_model 追踪溢出风险
- **图像压缩**: 47MB 触发门控，25MB 回收目标，oldest-first 淘汰
- **工具完整性修复**: dedup 重复 ToolResult，repair dangling tool calls

### 2. xai-agent-lifecycle — 生命周期钩子

**核心模式**: Contributor 模式

支持 Turn、Session、Command 三种生命周期钩子。

**关键结构**:

| 结构 | 职责 |
|------|------|
| `TurnLifecycleContributor` | turn 生命周期钩子接口（on_turn_start/done/abort/error） |
| `SessionLifecycleContributor` | 会话钩子（on_session_idle） |
| `CommandContributor` | 命令贡献者（注册命令规范） |
| `ExtensionRegistry` | Contributor 注册表，支持 Builder 模式 |

**关键 API**:

```rust
// 注册钩子
ExtensionRegistry::register_turn_lifecycle(contributor)
ExtensionRegistry::register_session_lifecycle(contributor)

// 生命周期回调
.on_turn_start(ctx)   // Turn 开始时调用
.on_turn_done(ctx)    // Turn 完成后调用
.on_turn_abort(ctx)   // Turn 中止时调用
.on_turn_error(ctx)   // Turn 出错时调用
```

**关键特性**:

- **Send/Local 双版本**: `LocalExtensionRegistryBuilder` 用于 Rc/RefCell 的 TUI 环境
- **无锁设计**: 钩子通过 immutable 快照触发，避免死锁

### 3. xai-codebase-graph — 代码图索引

**核心模式**: Navigator 模式

基于 Tree-sitter 实现多语言代码解析和符号导航。

**关键结构**:

| 结构 | 职责 |
|------|------|
| `ScopeGraph` | 单文件符号图（definitions/references/imports） |
| `ScopeGraphIndex` | 全局索引，Navigator 核心 |
| `Navigator` | 基于位置导航（Goto 定义/引用） |
| `IndexManager` | 增量索引管理器，响应 fsnotify 事件 |
| `IndexBuilder` | 全量索引构建器 |

**关键 API**:

```rust
// 索引操作
IndexBuilder::build()                           // 全量索引
IndexManager::spawn()                           // 创建管理器

// 导航操作
IndexManagerHandle::goto_definition_blocking()  // 跳转到定义
Navigator::goto_definition()                    // 位置导航

// 缓存
load_index() / save_index()                     // 索引序列化
```

**关键特性**:

- **内存映射优化**: 使用 memmap2 处理大型代码库
- **增量索引**: IndexManager 监听 fsnotify 事件，局部更新索引
- **多语言支持**: tree-sitter-\<lang\> 插件支持 30+ 语言

### 4. xai-acp-lib — Agent-Client Protocol

**核心模式**: Channel + Gateway 模式

双向通信框架，支持消息路由和 channel 管理。

**关键结构**:

| 结构 | 职责 |
|------|------|
| `AcpAgentMessage` | Agent 接收的消息枚举 |
| `AcpClientMessage` | Client 接收的消息枚举 |
| `AcpArgs<T>` | 请求 + 响应 channel 的包装 |
| `AcpChannel` | 双向通信 channel |

**关键 API**:

```rust
// 创建通信
acp_channel()    // 创建双向 channel
acp_gateway()    // 创建 gateway

// 消息路由
AcpAgentMessage::route_to_agent()  // 消息路由到对应处理器
```

### 5. xai-fast-worktree — 快速工作树

**核心模式**: Builder 模式 + 委托模式

Git 工作树快速创建，支持 Btrfs 快照和 CoW 复制。

**关键结构**:

| 结构 | 职责 |
|------|------|
| `WorktreeBuilder` | 工作树创建 Builder，链式配置 |
| `WorktreePlan` | 执行计划参数封装 |
| `BtrfsDelegate` | 特权 btrfs 操作委托 trait（沙箱环境） |

**关键 API**:

```rust
// 创建工作树
WorktreeBuilder::new().create()   // 创建工作树

// 清理操作
remove_worktree()                 // O(1) btrfs 删除
cleanup_worktrees_in()            // 批量清理
gc::gc_worktrees()                // 垃圾回收过期工作树
```

**关键特性**:

- **Btrfs 快照**: 可达 O(1) 创建时间
- **权限委托**: BtrfsDelegate trait 解决沙箱环境 CAP_SYS_ADMIN 缺失问题
- **GC 机制**: 定期清理过期工作树

### 6. xai-grok-agent — Agent 构建与发现

**核心模式**: Builder 模式 + Registry 模式

Agent 构造器，支持从 Markdown 文件解析定义，动态发现 Agent、Skills、Plugins。

**关键结构**:

| 结构 | 职责 |
|------|------|
| `Agent` | 不可变 Agent 实例，bundles tools、prompts、policies |
| `AgentBuilder` | 10 步异步构建流程，fluent API |
| `AgentDefinition` | 从 Markdown YAML frontmatter 解析的便携定义 |
| `BuiltinAgentName` | 11 种内置 Agent 名称枚举 |
| `PluginRegistry` | 插件注册表，管理发现、信任、安装 |

**关键 API**:

```rust
// 构建流程
AgentBuilder::new(cwd, terminal_backend, notification_handle)
    .from_definition(def)
    .build()                                     // 10 步异步构建

// 发现机制
discover(cwd)                                    // 发现所有 Agent
by_name_in_cwd(name, cwd)                        // 按名称查找（优先级：project > built-in > user > bundled）
all_subagents(cwd, toggle)                       // 构建完整 subagent 列表
```

**工具集预设**:

| 预设 | 工具集 |
|------|--------|
| `grok-build` | Read, Glob, Grep, GrepSymbols, GrepPath, GrepDir, GrepWeb, Bash, Write, NotebookEdit, MultiEdit, SearchReplace, ApplyPatch, TODO, Revert, ReadNoContext, ReadRelocated |
| `grok-build-plan` | 同 grok-build + PlanMode 工具 |
| `codex` | ReadFile, ListDir, GrepFiles, ApplyPatch |
| `explore` | Read, Glob, Grep, GrepWeb, Bash |
| `plan` | Read, Glob, Grep |

### 7. xai-grok-tools — 工具注册与调度

**核心模式**: Registry 模式 + Trait-based 架构

工具实现与运行时解耦，通过 FinalizedToolset 统一管理。

**关键结构**:

| 结构 | 职责 |
|------|------|
| `FinalizedToolset` | 工具集核心，tools RwLock、reminders、resources |
| `ToolRegistryBuilder` | 工具构建器，预注册内置工具 |
| `SessionContext` | 会话上下文：terminal、fs、cwd、skills |
| `ToolBridge` | 连接 ToolRegistry 到会话层 |
| `ToolEntry` | 工具条目：类型擦除调度句柄、元数据、验证器 |
| `TerminalBackend` | 终端执行抽象 trait（Local/ACP 两种实现） |

**关键 API**:

```rust
// 构建工具集
ToolRegistryBuilder::new()
    .finalize(config, ctx)              // 验证并最终化

// 工具调用
FinalizedToolset::call(tool_name, args, call_id, cwd_override) -> ToolRunResult

// 桥接层
ToolBridge::finalize_builder(builder, config, ctx) -> Self
```

**关键特性**:

- **版本管理**: behavior_preset（current/legacy-0.4.10）实现向后兼容
- **动态注册**: MCP 工具支持运行时注册
- **能力过滤**: CapabilityMode 枚举（ReadOnly/ReadWrite/Execute/All）

### 8. xai-grok-workspace — 远程沙箱 Workspace

**核心模式**: Session Multiplexing + Hub Connection

多路复用会话，独立 CWD/shell 状态/工具集，支持 fork/bind/unbind。

**关键结构**:

| 结构 | 职责 |
|------|------|
| `WorkspaceHandle` | 主入口，管理 sessions、Hub 连接、ActivityTracker |
| `WorkspaceSession` | 每 Hub 会话的独立状态容器 |
| `HubConfig` | Hub 连接配置：WebSocket URL、AuthProvider |
| `HubHandle` | Hub 连接持有者，7 个后台任务 |
| `WorkspaceOps` | 双模式操作句柄（Local/Proxy） |
| `CapabilityMode` | 会话能力模式：ReadOnly/ReadWrite/Execute/All |
| `FileStateTracker` | 追踪会话内文件状态，支持 rewind points |

**关键 API**:

```rust
// Workspace Server 生命周期
WorkspaceHandle::connect_local_workspace()  // 连接 hub
.handle().two_phase_drain()                  // 两阶段优雅关闭

// 会话管理
WorkspaceHandle::bind_session(config)        // 创建会话
WorkspaceHandle::fork_session(parent_id)     // 派生会话
WorkspaceHandle::drop_session(session_id)    // 销毁会话

// 工具集更新
WorkspaceSession::update_tool_config(config) // 热重载工具集
```

**关键特性**:

- **沙箱支持**: bwrap/namespace 隔离，restrict_network_at_known_linux_launches
- **Hunk 追踪**: 跟踪文件变更，支持会话 rewind/snapshot/restore
- **OIDC 认证**: ~/.grok/auth.json 配置认证信息
- **诊断端点**: /ready、/statusz、/logs HTTP 服务器

### 9. ptyctl — PTY 控制服务

跨平台 PTY 控制，提供 HTTP REST API。

**关键结构**:

| 结构 | 职责 |
|------|------|
| `PtyConfig` | PTY 会话配置：command/cwd/env/rows/cols |
| `PtyHandle` | 运行的 PTY 会话句柄 |

---

## 设计模式总结

### 1. Actor 模式

**应用**: `xai-chat-state`

所有状态修改在单一 tokio task 中串行执行，无需锁。

```rust
// ChatStateActor 运行独立任务
tokio::spawn(actor.run());  // cmd_rx 处理所有状态变更

// ChatStateHandle 通过 mpsc 发送命令
handle.push_user_message(item);  // fire-and-forget
```

### 2. Builder 模式

**应用**: `AgentBuilder`, `WorktreeBuilder`, `ToolRegistryBuilder`

链式配置，10 步异步构建流程。

```rust
AgentBuilder::new(cwd, backend, notification)
    .from_definition(def)
    .with_tool_config(config)
    .with_skills(skills)
    .build()                    // 异步最终化
```

### 3. Registry 模式

**应用**: `ToolRegistry`, `PluginRegistry`, `ExtensionRegistry`

集中注册和查询，支持动态扩展。

```rust
ToolRegistryBuilder::new()  // 预注册所有内置工具
    .finalize(config, ctx)   // 配置过滤后最终化
```

### 4. Trait-based 抽象

**应用**: `TerminalBackend`, `AsyncFileSystem`, `ChatPersistence`

支持多后端实现（Local/ACP、Fs/ObjectStorage）。

```rust
trait TerminalBackend {
    async fn run(&self, request: TerminalRunRequest) -> Result<TerminalRunResult>;
    async fn run_background(&self, request: TerminalRunRequest) -> Result<BackgroundHandle>;
}
```

### 5. Contributor 模式

**应用**: `xai-agent-lifecycle`

生命周期钩子注册，支持 Send/Local 双版本。

```rust
trait TurnLifecycleContributor: Send + Sync {
    fn on_turn_start(&self, ctx: TurnStartCtx);
    fn on_turn_done(&self, ctx: TurnDoneCtx);
}
```

### 6. Channel + Gateway 模式

**应用**: `xai-acp-lib`

双向通信，通过 method_name 路由消息。

```rust
acp_channel()   // 创建双向 channel
acp_gateway()   // 创建 gateway
```

### 7. Snapshot + Rewind 模式

**应用**: `xai-chat-state`, `xai-grok-workspace`

支持状态快照和历史回滚。

```rust
handle.snapshot()                      // 获取快照
handle.truncate_to_prompt_index(idx)   // Rewind 到指定轮次
```

### 8. Session Multiplexing

**应用**: `xai-grok-workspace`

多个并发会话共享 Workspace，每个会话独立状态。

```rust
WorkspaceHandle::bind_session(config)    // 创建会话
WorkspaceHandle::fork_session(parent)    // 派生会话
WorkspaceHandle::drop_session(id)        // 销毁会话
```

---

## 关键流程详解

### 会话创建流程（Session Bind）

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

### 工具调用流程

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

### 对话压缩流程（Compaction）

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

## 重要设计决策

| 决策 | 说明 |
|------|------|
| **Actor 模式替代锁** | ChatState 所有状态修改在单一 tokio task 中串行执行，无需 Mutex |
| **Send/Local 双版本** | AgentLifecycle 区分 Send 和 Local 两种 Contributor，Local 用于 Rc/RefCell 的 TUI 环境 |
| **内存映射优化** | CodebaseGraph 使用 memmap2 处理大型代码库索引 |
| **Btrfs 委托** | FastWorktree 的 BtrfsDelegate trait 解决沙箱环境 CAP_SYS_ADMIN 缺失问题 |
| **崩溃处理时机** | CrashHandler 必须在异步 runtime 启动前 install 以捕获启动崩溃 |
| **压缩模式分离** | Summary/Transcript/Segments 三种模式控制压缩后历史恢复粒度 |
| **Turn Capture 高效实现** | 记录 conversation 长度而非克隆，实现高效单轮消息捕获 |
| **能力偏序关系** | CapabilityMode.is_subset_of() 确保 fork 时能力不扩大 |
| **双工通信分离** | Workspace Server Provider（暴露工具）和 Consumer（代理工具）方向分离 |

---

*文档版本: 1.0.0*  
*来源: Grok Build 源码分析*