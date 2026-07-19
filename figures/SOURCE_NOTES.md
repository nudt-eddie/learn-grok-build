# Grok Build 源码调研摘要（第二批）

## 07 Compaction
- `xai-grok-compaction` 是 transport-agnostic compaction core。
- grok-build 使用 whole-session full-replace：build prompt → sample/retry → clean/validate → assemble fresh history。
- 触发、持久化、回放/回滚、状态提交与指标由宿主负责。

## 08 Memory
- Markdown 存储：全局 `MEMORY.md`、工作区 `MEMORY.md`、按日期的 session logs。
- 工作区标识优先使用 git origin 的 `org/repo`，后缀使用 blake3 hash。
- 检索为 FTS5 BM25 + 可选 sqlite-vec KNN；之后合并、时间衰减、来源权重、访问频率 boost 与 MMR。
- 无向量能力时退化为 FTS-only；临时目录工作区跳过持久写入。

## 09 Hooks
- Global 来源先于 Project 来源；目录文件按词典序加载。
- 去重键为 `(event, command, url, matcher)`，先加载者保留。
- PreToolUse 顺序执行，显式 Deny 立即阻断；超时、崩溃、格式错误默认 fail-open，但会进入日志和 UI。

## 10 Sandbox
- 进程级内核沙箱由 nono 提供，Unix 上对应 Landlock/Seatbelt。
- Linux 可先使用 bwrap 重新执行，处理 deny_write 与 deny_read bind-over。
- 主进程保留 LLM API 网络；子进程网络通过已知启动路径安装 seccomp 过滤。
- 某些读拒绝与 glob 解析路径采用 fail-closed，避免静默欠隔离。

## 11 Crash Handler
- 启动时先 `check_previous_crash`，再 `install`；后者会截断 crash blob。
- Unix 捕获 SIGSEGV/SIGBUS，Windows 捕获 access violation。
- 信号处理路径记录二进制 blob 并恢复终端；下一次启动再符号化并写 0600 报告，历史最多保留 5 份。

## 12 Background Tasks
- background command、monitor、scheduler/loop 与 subagent 统一以 task_id 管理。
- 支持查询、等待多个任务、终止以及完成/事件通知。
- Tasks Pane 与 watching 状态行统一展示后台活动；完成、monitor 行与 loop timer 均可唤醒 agent。

## 13 Plugins
- 来源优先级：session meta → CLI → project → user → custom path。
- plugin.json 可选；缺省按 convention directories 发现 skills、commands、agents、hooks、MCP 与 LSP。
- Enable 决定是否加载插件；Trust 单独控制 Hooks/MCP/LSP 等可执行组件。
- Marketplace 可启用 tighten-only 的 `require_sha`，拒绝未固定 commit 的远程安装/更新。

## 主要公开源码入口
- https://github.com/xai-org/grok-build
- https://raw.githubusercontent.com/xai-org/grok-build/main/crates/common/xai-grok-compaction/src/lib.rs
- https://raw.githubusercontent.com/xai-org/grok-build/main/crates/common/xai-grok-compaction/src/code_compaction/mod.rs
- https://raw.githubusercontent.com/xai-org/grok-build/main/crates/codegen/xai-grok-memory/src/lib.rs
- https://raw.githubusercontent.com/xai-org/grok-build/main/crates/codegen/xai-grok-memory/src/storage.rs
- https://raw.githubusercontent.com/xai-org/grok-build/main/crates/codegen/xai-grok-memory/src/search.rs
- https://raw.githubusercontent.com/xai-org/grok-build/main/crates/codegen/xai-grok-hooks/src/discovery.rs
- https://raw.githubusercontent.com/xai-org/grok-build/main/crates/codegen/xai-grok-hooks/src/dispatcher.rs
- https://raw.githubusercontent.com/xai-org/grok-build/main/crates/codegen/xai-grok-sandbox/src/lib.rs
- https://raw.githubusercontent.com/xai-org/grok-build/main/crates/codegen/xai-crash-handler/src/lib.rs
- https://raw.githubusercontent.com/xai-org/grok-build/main/crates/codegen/xai-grok-pager/docs/user-guide/20-background-tasks.md
- https://raw.githubusercontent.com/xai-org/grok-build/main/crates/codegen/xai-grok-pager/docs/user-guide/09-plugins.md
