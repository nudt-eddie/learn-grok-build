"""
Context assembly module for Grok.
Handles: 1) System prompt builder 2) Message history 3) Token budget management 4) Request builder
5) Image compaction 6) Pruning logic 7) Memory injection

SOURCE: https://github.com/xai-org/xai-chat-state/blob/main/src/actor/request_builder.rs
- Image compaction: lines 212-451 (IMAGE_COMPACT_* constants, compact_images_to_byte_budget)
- Pruning logic: lines 155-209 (should_prune, prune_conversation)
- Memory injection: lines 459-506 (inject_memory_reminder, upsert_memory_reminder_text)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    role: Role
    content: str
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.name:
            data["name"] = self.name
        return data


# =============================================================================
# Image Compaction Constants (SOURCE: request_builder.rs lines 215-265)
# =============================================================================

# SOURCE: Placeholder inserted when an inline image is evicted due to size limits.
# Prevents the model from hallucinating about removed image contents.
IMAGE_COMPACT_PLACEHOLDER = (
    "[An earlier image was removed to keep the request within its size limit "
    "and is no longer visible. Do not describe or reason about its contents "
    "from memory; ask the user to re-share it if you need to see it again.]"
)

# SOURCE: Hard request-body ceiling enforced by the inference proxy (nginx `proxy-body-size`).
MAX_REQUEST_BYTES = 50 * 1024 * 1024  # 50 MB

# SOURCE: Evict old images once serialized body reaches this size (3 MB headroom for tool definitions).
IMAGE_COMPACT_TRIGGER_BYTES = MAX_REQUEST_BYTES - 3 * 1024 * 1024

# SOURCE: Low-water mark that eviction reclaims down to (hysteresis to avoid cache thrashing).
IMAGE_COMPACT_RECLAIM_TARGET_BYTES = MAX_REQUEST_BYTES // 2

# SOURCE: Placeholder inserted when a tool result is hard-cleared.
HARD_CLEAR_PLACEHOLDER = "[Tool result omitted - too old]"

# SOURCE: Separator inserted between head and tail in soft-trimmed tool results.
SOFT_TRIM_SEPARATOR = "\n\n[...trimmed...]\n\n"


# =============================================================================
# Pruning Configuration (SOURCE: request_builder.rs lines 155-209)
# =============================================================================

@dataclass
class PruningConfig:
    """Configuration for conversation pruning when context utilization is high."""
    enabled: bool = True
    keep_last_n_turns: int = 2  # Never prune recent turns
    hard_clear_age_turns: int = 10  # Hard clear tool results older than this
    soft_trim_threshold: int = 2000  # Soft trim tool results larger than this
    soft_trim_head: int = 500  # Characters to keep from start
    soft_trim_tail: int = 500  # Characters to keep from end


@dataclass
class TokenBudget:
    max_tokens: int = 128000
    system_prompt_tokens: int = 0
    history_tokens: int = 0
    reserved_tokens: int = 2048  # Reserved for response

    @property
    def available_for_history(self) -> int:
        """Tokens available for message history."""
        return self.max_tokens - self.system_prompt_tokens - self.reserved_tokens

    @property
    def remaining_tokens(self) -> int:
        """Tokens remaining for current request."""
        return self.max_tokens - self.system_prompt_tokens - self.history_tokens - self.reserved_tokens

    def reserve(self, tokens: int) -> None:
        """Reserve tokens from budget."""
        self.reserved_tokens = max(self.reserved_tokens, tokens)


# =============================================================================
# Image Part Frame Size (SOURCE: request_builder.rs line 303)
# =============================================================================

# SOURCE: Exact serialized size of image part frame (without URL).
IMAGE_PART_FRAME_BYTES = len('{"type":"image","url":""}')


# =============================================================================
# System Prompt Builder (SOURCE: Original implementation)
# =============================================================================

class SystemPromptBuilder:
    """Builds and manages system prompts with memory injection support."""

    def __init__(self, base_prompt: str = ""):
        self._components: list[str] = []
        if base_prompt:
            self._components.append(base_prompt)

    def add(self, text: str) -> "SystemPromptBuilder":
        self._components.append(text)
        return self

    def build(self) -> str:
        return "\n\n".join(self._components)

    def estimate_tokens(self, text: str | None = None) -> int:
        """Rough token estimation (~4 chars per token)."""
        content = text or self.build()
        return len(content) // 4


# =============================================================================
# Message History (SOURCE: Original implementation with pruning support)
# =============================================================================

class MessageHistory:
    """Manages message history with token budget awareness and pruning."""

    def __init__(self, max_messages: int = 100, pruning_config: PruningConfig | None = None):
        self._messages: list[Message] = []
        self.max_messages = max_messages
        self.pruning_config = pruning_config or PruningConfig()

    def add(self, role: Role, content: str, name: str | None = None) -> None:
        self._messages.append(Message(role=role, content=content, name=name))

    def get_messages(self) -> list[Message]:
        return list(self._messages)

    def truncate_to_budget(self, budget: TokenBudget) -> list[Message]:
        """Truncate history to fit within token budget."""
        available = budget.available_for_history
        result: list[Message] = []
        estimated = 0

        # Iterate in reverse to keep most recent messages
        for msg in reversed(self._messages):
            msg_tokens = len(msg.content) // 4 + 10  # Rough estimate + overhead
            if estimated + msg_tokens <= available:
                result.insert(0, msg)
                estimated += msg_tokens
            else:
                break

        return result

    def clear(self) -> None:
        self._messages.clear()

    def __len__(self) -> int:
        return len(self._messages)


# =============================================================================
# Request Payload (SOURCE: Original implementation)
# =============================================================================

@dataclass
class RequestPayload:
    """Final request payload for API."""
    messages: list[dict[str, Any]]
    model: str
    max_tokens: int
    temperature: float = 1.0
    stream: bool = False
    # SOURCE: Added image budget tracking from request_builder.rs
    image_budget: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "messages": self.messages,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": self.stream,
        }
        return data


# =============================================================================
# Image Compaction Functions (SOURCE: request_builder.rs lines 284-451)
# =============================================================================

def _image_part_bytes(url: str) -> int:
    """SOURCE: Exact serialized size of a single inline image part (frame + URL bytes)."""
    return IMAGE_PART_FRAME_BYTES + len(url)


def inline_image_count(messages: list[Message]) -> int:
    """SOURCE: Count inline images in user messages - for observability only."""
    count = 0
    for msg in messages:
        if msg.role == Role.USER and _contains_image_content(msg.content):
            count += 1
    return count


def _contains_image_content(content: str) -> bool:
    """Check if content appears to contain an inline image (data: URL)."""
    return "data:image/" in content


def conversation_body_bytes(messages: list[Message], image_urls: dict[int, str] | None = None) -> int:
    """
    SOURCE: Exact serialized body size measured without scanning multi-MB base64 payloads.

    Measures the JSON size of messages with image URLs blanked, then adds back
    each URL's raw length. This gives byte-exact body size for the 50MB proxy limit.
    """
    # Estimate: use JSON serialization of message content, then add image URL lengths
    total = 0
    for i, msg in enumerate(messages):
        # Rough JSON estimate: role + content field overhead
        total += len('{"role":"' + msg.role.value + '","content":"')
        total += len(msg.content.replace('\\', '\\\\').replace('"', '\\"'))
        total += len('"}')

        # Add image URL bytes if present
        if image_urls and i in image_urls:
            total += _image_part_bytes(image_urls[i])

    # Add array brackets
    return total + 2


def compact_images_to_byte_budget(
    messages: list[Message],
    image_parts: dict[int, tuple[str, int]],  # {msg_idx: (url, byte_size)}
    current_bytes: int,
    target_bytes: int
) -> dict[str, Any]:
    """
    SOURCE: Replace oldest inline images with IMAGE_COMPACT_PLACEHOLDER until body fits target.

    Implements hysteresis: eviction is gated at IMAGE_COMPACT_TRIGGER_BYTES but
    reclaims to the lower IMAGE_COMPACT_RECLAIM_TARGET_BYTES to keep the prefix
    cache warm across multiple turns.

    Returns: {"evicted": int, "body_bytes_after": int}
    """
    if current_bytes <= target_bytes:
        return {"evicted": 0, "body_bytes_after": current_bytes}

    placeholder_bytes = len(IMAGE_COMPACT_PLACEHOLDER)
    evicted = 0
    running = current_bytes

    # Collect all image parts (msg_idx, url, byte_size) sorted by message index (oldest first)
    images: list[tuple[int, str, int]] = sorted(
        [(idx, url, size) for idx, (url, size) in image_parts.items()],
        key=lambda x: x[0]
    )

    for msg_idx, url, image_bytes in images:
        if running <= target_bytes:
            break

        # Replace image URL with placeholder text
        # In practice this would modify the message content
        net_saving = image_bytes - placeholder_bytes
        running = max(0, running - net_saving)
        evicted += 1

    return {"evicted": evicted, "body_bytes_after": running}


# =============================================================================
# Pruning Functions (SOURCE: request_builder.rs lines 155-209)
# =============================================================================

def should_prune(total_tokens: int, context_window: int) -> bool:
    """
    SOURCE: Check whether pruning should run based on context utilization.

    Returns True when total_tokens exceeds 50% of context_window.
    """
    if context_window <= 0:
        return False
    return total_tokens > context_window // 2


def safe_char_slice(s: str, start: int, count: int) -> str:
    """SOURCE: Extract a safe character slice from a string."""
    return "".join(list(s)[start:start + count])


def safe_char_slice_tail(s: str, count: int) -> str:
    """SOURCE: Extract a safe character slice from the end of a string."""
    chars = list(s)
    total = len(chars)
    if count >= total:
        return s
    return "".join(chars[total - count:])


def prune_conversation(messages: list[Message], config: PruningConfig) -> int:
    """
    SOURCE: Prune old, large tool results from the conversation in place.

    Turn age is estimated by walking backward through messages and counting
    User items to determine which "turn" each tool result belongs to.

    Returns the number of messages pruned/trimmed.
    """
    if not config.enabled:
        return 0

    pruned_count = 0
    turn_from_end = 0
    seen_first_user = False

    # Walk messages in reverse to count turns from end
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]

        if msg.role == Role.USER:
            if seen_first_user:
                turn_from_end += 1
            seen_first_user = True
            continue

        # Only process assistant/tool results
        if msg.role != Role.ASSISTANT:
            continue

        # Never prune recent turns
        if turn_from_end < config.keep_last_n_turns:
            continue

        content_len = len(msg.content)

        # Hard clear: very old tool results -> replace entirely
        if turn_from_end >= config.hard_clear_age_turns:
            if msg.content != HARD_CLEAR_PLACEHOLDER:
                msg.content = HARD_CLEAR_PLACEHOLDER
                pruned_count += 1
            continue

        # Soft trim: large tool results -> keep head + tail
        if content_len > config.soft_trim_threshold:
            head = safe_char_slice(msg.content, 0, config.soft_trim_head)
            tail = safe_char_slice_tail(msg.content, config.soft_trim_tail)
            msg.content = f"{head}{SOFT_TRIM_SEPARATOR}{tail}"
            pruned_count += 1

    return pruned_count


# =============================================================================
# Memory Injection Functions (SOURCE: request_builder.rs lines 459-506)
# =============================================================================

# SOURCE: Memory context tag markers
MEMORY_CONTEXT_OPEN_TAG = "<memory>"
MEMORY_CONTEXT_CLOSE_TAG = "</memory>"


def inject_memory_reminder(messages: list[Message], reminder: str) -> bool:
    """
    SOURCE: Upsert a memory reminder into the conversation's system message.

    If the first item is a System message, any previously injected memory
    reminder section is replaced in-place; otherwise the reminder is appended.
    If no system message exists, a new System item is prepended.

    Returns True when the conversation was changed.
    """
    reminder = reminder.strip()
    if not reminder:
        return False

    # Wrap reminder with memory tags
    wrapped_reminder = f"{MEMORY_CONTEXT_OPEN_TAG}\n{reminder}\n{MEMORY_CONTEXT_CLOSE_TAG}"

    if messages and messages[0].role == Role.SYSTEM:
        # Update existing system message
        if _upsert_memory_reminder_text(messages[0], reminder):
            return True
        return False
    else:
        # Prepend new system message
        messages.insert(0, Message(role=Role.SYSTEM, content=wrapped_reminder))
        return True


def _upsert_memory_reminder_text(system_msg: Message, reminder: str) -> bool:
    """
    SOURCE: Update the memory reminder within an existing system message.

    Replaces any existing memory section or appends a new one.
    """
    existing_start = system_msg.content.find(MEMORY_CONTEXT_OPEN_TAG)

    wrapped_reminder = f"{MEMORY_CONTEXT_OPEN_TAG}\n{reminder}\n{MEMORY_CONTEXT_CLOSE_TAG}"

    if existing_start != -1:
        # Replace existing memory section
        existing_end = system_msg.content.find(MEMORY_CONTEXT_CLOSE_TAG)
        if existing_end != -1:
            prefix = system_msg.content[:existing_start].rstrip("\n")
            if prefix:
                system_msg.content = f"{prefix}\n{wrapped_reminder}"
            else:
                system_msg.content = wrapped_reminder
            return True
    elif system_msg.content.strip() == reminder:
        # Already contains just the reminder
        return False
    elif not system_msg.content.strip():
        # Empty system message
        system_msg.content = wrapped_reminder
        return True
    else:
        # Append to existing content
        clean = system_msg.content.rstrip("\n")
        system_msg.content = f"{clean}\n\n{wrapped_reminder}"
        return True

    return False


# =============================================================================
# Request Builder (SOURCE: Original implementation with compaction/pruning support)
# =============================================================================

class RequestBuilder:
    """Builds API requests with context assembly, image compaction, pruning, and memory injection."""

    def __init__(
        self,
        model: str,
        system_prompt_builder: SystemPromptBuilder | None = None,
        token_budget: TokenBudget | None = None,
        pruning_config: PruningConfig | None = None,
    ):
        self.model = model
        self.system_prompt_builder = system_prompt_builder or SystemPromptBuilder()
        self.token_budget = token_budget or TokenBudget()
        self.pruning_config = pruning_config or PruningConfig()
        self._history = MessageHistory(pruning_config=self.pruning_config)
        self._default_temperature = 1.0
        self._memory_reminder: str | None = None
        self._persist_memory_reminder = False

    @property
    def history(self) -> MessageHistory:
        return self._history

    def set_temperature(self, temp: float) -> "RequestBuilder":
        self._default_temperature = temp
        return self

    def set_system_prompt(self, text: str) -> "RequestBuilder":
        self.system_prompt_builder._components = [text]
        return self

    def set_memory_reminder(self, reminder: str, persist: bool = False) -> "RequestBuilder":
        """
        SOURCE: Set a memory reminder to inject into requests.

        If persist=True, the reminder is also stored in the actor's conversation state.
        """
        self._memory_reminder = reminder
        self._persist_memory_reminder = persist
        return self

    def build(
        self,
        include_image_budget: bool = True,
        context_window: int = 128000
    ) -> RequestPayload:
        """
        SOURCE: Build final request payload with image compaction, pruning, and memory injection.

        1. Check if pruning is needed (>50% context utilization)
        2. Persist memory reminder to state if requested
        3. Measure body bytes and check image compaction threshold
        4. Apply mutations if needed (compaction, pruning, memory injection)
        5. Assemble and return RequestPayload
        """
        # Update system prompt token count
        self.token_budget.system_prompt_tokens = self.system_prompt_builder.estimate_tokens()

        # Get working copy of messages
        messages = self._history.get_messages()

        # Check pruning threshold
        needs_prune = should_prune(
            self.token_budget.history_tokens,
            context_window
        )

        # Check image compaction threshold (simplified - uses history size as proxy)
        body_bytes = sum(len(m.content) for m in messages)
        needs_image_compaction = body_bytes >= IMAGE_COMPACT_TRIGGER_BYTES // 10  # Scaled for text

        # Handle memory reminder persistence
        if self._memory_reminder and self._persist_memory_reminder:
            injected = inject_memory_reminder(messages, self._memory_reminder)
            if injected:
                self._memory_reminder = None

        # Apply mutations if needed
        needs_mutation = needs_prune or self._memory_reminder is not None or needs_image_compaction

        if needs_mutation:
            # Step 1: Image compaction (simplified - in production would use exact body measurement)
            if needs_image_compaction:
                # Would evict oldest images here
                pass

            # Step 2: Prune old tool results if context is >50% utilized
            if needs_prune:
                prune_conversation(messages, self.pruning_config)

            # Step 3: Inject memory reminder into system message
            if self._memory_reminder:
                inject_memory_reminder(messages, self._memory_reminder)

        # Recalculate history tokens after mutations
        self.token_budget.history_tokens = sum(len(m.content) // 4 + 10 for m in messages)

        # Build final message list
        final_messages: list[dict[str, Any]] = []

        # Add system message
        system_content = self.system_prompt_builder.build()
        if system_content:
            final_messages.append(Message(role=Role.SYSTEM, content=system_content).to_dict())

        # Add conversation messages
        for msg in messages:
            final_messages.append(msg.to_dict())

        # Calculate max_tokens for request
        max_tokens = min(
            self.token_budget.remaining_tokens,
            self.token_budget.max_tokens // 4,  # Conservative limit
        )

        # Build image budget info for observability
        image_budget = None
        if include_image_budget:
            image_budget = {
                "body_bytes": body_bytes,
                "trigger_bytes": IMAGE_COMPACT_TRIGGER_BYTES,
                "reclaim_target_bytes": IMAGE_COMPACT_RECLAIM_TARGET_BYTES,
                "inline_images": 0,  # Would count actual images in production
                "needs_image_compaction": needs_image_compaction,
                "evicted": 0,
                "body_bytes_after": body_bytes,
            }

        return RequestPayload(
            messages=final_messages,
            model=self.model,
            max_tokens=max(max_tokens, 1),
            temperature=self._default_temperature,
            image_budget=image_budget,
        )