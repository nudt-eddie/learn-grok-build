# Lesson 04: Context Assembly

**Source:** `xai-chat-state/src/actor/request_builder.rs`

Context assembly is the process of building the final `ConversationRequest` that gets sent to the inference proxy. This lesson covers the key mechanisms: conversation structure, image compaction, tool result pruning, memory injection, and token budget management.

---

## 1. ConversationRequest Structure

The `ConversationRequest` is the final payload sent to the model. It combines the conversation history with sampling parameters.

**Rust struct fields:**
```rust
ConversationRequest {
    items,                              // ConversationItem[]
    tools: Vec<ToolSpec>,               // Tool definitions
    hosted_tools: Vec<...>,             // MCP tools
    tool_choice: Option<...>,
    model: Option<String>,
    temperature: Option<f32>,
    max_output_tokens: Option<u32>,
    top_p: Option<f32>,
    x_grok_conv_id: Option<String>,
    x_grok_req_id: Option<String>,
    trace: Option<Box<dyn TraceContext>>,
    reasoning_effort: Option<...>,
    // ... headers and metadata
}
```

**Key invariant:** The request starts from an already-repaired conversation state (via `ensure_conversation_integrity()`), so deduplication and repair are O(n) no-ops on the clone.

---

## 2. Image Compaction (50MB Limit)

The inference proxy enforces a hard `MAX_REQUEST_BYTES = 50 * 1024 * 1024` (50MB) body limit. Inline base64 images are the dominant term.

### Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `MAX_REQUEST_BYTES` | 50 MB | Hard ceiling (nginx `proxy-body-size`) |
| `IMAGE_COMPACT_TRIGGER_BYTES` | 47 MB | Gate for eviction (3MB headroom) |
| `IMAGE_COMPACT_RECLAIM_TARGET_BYTES` | 25 MB | Low-water mark after eviction |

**Hysteresis invariant:** The reclaim target is strictly lower than the trigger, ensuring batch eviction keeps the prefix cache-warm across many turns.

### Measurement Strategy

Rather than serializing multi-MB base64 payloads on every turn:
1. Blank image URLs in a clone (cheap: only bumps refcounts)
2. Measure the serialized size of blanked content exactly
3. Add back raw URL lengths (base64 has no JSON escapes)

```rust
fn conversation_body_bytes(conversation: &[ConversationItem]) -> usize {
    let mut blanked = conversation.to_vec();
    let mut image_url_bytes = 0usize;
    for item in &mut blanked {
        if let ConversationItem::User(user) = item {
            for part in &mut user.content {
                if let ContentPart::Image { url } = part {
                    image_url_bytes += url.len();
                    *url = Arc::<str>::from("");  // Blank to measure
                }
            }
        }
    }
    serialized_json_bytes(&blanked) + image_url_bytes
}
```

### Eviction Policy

- **Oldest-first:** Keeps newest images (most useful to the model)
- **Honest placeholder:** Replaced images use a message telling the model not to hallucinate contents:
  ```
  "[An earlier image was removed to keep the request within its size limit 
   and is no longer visible. Do not describe or reason about its contents 
   from memory; ask the user to re-share it if you need to see it again.]"
  ```

---

## 3. Tool Result Pruning (50% Threshold)

Tool results are pruned when context utilization exceeds 50% of the context window.

### Pruning Trigger

```rust
pub(crate) fn should_prune(total_tokens: u64, context_window: NonZeroU64) -> bool {
    total_tokens > context_window.get() / 2  // > 50%, not >= 50%
}
```

### Pruning Strategies

| Strategy | Age | Action |
|----------|-----|--------|
| **Keep** | Recent turns | No modification |
| **Soft Trim** | Middle-aged | Keep head + tail, add separator |
| **Hard Clear** | Very old | Replace with `[Tool result omitted - too old]` |

```rust
// Soft trim: large results get head + tail preserved
let head = safe_char_slice(&content, 0, config.soft_trim_head);
let tail = safe_char_slice_tail(&content, config.soft_trim_tail);
tool_result.content = format!("{head}\n\n[…trimmed…]\n\n{tail}");

// Hard clear: oldest results replaced entirely
tool_result.content = Arc::<str>::from("[Tool result omitted — too old]");
```

### Turn Age Estimation

Turn age is calculated by walking backward through the conversation and counting `User` items.

---

## 4. Memory Reminder Injection

Memory reminders are injected into the system message to maintain long-term context.

### Injection Logic

```rust
pub(super) fn inject_memory_reminder(items: &mut Vec<ConversationItem>, reminder: &str) -> bool {
    if let Some(ConversationItem::System(sys)) = items.first_mut() {
        upsert_memory_reminder_text(&mut sys.content, reminder)
    } else {
        items.insert(0, ConversationItem::system(reminder));
        true
    }
}
```

**Behavior:**
- If system message exists: upsert into it (replace previous reminder section)
- If no system message: prepend a new System item
- Uses `MEMORY_CONTEXT_OPEN_TAG` to locate and replace existing reminders

### Persistence Option

Memory reminders can optionally be persisted to the in-memory conversation state (with snapshot/rebase for active captures).

---

## 5. Token Budget Management

### Build Flow

```
1. Check pruning need (50% threshold)
2. Optionally persist memory reminder to actor state
3. Measure conversation body bytes
4. If mutation needed (prune OR memory OR image compaction):
   a. Clone conversation
   b. Apply image eviction if body >= trigger
   c. Apply pruning if context > 50%
   d. Inject memory reminder if present
5. Assemble ConversationRequest
6. Emit ImageBudget event if images present
```

### Hot Path Optimization

When no mutations are needed (no pruning, no memory reminder, body below trigger), the conversation is cloned directly without intermediate passes.

```rust
let items = if needs_mutation {
    // Clone and apply mutations...
    let mut items = self.state.conversation.clone();
    // Apply compact_images_to_byte_budget, prune_conversation, inject_memory_reminder
    items
} else {
    // Hot path: direct clone, no intermediate passes
    self.state.conversation.clone()
};
```

---

## Python Implementation

```python
"""
Context Assembly - Token budget management, image compaction, and pruning
"""
import json
from dataclasses import dataclass, field
from typing import Optional

# Constants
MAX_REQUEST_BYTES = 50 * 1024 * 1024  # 50 MB hard ceiling
IMAGE_COMPACT_TRIGGER_BYTES = MAX_REQUEST_BYTES - 3 * 1024 * 1024  # 47 MB
IMAGE_COMPACT_RECLAIM_TARGET_BYTES = MAX_REQUEST_BYTES // 2  # 25 MB

HARD_CLEAR_PLACEHOLDER = "[Tool result omitted - too old]"
SOFT_TRIM_SEPARATOR = "\n\n[…trimmed…]\n\n"
IMAGE_COMPACT_PLACEHOLDER = (
    "[An earlier image was removed to keep the request within its size limit "
    "and is no longer visible. Do not describe or reason about its contents "
    "from memory; ask the user to re-share it if you need to see it again.]"
)


@dataclass
class PruningConfig:
    enabled: bool = True
    keep_last_n_turns: int = 2
    hard_clear_age_turns: int = 10
    soft_trim_threshold: int = 5000
    soft_trim_head: int = 1000
    soft_trim_tail: int = 500


@dataclass
class ImageEvictionOutcome:
    evicted: int
    body_bytes_after: int


def conversation_body_bytes(conversation: list) -> int:
    """Measure serialized conversation size without scanning base64."""
    blanked = []
    image_url_bytes = 0
    
    for item in conversation:
        new_item = dict(item) if isinstance(item, dict) else {"type": str(item)}
        
        if new_item.get("type") == "user":
            content = new_item.get("content", [])
            new_content = []
            for part in content:
                if part.get("type") == "image":
                    url = part.get("url", "")
                    image_url_bytes += len(url)
                    new_content.append({"type": "image", "url": ""})
                else:
                    new_content.append(part)
            new_item["content"] = new_content
        
        blanked.append(new_item)
    
    return len(json.dumps(blanked)) + image_url_bytes


def compact_images_to_byte_budget(
    conversation: list,
    current_bytes: int,
    target_bytes: int
) -> ImageEvictionOutcome:
    """Evict oldest images until body fits target budget."""
    if current_bytes <= target_bytes:
        return ImageEvictionOutcome(evicted=0, body_bytes_after=current_bytes)
    
    placeholder_bytes = len(json.dumps({"type": "text", "text": IMAGE_COMPACT_PLACEHOLDER}))
    
    # Collect all images (oldest first)
    images = []
    for i, item in enumerate(conversation):
        if item.get("type") == "user":
            content = item.get("content", [])
            for j, part in enumerate(content):
                if part.get("type") == "image":
                    url = part.get("url", "")
                    frame = f'{{"type":"image","url":""}}'
                    image_bytes = len(frame) + len(url)
                    images.append((i, j, image_bytes))
    
    running = current_bytes
    evicted = 0
    
    for i, j, image_bytes in images:
        if running <= target_bytes:
            break
        
        item = conversation[i]
        content = item.get("content", [])
        content[j] = {"type": "text", "text": IMAGE_COMPACT_PLACEHOLDER}
        running -= max(0, image_bytes - placeholder_bytes)
        evicted += 1
    
    return ImageEvictionOutcome(evicted=evicted, body_bytes_after=running)


def should_prune(total_tokens: int, context_window: int) -> bool:
    """Check if pruning should run based on context utilization."""
    return total_tokens > context_window // 2


def safe_char_slice(s: str, start: int, count: int) -> str:
    """Get a slice of characters from string."""
    return "".join(s[start:start + count]) if len(s) >= start else ""


def safe_char_slice_tail(s: str, count: int) -> str:
    """Get last N characters from string."""
    return s[-count:] if len(s) >= count else s


def prune_conversation(conversation: list, config: PruningConfig) -> None:
    """Prune old tool results based on config."""
    if not config.enabled:
        return
    
    turn_from_end = 0
    seen_first_user = False
    
    for i in range(len(conversation) - 1, -1, -1):
        item = conversation[i]
        
        if item.get("type") == "user":
            if seen_first_user:
                turn_from_end += 1
            seen_first_user = True
            continue
        
        if item.get("type") != "tool_result":
            continue
        
        # Keep recent turns
        if turn_from_end < config.keep_last_n_turns:
            continue
        
        content = item.get("content", "")
        if turn_from_end >= config.hard_clear_age_turns:
            # Hard clear
            if content != HARD_CLEAR_PLACEHOLDER:
                item["content"] = HARD_CLEAR_PLACEHOLDER
            continue
        
        # Soft trim
        if len(content) > config.soft_trim_threshold:
            head = safe_char_slice(content, 0, config.soft_trim_head)
            tail = safe_char_slice_tail(content, config.soft_trim_tail)
            item["content"] = f"{head}{SOFT_TRIM_SEPARATOR}{tail}"


def inject_memory_reminder(conversation: list, reminder: str) -> bool:
    """Inject memory reminder into system message."""
    reminder = reminder.strip()
    if not reminder:
        return False
    
    if conversation and conversation[0].get("type") == "system":
        # Upsert into existing system message
        existing = conversation[0].get("content", "")
        if existing:
            conversation[0]["content"] = f"{existing}\n\n{reminder}"
        else:
            conversation[0]["content"] = reminder
        return True
    else:
        # Prepend new system message
        conversation.insert(0, {"type": "system", "content": reminder})
        return True


def build_conversation_request(
    conversation: list,
    total_tokens: int,
    context_window: int,
    pruning_config: Optional[PruningConfig] = None,
    memory_reminder: Optional[str] = None
) -> dict:
    """Build final ConversationRequest with all optimizations applied."""
    if pruning_config is None:
        pruning_config = PruningConfig()
    
    needs_prune = should_prune(total_tokens, context_window)
    body_bytes = conversation_body_bytes(conversation)
    needs_image_compaction = body_bytes >= IMAGE_COMPACT_TRIGGER_BYTES
    
    needs_mutation = needs_prune or memory_reminder or needs_image_compaction
    
    if needs_mutation:
        # Deep copy for mutation
        items = json.loads(json.dumps(conversation))
        
        if needs_image_compaction:
            compact_images_to_byte_budget(
                items, body_bytes, IMAGE_COMPACT_RECLAIM_TARGET_BYTES
            )
        
        if needs_prune:
            prune_conversation(items, pruning_config)
        
        if memory_reminder:
            inject_memory_reminder(items, memory_reminder)
    else:
        items = conversation
    
    return {"items": items}


# Example usage
if __name__ == "__main__":
    # Sample conversation with images
    conversation = [
        {"type": "system", "content": "You are a helpful assistant."},
        {"type": "user", "content": [
            {"type": "image", "url": "data:image/png;base64," + "A" * 50000},
            {"type": "text", "text": "First image"}
        ]},
        {"type": "assistant", "content": "I see the image."},
        {"type": "tool_result", "content": "x" * 10000},  # Large tool result
    ]
    
    # Build request with optimizations
    request = build_conversation_request(
        conversation=conversation,
        total_tokens=128000,  # Over 50% for 200k context window
        context_window=200000,
        memory_reminder="User prefers concise responses."
    )
    
    print(f"Built request with {len(request['items'])} items")
```

---

## Summary

| Mechanism | Trigger | Action |
|-----------|---------|--------|
| **Image Compaction** | Body >= 47MB | Evict oldest images, keep newest |
| **Tool Pruning** | Tokens > 50% context | Soft trim or hard clear old results |
| **Memory Injection** | Always if provided | Upsert into system message |
| **Hot Path** | No mutations needed | Direct clone, no passes |

This architecture ensures efficient token budget management while maintaining model accuracy and context integrity.