# Prompt System

> This section analyzes the prompt templating, composition, and rendering system in Grok Build.

## 1. Overview

The Prompt System is the core of how Grok Build communicates with language models. It handles:

- **Template Rendering**: Compile-time Tera templates with conditional logic
- **System Prompt Composition**: Layered assembly of core + mode + tools + context
- **Multi-Mode Support**: Interactive TUI, headless, and subagent modes
- **Role-Based Instructions**: Role definitions and persona overrides

## 2. Architecture

```
Prompt System Architecture
───────────────────────────────────────────────────────
                                                       │
┌─────────────────────────────────────────────────────┐│
│                  Template Files                      ││
│  ┌───────────────────────────────────────────────┐  ││
│  │ prompt.md          (Main agent prompt)        │  ││
│  │ subagent_prompt.md (Subagent prompt)          │  ││
│  │ apply_patch_prompt.md (Patch-only mode)       │  ││
│  └───────────────────────────────────────────────┘  ││
└──────────────────────┬──────────────────────────────┘│
                       │ codegen                        │
                       ▼                                │
┌─────────────────────────────────────────────────────┐│
│              Tera Template Engine                    ││
│  ┌───────────────────────────────────────────────┐  ││
│  │ Conditionals: {%- if ... -%}                  │  ││
│  │ Variables: ${{ variable_name }}               │  ││
│  │ Loops: {%- for ... -%}                        │  ││
│  └───────────────────────────────────────────────┘  ││
└──────────────────────┬──────────────────────────────┘│
                       │ render()                       │
                       ▼                                │
┌─────────────────────────────────────────────────────┐│
│              PromptContext (Runtime)                 ││
│  ┌───────────────────────────────────────────────┐  ││
│  │ system_prompt_label     is_non_interactive    │  ││
│  │ tools (by_kind)        is_subagent            │  ││
│  │ role_instructions      persona_instructions   │  ││
│  │ memory_enabled         current_date           │  ││
│  │ os_name                shell_path             │  ││
│  │ working_directory                             │  ││
│  └───────────────────────────────────────────────┘  ││
└─────────────────────────────────────────────────────┘│
```

## 3. Template Files

### 3.1 Main Prompt (prompt.md)

The primary prompt template for the main agent:

```rust
You are ${{ system_prompt_label }} released by xAI. You are ${%- if is_non_interactive %} an autonomous agent that completes software engineering tasks.${%- else %} an interactive CLI tool that helps users with software engineering tasks.${%- endif %} Your main goal is to complete the user's request, denoted within the <user_query> tag.
```

Key sections include:
- **Action Safety**: Risk assessment guidelines for destructive operations
- **Tool Calling**: When to use specialized tools vs bash
- **Background Tasks**: Monitoring with `${{ tools.by_kind.monitor }}`
- **Output Efficiency**: Writing style guidelines
- **Formatting**: Markdown rendering expectations
- **User Guide**: TUI documentation references

### 3.2 Subagent Prompt (subagent_prompt.md)

Focused instructions for spawned subagents:

```
You are a coding agent running in the Grok Build CLI, a terminal-based coding assistant. You are expected to be precise, safe, and helpful.
```

Key characteristics:
- No reproduction of prompt contents to user
- Personality: concise, direct, friendly
- AGENTS.md spec compliance
- Planning tool integration
- Task execution until completion

### 3.3 Apply Patch Prompt (apply_patch_prompt.md)

Minimal prompt for patch application mode:

```
You are a Grok Build subagent — a focused worker delegated a specific task.
```

Features:
- Parallel tool calls in single response
- Hashline workflow for targeted edits
- Project instruction file (AGENTS.md) support
- Memory and role-based instructions

## 4. Template Syntax

### 4.1 Variables

```tera
${{ system_prompt_label }}           {{ ! String interpolation }}
${{ tools.by_kind.read }}            {{ ! Nested object access }}
${{ params.execute.is_background }}  {{ ! Conditional parameter }}
```

### 4.2 Conditionals

```tera
{%- if is_non_interactive -%}
  autonomous agent mode
{%- else -%}
  interactive CLI mode
{%- endif -%}

{%- if tools.by_kind.read -%}
  Use ${{ tools.by_kind.read }} for reading
{%- endif -%}
```

### 4.3 Existence Checks

```tera
{%- if tools.by_kind.monitor %}
  <background_tasks>...</background_tasks>
{%- endif %}
```

Note: Tera treats missing variables as empty strings, so explicit existence checks are needed for optional sections.

## 5. Prompt Context

### 5.1 Runtime Context Structure

```rust
pub struct PromptContext {
    pub system_prompt_label: String,        // "Grok Build"
    pub is_non_interactive: bool,           // Headless mode flag
    pub is_subagent: bool,                  // Subagent flag
    pub tools: ToolSetContext,              // Available tools by kind
    pub role_instructions: Option<String>,  // Role override
    pub persona_instructions: Option<String>, // Persona override
    pub memory_enabled: bool,               // Memory system enabled
    pub current_date: String,               // Current date string
    pub os_name: String,                    // OS identifier
    pub shell_path: String,                 // Shell executable path
    pub working_directory: String,          // Current working directory
}
```

### 5.2 Tool Context

```rust
pub struct ToolSetContext {
    pub by_kind: HashMap<ToolKind, String>,  // Tool name by kind
    // Example: { "read": "hashline_read", "edit": "search_replace" }
}
```

## 6. Safety and Action Guidelines

### 6.1 Risk Categories

The prompt distinguishes three risk levels:

| Level | Examples | Behavior |
|-------|----------|----------|
| **Low** | Edit files, run tests | Act freely |
| **Medium** | Git push, destructive ops | Confirm first |
| **High** | Force-push, drop DB, rm -rf | Confirm + context |

### 6.2 Safety Rules

```
Weigh each action by how easily it can be undone and how far its effects reach.
Local, reversible work such as editing files and running tests is fine to do freely.
Before executing any actions that are hard to reverse, reach shared external systems,
or are otherwise risky or destructive, check with the user first.
```

## 7. Output Guidelines

### 7.1 Writing Style

- Write like an excellent technical blog post
- Precise, well-structured, and clear
- Complete sentences and good grammar
- Prefer simple, accessible language
- Keep responses proportional to task complexity

### 7.2 Formatting Rules

- **Section Headers**: `**Title Case**`, 1-3 words, descriptive
- **Bullets**: `-` followed by space, group related points
- **Monospace**: Commands, file paths, env vars in backticks
- **File References**: Include line numbers, use clickable paths

### 7.3 Tone

- Collaborative and natural
- Present tense and active voice
- Concise and factual
- No filler or unnecessary repetition

## 8. Tool Integration

### 8.1 Tool Selection Preference

```
Use specialized tools instead of bash commands when possible.
- ${{ tools.by_kind.read }} for reading files
- ${{ tools.by_kind.edit }} for editing and creating files
Reserve bash exclusively for system commands.
```

### 8.2 Tool Kind Mapping

| ToolKind | Example Tool | Purpose |
|----------|--------------|---------|
| Read | `hashline_read` | File reading |
| Edit | `search_replace` | File editing |
| Bash | `run_terminal_cmd` | Shell execution |
| Monitor | `scheduler_*` | Background tasks |
| Memory | `memory_*` | Memory operations |
| Plan | `todo_write` | Task planning |
| Web | `web_search` | Internet search |

## 9. AGENTS.md Spec

### 9.1 Scope Rules

```
- Scope: entire directory tree rooted at the containing folder
- Apply to every file touched in the final patch
- More deeply nested files take precedence
- Direct instructions override AGENTS.md
```

### 9.2 Content Types

- Coding conventions and style guides
- Project structure explanations
- Build and test instructions
- PR description requirements

## 10. Subagent Communication

### 10.1 Message Types

| Type | Description | Usage |
|------|-------------|-------|
| Preamble | Brief description before tool calls | Logically grouped actions |
| Progress Update | Concise recap (8-10 words) | Long tasks |
| Final Answer | Structured results | Completed work |

### 10.2 Preamble Guidelines

```
- Logically group related actions
- Keep concise (8-12 words)
- Build on prior context
- Light, friendly tone
- Pair with tool calls in same response
```

## 11. Key Source Files

| File | Purpose |
|------|---------|
| `templates/prompt.md` | Main agent prompt template |
| `templates/subagent_prompt.md` | Subagent prompt template |
| `templates/apply_patch_prompt.md` | Apply patch prompt template |
| `codegen/src/prompt.rs` | Template codegen and rendering |
| `xai-grok-agent/src/prompt_context.rs` | Runtime context structure |

## 12. Summary

The Prompt System provides:

1. **Template Flexibility**: Compile-time Tera templates with conditional logic
2. **Multi-Mode Support**: Interactive TUI, headless, and subagent variants
3. **Safety Integration**: Built-in risk assessment and confirmation workflows
4. **Tool Coordination**: Dynamic tool name injection by kind
5. **Role-Based Customization**: Role and persona instruction overrides
6. **Consistent Output**: Style guidelines embedded in prompts

The template-based approach allows Grok Build to generate contextually appropriate prompts for different scenarios while maintaining consistency in agent behavior and output quality.