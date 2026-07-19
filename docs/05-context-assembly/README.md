# 上下文组装 (Context Assembly)

本文档分析 Grok Build 中上下文组装的核心代码实现，涵盖系统提示词构建、用户上下文管理、工具描述、历史消息处理及 Token 预算管理。

## 目录

1. [系统提示词构建](#1-系统提示词构建)
2. [用户上下文](#2-用户上下文)
3. [工具描述](#3-工具描述)
4. [历史消息处理](#4-历史消息处理)
5. [Token 预算管理](#5-token-预算管理)

---

## 1. 系统提示词构建

### 1.1 PromptContext 结构体

**源码位置**: `source/crates/codegen/xai-grok-agent/src/prompt/context.rs`

`PromptContext` 是系统提示词渲染的核心数据结构，可序列化为 JSON/YAML 供用户检查：

```rust
pub struct PromptContext {
    pub version: u32,                    // 模式版本
    pub prompt_mode: PromptMode,         // Extend | Full
    pub audience: PromptAudience,        // Primary | Subagent
    pub prompt_body: Option<String>,     // 自定义主体内容
    pub system_prompt: TemplateOverride, // 模板覆盖选项
    pub agents_md_files: Vec<AgentConfigFile>, // AGENTS.md 文件
    pub persona_summaries: Vec<String>,  // 角色摘要
    pub build_timestamp_utc: String,     // 构建时间戳
    pub memory_enabled: bool,            // 记忆系统启用状态
    pub memory_global_path: Option<String>,
    pub memory_workspace_path: Option<String>,
    pub role_instructions: Option<String>,
    pub persona_instructions: Option<String>,
    pub os_name: Option<String>,
    pub shell_path: Option<String>,
    pub working_directory: Option<String>,
    pub current_date: Option<String>,
    pub is_non_interactive: bool,
    pub system_prompt_label: String,     // "You are <label>..."
}
```

### 1.2 PromptMode 模式

```rust
pub enum PromptMode {
    /// Extend: 在基础模板上追加内容
    Extend,
    /// Full: 完全替换的提示词
    Full,
}
```

### 1.3 PromptAudience 受众类型

```rust
pub enum PromptAudience {
    /// 顶级交互会话，使用完整基础模板
    Primary,
    /// 子智能体会话，使用精简模板
    Subagent,
}
```

### 1.4 TemplateOverride 模板覆盖

```rust
pub enum TemplateOverride {
    None,        // 使用标准基础/子智能体模板
    Codex,       // 使用 apply-patch 配置模板
    Custom(String), // 自定义模板字符串
}
```

### 1.5 系统提示词标签解析

**源码位置**: `source/crates/codegen/xai-grok-shell/src/util/config/resolve/system_prompt.rs`

系统提示词身份标签解析优先级：

```
环境变量 → 用户按模型配置 → 用户全局配置 → GB 按模型配置 → GB 全局配置 → "Grok"
```

```rust
pub fn resolve_system_prompt_label_from_tiers(
    user_per_model: Option<String>,
    user_global: Option<String>,
    gb_per_model: Option<String>,
    gb_global: Option<String>,
) -> String {
    // 非空验证和逐层解析
}
```

### 1.6 占位符渲染

```rust
pub fn placeholders(&self) -> serde_json::Value {
    serde_json::json!({
        "memory_enabled": self.memory_enabled,
        "memory_global_path": self.memory_global_path.as_deref().unwrap_or(""),
        "memory_workspace_path": self.memory_workspace_path.as_deref().unwrap_or(""),
        "role_instructions": self.role_instructions.as_deref().unwrap_or(""),
        "persona_instructions": self.persona_instructions.as_deref().unwrap_or(""),
        "os_name": self.os_name.as_deref().unwrap_or(""),
        "shell_path": self.shell_path.as_deref().unwrap_or(""),
        "working_directory": self.working_directory.as_deref().unwrap_or(""),
        "current_date": self.current_date.as_deref().unwrap_or(""),
        "is_non_interactive": self.is_non_interactive,
        "system_prompt_label": self.system_prompt_label.as_str(),
    })
}
```

---

## 2. 用户上下文

### 2.1 UserInfo 块

系统提示词中包含用户信息块：

```xml
<user_info>
OS: {os_name}
Shell: {shell_path}
Workspace Path: {working_directory}
Current Date: {current_date}
</user_info>
```

### 2.2 AGENTS.md 集成

```rust
/// 格式化 AGENTS.md 部分为 <system-reminder> 块
pub fn format_agents_md_section(&self) -> Option<String> {
    agents_md::format_agents_md_section(&self.agents_md_files)
}

/// AGENTS.md 作为预置用户消息注入
pub fn agents_md_user_reminder(&self) -> Option<String> {
    self.format_agents_md_section()
}
```

AGENTS.md 文件按优先级顺序发现（仓库根目录 → CWD），更深层的文件会覆盖。

### 2.3 角色和人格指令

```rust
/// 角色指令存储在持久化身份中
pub struct PromptContext {
    pub role_instructions: Option<String>,     // 角色说明
    pub persona_instructions: Option<String>,  // 人格说明
}
```

### 2.4 记忆系统上下文

```rust
pub struct PromptContext {
    pub memory_enabled: bool,
    pub memory_global_path: Option<String>,
    pub memory_workspace_path: Option<String>,
}
```

当启用时，系统提示词包含 `<memory>` 部分，告知模型可使用 `memory_search` 和 `memory_get` 工具。

---

## 3. 工具描述

### 3.1 工具桥接渲染

**源码位置**: `source/crates/codegen/xai-grok-tools/src/bridge.rs`

工具描述通过 `ToolBridge::render_prompt()` 进行渲染：

```rust
pub async fn render(&self, tool_bridge: &ToolBridge) -> Option<String> {
    let placeholders = self.placeholders();
    let prompt = match self.prompt_mode {
        PromptMode::Extend => {
            // 渲染基础模板
            let mut p = tool_bridge.render_prompt(base, &placeholders).await?;
            // 追加 prompt_body
            if let Some(ref body) = self.prompt_body {
                p.push_str("\n\n");
                p.push_str(&tool_bridge.render_prompt(body, &placeholders).await?);
            }
            p
        }
        PromptMode::Full => {
            tool_bridge.render_prompt(self.prompt_body.as_deref().unwrap_or(""), &placeholders).await?
        }
    };
    Some(prompt)
}
```

### 3.2 工具模板变量

MiniJinja 模板中使用 `${{ tools.by_kind.* }}` 变量引用工具：

```rust
tools: {
    by_kind: {
        read => "hashline_read",
        edit => "hashline_edit", 
        search => "hashline_grep",
        execute => "run_terminal_cmd",
        background_task_action => "get_task_output",
        memory_search => "memory_search",
        memory_get => "memory_get",
    }
}
```

---

## 4. 历史消息处理

### 4.1 CompactionItem 特征

**源码位置**: `source/crates/common/xai-grok-compaction/src/item.rs`

历史消息通过 `CompactionItem` 特征抽象：

```rust
pub trait CompactionItem {
    fn role(&self) -> CompactionRole;
    fn text(&self) -> Option<String>;
    fn is_tool_result(&self) -> bool;
    fn has_tool_requests(&self) -> bool;
    fn is_compaction_summary(&self) -> bool;
    fn attachment_refs(&self) -> Vec<CompactionFileRef>;
}
```

### 4.2 角色类型

```rust
pub enum CompactionRole {
    System,      // 系统提示词
    Developer,   // 开发者提示词
    User,        // 用户消息
    Assistant,   // 助手输出（可能包含工具调用）
    Tool,        // 工具结果
}
```

### 4.3 压缩策略

**源码位置**: `source/crates/common/xai-grok-compaction/src/history/types.rs`

```rust
pub enum CompactionStrategy {
    /// 基本压缩：过滤并保留重要消息
    Basic,
    /// 内部压缩：尾部保留，逐步骤处理
    Intra,
    /// 外部压缩：分块处理，块间压缩
    Inter,
    /// 全量替换：为完整会话生成摘要
    FullReplace,
}
```

### 4.4 压缩项目工厂

```rust
pub trait CompactionItemFactory: Sized {
    fn new_user(text: String) -> Self;              // 用户消息
    fn new_user_meta(text: String) -> Self;         // 元数据载体
    fn new_project_instructions(text: String) -> Self; // 项目指令
    fn new_system_reminder(text: String) -> Self;   // 系统提醒
}
```

### 4.5 历史消息过滤

```rust
// 过滤历史消息，保留基本压缩所需内容
pub fn filter_turns_for_basic(items: &[Arc<dyn CompactionItem>]) -> Vec<Arc<dyn CompactionItem>>;

// 构建用户查询前导词
pub fn build_user_queries_preamble(
    prior_summary: Option<&str>,
    user_query: &str,
    attachments: &[CompactionFileRef],
) -> String;
```

---

## 5. Token 预算管理

### 5.1 Token 估算常量

**源码位置**: `source/crates/codegen/xai-token-estimation/src/lib.rs`

```rust
/// 字符到 Token 的估算比率
pub const BYTES_PER_TOKEN: u64 = 4;

/// 图像 Token 估算成本
pub const IMAGE_TOKEN_ESTIMATE: u64 = 765;
```

### 5.2 核心估算函数

```rust
/// 估算字符串的 Token 数量
#[inline]
pub fn estimate_tokens(s: &str) -> u64 {
    (s.len() as u64) / BYTES_PER_TOKEN
}

/// Token 预算转换为字符预算
#[inline]
pub fn estimate_chars(tokens: u64) -> u64 {
    tokens.saturating_mul(BYTES_PER_TOKEN)
}

/// 估算图像的 Token 数量
#[inline]
pub fn estimate_image_tokens(image_count: u64) -> u64 {
    image_count.saturating_mul(IMAGE_TOKEN_ESTIMATE)
}
```

### 5.3 使用率计算

```rust
/// 计算使用率百分比 (f64)
#[inline]
pub fn usage_percentage(used: u64, total: u64) -> f64 {
    if total == 0 {
        0.0
    } else {
        ((used as f64) / (total as f64) * 100.0).min(100.0)
    }
}

/// 计算使用率百分比 (四舍五入到 u8)
#[inline]
pub fn usage_percentage_u8(used: u64, total: u64) -> u8 {
    usage_percentage(used, total).round() as u8
}

/// 计算使用率百分比 (截断到 u8)
#[inline]
pub fn usage_percentage_truncated_u8(used: u64, total: u64) -> u8 {
    if total == 0 {
        0
    } else {
        ((used.saturating_mul(100) / total).min(100)) as u8
    }
}
```

### 5.4 空闲 Token 计算

```rust
/// 计算空闲 Token 数量
#[inline]
pub fn free_tokens(total: u64, used: u64) -> u64 {
    total.saturating_sub(used)
}
```

### 5.5 阈值检查

```rust
/// 检查是否超过阈值
#[inline]
pub fn exceeds_threshold(used: u64, context_window: u64, threshold_percent: u8) -> bool {
    if context_window == 0 {
        return false;
    }
    used.saturating_mul(100) >= context_window.saturating_mul(threshold_percent as u64)
}

/// 检查是否超过阈值（带余量）
#[inline]
pub fn exceeds_threshold_with_headroom(
    used: u64,
    context_window: u64,
    threshold_percent: u8,
    headroom: u64,
) -> bool {
    if context_window == 0 {
        return false;
    }
    used.saturating_mul(100)
        >= context_window
            .saturating_mul(threshold_percent as u64)
            .saturating_sub(headroom.saturating_mul(100))
}
```

### 5.6 默认压缩阈值

```rust
pub const DEFAULT_AUTO_COMPACT_THRESHOLD_PERCENT: u8 = 85;
```

### 5.7 阈值计算示例

| 已使用 Token | 上下文窗口 | 阈值 | 结果 |
|-------------|-----------|------|------|
| 85,000 | 100,000 | 85% | 触发压缩 |
| 84,999 | 100,000 | 85% | 不触发 |
| 81,000 | 100,000 | 85% (4000 余量) | 触发 |

---

## 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    Context Assembly                          │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐    ┌─────────────────┐                 │
│  │ PromptContext   │───>│ ToolBridge      │                 │
│  │ - system_prompt │    │ .render_prompt()│                 │
│  │ - agents_md     │    └────────┬────────┘                 │
│  │ - placeholders  │             │                          │
│  └────────┬────────┘             v                          │
│           │          ┌─────────────────────┐                │
│           └────────> │  MiniJinja Template │                │
│                      │  ${{ tools.by_kind }}│               │
│                      └──────────┬──────────┘                │
│                                 │                            │
│                                 v                            │
│                      ┌─────────────────────┐                │
│                      │  System Prompt      │                │
│                      │  + User Context     │                │
│                      │  + Tool Descriptions│                │
│                      └──────────┬──────────┘                │
│                                 │                            │
│                                 v                            │
│                      ┌─────────────────────┐                │
│                      │  Token Estimation   │───> 压缩检查   │
│                      │  (bytes / 4)        │                │
│                      └─────────────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

---

## 相关源码文件

| 模块 | 路径 |
|------|------|
| PromptContext | `source/crates/codegen/xai-grok-agent/src/prompt/context.rs` |
| 系统提示词标签解析 | `source/crates/codegen/xai-grok-shell/src/util/config/resolve/system_prompt.rs` |
| 压缩核心库 | `source/crates/common/xai-grok-compaction/src/lib.rs` |
| 压缩项目抽象 | `source/crates/common/xai-grok-compaction/src/item.rs` |
| 历史消息处理 | `source/crates/common/xai-grok-compaction/src/history/mod.rs` |
| Token 估算 | `source/crates/codegen/xai-token-estimation/src/lib.rs` |