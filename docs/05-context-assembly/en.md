# Context Assembly

This document analyzes the core code implementation of context assembly in Grok Build, covering system prompt construction, user context management, tool descriptions, history message processing, and token budget management.

## Table of Contents

1. [System Prompt Construction](#1-system-prompt-construction)
2. [User Context](#2-user-context)
3. [Tool Descriptions](#3-tool-descriptions)
4. [History Message Processing](#4-history-message-processing)
5. [Token Budget Management](#5-token-budget-management)

---

## 1. System Prompt Construction

### 1.1 PromptContext Struct

**Source Location**: `source/crates/codegen/xai-grok-agent/src/prompt/context.rs`

`PromptContext` is the core data structure for system prompt rendering, serializable to JSON/YAML for user inspection:

```rust
pub struct PromptContext {
    pub version: u32,                    // Schema version
    pub prompt_mode: PromptMode,         // Extend | Full
    pub audience: PromptAudience,        // Primary | Subagent
    pub prompt_body: Option<String>,     // Custom body content
    pub system_prompt: TemplateOverride, // Template override options
    pub agents_md_files: Vec<AgentConfigFile>, // AGENTS.md files
    pub persona_summaries: Vec<String>,  // Persona summaries
    pub build_timestamp_utc: String,     // Build timestamp
    pub memory_enabled: bool,            // Memory system enabled state
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

### 1.2 PromptMode Enum

```rust
pub enum PromptMode {
    /// Extend: Append content to base template
    Extend,
    /// Full: Completely replace the prompt
    Full,
}
```

### 1.3 PromptAudience Enum

```rust
pub enum PromptAudience {
    /// Top-level interactive session, uses full base template
    Primary,
    /// Sub-agent session, uses simplified template
    Subagent,
}
```

### 1.4 TemplateOverride Enum

```rust
pub enum TemplateOverride {
    None,        // Use standard base/subagent template
    Codex,       // Use apply-patch configuration template
    Custom(String), // Custom template string
}
```

### 1.5 System Prompt Label Resolution

**Source Location**: `source/crates/codegen/xai-grok-shell/src/util/config/resolve/system_prompt.rs`

System prompt identity label resolution priority:

```
Environment Variable -> User Per-Model Config -> User Global Config -> GB Per-Model Config -> GB Global Config -> "Grok"
```

```rust
pub fn resolve_system_prompt_label_from_tiers(
    user_per_model: Option<String>,
    user_global: Option<String>,
    gb_per_model: Option<String>,
    gb_global: Option<String>,
) -> String {
    // Non-empty validation and tier-by-tier resolution
}
```

### 1.6 Placeholder Rendering

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

## 2. User Context

### 2.1 UserInfo Block

The system prompt includes a user info block:

```xml
<user_info>
OS: {os_name}
Shell: {shell_path}
Workspace Path: {working_directory}
Current Date: {current_date}
</user_info>
```

### 2.2 AGENTS.md Integration

```rust
/// Format AGENTS.md section as <system-reminder> block
pub fn format_agents_md_section(&self) -> Option<String> {
    agents_md::format_agents_md_section(&self.agents_md_files)
}

/// AGENTS.md injected as preset user message
pub fn agents_md_user_reminder(&self) -> Option<String> {
    self.format_agents_md_section()
}
```

AGENTS.md files are discovered in priority order (repo root -> CWD), with deeper files taking precedence.

### 2.3 Role and Persona Instructions

```rust
/// Role instructions stored in persistent identity
pub struct PromptContext {
    pub role_instructions: Option<String>,     // Role description
    pub persona_instructions: Option<String>,  // Persona description
}
```

### 2.4 Memory System Context

```rust
pub struct PromptContext {
    pub memory_enabled: bool,
    pub memory_global_path: Option<String>,
    pub memory_workspace_path: Option<String>,
}
```

When enabled, the system prompt includes a `<memory>` section informing the model about available `memory_search` and `memory_get` tools.

---

## 3. Tool Descriptions

### 3.1 Tool Bridge Rendering

**Source Location**: `source/crates/codegen/xai-grok-tools/src/bridge.rs`

Tool descriptions are rendered via `ToolBridge::render_prompt()`:

```rust
pub async fn render(&self, tool_bridge: &ToolBridge) -> Option<String> {
    let placeholders = self.placeholders();
    let prompt = match self.prompt_mode {
        PromptMode::Extend => {
            // Render base template
            let mut p = tool_bridge.render_prompt(base, &placeholders).await?;
            // Append prompt_body
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

### 3.2 Tool Template Variables

MiniJinja templates use `${{ tools.by_kind.* }}` variables to reference tools:

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

## 4. History Message Processing

### 4.1 CompactionItem Trait

**Source Location**: `source/crates/common/xai-grok-compaction/src/item.rs`

History messages are abstracted through the `CompactionItem` trait:

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

### 4.2 Role Types

```rust
pub enum CompactionRole {
    System,      // System prompt
    Developer,   // Developer prompt
    User,        // User message
    Assistant,   // Assistant output (may contain tool calls)
    Tool,        // Tool result
}
```

### 4.3 Compaction Strategies

**Source Location**: `source/crates/common/xai-grok-compaction/src/history/types.rs`

```rust
pub enum CompactionStrategy {
    /// Basic: Filter and keep important messages
    Basic,
    /// Intra: Keep tail, process step-by-step
    Intra,
    /// Inter: Chunk processing, compress between chunks
    Inter,
    /// FullReplace: Generate summary for full session
    FullReplace,
}
```

### 4.4 Compaction Item Factory

```rust
pub trait CompactionItemFactory: Sized {
    fn new_user(text: String) -> Self;              // User message
    fn new_user_meta(text: String) -> Self;         // Metadata carrier
    fn new_project_instructions(text: String) -> Self; // Project instructions
    fn new_system_reminder(text: String) -> Self;   // System reminder
}
```

### 4.5 History Message Filtering

```rust
// Filter history messages, keeping content needed for basic compaction
pub fn filter_turns_for_basic(items: &[Arc<dyn CompactionItem>]) -> Vec<Arc<dyn CompactionItem>>;

// Build user query preamble
pub fn build_user_queries_preamble(
    prior_summary: Option<&str>,
    user_query: &str,
    attachments: &[CompactionFileRef],
) -> String;
```

---

## 5. Token Budget Management

### 5.1 Token Estimation Constants

**Source Location**: `source/crates/codegen/xai-token-estimation/src/lib.rs`

```rust
/// Character to token estimation ratio
pub const BYTES_PER_TOKEN: u64 = 4;

/// Image token estimation cost
pub const IMAGE_TOKEN_ESTIMATE: u64 = 765;
```

### 5.2 Core Estimation Functions

```rust
/// Estimate token count for a string
#[inline]
pub fn estimate_tokens(s: &str) -> u64 {
    (s.len() as u64) / BYTES_PER_TOKEN
}

/// Convert token budget to character budget
#[inline]
pub fn estimate_chars(tokens: u64) -> u64 {
    tokens.saturating_mul(BYTES_PER_TOKEN)
}

/// Estimate tokens for images
#[inline]
pub fn estimate_image_tokens(image_count: u64) -> u64 {
    image_count.saturating_mul(IMAGE_TOKEN_ESTIMATE)
}
```

### 5.3 Usage Calculation

```rust
/// Calculate usage percentage (f64)
#[inline]
pub fn usage_percentage(used: u64, total: u64) -> f64 {
    if total == 0 {
        0.0
    } else {
        ((used as f64) / (total as f64) * 100.0).min(100.0)
    }
}

/// Calculate usage percentage (rounded to u8)
#[inline]
pub fn usage_percentage_u8(used: u64, total: u64) -> u8 {
    usage_percentage(used, total).round() as u8
}

/// Calculate usage percentage (truncated to u8)
#[inline]
pub fn usage_percentage_truncated_u8(used: u64, total: u64) -> u8 {
    if total == 0 {
        0
    } else {
        ((used.saturating_mul(100) / total).min(100)) as u8
    }
}
```

### 5.4 Free Token Calculation

```rust
/// Calculate free token count
#[inline]
pub fn free_tokens(total: u64, used: u64) -> u64 {
    total.saturating_sub(used)
}
```

### 5.5 Threshold Checking

```rust
/// Check if threshold is exceeded
#[inline]
pub fn exceeds_threshold(used: u64, context_window: u64, threshold_percent: u8) -> bool {
    if context_window == 0 {
        return false;
    }
    used.saturating_mul(100) >= context_window.saturating_mul(threshold_percent as u64)
}

/// Check if threshold is exceeded (with headroom)
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

### 5.6 Default Compaction Threshold

```rust
pub const DEFAULT_AUTO_COMPACT_THRESHOLD_PERCENT: u8 = 85;
```

### 5.7 Threshold Calculation Examples

| Used Tokens | Context Window | Threshold | Result |
|-------------|---------------|-----------|--------|
| 85,000 | 100,000 | 85% | Triggers compaction |
| 84,999 | 100,000 | 85% | Does not trigger |
| 81,000 | 100,000 | 85% (4000 headroom) | Triggers |

---

## Architecture Diagram

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
│                      │  Token Estimation   │───> Compaction │
│                      │  (bytes / 4)        │    Check       │
│                      └─────────────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

---

## Related Source Files

| Module | Path |
|--------|------|
| PromptContext | `source/crates/codegen/xai-grok-agent/src/prompt/context.rs` |
| System Prompt Label Resolution | `source/crates/codegen/xai-grok-shell/src/util/config/resolve/system_prompt.rs` |
| Compaction Core Library | `source/crates/common/xai-grok-compaction/src/lib.rs` |
| Compaction Item Abstraction | `source/crates/common/xai-grok-compaction/src/item.rs` |
| History Message Processing | `source/crates/common/xai-grok-compaction/src/history/mod.rs` |
| Token Estimation | `source/crates/codegen/xai-token-estimation/src/lib.rs` |