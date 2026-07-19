# 🔬 learn-grok-build

> 用中文深度解读 Grok Build 的 Agent Harness 架构

[![Commit](https://img.shields.io/badge/commit-7cfcb20-blue)](https://github.com/xai-org/grok-build)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![Stars](https://img.shields.io/github/stars/nudt-eddie/learn-grok-build)](https://github.com/nudt-eddie/learn-grok-build/stargazers)

## 项目简介

本项目对 [Grok Build](https://github.com/xai-org/grok-build) 源码进行系统性解读，通过**源码地图**、**调用链追踪**、**时序图分析**和**可复现实验**，研究一个生产级 Coding Agent 如何将模型推理、上下文组装、工具系统、工作区管理、权限控制等模块有机组合。

### 核心研究问题

| 层次 | 研究问题 |
|------|----------|
| **请求入口** | 用户请求如何进入 Agent Loop？|
| **上下文组装** | 系统提示词如何构建？历史消息如何管理？|
| **模型交互** | Tool Call 如何解析？流式响应如何处理？|
| **工具执行** | 工具如何注册、审批、执行、返回结果？|
| **工作区** | 文件修改、Git 操作、Checkpoint 如何协作？|
| **状态管理** | Session、Compaction、Memory 如何管理状态？|
| **安全隔离** | Sandbox 和权限系统如何限制风险边界？|
| **扩展机制** | Skills、Plugins、Hooks、MCP 如何扩展 Harness？|

---

## 架构概览

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              Grok Build 架构                                   │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                         User Interface Layer                            │  │
│  │                    TUI (ratatui) │ Headless │ ACP                       │  │
│  └────────────────────────────────┬───────────────────────────────────────┘  │
│                                   │                                          │
│                                   ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                          Agent Harness Layer                            │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │  │
│  │  │   Agent     │  │    Tool     │  │  Workspace  │  │   Session   │    │  │
│  │  │   Loop      │  │   System    │  │   Manager   │  │   State     │    │  │
│  │  │ (Actor)     │  │             │  │             │  │ (Compaction)│    │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │  │
│  └────────────────────────────────┬───────────────────────────────────────┘  │
│                                   │                                          │
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

### 核心模块

| 模块 | Crate | 职责 |
|------|-------|------|
| **Agent Loop** | `xai-grok-agent` | 基于 Actor 模型的对话状态管理 |
| **Tool System** | `xai-grok-tools` | 工具注册、发现、调度、执行 |
| **Workspace** | `xai-grok-workspace` | 文件操作、Git 集成、权限控制 |
| **Session State** | `xai-chat-state` | 会话状态、Compaction、持久化 |
| **Context Assembly** | `xai-chat-state/actor` | 系统提示词构建、请求组装 |
| **Sandbox** | `xai-grok-sandbox` | 进程隔离、安全执行 |
| **MCP** | `xai-grok-mcp` | Model Context Protocol 支持 |
| **Hooks** | `xai-grok-hooks` | Agent 生命周期钩子扩展 |

---

## 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| **Rust** | edition 2024 | 核心语言，避免 GC 停顿 |
| **Tokio** | 1.x | 异步运行时 |
| **ratatui** | 0.29 | TUI 终端界面渲染 |
| **gix** | 0.83 | Git 仓库操作 |
| **tonic/prost** | 0.14 | gRPC 通信 |
| **moka** | 0.12 | 高性能缓存 |
| **minijinja** | 2.9 | 模板渲染 |

---

## 文档目录

```
docs/
├── 01-architecture/          # 总体架构
│   ├── 1.1-项目概述.md       # 设计目标与技术选型
│   ├── 1.2-技术栈.md         # 核心依赖详解
│   ├── 1.3-Crate地图.md      # 模块依赖关系
│   └── 1.4-运行模式.md       # TUI/Headless/ACP
├── 02-startup/               # 启动与组件装配
│   ├── 2.1-入口点.md         # main.rs 分析
│   ├── 2.2-配置加载.md       # Config 解析
│   └── 2.3-初始化顺序.md     # 组件装配时序
├── 03-request-flow/          # 请求调用链
│   ├── 3.1-输入入口.md       # TTY/文件/Socket
│   ├── 3.2-Agent处理.md      # 请求路由分发
│   └── 3.3-响应生成.md       # 流式响应处理
├── 04-agent-loop/            # Agent Loop
│   ├── 4.1-Actor模型.md      # ChatStateActor
│   ├── 4.2-生命周期.md       # Turn/Command 处理
│   └── 4.3-状态管理.md       # ConversationItem
├── 05-context-assembly/      # 上下文组装
│   ├── 5.1-系统提示词.md     # Prompt 模板
│   ├── 5.2-工具描述.md       # Tool Schema 注入
│   └── 5.3-Token管理.md      # 上下文窗口控制
├── 06-tool-system/           # 工具系统
│   ├── 6.1-工具注册.md       # Tool Trait
│   ├── 6.2-工具发现.md       # Discovery 机制
│   ├── 6.3-工具执行.md       # ToolDispatch
│   └── 6.4-结果处理.md       # 响应格式化
├── 07-workspace/             # 工作区
│   ├── 7.1-文件操作.md       # FS 操作
│   ├── 7.2-Git集成.md        # gix 封装
│   ├── 7.3-权限模型.md       # Trust/Capability
│   └── 7.4-Checkpoint.md     # 快照机制
├── 08-session-memory/        # 会话与记忆
│   ├── 8.1-Session.md        # 会话生命周期
│   ├── 8.2-Compaction.md     # 上下文压缩
│   └── 8.3-持久化.md         # Journal/SQLite
├── 09-permissions/           # 权限与安全
│   ├── 9.1-Sandbox.md        # 进程隔离
│   ├── 9.2-文件访问.md       # 路径限制
│   └── 9.3-命令执行.md       # 白名单机制
└── 10-extensions/            # 扩展机制
    ├── 10.1-MCP.md           # Model Context Protocol
    ├── 10.2-Hooks.md         # 生命周期钩子
    └── 10.3-Skills.md        # 技能系统
```

---

## 学习路径

### 入门路径（推荐阅读顺序）

```
1. 01-architecture     → 建立整体印象
      ↓
2. 02-startup          → 理解启动流程
      ↓
3. 03-request-flow     → 追踪请求全貌
      ↓
4. 04-agent-loop       → 掌握核心机制 ⭐
      ↓
5. 05-context-assembly → 理解上下文
      ↓
6. 06-tool-system      → 工具执行原理
      ↓
7. 07-workspace        → 工作区管理
      ↓
8. 08-session-memory   → 状态持久化
      ↓
9. 09-permissions      → 安全机制
      ↓
10. 10-extensions      → 扩展生态
```

### 专题路径

| 专题 | 关联文档 |
|------|----------|
| **Actor 并发模型** | 04-agent-loop, 08-session-memory |
| **工具系统设计** | 06-tool-system, 10-extensions |
| **安全沙箱** | 09-permissions, 07-workspace |
| **上下文压缩** | 08-session-memory, 05-context-assembly |

---

## 源码信息

| 项目 | 值 |
|------|---|
| **上游仓库** | https://github.com/xai-org/grok-build |
| **当前版本** | `7cfcb20d2b50b0d18801a6c0af2e401c0e060894` |
| **分析日期** | 2026-07-19 |
| **Crate 数量** | 87+ |
| **源码规模** | ~500K LOC |

> ⚠️ 本项目为**个人学习笔记**，不代表 Grok Build 官方立场。源码更新后，旧文档可能不再反映最新实现。

---

## 快速开始

### 克隆项目

```bash
git clone https://github.com/nudt-eddie/learn-grok-build.git
cd learn-grok-build
```

### 添加源码（Submodule）

```bash
git submodule add https://github.com/xai-org/grok-build.git source
cd source
git checkout 7cfcb20d2b50b0d18801a6c0af2e401c0e060894
```

### 构建验证

```bash
cd source
cargo build --release
```

---

## 项目原则

1. **行为优先于实现** - 关注"做什么"和"为什么"，而非逐行代码
2. **关联固定版本** - 所有结论关联到特定 commit，便于回溯
3. **可复现验证** - 关键机制提供最小可验证实验
4. **区分事实与推断** - 明确标注源码事实 vs 个人推断
5. **安全脱敏** - 不包含密钥、认证信息或敏感日志

---

## 贡献指南

欢迎提交 PR 完善文档！

```bash
# 1. Fork 本仓库
# 2. 创建特性分支
git checkout -b docs/improve-agent-loop

# 3. 编辑文档
# 4. 提交 (引用对应源码 commit)
git commit -m "docs: 补充 Agent Loop 重试机制说明

Co-Authored-By: Claude <noreply@anthropic.com>"

# 5. Push 并创建 PR
git push origin docs/improve-agent-loop
```

---

## License

本项目基于学习目的创建，内容为个人对源码的理解和分析，基于 MIT 协议开源。

Grok Build 源码基于 Apache-2.0 许可证。

---

<p align="center">
  <i>Built with ❤️ for the Rust community</i><br>
  <a href="https://github.com/nudt-eddie/learn-grok-build">GitHub</a> •
  <a href="docs/">Documentation</a> •
  <a href="PROGRESS.md">Progress</a>
</p>