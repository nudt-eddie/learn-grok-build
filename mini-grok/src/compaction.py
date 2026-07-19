"""
Context Compaction Module

Handles context window management through:
1. Token counting
2. Message summarization
3. Threshold triggers
4. Rewind support
"""

import tiktoken
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Any
from enum import Enum


class CompactionStrategy(Enum):
    """Strategy for handling compaction when threshold is reached."""
    SUMMARIZE = "summarize"
    REWIND = "rewind"
    TRUNCATE = "truncate"


@dataclass
class CompactionConfig:
    """Configuration for context compaction."""
    # Token limits
    max_tokens: int = 128000  # Context window limit
    warning_threshold: float = 0.80  # Start warning at 80%
    compaction_threshold: float = 0.90  # Trigger compaction at 90%

    # Summarization settings
    summary_target_tokens: int = 4000  # Target tokens after summarization
    preserve_recent_messages: int = 3  # Keep recent messages unaltered

    # Rewind settings
    max_rewind_messages: int = 10  # Maximum messages to rewind
    rewind_to_message: Optional[int] = None  # Specific message index to rewind to

    # Strategy
    strategy: CompactionStrategy = CompactionStrategy.SUMMARIZE

    # Summary prompt template
    summary_prompt: str = (
        "Summarize the following conversation concisely, preserving key information, "
        "decisions, and important context:\n\n{conversation}"
    )


@dataclass
class Message:
    """Represents a chat message."""
    role: str
    content: str
    token_count: int = 0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.token_count == 0:
            self.token_count = count_tokens(self.content)


@dataclass
class CompactionResult:
    """Result of a compaction operation."""
    original_count: int
    new_count: int
    original_tokens: int
    new_tokens: int
    strategy_used: CompactionStrategy
    summary: Optional[str] = None
    rewound_to_index: Optional[int] = None


class TokenCounter:
    """Handles token counting using tiktoken."""

    def __init__(self, model: str = "gpt-4"):
        self.model = model
        try:
            self.encoder = tiktoken.encoding_for_model(model)
        except KeyError:
            self.encoder = tiktoken.get_encoding("cl100k_base")

    def count(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.encoder.encode(text))

    def count_messages(self, messages: List[Message]) -> int:
        """Count total tokens in messages including overhead."""
        total = 0
        # Add overhead per message (role + content structure)
        per_message_overhead = 4  # ~4 tokens for role/content markers
        for msg in messages:
            total += msg.token_count + per_message_overhead
        return total

    def count_messages_with_limit(self, messages: List[Message], max_tokens: int) -> List[Message]:
        """Return messages that fit within token limit."""
        result = []
        total = 0
        per_message_overhead = 4

        for msg in messages:
            msg_tokens = msg.token_count + per_message_overhead
            if total + msg_tokens <= max_tokens:
                result.append(msg)
                total += msg_tokens
            else:
                break

        return result


def count_tokens(text: str, model: str = "gpt-4") -> int:
    """Count tokens in text."""
    try:
        encoder = tiktoken.encoding_for_model(model)
    except KeyError:
        encoder = tiktoken.get_encoding("cl100k_base")
    return len(encoder.encode(text))


class MessageSummarizer:
    """Handles summarization of message history."""

    def __init__(self, config: CompactionConfig, summarize_fn: Optional[Callable] = None):
        self.config = config
        self.summarize_fn = summarize_fn or self._default_summarize

    def _default_summarize(self, conversation: str) -> str:
        """Default summarization using available tokens."""
        # This would typically call an LLM API
        # For now, return a placeholder
        return f"[Summary of {len(conversation)} characters of conversation]"

    def summarize_conversation(
        self,
        messages: List[Message],
        api_call_fn: Optional[Callable[[str], str]] = None
    ) -> tuple[str, List[Message]]:
        """
        Summarize older messages while preserving recent ones.

        Returns:
            Tuple of (summary_text, remaining_messages)
        """
        if len(messages) <= self.config.preserve_recent_messages:
            return "", messages

        # Split into older and recent messages
        preserve_count = self.config.preserve_recent_messages
        older_messages = messages[:-preserve_count]
        recent_messages = messages[-preserve_count:]

        # Build conversation text for summarization
        conversation_text = self._format_for_summary(older_messages)

        # Generate summary
        if api_call_fn:
            prompt = self.config.summary_prompt.format(conversation=conversation_text)
            summary = api_call_fn(prompt)
        else:
            summary = self.summarize_fn(conversation_text)

        # Create summary message
        summary_message = Message(
            role="system",
            content=summary,
            token_count=count_tokens(summary)
        )

        # Return summary + recent messages
        return summary, [summary_message] + recent_messages

    def _format_for_summary(self, messages: List[Message]) -> str:
        """Format messages for summarization prompt."""
        lines = []
        for msg in messages:
            lines.append(f"{msg.role}: {msg.content}")
        return "\n\n".join(lines)


class RewindHandler:
    """Handles message history rewinding."""

    def __init__(self, config: CompactionConfig):
        self.config = config

    def rewind(
        self,
        messages: List[Message],
        to_index: Optional[int] = None
    ) -> tuple[int, List[Message]]:
        """
        Rewind message history to a specific point.

        Args:
            messages: Current message list
            to_index: Optional specific index to rewind to

        Returns:
            Tuple of (rewound_to_index, remaining_messages)
        """
        if not messages:
            return 0, []

        # Determine rewind target
        if to_index is not None:
            target = max(0, min(to_index, len(messages) - 1))
        elif self.config.rewind_to_message is not None:
            target = self.config.rewind_to_message
        else:
            # Default: rewind to keep last N messages
            target = max(0, len(messages) - self.config.max_rewind_messages)

        return target, messages[:target]


class CompactionTrigger:
    """Handles threshold-based compaction triggering."""

    def __init__(self, config: CompactionConfig):
        self.config = config
        self.token_counter = TokenCounter()

    def check_threshold(self, messages: List[Message]) -> tuple[bool, float, str]:
        """
        Check if compaction threshold is reached.

        Returns:
            Tuple of (should_compact, current_ratio, status)
        """
        total_tokens = self.token_counter.count_messages(messages)
        ratio = total_tokens / self.config.max_tokens

        if ratio >= self.config.compaction_threshold:
            return True, ratio, "compaction_required"
        elif ratio >= self.config.warning_threshold:
            return False, ratio, "warning"
        else:
            return False, ratio, "ok"

    def get_remaining_capacity(self, messages: List[Message]) -> int:
        """Get remaining token capacity."""
        current = self.token_counter.count_messages(messages)
        return max(0, self.config.max_tokens - current)


class ContextCompactor:
    """
    Main context compaction handler.

    Orchestrates token counting, summarization, threshold checking,
    and rewinding for efficient context window management.
    """

    def __init__(
        self,
        config: Optional[CompactionConfig] = None,
        summarize_fn: Optional[Callable[[str], str]] = None
    ):
        self.config = config or CompactionConfig()
        self.token_counter = TokenCounter()
        self.summarizer = MessageSummarizer(self.config, summarize_fn)
        self.rewind_handler = RewindHandler(self.config)
        self.trigger = CompactionTrigger(self.config)

        # State
        self._compaction_count = 0
        self._last_summary: Optional[str] = None

    def analyze(self, messages: List[Message]) -> dict:
        """
        Analyze current context state.

        Returns:
            Dictionary with analysis results
        """
        total_tokens = self.token_counter.count_messages(messages)
        should_compact, ratio, status = self.trigger.check_threshold(messages)
        remaining = self.trigger.get_remaining_capacity(messages)

        return {
            "message_count": len(messages),
            "total_tokens": total_tokens,
            "token_ratio": ratio,
            "max_tokens": self.config.max_tokens,
            "remaining_capacity": remaining,
            "status": status,
            "should_compact": should_compact,
            "compaction_count": self._compaction_count
        }

    def compact(
        self,
        messages: List[Message],
        strategy: Optional[CompactionStrategy] = None,
        api_call_fn: Optional[Callable[[str], str]] = None
    ) -> CompactionResult:
        """
        Perform context compaction using the configured or specified strategy.

        Args:
            messages: Current message list
            strategy: Optional override strategy
            api_call_fn: Optional function to call LLM for summarization

        Returns:
            CompactionResult with details of the operation
        """
        strategy = strategy or self.config.strategy
        original_count = len(messages)
        original_tokens = self.token_counter.count_messages(messages)

        if strategy == CompactionStrategy.SUMMARIZE:
            summary, new_messages = self.summarizer.summarize_conversation(
                messages, api_call_fn
            )
            self._last_summary = summary
            result = CompactionResult(
                original_count=original_count,
                new_count=len(new_messages),
                original_tokens=original_tokens,
                new_tokens=self.token_counter.count_messages(new_messages),
                strategy_used=strategy,
                summary=summary
            )

        elif strategy == CompactionStrategy.REWIND:
            rewound_to, new_messages = self.rewind_handler.rewind(messages)
            result = CompactionResult(
                original_count=original_count,
                new_count=len(new_messages),
                original_tokens=original_tokens,
                new_tokens=self.token_counter.count_messages(new_messages),
                strategy_used=strategy,
                rewound_to_index=rewound_to
            )

        elif strategy == CompactionStrategy.TRUNCATE:
            new_messages = self.token_counter.count_messages_with_limit(
                messages, self.config.summary_target_tokens
            )
            result = CompactionResult(
                original_count=original_count,
                new_count=len(new_messages),
                original_tokens=original_tokens,
                new_tokens=self.token_counter.count_messages(new_messages),
                strategy_used=strategy
            )

        else:
            raise ValueError(f"Unknown compaction strategy: {strategy}")

        self._compaction_count += 1
        return result

    def should_compact(self, messages: List[Message]) -> bool:
        """Quick check if compaction is needed."""
        should, _, _ = self.trigger.check_threshold(messages)
        return should

    def get_last_summary(self) -> Optional[str]:
        """Get the last generated summary."""
        return self._last_summary

    def reset_stats(self):
        """Reset compaction statistics."""
        self._compaction_count = 0
        self._last_summary = None


# Convenience function for quick compaction
def compact_context(
    messages: List[dict],
    max_tokens: int = 128000,
    strategy: CompactionStrategy = CompactionStrategy.SUMMARIZE
) -> tuple[List[dict], CompactionResult]:
    """
    Quick context compaction utility.

    Args:
        messages: List of message dicts with 'role' and 'content'
        max_tokens: Maximum tokens allowed
        strategy: Compaction strategy to use

    Returns:
        Tuple of (compacted_messages, result)
    """
    # Convert to Message objects
    msg_objects = [
        Message(role=m["role"], content=m["content"])
        for m in messages
    ]

    config = CompactionConfig(max_tokens=max_tokens, strategy=strategy)
    compactor = ContextCompactor(config)

    result = compactor.compact(msg_objects)

    # Convert back to dicts
    compacted = [
        {"role": m.role, "content": m.content}
        for m in msg_objects
    ]

    return compacted, result