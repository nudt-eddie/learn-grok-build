# learn-grok-build

用中文解读 Grok Build 的 Agent Harness。

本项目通过源码地图、调用链、时序图和可复现实验，研究 Grok Build 如何将模型、上下文、工具、工作区、权限系统和终端界面组合成一个 Coding Agent。

## 我们关注什么

* 一条用户请求如何进入 Agent Loop
* 上下文和系统提示如何组装
* 模型响应和 Tool Call 如何解析
* 工具如何注册、审批和执行
* 文件修改、Git 与 Checkpoint 如何协作
* Session、Compaction 和 Memory 如何管理状态
* Sandbox 和权限系统如何限制风险
* Skills、Plugins、Hooks、MCP 和 Subagents 如何扩展 Harness
* TUI、Headless 与 ACP 模式如何共享运行时

## 阅读方式

建议按照以下顺序阅读：

1. 总体架构
2. 启动与组件装配
3. 第一条请求的完整调用链
4. Agent Loop
5. Context Assembly
6. Tool Registry 与工具执行
7. Workspace 与文件修改
8. Session、Memory 与 Compaction
9. Permissions 与 Sandbox
10. Extensions、TUI、Headless 与 ACP

## 项目原则

* 行为优先，而不是逐文件阅读
* 所有结论尽量关联到固定版本的源码
* 所有关键机制尽量提供最小复现实验
* 明确区分源码事实、实验观察和个人推断
* 不提交密钥、认证数据或未经脱敏的运行记录

## 上游版本

本项目不是 Grok Build 官方项目。

每篇源码解读都会记录对应的上游 Git commit、SOURCE_REV 和验证日期。上游代码发生变化后，旧文章不会自动代表最新实现。

## 当前进度

* [ ] 构建与运行验证
* [ ] Crate 依赖地图
* [ ] 总体架构图
* [ ] 第一条请求调用链
* [ ] Agent Loop
* [ ] Context Assembly
* [ ] Tool System
* [ ] Workspace 与 Checkpoint
* [ ] Session、Memory 与 Compaction
* [ ] Permissions 与 Sandbox
* [ ] Skills、Plugins、Hooks、MCP 与 Subagents
