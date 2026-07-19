# Grok Build 源码架构图集

生成日期：2026-07-19

## 图集

1. `01_source_architecture`：源码分层与控制/执行边界
2. `02_agent_build_discovery`：Agent 构建、发现与工具裁剪
3. `03_turn_tool_sequence`：单轮对话、工具调用与取消安全时序
4. `04_workspace_session_lifecycle`：Session 创建、Fork、热切换与释放
5. `05_codebase_graph_lifecycle`：代码图启动、增量索引、查询与缓存
6. `06_checkpoint_rewind`：Turn checkpoint、Hunk 与 Rewind

每张图同时提供 SVG（可编辑）和 PNG（便于预览）。

## 研究依据

- 官方仓库 `xai-org/grok-build` 的 README 与 `crates/codegen` 源码。
- 用户提供的《Grok Build 总体架构文档》作为初始模块地图，随后以公开源码逐项校正和深化。
- 重点检查文件包括：`xai-grok-agent/{builder,config,discovery,agent}.rs`、`xai-chat-state/actor/*`、`xai-grok-tools/bridge.rs`、`xai-grok-workspace/{handle,capability,session/*}.rs`、`xai-codebase-graph/{lib,index_manager,navigation}.rs`。

## 注意

这些图是对源码结构和运行语义的工程化归纳，不是上游项目官方发布的架构图。



独立图：

- 07 Full-Replace Compaction
- 08 Memory Hybrid Search & Dream
- 09 Hooks Policy Pipeline
- 10 Sandbox Enforcement
- 11 Crash Handler Lifecycle
- 12 Background Tasks & Scheduler
- 13 Plugin Trust & Marketplace

每张图同时提供 PNG、SVG 和 DOT 源文件。
