# 会话与状态管理 (Session and State Management)

本文档详细描述 `xai-chat-state` crate 中的会话与状态管理架构，包括核心数据结构、关键流程、API接口和设计模式。

## 概述

`xai-chat-state` 是从 `xai-grok-shell` 的 `acp_session.rs` 提取出来的会话状态管理模块，采用 Actor 模式运行在独立的 tokio 任务中。它管理对话历史、令牌计数、采样配置、凭证等核心状态，并通过事件通道与主会话循环协调。

### 架构图

```
┌────────────────┐                  ┌──────────────────────────────────────┐
│ SessionActor   │ ─── Command ───▶ │        ChatStateActor                │
│  (push_user,   │                  │  (runs in dedicated tokio task)      │
│   build_req)   │                  │                                      │
└────────────────┘                  │  State (no locks needed):            │
                                    │  - conversation: Vec<ConversationItem>│
┌────────────────┐                  │  - sampling_config: SamplingConfig   │
│   Query (e.g.  │ ── Cmd+Oneshot ─▶│  - prompt_index: usize              │
│  get_conv)     │ ◀── Response ────│  - total_tokens: u64                │
└────────────────┘                  │                                      │
                                    │         │ ChatStateEvent             │
                                    │         ▼                            │
                                    │  ┌──────────────────┐               │
                                    │  │ event_tx         │───▶ Session   │
                                    │  └──────────────────┘               │
                                    └──────────────────────────────────────┘
```

## 核心数据结构

### ChatStateConfig

配置 ChatStateActor 初始化时的参数：

```rust
pub struct ChatStateConfig {
    /// 初始对话项列表
    pub initial_conversation: Vec<ConversationItem>,
    /// 采样配置（模型、上下文窗口等）
    pub sampling_config: SamplingConfig,
}
```

### ChatStateSnapshot

Actor 状态的不可变快照，用于会话分叉（fork）和回退（rewind）：

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatStateSnapshot {
    /// 完整对话历史
    pub conversation: Vec<ConversationItem>,
    /// 当前采样配置
    pub sampling_config: SamplingConfig,
    /// 当前提示索引（每个用户轮次递增）
    pub prompt_index: usize,
    /// 累积的令牌使用量
    pub total_tokens: u64,
    /// 上一次响应时的估算值（用于压缩后的重估算）
    pub estimate_at_last_response: u64,
    /// Agent 编辑过的文件路径
    pub agent_edited_paths: BTreeSet<String>,
    /// 回退预览用的缓存提示文本
    pub prompt_texts: Vec<String>,
    /// 当前流开始的时间戳（毫秒）
    pub stream_start_ms: Option<i64>,
    /// 当前轮次开始的时间戳（毫秒）
    pub turn_start_ms: Option<i64>,
    /// 上一次压缩发生的提示索引
    pub last_compaction_prompt_index: Option<usize>,
    /// 凭证密钥
    pub credentials: Credentials,
}
```

### ChatState

内部可变状态，由 Actor 独占拥有，无需锁：

```rust
pub(crate) struct ChatState {
    /// 完整对话历史
    pub conversation: Vec<ConversationItem>,
    /// 当前采样配置
    pub sampling_config: SamplingConfig,
    /// 当前提示索引
    pub prompt_index: usize,
    /// 缓存的提示文本
    pub prompt_texts: Vec<String>,
    /// 累积令牌使用量
    pub total_tokens: u64,
    /// 当前流开始时间戳
    pub stream_start_ms: Option<i64>,
    /// 当前轮次开始时间戳
    pub turn_start_ms: Option<i64>,
    /// Agent 编辑过的文件路径
    pub agent_edited_paths: BTreeSet<String>,
    /// 上一次压缩的提示索引
    pub last_compaction_prompt_index: Option<usize>,
    /// 凭证密钥（API key、可选额外认证、客户端版本）
    pub credentials: Credentials,
    /// 自上次 record_token_usage 后估算的新增令牌数
    pub estimated_tokens_since_model: u64,
    /// 上次响应时的对话估算值
    pub estimate_at_last_response: u64,
    /// 最近一次模型响应的轮次令牌使用
    pub last_turn_usage: Option<TokenUsage>,
    /// 当前提示的计费（下一提示时清除）
    pub prompt_usage: Option<UsageLedger>,
    /// 会话生命周期计费（不持久化）
    pub session_usage: UsageLedger,
    /// 基于偏移量的轮次捕获状态
    pub turn_capture: Option<TurnCaptureState>,
    /// 工具链追踪缓冲区
    pub harness_trace_buffer: Vec<ConversationItem>,
    /// 已密封的工具链追踪轮次
    pub harness_trace_turns: Vec<Vec<ConversationItem>>,
}
```

### TurnCaptureState

追踪当前轮次中属于哪个对话项，无需克隆每个推送的项：

```rust
pub(super) struct TurnCaptureState {
    /// 对话中本轮消息开始的索引
    pub turn_start_offset: usize,
    /// 对话替换前保存的消息
    pub pre_replacement_messages: Vec<ConversationItem>,
    /// 本轮是否发生了压缩
    pub compaction_occurred: bool,
}
```

### Credentials

存储在 Actor 中供请求构建器使用的密钥：

```rust
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Credentials {
    /// API 密钥
    pub api_key: Option<String>,
    /// 认证类型（会话令牌 vs API 密钥）
    pub auth_type: AuthType,
    /// 可选的额外认证材料
    pub alpha_test_key: Option<String>,
    /// 客户端版本字符串
    pub client_version: Option<String>,
}

pub enum AuthType {
    /// 来自 AuthManager（grok 登录、OIDC、外部二进制）
    SessionToken,
    /// 来自用户配置或环境变量
    ApiKey,
}
```

### PruningConfig

工具结果修剪配置，用于释放上下文空间：

```rust
pub struct PruningConfig {
    /// 是否启用修剪
    pub enabled: bool,
    /// 最近 N 个轮次的工具结果永不修剪
    pub keep_last_n_turns: usize,
    /// 旧工具结果软修剪的字符阈值
    pub soft_trim_threshold: usize,
    /// 软修剪时从开头保留的字符数
    pub soft_trim_head: usize,
    /// 软修剪时从结尾保留的字符数
    pub soft_trim_tail: usize,
    /// 工具结果被硬清除（替换为占位符）的轮次年龄
    pub hard_clear_age_turns: usize,
}
```

## 关键流程

### Actor 生命周期

1. **Spawn**: 通过 `ChatStateActor::spawn()` 创建 Actor 和 Handle
2. **Run Loop**: Actor 在独立的 tokio 任务中运行，处理命令
3. **Shutdown**: 通过 cancellation token 或所有 handle 丢弃触发

```rust
impl ChatStateActor {
    pub fn spawn(
        initial_conversation: Vec<ConversationItem>,
        sampling_config: SamplingConfig,
        persistence: Box<dyn ChatPersistence>,
        event_tx: mpsc::UnboundedSender<ChatStateEvent>,
        cancellation_token: CancellationToken,
    ) -> ChatStateHandle
}
```

### 命令处理循环

```rust
async fn run(mut self) {
    loop {
        tokio::select! {
            biased;
            _ = self.cancellation_token.cancelled() => break,
            cmd = self.cmd_rx.recv() => {
                let Some(cmd) = cmd else { break; };
                self.handle_command(cmd);
            }
        }
    }
}
```

### 用户消息推送流程

```
push_user_message(item)
    │
    ├─► ensure_conversation_integrity()  // 修复悬空工具调用
    │
    ├─► 估算新增令牌
    │
    ├─► persistence.persist_message(&item)
    │
    ├─► self.state.conversation.push(item)
    │
    └─► prune_retained_conversation()  // 主动清理旧工具结果
```

### 会话回退流程

```
truncate_to_prompt_index(target)
    │
    ├─► 找到第 N 个 User 消息的位置
    │
    ├─► 截断对话到该位置
    │
    ├─► 重新估算令牌数
    │
    ├─► persistence.replace_history()
    │
    └─► 发送 ConversationReset 事件
```

### 状态快照与恢复

```rust
// 快照
pub(super) fn snapshot(&self) -> ChatStateSnapshot {
    ChatStateSnapshot {
        conversation: self.state.conversation.clone(),
        sampling_config: self.state.sampling_config.clone(),
        prompt_index: self.state.prompt_index,
        total_tokens: self.state.total_tokens,
        // ... 其他字段
    }
}

// 恢复
pub(super) fn restore_snapshot(&mut self, snap: ChatStateSnapshot) {
    self.snapshot_turn_slice();
    self.state.conversation = snap.conversation;
    self.state.sampling_config = snap.sampling_config;
    self.state.prompt_index = snap.prompt_index;
    // ... 恢复其他字段
}
```

## API 接口

### ChatStateHandle

与 Actor 通信的句柄，可以安全克隆并在任务间共享。

#### 变异命令（fire-and-forget）

```rust
impl ChatStateHandle {
    /// 推送用户消息
    pub fn push_user_message(&self, item: ConversationItem);

    /// 推送助手响应
    pub fn push_assistant_response(&self, item: ConversationItem);

    /// 推送工具结果
    pub fn push_tool_result(&self, item: ConversationItem);

    /// 记录令牌使用量
    pub fn record_token_usage(&self, total_tokens: u64);

    /// 递增提示索引
    pub fn increment_prompt_index(&self);

    /// 替换对话历史
    pub fn replace_conversation(&self, items: Vec<ConversationItem>);

    /// 替换对话历史（用于压缩）
    pub fn replace_conversation_for_compaction(&self, items: Vec<ConversationItem>);

    /// 开始捕获轮次消息
    pub fn begin_turn_capture(&self);

    /// 刷新持久化写入
    pub fn flush(&self);
}
```

#### 异步查询命令

```rust
impl ChatStateHandle {
    /// 构建 API 请求
    pub async fn build_request(
        &self,
        tool_definitions: Vec<ToolSpec>,
        memory_reminder: Option<String>,
        persist_memory_reminder: bool,
        trace: Option<Box<dyn TraceContext>>,
        conv_id: String,
        req_id: String,
    ) -> Option<ConversationRequest>;

    /// 获取完整对话
    pub async fn get_conversation(&self) -> Vec<ConversationItem>;

    /// 获取当前提示索引
    pub async fn get_prompt_index(&self) -> usize;

    /// 获取总令牌数
    pub async fn get_total_tokens(&self) -> u64;

    /// 获取采样配置
    pub async fn get_sampling_config(&self) -> Option<SamplingConfig>;

    /// 状态快照
    pub async fn snapshot(&self) -> Option<ChatStateSnapshot>;

    /// 截断到指定提示索引
    pub async fn truncate_to_prompt_index(&self, target: usize);

    /// 检查是否需要自动压缩
    pub async fn check_auto_compact_needed(&self, threshold_percent: u8) -> Option<AutoCompactTrigger>;
}
```

#### 精确查询（避免完整克隆）

```rust
impl ChatStateHandle {
    /// 获取对话长度（无需克隆）
    pub async fn get_conversation_len(&self) -> usize;

    /// 是否有悬空工具调用
    pub async fn has_dangling_tool_calls(&self) -> bool;

    /// 获取最后一条助手文本
    pub async fn get_last_assistant_text(&self) -> Option<String>;

    /// 获取第一条用户文本
    pub async fn get_first_user_text(&self) -> Option<String>;

    /// 获取对话项计数
    pub async fn get_conversation_counts(&self) -> ConversationCounts;

    /// 获取第一条系统消息
    pub async fn get_system_message(&self) -> Option<ConversationItem>;
}
```

## 事件系统

Actor 通过事件通道向会话主循环发送事件：

```rust
pub enum ChatStateEvent {
    /// 提示索引改变
    PromptIndexChanged { new_index: usize },

    /// 令牌计数更新
    TokensUpdated { total_tokens: u64 },

    /// 对话被替换（压缩/回退）
    ConversationReset { new_len: usize },

    /// 图片预算信息
    ImageBudget {
        body_bytes: usize,
        trigger_bytes: usize,
        reclaim_target_bytes: usize,
        inline_images: usize,
        needs_image_compaction: bool,
        evicted: usize,
        body_bytes_after: usize,
    },
}
```

## 持久化接口

```rust
pub trait ChatPersistence: Send + 'static {
    /// 持久化单个对话项
    fn persist_message(&mut self, item: &ConversationItem);

    /// 替换整个对话历史
    fn replace_history(&mut self, items: &[ConversationItem]);

    /// 刷新待写入磁盘的数据
    fn flush(&mut self);
}
```

### 实现变体

- **MockChatPersistence**: 测试用的通道实现
- **NullChatPersistence**: 无操作实现（用于基准测试）

### 持久化流程图

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Persistence Flow                                  │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ push_user_message / push_assistant_response / push_tool_result      │
│    │                                                                  │
│    ▼                                                                  │
│ persist_message(item)                                                │
│    │                                                                  │
│    ├── [可选] 写入 updates.jsonl (append only)                       │
│    └── [可选] 追加到内存缓冲区                                       │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ flush() call (debounced)                                             │
│    │                                                                  │
│    ▼                                                                  │
│ Batch write to disk                                                  │
│    ├── 序列化 conversation 数组                                      │
│    ├── 更新 state.json 原子写入                                      │
│    └── 确保文件系统同步 (fsync)                                       │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ truncate_to_prompt_index / replace_conversation_for_compaction      │
│    │                                                                  │
│    ▼                                                                  │
│ replace_history(new_items)                                           │
│    ├── 清除旧文件                                                    │
│    ├── 写入新的 updates.jsonl                                        │
│    └── 更新 state.json                                               │
└─────────────────────────────────────────────────────────────────────┘
```

### 持久化文件结构

典型会话目录结构：
```
session_dir/
├── state.json           # Actor 快照状态 (ChatStateSnapshot)
│                        # - conversation 完整历史
│                        # - sampling_config
│                        # - prompt_index
│                        # - total_tokens
│                        # - credentials (加密)
│
├── updates.jsonl        # 追加式对话项日志
│                        # 每行一个 ConversationItem JSON
│                        # 用于快速重放和增量恢复
│
└── segments/            # CompactionMode::Segments 时使用
    ├── summary.md       # 压缩摘要
    ├── turn_001.md      # 分段轮次详情
    ├── turn_002.md
    └── ...
```

### 恢复流程

```
Session Startup
      │
      ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 1. Load state.json                                                   │
│    - 解析 ChatStateSnapshot                                          │
│    - 恢复 conversation, prompt_index, tokens 等                      │
└─────────────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 2. [可选] Replay updates.jsonl                                       │
│    - 按时间顺序回放每条记录                                          │
│    - 验证数据完整性                                                  │
│    - 处理可能的部分写入 (recovery)                                   │
└─────────────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 3. ensure_conversation_integrity()                                   │
│    - 检测悬空工具调用                                                │
│    - 修复数据不一致状态                                              │
└─────────────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 4. Actor Ready                                                       │
│    - ChatStateActor 运行中                                          │
│    - 接收命令并响应查询                                              │
└─────────────────────────────────────────────────────────────────────┘
```

### 原子性保证

- `replace_history()` 使用原子文件操作
- 写入临时文件后 rename，避免部分写入
- 崩溃恢复通过 `updates.jsonl` 重放实现

## 设计模式

### 1. Actor 模式

- Actor 运行在独立的 tokio 任务中
- 所有状态由 Actor 独占，无需锁
- 通过 mpsc 通道接收命令
- 通过 oneshot 通道返回查询响应

### 2. 命令模式

```rust
pub enum ChatStateCommand {
    // 变异命令
    PushUserMessage { item: ConversationItem },
    ReplaceConversation { items: Vec<ConversationItem>, is_compaction: bool },
    // ...
    
    // 查询命令
    GetConversation { reply: oneshot::Sender<Vec<ConversationItem>> },
    Snapshot { reply: oneshot::Sender<ChatStateSnapshot> },
    // ...
}
```

### 3. 写边界完整性修复

完整性修复仅在写边界调用：

- `ChatState::new()` - 启动时
- `push_user_message()` - 新轮次开始时
- `BuildConversationRequest` - 构建请求前

不在读处理程序中调用，避免将进行中的工具调用误判为悬空。

### 4. 轮次捕获模式

使用偏移量而非复制每个项：

```rust
pub(super) struct TurnCaptureState {
    turn_start_offset: usize,  // 捕获开始时的对话长度
    pre_replacement_messages: Vec<ConversationItem>,  // 替换前保存的消息
    compaction_occurred: bool,
}
```

### 5. 令牌估算

使用 bytes/4 估算，无需真实分词：

```rust
pub fn estimate_item_tokens(item: &ConversationItem) -> u64 {
    // 图片按固定常量计
    // 文本按字节/4
    // ...
}
```

### 6. 凭证不透明存储

Actor 存储凭证但从不解释它们：

```rust
pub struct Credentials {
    pub api_key: Option<String>,
    pub auth_type: AuthType,
    pub alpha_test_key: Option<String>,
    pub client_version: Option<String>,
}
```

## 压缩模式 (Compaction)

### 压缩算法流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Compaction Flow                                  │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 1. Trigger Check: check_auto_compact_needed(threshold_percent)      │
│    - 计算 current_tokens / max_context_tokens                       │
│    - 返回 AutoCompactTrigger { reason, ... } 当超过阈值             │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 2. Capture Context: CompactionStateContext                          │
│    - recent_messages: 最近消息                                       │
│    - last_user_query: 最后用户查询                                   │
│    - agent_edited_paths: Agent 编辑过的文件                         │
│    - running_tasks/subagents: 后台任务状态                          │
│    - connected_mcp_servers: MCP 服务器连接                          │
│    - todos: Todo 列表                                               │
└─────────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         ┌─────────┐    ┌──────────┐    ┌───────────┐
         │ Summary │    │Transcript│    │ Segments  │
         │  Mode   │    │  Mode    │    │   Mode    │
         └────┬────┘    └────┬─────┘    └─────┬─────┘
              │              │                │
              ▼              ▼                ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 3. Build Summary / Transcript / Segments                            │
│    - is_real_user_turn() 过滤真实用户轮次                          │
│    - 工具结果按 PruningConfig 策略修剪                               │
│    - 保留最近 N 轮完整，旧轮摘要化                                   │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 4. Replace Conversation                                              │
│    - replace_conversation_for_compaction(new_items)                 │
│    - 更新 last_compaction_prompt_index                               │
│    - persistence.replace_history(new_items)                         │
│    - 发送 ConversationReset 事件                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### CompactionMode

定义压缩后模型如何访问历史详情：

```rust
pub enum CompactionMode {
    /// 仅摘要（默认）
    Summary,
    /// 摘要 + 指向完整原始 updates.jsonl 的指针
    Transcript,
    /// 摘要 + 压缩文件夹中的分段 markdown
    Segments(CompactionDetail),
}

pub enum CompactionDetail {
    None,      // 仅统计
    Minimal,   // 每轮一行工具签名
    Balanced,  // 工具调用 + 截断响应
    Verbose,   // 完整逐字轮次
}
```

### 压缩上下文

压缩时捕获的会话状态：

```rust
pub struct CompactionStateContext {
    /// 自上一次真实用户轮次以来的消息
    pub recent_messages: Vec<ConversationItem>,
    /// 最后一个真实用户查询文本
    pub last_user_query: Option<String>,
    /// Agent 编辑过的文件
    pub agent_edited_paths: Vec<String>,
    /// 运行中的后台任务
    pub running_tasks: Vec<BackgroundTaskSummary>,
    /// 仍在运行的子代理
    pub running_subagents: Vec<RunningSubagentSummary>,
    /// 已连接的 MCP 服务器
    pub connected_mcp_servers: Vec<CompactionServerSummary>,
    /// Todo 列表
    pub todos: Vec<TodoSummary>,
}
```

### PruningConfig 修剪策略

工具结果修剪策略影响压缩质量：

```
PruningConfig Behavior:
                        
Messages in Conversation
├── Recent N turns (keep_last_n_turns)
│   └── 工具结果完整保留
│
└── Older turns
    ├── Age < hard_clear_age_turns
    │   └── 软修剪: 保留 head + tail 字符
    │       ├── soft_trim_threshold 以下: 完整保留
    │       └── 超过阈值: 保留 soft_trim_head + soft_trim_tail
    │
    └── Age >= hard_clear_age_turns
        └── 硬清除: 替换为占位符文本
```

## 计费系统 (Usage)

### UsageLedger

按提示和会话追踪计费：

```rust
pub struct UsageTotals {
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub cached_read_tokens: u64,
    pub reasoning_tokens: u64,
    pub model_calls: u64,
    pub api_duration_ms: u64,
    pub cost_usd_ticks: Option<i64>,
    pub cost_missing_calls: u64,
}

pub struct UsageLedger {
    pub totals: UsageTotals,
    pub by_model: IndexMap<String, UsageTotals>,
    pub main_loop_model_calls: u64,
    pub incomplete: bool,  // 计费可能不完整
}
```

### 完整性所有权

- `UsageLedger.incomplete`: 账单快照上持久化
- Sticky flag: 仅报告级别信号
- Foreground live IDs: 折叠可能仍会发生
- Background live: 从不等待，立即标记不完整

## 真实用户识别

区分真实用户轮次和合成注入：

```rust
pub fn is_real_user_turn(item: &ConversationItem) -> bool {
    match item {
        ConversationItem::User(u) => {
            // synthetic_reason 非空 = 非真实
            if u.synthetic_reason.is_some() {
                return false;
            }
            // 有图片 = 真实
            if has_images { return true; }
            // 提取的查询文本是合成的？
            !is_synthetic_extracted_query(&extracted)
        }
        _ => false,
    }
}
```

合成轮次包括：
- 系统提醒
- 自动继续提示
- 仅包含元数据的引导消息

## 文件结构

```
xai-chat-state/src/
├── lib.rs              # 模块导出和公开 API
├── actor/
│   ├── mod.rs          # ChatStateActor 主模块
│   ├── state.rs        # ChatState 内部状态
│   ├── mutations.rs    # 状态变更处理
│   ├── queries.rs      # 只读查询处理
│   ├── request_builder.rs  # 请求构建逻辑
│   └── tests.rs        # Actor 测试
├── commands.rs         # ChatStateCommand 枚举
├── events.rs           # ChatStateEvent 枚举
├── handle.rs           # ChatStateHandle 实现
├── persistence.rs      # ChatPersistence trait 和实现
├── types.rs            # 共享域类型
├── compaction_mode.rs  # 压缩模式定义
├── compaction_transcript.rs  # 分段 markdown 渲染
├── compaction_utils.rs # 压缩工具函数
├── conversation_util.rs # 对话工具函数
└── usage.rs            # 计费分类账
```

## 使用示例

### 创建 Actor

```rust
let (event_tx, _event_rx) = mpsc::unbounded_channel();
let cancellation_token = CancellationToken::new();
let persistence = Box::new(MockChatPersistence::new());

let handle = ChatStateActor::spawn(
    initial_conversation,
    sampling_config,
    persistence,
    event_tx,
    cancellation_token,
);
```

### 推送消息

```rust
handle.push_user_message(ConversationItem::user("Hello!"));
handle.increment_prompt_index();
handle.push_assistant_response(ConversationItem::assistant("Hi there!"));
handle.push_tool_result(ConversationItem::tool_result("call-1", "result"));
```

### 构建请求

```rust
let request = handle
    .build_request(
        tool_definitions,
        memory_reminder,
        false,
        None,
        conv_id,
        req_id,
    )
    .await;
```

### 会话回退

```rust
handle.truncate_to_prompt_index(2).await;
```

### 状态快照与恢复

```rust
let snapshot = handle.snapshot().await.unwrap();
handle.restore_snapshot(snapshot);
```

## 线程安全

- `ChatStateHandle` 是 `Clone + Send + 'static`
- 可以安全地在多个任务间共享
- Actor 运行在独立的任务中，顺序处理所有命令
- 无需外部同步机制

## 错误处理

- 命令发送失败（Actor 死亡）返回 `None` 或 `Err(())`
- 查询响应丢失（Actor 死亡）返回 `None`
- 完整性修复拒绝（轮次进行中）返回 `RepairHistoryBlocked`

```rust
pub struct RepairHistoryBlocked;

impl std::fmt::Display for RepairHistoryBlocked {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "cannot repair history while a turn is in flight")
    }
}
```

## 测试

模块包含全面的单元测试：

- 命令变体构造测试
- 状态默认初始化测试
- 令牌估算测试
- 压缩摘要格式测试
- 真实用户识别测试
- 持久化模拟测试

运行测试：

```bash
cargo test -p xai-chat-state
```