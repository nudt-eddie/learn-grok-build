# learn-grok-build

用中文解读 Grok Build 的 Agent Harness。

本项目通过源码地图、调用链、时序图和可复现实验，研究 Grok Build 如何将模型、上下文、工具、工作区、权限系统和终端界面组合成一个 Coding Agent。

## 上游版本

- **Commit**: `7cfcb20d2b50b0d18801a6c0af2e401c0e060894`
- **日期**: `2026-07-18`
- **仓库**: https://github.com/xai-org/grok-build.git

> ⚠️ 本项目不是 Grok Build 官方项目。每篇源码解读都会记录对应的上游 Git commit，代码变化后旧文章不代表最新实现。

---

## 项目结构

```
learn-grok-build/
├── source/                     # Grok Build 源码 (87个crate)
│   ├── crates/codegen/         # 核心代码生成模块
│   ├── crates/common/          # 公共库
│   ├── crates/build/           # 构建工具
│   └── third_party/            # 第三方依赖
├── docs/                       # 源码解读文档
│   ├── 01-architecture/        # 总体架构
│   ├── 02-startup/             # 启动与组件装配
│   ├── 03-request-flow/        # 第一条请求的完整调用链
│   ├── 04-agent-loop/          # Agent Loop
│   ├── 05-context-assembly/    # Context Assembly
│   ├── 06-tool-system/         # Tool System
│   ├── 07-workspace/           # Workspace 与 Checkpoint
│   ├── 08-session-memory/      # Session、Memory 与 Compaction
│   ├── 09-permissions/         # Permissions 与 Sandbox
│   └── 10-extensions/          # Extensions、TUI、Headless、ACP
├── experiments/                # 可复现实验代码
├── scripts/                    # 辅助脚本
├── figures/                    # 架构图、时序图
├── assets/                     # 静态资源
└── PROGRESS.md                 # 学习进度追踪
```

---

## 核心技术栈

| 技术 | 用途 |
|------|------|
| Rust edition 2024 | 核心语言 |
| tokio | 异步运行时 |
| ratatui | TUI 渲染 |
| gix | Git 操作 |
| tonic/prost | gRPC 通信 |
| moka | 缓存 |
| minijinja | 模板渲染 |

---

## 我们关注什么

- 一条用户请求如何进入 Agent Loop
- 上下文和系统提示如何组装
- 模型响应和 Tool Call 如何解析
- 工具如何注册、审批和执行
- 文件修改、Git 与 Checkpoint 如何协作
- Session、Compaction 和 Memory 如何管理状态
- Sandbox 和权限系统如何限制风险
- Skills、Plugins、Hooks、MCP 和 Subagents 如何扩展 Harness
- TUI、Headless 与 ACP 模式如何共享运行时

---

## 阅读顺序

建议按照以下顺序阅读：

1. **01-architecture** - 总体架构（技术栈、模块关系、三种运行模式）
2. **02-startup** - 启动与组件装配
3. **03-request-flow** - 第一条请求的完整调用链
4. **04-agent-loop** - Agent Loop（Actor模型、生命周期）
5. **05-context-assembly** - Context Assembly（系统提示词构建）
6. **06-tool-system** - Tool System（工具注册、发现、执行）
7. **07-workspace** - Workspace（文件操作、Git、权限）
8. **08-session-memory** - Session、Memory 与 Compaction
9. **09-permissions** - Permissions 与 Sandbox
10. **10-extensions** - Extensions、TUI、Headless 与 ACP

---

## 项目原则

- 行为优先，而不是逐文件阅读
- 所有结论尽量关联到固定版本的源码
- 所有关键机制尽量提供最小复现实验
- 明确区分源码事实、实验观察和个人推断
- 不提交密钥、认证数据或未经脱敏的运行记录

---

## 当前进度

### 阶段 0：源码获取 ✅
- [x] Clone 源码到 `source/` 目录
- [x] Commit: `7cfcb20d2b50b0d18801a6c0af2e401c0e060894` (2026-07-18)

### 阶段 1：构建验证
- [ ] Rust 环境检查
- [ ] `cargo build --release`
- [ ] 验证可执行文件

### 阶段 2：文档撰写 ✅
- [x] 01-architecture - 总体架构
- [x] 02-startup - 启动与组件装配
- [x] 03-request-flow - 请求调用链
- [x] 04-agent-loop - Agent Loop
- [x] 05-context-assembly - Context Assembly
- [x] 06-tool-system - Tool System
- [x] 07-workspace - Workspace
- [x] 08-session-memory - Session/Memory
- [x] 09-permissions - Permissions
- [x] 10-extensions - Extensions

### 阶段 3：可复现实验
- [ ] 构建验证实验
- [ ] Agent Loop 实验
- [ ] 工具调用实验
- [ ] 工作区操作实验

---

## 贡献指南

欢迎提交 PR 完善文档和实验代码！

1. Fork 本仓库
2. 创建特性分支
3. 撰写文档或实验代码
4. 确保引用正确的源码 commit
5. 提交 PR

---

## License

本项目基于学习目的创建，内容为个人对源码的理解和分析。