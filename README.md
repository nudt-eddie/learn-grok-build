# Learn Grok Build: 从源码到复刻

> 拆解 Agent Loop、Tool Calling、Context Compaction、Sandbox

[![Commit](https://img.shields.io/badge/commit-7cfcb20-blue)](https://github.com/xai-org/grok-build)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Stars](https://img.shields.io/github/stars/nudt-eddie/learn-grok-build)](https://github.com/nudt-eddie/learn-grok-build/stargazers)

---

## 一句话定位

Grok Build 是 xAI 开源的生产级 Coding Agent，本项目通过源码地图、调用链追踪和时序图分析，系统性解读其 Agent Harness 架构。

---

## 学到什么

| 层次 | 核心问题 |
|------|----------|
| **Agent Loop** | 用户请求如何进入循环？状态机如何驱动对话？ |
| **Tool Calling** | 工具如何注册、审批、执行、返回结果？ |
| **Context Compaction** | 上下文如何压缩以控制 token 成本？ |
| **Sandbox** | 进程隔离如何限制风险边界？ |

---

## 5分钟运行

```bash
# 克隆项目
git clone https://github.com/nudt-eddie/learn-grok-build.git
cd learn-grok-build

# 添加源码 submodule
git submodule add https://github.com/xai-org/grok-build.git source
cd source
git checkout 7cfcb20d2b50b0d18801a6c0af2e401c0e060894

# 构建验证
cargo build --release

# 运行 TUI
cargo run -p xai-grok-pager-bin --release
```

---

## 最终成果

你将掌握一个完整 Coding Agent 的核心设计模式，能够：
- 理解 Agent Loop 与 Actor 模型的关系
- 实现自定义工具注册与执行管道
- 设计上下文压缩与记忆系统
- 构建安全的进程隔离沙箱

---

## 8节课大纲

### Lesson 1: 源码架构
建立整体印象，理解模块划分与依赖层次。

### Lesson 2: 启动流程
追踪从入口到 Agent 构建发现的完整流程。

### Lesson 3: Agent Loop
深入 Actor 状态机，理解消息循环与模型调用机制。

### Lesson 4: 工具系统
学习工具注册、发现、调度与执行管道设计。

### Lesson 5: 上下文组装
掌握系统提示词构建与历史消息管理策略。

### Lesson 6: 工作区管理
理解文件操作、Git 集成与权限控制协作。

### Lesson 7: 会话记忆
学习 Checkpoint、Compaction 与混合记忆系统。

### Lesson 8: 安全沙箱
掌握进程隔离与权限强制执行机制。

---

## 架构概览

![总体架构图](figures/grok解读.png)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              Grok Build 架构                                   │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                         User Interface Layer                            │  │
│  │                    TUI (ratatui) │ Headless │ ACP                       │  │
│  └────────────────────────────────┬───────────────────────────────────────┘  │
│                                   ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                          Agent Harness Layer                            │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │  │
│  │  │   Agent     │  │    Tool     │  │  Workspace  │  │   Session   │    │  │
│  │  │   Loop      │  │   System    │  │   Manager   │  │   State     │    │  │
│  │  │ (Actor)     │  │             │  │             │  │ (Compaction)│    │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │  │
│  └────────────────────────────────┬───────────────────────────────────────┘  │
│                                   ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                          Runtime Layer                                  │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │  │
│  │  │   Tokio     │  │   Sandbox   │  │    MCP      │  │   Memory    │    │  │
│  │  │  (async)    │  │  (隔离执行)  │  │  Protocol   │  │   (记忆)    │    │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 文档结构

| Lesson | 主题 | 文档 |
|--------|------|------|
| 01 | 源码架构 | [README](docs/01-architecture/README.md) |
| 02 | 启动流程 | [README](docs/02-startup/README.md) |
| 03 | 请求流程 | [README](docs/03-request-flow/README.md) |
| 04 | Agent Loop | [README](docs/04-agent-loop/README.md) |
| 05 | 上下文组装 | [README](docs/05-context-assembly/README.md) |
| 06 | 工具系统 | [README](docs/06-tool-system/README.md) |
| 07 | 工作区 | [README](docs/07-workspace/README.md) |
| 08 | 会话记忆 | [README](docs/08-session-memory/README.md) |

---

## 模块层次结构

```
grok-build/
├── codegen/
│   ├── xai-grok-shell              # Agent Loop 运行时
│   ├── xai-chat-state              # Actor 状态机 (上下文组装)
│   ├── xai-grok-agent              # Agent 编排层
│   ├── xai-grok-tools              # 工具系统
│   ├── xai-grok-workspace          # 工作区管理
│   ├── xai-grok-sandbox            # 进程隔离沙箱
│   ├── xai-grok-memory             # 混合记忆系统
│   └── xai-grok-hooks              # 生命周期钩子
└── common/
    └── xai-grok-compaction          # 压缩核心逻辑
```

---

## 核心模块

| 模块 | Crate | 职责 |
|------|-------|------|
| **Agent Loop** | `xai-grok-shell` | 消息循环、模型调用、响应处理 |
| **Actor 状态机** | `xai-chat-state` | 对话状态管理与上下文组装 |
| **工具系统** | `xai-grok-tools` | 工具注册、发现、调度、执行 |
| **工作区** | `xai-grok-workspace` | 文件操作、Git 集成、权限控制 |
| **沙箱** | `xai-grok-sandbox` | 进程隔离、安全执行 |
| **上下文压缩** | `xai-chat-state` | Compaction 与状态管理 |

---

## 图示集

| 编号 | 图表 | 说明 |
|------|------|------|
| 01 | ![源码架构](figures/01_source_architecture.png) | 源码整体架构与模块关系 |
| 02 | ![Agent 构建发现](figures/02_agent_build_discovery.png) | Agent 启动与工具发现流程 |
| 03 | ![Turn 工具时序](figures/03_turn_tool_sequence.png) | 单轮对话与工具调用时序 |
| 04 | ![工作区会话生命周期](figures/04_workspace_session_lifecycle.png) | 工作区与会话状态管理 |
| 05 | ![代码库图谱](figures/05_codebase_graph_lifecycle.png) | 代码库图谱构建与使用 |
| 06 | ![Checkpoint 回退](figures/06_checkpoint_rewind.png) | 状态Checkpoint与回退机制 |
| 07 | ![Compaction 压缩](figures/07_compaction_full_replace.png) | 上下文压缩替换策略 |
| 08 | ![混合记忆搜索](figures/08_memory_hybrid_search.png) | 混合记忆与向量搜索 |
| 09 | ![Hooks 策略管道](figures/09_hooks_policy_pipeline.png) | Hooks 策略执行管道 |
| 10 | ![沙箱执行](figures/10_sandbox_enforcement.png) | 沙箱权限强制执行 |

---

## 技术栈

| 技术 | 用途 |
|------|------|
| **Rust** | 核心语言，避免 GC 停顿 |
| **Tokio** | 异步运行时 |
| **ratatui** | TUI 终端界面渲染 |
| **gix** | Git 仓库操作 |
| **tonic/prost** | gRPC 通信 |
| **moka** | 高性能缓存 |

---

## 源码信息

| 项目 | 值 |
|------|---|
| **上游仓库** | https://github.com/xai-org/grok-build |
| **当前版本** | `7cfcb20d2b50b0d18801a6c0af2e401c0e060894` |
| **分析日期** | 2026-07-19 |

---

## 项目原则

1. **行为优先于实现** - 关注"做什么"和"为什么"，而非逐行代码
2. **关联固定版本** - 所有结论关联到特定 commit，便于回溯
3. **源码证据** - 重要结论关联到具体的源码位置
4. **区分事实与推断** - 明确标注源码事实 vs 个人推断

---

## License

本项目基于学习目的创建，内容为个人对源码的理解和分析，基于 MIT 协议开源。

Grok Build 源码基于 Apache-2.0 许可证。

---

<p align="center">
  <i>Built with for the Rust community</i><br>
  <a href="https://github.com/nudt-eddie/learn-grok-build">GitHub</a>
</p>