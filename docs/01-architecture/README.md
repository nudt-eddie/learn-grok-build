# Grok Build 架构文档

<!-- SOURCE: https://github.com/xai-org/grok-build/blob/7cfcb20/README.md#L1 -->

## 1图看懂

![Grok Build Architecture](assets/architecture-overview.svg)

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

**一句话总结**: Grok Build 是 xAI 开发的高性能 AI 代码助手基础设施，通过 Actor 模型管理对话状态，基于 Tree-sitter 构建代码图索引，支持 Btrfs 快照实现 O(1) 工作树创建。

---

## 行为

### 三种运行模式

#### 1. Local 模式（嵌入式）

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

#### 2. Workspace Server 模式（远程沙箱）

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

#### 3. Proxy 模式（混合）

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

### 关键流程

#### 会话创建流程（Session Bind）

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

#### 工具调用流程

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

#### 对话压缩流程（Compaction）

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

## 源码

### 技术栈

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

### 核心组件 API

#### xai-chat-state

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

#### xai-grok-agent

```rust
// 构建流程
AgentBuilder::new(cwd, terminal_backend, notification_handle)
    .from_definition(def)
    .build()                                     // 10 步异步构建

// 发现机制
discover(cwd)                                    // 发现所有 Agent
by_name_in_cwd(name, cwd)                        // 按名称查找
all_subagents(cwd, toggle)                       // 构建完整 subagent 列表
```

#### xai-grok-tools

```rust
// 构建工具集
ToolRegistryBuilder::new()
    .finalize(config, ctx)              // 验证并最终化

// 工具调用
FinalizedToolset::call(tool_name, args, call_id, cwd_override) -> ToolRunResult

// 桥接层
ToolBridge::finalize_builder(builder, config, ctx) -> Self
```

#### xai-grok-workspace

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

---

## 设计原因

### 重要设计决策

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

### 设计目标

- **高性能**: 全链路 Rust 实现，避免 GC 停顿，确保低延迟工具调用
- **安全隔离**: Workspace 运行在远程沙箱，通过 capability mode 限制权限
- **可扩展**: 插件系统支持动态注册工具、Agent、Skills
- **可追溯**: Hunk 追踪支持对话 rewind 和快照恢复

---

## Mini实现

### 设计模式示例

#### 1. Actor 模式

```rust
// ChatStateActor 运行独立任务
tokio::spawn(actor.run());  // cmd_rx 处理所有状态变更

// ChatStateHandle 通过 mpsc 发送命令
handle.push_user_message(item);  // fire-and-forget
```

#### 2. Builder 模式

```rust
AgentBuilder::new(cwd, backend, notification)
    .from_definition(def)
    .with_tool_config(config)
    .with_skills(skills)
    .build()                    // 异步最终化
```

#### 3. Registry 模式

```rust
ToolRegistryBuilder::new()  // 预注册所有内置工具
    .finalize(config, ctx)   // 配置过滤后最终化
```

#### 4. Trait-based 抽象

```rust
trait TerminalBackend {
    async fn run(&self, request: TerminalRunRequest) -> Result<TerminalRunResult>;
    async fn run_background(&self, request: TerminalRunRequest) -> Result<BackgroundHandle>;
}
```

#### 5. Contributor 模式

```rust
trait TurnLifecycleContributor: Send + Sync {
    fn on_turn_start(&self, ctx: TurnStartCtx);
    fn on_turn_done(&self, ctx: TurnDoneCtx);
}
```

#### 6. Snapshot + Rewind 模式

```rust
handle.snapshot()                      // 获取快照
handle.truncate_to_prompt_index(idx)   // Rewind 到指定轮次
```

---

## 实验

### 关键特性验证

1. **Turn Capture**: 支持 mid-turn conversation replacement 时保留 turn tail items
2. **Token 估算**: bytes/4 模型，estimated_tokens_since_model 追踪溢出风险
3. **图像压缩**: 47MB 触发门控，25MB 回收目标，oldest-first 淘汰
4. **工具完整性修复**: dedup 重复 ToolResult，repair dangling tool calls
5. **Btrfs 快照**: 可达 O(1) 创建时间
6. **权限委托**: BtrfsDelegate trait 解决沙箱环境 CAP_SYS_ADMIN 缺失问题
7. **GC 机制**: 定期清理过期工作树
8. **增量索引**: IndexManager 监听 fsnotify 事件，局部更新索引
9. **沙箱支持**: bwrap/namespace 隔离，restrict_network_at_known_linux_launches
10. **Hunk 追踪**: 跟踪文件变更，支持会话 rewind/snapshot/restore

### 工具集预设

| 预设 | 工具集 |
|------|--------|
| `grok-build` | Read, Glob, Grep, GrepSymbols, GrepPath, GrepDir, GrepWeb, Bash, Write, NotebookEdit, MultiEdit, SearchReplace, ApplyPatch, TODO, Revert, ReadNoContext, ReadRelocated |
| `grok-build-plan` | 同 grok-build + PlanMode 工具 |
| `codex` | ReadFile, ListDir, GrepFiles, ApplyPatch |
| `explore` | Read, Glob, Grep, GrepWeb, Bash |
| `plan` | Read, Glob, Grep |

---

## 对比

### 与其他代码助手架构对比

| 特性 | Grok Build | 其他方案 |
|------|------------|----------|
| **状态管理** | Actor 模式，无锁设计 | 常见 Mutex/RwLock |
| **工作树创建** | Btrfs 快照 O(1) | Git clone O(n) |
| **代码索引** | Tree-sitter 本地索引 | 依赖 LSP 服务器 |
| **沙箱隔离** | Capability Mode + bwrap | 容器或无隔离 |
| **压缩策略** | Summary/Transcript/Segments 三模式 | 简单截断 |
| **会话管理** | Session Multiplexing | 单会话 |

### 核心模式对比

| 模式 | Grok Build 实现 | 替代方案 |
|------|-----------------|----------|
| **Actor vs 直接调用** | Tokio task + mpsc | 直接方法调用 |
| **Builder vs 构造函数** | 链式异步构建 | 一步构造 |
| **Registry vs 硬编码** | 动态注册查询 | 静态注册 |
| **Trait vs 泛型** | 多后端实现 | 单实现 |
| **Contributor vs 继承** | 组合优于继承 | 继承链 |

---

## 误解

### 常见误解

1. **"Actor 模式性能差"**: 实际上 Tokio Actor 通过 mpsc 实现无锁并发，单 task 串行执行反而避免了死锁和竞争。

2. **"Btrfs 快照总是 O(1)"**: 只有在 btrfs 文件系统上且内核支持时才 O(1)，其他文件系统会回退到 CoW 复制。

3. **"沙箱绝对安全"**: CapabilityMode 只能限制工具能力，无法防止 0-day 漏洞，bwrap 也需正确配置。

4. **"代码图索引实时更新"**: 增量索引依赖 fsnotify，可能有短暂延迟，全量重建更可靠。

5. **"Proxy 模式等同于 Server 模式"**: Proxy 模式下工具仍本地执行，只是转发到远程 Workspace。

6. **"Agent 发现即加载"**: discover() 只返回定义，加载和初始化在 build() 时才发生。

7. **"Turn Capture 会克隆整个对话"**: 实际上只记录长度，实现零拷贝捕获。

8. **"CapabilityMode 可任意组合"**: 存在偏序关系，必须 is_subset_of() 检查。

---

## 练习

### 实践任务

1. **实现一个简单的 Actor**
   ```rust
   // 创建一个处理计数器命令的 Actor
   // 命令: Inc, Dec, Get
   // 要求: 使用 Tokio spawn + mpsc，无锁设计
   ```

2. **扩展 ToolRegistry**
   ```rust
   // 添加一个新的 MCP 工具到注册表
   // 要求: 实现 Tool trait，正确注册元数据
   ```

3. **构建自定义 Agent**
   ```rust
   // 从 Markdown YAML frontmatter 定义并构建 Agent
   // 要求: 包含自定义工具集和系统提示
   ```

4. **实现 Workspace Session Fork**
   ```rust
   // 派生一个新的 WorkspaceSession
   // 要求: 正确继承 CapabilityMode，处理 HunkTracker
   ```

5. **添加生命周期钩子**
   ```rust
   // 实现 TurnLifecycleContributor
   // 要求: 在 on_turn_done 时记录指标
   ```

6. **性能对比实验**
   ```bash
   # 比较 Local vs Proxy vs Server 模式的工具调用延迟
   # 记录不同负载下的 P50/P99 延迟
   ```

7. **调试 Hunk 追踪**
   ```rust
   // 在文件修改后检查 HunkTracker 状态
   // 验证 rewind 和 restore 功能
   ```

8. **Btrfs 环境检测**
   ```rust
   // 检测当前环境是否支持 btrfs 快照
   // 实现优雅降级到 CoW 复制
   ```

---

*文档版本: 2.0.0 (新模板)*

<!-- SOURCE: https://github.com/xai-org/grok-build/blob/7cfcb20/README.md#L1 -->