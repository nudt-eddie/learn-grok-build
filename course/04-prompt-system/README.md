# Prompt System / 提示词系统

## Overview / 概述

The prompt system in `xai-grok-agent` is responsible for rendering the system prompt that informs the model about its capabilities, tools, and context. It centers on `PromptContext`, a serializable data structure that captures all inputs needed for prompt rendering.

`xai-grok-agent` 的提示词系统负责渲染系统提示词，告知模型其能力、工具和上下文。其核心是 `PromptContext`，一个可序列化的数据结构，包含了渲染提示词所需的所有输入。

## Core Structure: `PromptContext` / 核心结构：`PromptContext`

`PromptContext` is defined in `context.rs`. It aggregates all agent-specific inputs used during system prompt rendering via `ToolBridge::render_prompt()`.

`PromptContext` 定义于 `context.rs` 中。它聚合了所有在通过 `ToolBridge::render_prompt()` 渲染系统提示词时所需的代理特定输入。

```rust
pub struct PromptContext {
    pub version: u32,
    pub prompt_mode: PromptMode,
    pub audience: PromptAudience,
    pub prompt_body: Option<String>,
    pub system_prompt: TemplateOverride,
    pub agents_md_files: Vec<AgentConfigFile>,
    pub persona_summaries: Vec<String>,
    pub build_timestamp_utc: String,
    pub memory_enabled: bool,
    pub memory_global_path: Option<String>,
    pub memory_workspace_path: Option<String>,
    pub role_instructions: Option<String>,
    pub persona_instructions: Option<String>,
    pub os_name: Option<String>,
    pub shell_path: Option<String>,
    pub working_directory: Option<String>,
    pub current_date: Option<String>,
    pub is_non_interactive: bool,
    pub system_prompt_label: String,
}
```

### Key Fields / 关键字段

- **`version`**: Schema version for forward-compatible persistence.  用于向前兼容持久化的模式版本。
- **`prompt_mode`**: Controls which rendering mode was used (`Extend` or `Full`).  控制使用的渲染模式（`Extend` 或 `Full`）。
- **`audience`**: Distinguishes primary (parent) from subagent (child) sessions, controlling base template and catalog section rendering.  区分主会话（父代理）和子代理（子会话），控制基础模板和目录部分渲染。
- **`prompt_body`**: Custom body appended after the base template (`Extend`) or the entire prompt (`Full`). `None` means base template only.  自定义内容，可在基础模板之后（`Extend`）或整个提示词之前（`Full`）追加。`None` 表示仅使用基础模板。
- **`system_prompt`**: Allows overriding the base template — `None` (standard), `Codex` (apply-patch profile, decrypted on demand), or `Custom`.  允许覆盖基础模板 — `None`（标准）、`Codex`（应用补丁配置，按需解密）或 `Custom`（自定义）。
- **`agents_md_files`**: Discovered `AGENTS.md` files in precedence order (repo root to CWD, deeper files override).  按优先级排列发现的 `AGENTS.md` 文件（仓库根目录到 CWD，深层文件覆盖上层）。
- **`persona_summaries`**: Pre-rendered persona summaries for system prompt injection (e.g., `- **reviewer** [user]: Writes structured review notes...`).  用于系统提示词注入的预渲染角色摘要。
- **`memory_enabled`**: When true, includes a `<memory>` section in the system prompt, enabling `memory_search` and `memory_get` tools.  为 true 时，在系统提示词中包含 `<memory>` 部分，启用 `memory_search` 和 `memory_get` 工具。
- **`role_instructions` / `persona_instructions`**: Moved from the user task prompt to be part of durable identity.  从用户任务提示词移入，作为持久化身份的一部分。
- **`os_name`, `shell_path`, `working_directory`, `current_date`**: User environment info rendered into the `<user_info>` block.  用户环境信息，渲染到 `<user_info>` 块中。
- **`is_non_interactive`**: Whether the agent runs headless (SDK / stdio / generic-ACP).  代理是否以无头模式运行（SDK / stdio / 通用 ACP）。
- **`system_prompt_label`**: Identity label in the system prompt header (`You are <label>...`). Defaults to `"Grok"`.  系统提示词头部的身份标签（`You are <label>...`）。默认为 `"Grok"`。

### Serialization / 序列化

Fields use Serde attributes for JSON/YAML compatibility. Fields set to their defaults are skipped during serialization via `#[serde(skip_serializing_if = "...")]`.

字段使用 Serde 属性实现 JSON/YAML 兼容。通过 `#[serde(skip_serializing_if = "...")]` 跳过序列化时为默认值的字段。

### Design Principles / 设计原则

- **Serializable**: All prompt inputs are serializable so users can dump and inspect them.
- **Declarative**: Prompt content is derived from structured data rather than imperative code.
- **Extensible**: Custom bodies, persona summaries, and template overrides allow flexible composition without modifying core rendering logic.

- **可序列化**: 所有提示词输入均可序列化，用户可以转储和检查。
- **声明式**: 提示词内容由结构化数据派生，而非命令式代码。
- **可扩展**: 自定义内容、角色摘要和模板覆盖允许灵活组合，无需修改核心渲染逻辑。