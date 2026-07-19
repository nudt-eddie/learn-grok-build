"""
Context assembly module for Grok.
Handles: 1) System prompt builder 2) Message history 3) Token budget management 4) Request builder
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


class SystemPromptBuilder:
    """Builds and manages system prompts."""

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


class MessageHistory:
    """Manages message history with token budget awareness."""

    def __init__(self, max_messages: int = 100):
        self._messages: list[Message] = []
        self.max_messages = max_messages

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


@dataclass
class RequestPayload:
    """Final request payload for API."""
    messages: list[dict[str, Any]]
    model: str
    max_tokens: int
    temperature: float = 1.0
    stream: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": self.messages,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": self.stream,
        }


class RequestBuilder:
    """Builds API requests with context assembly."""

    def __init__(
        self,
        model: str,
        system_prompt_builder: SystemPromptBuilder | None = None,
        token_budget: TokenBudget | None = None,
    ):
        self.model = model
        self.system_prompt_builder = system_prompt_builder or SystemPromptBuilder()
        self.token_budget = token_budget or TokenBudget()
        self._history = MessageHistory()
        self._default_temperature = 1.0

    @property
    def history(self) -> MessageHistory:
        return self._history

    def set_temperature(self, temp: float) -> "RequestBuilder":
        self._default_temperature = temp
        return self

    def set_system_prompt(self, text: str) -> "RequestBuilder":
        self.system_prompt_builder._components = [text]
        return self

    def build(self) -> RequestPayload:
        """Build final request payload."""
        # Update system prompt token count
        self.token_budget.system_prompt_tokens = self.system_prompt_builder.estimate_tokens()

        # Truncate history to fit budget
        truncated = self._history.truncate_to_budget(self.token_budget)
        self.token_budget.history_tokens = sum(len(m.content) // 4 + 10 for m in truncated)

        # Build message list
        messages: list[dict[str, Any]] = []

        # Add system message
        system_content = self.system_prompt_builder.build()
        if system_content:
            messages.append(Message(role=Role.SYSTEM, content=system_content).to_dict())

        # Add conversation messages
        for msg in truncated:
            messages.append(msg.to_dict())

        # Calculate max_tokens for request
        max_tokens = min(
            self.token_budget.remaining_tokens,
            self.token_budget.max_tokens // 4,  # Conservative limit
        )

        return RequestPayload(
            messages=messages,
            model=self.model,
            max_tokens=max(max_tokens, 1),
            temperature=self._default_temperature,
        )