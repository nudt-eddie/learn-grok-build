"""
ChatStateActor pattern implementation.

This module implements the Actor pattern for chat state management:
1) Actor class with message queue
2) Conversation state management
3) Command handlers
4) Event emission

References:
    xai-chat-state/src/actor/mod.rs - Original Rust actor implementation
"""

import asyncio
import logging
import os
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Event types emitted by the actor system."""
    # SOURCE: xai-chat-state/src/actor/mod.rs - Event type definitions
    STATE_CHANGED = "state_changed"
    MESSAGE_RECEIVED = "message_received"
    COMMAND_EXECUTED = "command_executed"
    ERROR = "error"
    CONVERSATION_STARTED = "conversation_started"
    CONVERSATION_ENDED = "conversation_ended"


@dataclass
class Event:
    """Event object emitted by the actor.

    SOURCE: xai-chat-state/src/actor/mod.rs - Event struct definition
    """
    type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    conversation_id: Optional[str] = None


class ConversationState(Enum):
    """State of a conversation within an actor."""
    # SOURCE: xai-chat-state/src/actor/mod.rs - State enum variants
    IDLE = "idle"
    ACTIVE = "active"
    WAITING = "waiting"
    TERMINATED = "terminated"


@dataclass
class ConversationContext:
    """Context for a conversation managed by the actor.

    SOURCE: xai-chat-state/src/actor/mod.rs - Conversation context structure
    """
    conversation_id: str
    state: ConversationState = ConversationState.IDLE
    metadata: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


CommandHandler = Callable[['Actor', Dict[str, Any]], 'asyncio.coroutine']


@dataclass
class ActorMessage:
    """Message processed by the actor.

    SOURCE: xai-chat-state/src/actor/mod.rs - Message envelope structure
    """
    id: str
    command: str
    payload: Dict[str, Any] = field(default_factory=dict)
    reply_to: Optional[asyncio.Future] = None
    timestamp: datetime = field(default_factory=datetime.now)


class EventEmitter(ABC):
    """Abstract base for event emission.

    SOURCE: xai-chat-state/src/actor/mod.rs - Event emitter trait
    """

    @abstractmethod
    async def emit(self, event: Event) -> None:
        """Emit an event."""
        pass

    @abstractmethod
    async def subscribe(self, event_type: EventType, handler: Callable) -> None:
        """Subscribe to an event type."""
        pass


class SimpleEventEmitter(EventEmitter):
    """Simple event emitter implementation with in-memory subscriptions.

    SOURCE: xai-chat-state/src/actor/mod.rs - EventEmitter implementation
    """

    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._all_subscribers: List[Callable] = []

    async def emit(self, event: Event) -> None:
        """Emit an event to all subscribers.

        SOURCE: xai-chat-state/src/actor/mod.rs - emit method implementation
        """
        # Notify specific type subscribers
        for handler in self._subscribers.get(event.type, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}")

        # Notify global subscribers
        for handler in self._all_subscribers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"Global event handler error: {e}")

    async def subscribe(self, event_type: EventType, handler: Callable) -> None:
        """Subscribe to a specific event type.

        SOURCE: xai-chat-state/src/actor/mod.rs - subscribe method
        """
        self._subscribers[event_type].append(handler)

    def subscribe_all(self, handler: Callable) -> None:
        """Subscribe to all events."""
        self._all_subscribers.append(handler)


class Actor:
    """Actor with message queue for chat state management.

    SOURCE: xai-chat-state/src/actor/mod.rs - Actor struct definition

    This implements the actor model pattern:
    - All state is private to the actor
    - Communication via message passing through a queue
    - Sequential message processing ensures consistency
    """

    def __init__(self, actor_id: str):
        """Initialize the actor.

        SOURCE: xai-chat-state/src/actor/mod.rs - Actor::new constructor
        """
        self.actor_id = actor_id
        self._message_queue: asyncio.Queue[ActorMessage] = asyncio.Queue()
        self._running = False
        self._handlers: Dict[str, CommandHandler] = {}
        self._conversations: Dict[str, ConversationContext] = {}
        self._current_conversation: Optional[str] = None
        self._event_emitter = SimpleEventEmitter()
        self._lock = asyncio.Lock()

        # Register default command handlers
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register default command handlers.

        SOURCE: xai-chat-state/src/actor/mod.rs - default command registration
        """
        # SOURCE: xai-chat-state/src/actor/mod.rs - start_conversation handler
        self._handlers["start_conversation"] = self._handle_start_conversation
        # SOURCE: xai-chat-state/src/actor/mod.rs - end_conversation handler
        self._handlers["end_conversation"] = self._handle_end_conversation
        # SOURCE: xai-chat-state/src/actor/mod.rs - send_message handler
        self._handlers["send_message"] = self._handle_send_message
        # SOURCE: xai-chat-state/src/actor/mod.rs - update_state handler
        self._handlers["update_state"] = self._handle_update_state
        # SOURCE: xai-chat-state/src/actor/mod.rs - get_state handler
        self._handlers["get_state"] = self._handle_get_state
        # SOURCE: xai-chat-state/src/actor/mod.rs - get_conversation handler
        self._handlers["get_conversation"] = self._handle_get_conversation

    def register_handler(self, command: str, handler: CommandHandler) -> None:
        """Register a command handler.

        SOURCE: xai-chat-state/src/actor/mod.rs - register_handler method
        """
        self._handlers[command] = handler

    async def send(self, message: ActorMessage) -> Any:
        """Send a message to the actor's message queue.

        SOURCE: xai-chat-state/src/actor/mod.rs - Actor::send method
        """
        await self._message_queue.put(message)

        if message.reply_to:
            # Wait for response via future
            return await message.reply_to

    def send_nowait(self, message: ActorMessage) -> None:
        """Send a message without waiting (non-blocking).

        SOURCE: xai-chat-state/src/actor/mod.rs - Actor::send_nowait variant
        """
        self._message_queue.put_nowait(message)

    async def emit_event(self, event: Event) -> None:
        """Emit an event to subscribers.

        SOURCE: xai-chat-state/src/actor/mod.rs - emit_event method
        """
        await self._event_emitter.emit(event)

    async def subscribe(self, event_type: EventType, handler: Callable) -> None:
        """Subscribe to events.

        SOURCE: xai-chat-state/src/actor/mod.rs - subscribe method
        """
        await self._event_emitter.subscribe(event_type, handler)

    async def run(self) -> None:
        """Start processing messages from the queue.

        SOURCE: xai-chat-state/src/actor/mod.rs - Actor::run loop
        """
        self._running = True
        logger.info(f"Actor {self.actor_id} started")

        while self._running:
            try:
                message = await asyncio.wait_for(
                    self._message_queue.get(),
                    timeout=1.0
                )
                await self._process_message(message)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Actor {self.actor_id} error: {e}")
                await self.emit_event(Event(
                    type=EventType.ERROR,
                    data={"error": str(e)}
                ))

    async def _process_message(self, message: ActorMessage) -> None:
        """Process a single message from the queue.

        SOURCE: xai-chat-state/src/actor/mod.rs - message processing logic
        """
        handler = self._handlers.get(message.command)

        if not handler:
            error_msg = f"Unknown command: {message.command}"
            logger.warning(error_msg)
            await self.emit_event(Event(
                type=EventType.ERROR,
                data={"error": error_msg, "message_id": message.id}
            ))
            return

        try:
            result = await handler(message.payload)

            await self.emit_event(Event(
                type=EventType.COMMAND_EXECUTED,
                data={
                    "command": message.command,
                    "message_id": message.id,
                    "result": result
                }
            ))

            if message.reply_to and not message.reply_to.done():
                message.reply_to.set_result(result)

        except Exception as e:
            logger.error(f"Command execution error: {e}")
            if message.reply_to and not message.reply_to.done():
                message.reply_to.set_exception(e)
            await self.emit_event(Event(
                type=EventType.ERROR,
                data={
                    "command": message.command,
                    "error": str(e),
                    "message_id": message.id
                }
            ))

    def stop(self) -> None:
        """Stop the actor's message processing loop.

        SOURCE: xai-chat-state/src/actor/mod.rs - Actor::stop method
        """
        self._running = False
        logger.info(f"Actor {self.actor_id} stopped")

    # Default command handlers
    # SOURCE: xai-chat-state/src/actor/mod.rs - handler implementations

    async def _handle_start_conversation(self, payload: Dict[str, Any]) -> ConversationContext:
        """Handle start_conversation command.

        SOURCE: xai-chat-state/src/actor/mod.rs - start_conversation handler
        """
        conversation_id = payload.get("conversation_id")
        if not conversation_id:
            conversation_id = f"conv_{datetime.now().timestamp()}"

        context = ConversationContext(
            conversation_id=conversation_id,
            state=ConversationState.ACTIVE,
            metadata=payload.get("metadata", {})
        )

        async with self._lock:
            self._conversations[conversation_id] = context
            self._current_conversation = conversation_id

        await self.emit_event(Event(
            type=EventType.CONVERSATION_STARTED,
            data={"conversation_id": conversation_id},
            conversation_id=conversation_id
        ))

        return context

    async def _handle_end_conversation(self, payload: Dict[str, Any]) -> bool:
        """Handle end_conversation command.

        SOURCE: xai-chat-state/src/actor/mod.rs - end_conversation handler
        """
        conversation_id = payload.get("conversation_id") or self._current_conversation

        if not conversation_id or conversation_id not in self._conversations:
            return False

        async with self._lock:
            context = self._conversations[conversation_id]
            context.state = ConversationState.TERMINATED
            context.updated_at = datetime.now()

            if self._current_conversation == conversation_id:
                self._current_conversation = None

        await self.emit_event(Event(
            type=EventType.CONVERSATION_ENDED,
            data={"conversation_id": conversation_id},
            conversation_id=conversation_id
        ))

        return True

    async def _handle_send_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle send_message command.

        SOURCE: xai-chat-state/src/actor/mod.rs - send_message handler
        """
        conversation_id = payload.get("conversation_id") or self._current_conversation
        content = payload.get("content", "")
        message_type = payload.get("type", "user")

        if not conversation_id or conversation_id not in self._conversations:
            raise ValueError(f"Invalid conversation: {conversation_id}")

        context = self._conversations[conversation_id]

        message_record = {
            "type": message_type,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }

        async with self._lock:
            context.history.append(message_record)
            context.updated_at = datetime.now()

        await self.emit_event(Event(
            type=EventType.MESSAGE_RECEIVED,
            data=message_record,
            conversation_id=conversation_id
        ))

        return message_record

    async def _handle_update_state(self, payload: Dict[str, Any]) -> ConversationState:
        """Handle update_state command.

        SOURCE: xai-chat-state/src/actor/mod.rs - update_state handler
        """
        conversation_id = payload.get("conversation_id") or self._current_conversation
        new_state_str = payload.get("state")

        if not conversation_id or conversation_id not in self._conversations:
            raise ValueError(f"Invalid conversation: {conversation_id}")

        new_state = ConversationState(new_state_str)

        async with self._lock:
            context = self._conversations[conversation_id]
            old_state = context.state
            context.state = new_state
            context.updated_at = datetime.now()

        await self.emit_event(Event(
            type=EventType.STATE_CHANGED,
            data={
                "old_state": old_state.value,
                "new_state": new_state.value
            },
            conversation_id=conversation_id
        ))

        return new_state

    async def _handle_get_state(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle get_state command.

        SOURCE: xai-chat-state/src/actor/mod.rs - get_state handler
        """
        conversation_id = payload.get("conversation_id") or self._current_conversation

        if not conversation_id:
            return {
                "current_conversation": self._current_conversation,
                "conversations": list(self._conversations.keys())
            }

        if conversation_id not in self._conversations:
            raise ValueError(f"Invalid conversation: {conversation_id}")

        context = self._conversations[conversation_id]

        return {
            "conversation_id": context.conversation_id,
            "state": context.state.value,
            "metadata": context.metadata,
            "history_length": len(context.history),
            "created_at": context.created_at.isoformat(),
            "updated_at": context.updated_at.isoformat()
        }

    async def _handle_get_conversation(self, payload: Dict[str, Any]) -> Optional[ConversationContext]:
        """Handle get_conversation command.

        SOURCE: xai-chat-state/src/actor/mod.rs - get_conversation handler
        """
        conversation_id = payload.get("conversation_id") or self._current_conversation
        include_history = payload.get("include_history", False)

        if not conversation_id or conversation_id not in self._conversations:
            return None

        context = self._conversations[conversation_id]

        if not include_history:
            # Return context without history (shallow copy)
            return ConversationContext(
                conversation_id=context.conversation_id,
                state=context.state,
                metadata=context.metadata.copy(),
                history=[],
                created_at=context.created_at,
                updated_at=context.updated_at
            )

        return context

    @property
    def is_running(self) -> bool:
        """Check if the actor is running."""
        return self._running

    @property
    def current_conversation_id(self) -> Optional[str]:
        """Get the current active conversation ID."""
        return self._current_conversation

    def get_conversation_ids(self) -> List[str]:
        """Get all conversation IDs."""
        return list(self._conversations.keys())


class ActorSystem:
    """Actor system for managing multiple actors.

    SOURCE: xai-chat-state/src/actor/mod.rs - ActorSystem implementation
    """

    def __init__(self):
        self._actors: Dict[str, Actor] = {}
        self._lock = asyncio.Lock()

    async def spawn(self, actor_id: str) -> Actor:
        """Spawn a new actor.

        SOURCE: xai-chat-state/src/actor/mod.rs - spawn method
        """
        async with self._lock:
            if actor_id in self._actors:
                raise ValueError(f"Actor {actor_id} already exists")

            actor = Actor(actor_id)
            self._actors[actor_id] = actor
            return actor

    async def get_actor(self, actor_id: str) -> Optional[Actor]:
        """Get an actor by ID.

        SOURCE: xai-chat-state/src/actor/mod.rs - get_actor method
        """
        return self._actors.get(actor_id)

    async def remove_actor(self, actor_id: str) -> bool:
        """Remove an actor from the system.

        SOURCE: xai-chat-state/src/actor/mod.rs - remove_actor method
        """
        async with self._lock:
            if actor_id not in self._actors:
                return False

            actor = self._actors.pop(actor_id)
            actor.stop()
            return True

    def list_actors(self) -> List[str]:
        """List all actor IDs."""
        return list(self._actors.keys())


# Convenience function for creating actor messages
def create_message(
    command: str,
    payload: Optional[Dict[str, Any]] = None,
    message_id: Optional[str] = None
) -> ActorMessage:
    """Create an actor message.

    SOURCE: xai-chat-state/src/actor/mod.rs - Message creation helper
    """
    return ActorMessage(
        id=message_id or f"msg_{datetime.now().timestamp()}",
        command=command,
        payload=payload or {}
    )


# ============================================================================
# PromptContext Builder, Template Rendering, and AGENTS.md Support
# ============================================================================

@dataclass
class PromptContext:
    """Context for building prompts with template rendering support.

    Attributes:
        system_prompt: The base system prompt content
        user_message: The user's input message
        conversation_history: List of prior messages
        agent_config: Configuration loaded from AGENTS.md
        metadata: Additional metadata for template rendering
        custom_variables: User-defined template variables
    """
    system_prompt: str = ""
    user_message: str = ""
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    agent_config: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    custom_variables: Dict[str, str] = field(default_factory=dict)

    class Builder:
        """Builder for PromptContext with fluent API."""

        def __init__(self):
            self._system_prompt = ""
            self._user_message = ""
            self._conversation_history: List[Dict[str, Any]] = []
            self._agent_config: Dict[str, Any] = {}
            self._metadata: Dict[str, Any] = {}
            self._custom_variables: Dict[str, str] = {}

        def with_system_prompt(self, prompt: str) -> "PromptContext.Builder":
            """Set the system prompt."""
            self._system_prompt = prompt
            return self

        def with_user_message(self, message: str) -> "PromptContext.Builder":
            """Set the user message."""
            self._user_message = message
            return self

        def with_conversation_history(
            self, history: List[Dict[str, Any]]
        ) -> "PromptContext.Builder":
            """Set conversation history."""
            self._conversation_history = history
            return self

        def with_agent_config(self, config: Dict[str, Any]) -> "PromptContext.Builder":
            """Set agent configuration from AGENTS.md."""
            self._agent_config = config
            return self

        def with_metadata(self, metadata: Dict[str, Any]) -> "PromptContext.Builder":
            """Set metadata."""
            self._metadata = metadata
            return self

        def with_variable(self, key: str, value: str) -> "PromptContext.Builder":
            """Add a custom template variable."""
            self._custom_variables[key] = value
            return self

        def with_agents_md(self, path: str | Path) -> "PromptContext.Builder":
            """Load agent configuration from AGENTS.md file."""
            agents_md = AgentsMdLoader.load(path)
            self._agent_config.update(agents_md)
            return self

        def build(self) -> "PromptContext":
            """Build the PromptContext instance."""
            return PromptContext(
                system_prompt=self._system_prompt,
                user_message=self._user_message,
                conversation_history=self._conversation_history,
                agent_config=self._agent_config,
                metadata=self._metadata,
                custom_variables=self._custom_variables,
            )

    @classmethod
    def builder(cls) -> Builder:
        """Create a new PromptContext builder."""
        return cls.Builder()


def render_template(
    template: str,
    context: PromptContext | Dict[str, Any],
) -> str:
    """Render a template string with context variables.

    Supports {{variable}} and {{nested.variable}} syntax.
    Accesses all PromptContext fields plus custom_variables.

    Args:
        template: Template string with {{variable}} placeholders
        context: PromptContext instance or dict with variables

    Returns:
        Rendered string with placeholders replaced
    """
    if isinstance(context, PromptContext):
        context_dict = {
            "system_prompt": context.system_prompt,
            "user_message": context.user_message,
            "conversation_history": context.conversation_history,
            "agent_config": context.agent_config,
            "metadata": context.metadata,
            **context.custom_variables,
        }
    else:
        context_dict = context

    def replacer(match: re.Match) -> str:
        key = match.group(1).strip()
        # Support dot notation for nested access
        keys = key.split(".")
        value: Any = context_dict
        try:
            for k in keys:
                value = value[k]
            return str(value)
        except (KeyError, TypeError):
            return match.group(0)  # Return placeholder if not found

    return re.sub(r"\{\{([^}]+)\}\}", replacer, template)


class AgentsMdLoader:
    """Loader for AGENTS.md configuration files.

    Parses AGENTS.md files following the Anthropic/Claude convention
    for agent instructions and configuration.
    """

    SECTION_PATTERN = re.compile(r"^#\s+(.+)$", re.MULTILINE)
    KEY_VALUE_PATTERN = re.compile(r"^\s*([^:=\s]+)\s*[:=]\s*(.+)$", re.MULTILINE)
    LIST_ITEM_PATTERN = re.compile(r"^\s*[-*]\s+(.+)$", re.MULTILINE)

    @classmethod
    def load(cls, path: str | Path) -> Dict[str, Any]:
        """Load and parse an AGENTS.md file.

        Args:
            path: Path to the AGENTS.md file

        Returns:
            Dict with parsed configuration containing:
            - instructions: Main agent instructions
            - tools: List of available tools
            - guidelines: Agent guidelines
            - metadata: File-level metadata
        """
        path = Path(path)
        if not path.exists():
            logger.warning(f"AGENTS.md not found at {path}")
            return {}

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read AGENTS.md: {e}")
            return {}

        return cls.parse(content, {"source_file": str(path)})

    @classmethod
    def parse(cls, content: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Parse AGENTS.md content into structured configuration.

        Args:
            content: AGENTS.md file content
            metadata: Optional metadata to include in result

        Returns:
            Parsed configuration dictionary
        """
        result: Dict[str, Any] = {
            "instructions": "",
            "tools": [],
            "guidelines": [],
            "capabilities": [],
            "metadata": metadata or {},
        }

        lines = content.split("\n")
        current_section = "preamble"
        section_content: List[str] = []

        def _flush_section():
            nonlocal current_section, section_content
            if not section_content:
                return
            text = "\n".join(section_content).strip()
            if current_section == "preamble":
                result["instructions"] = text
            elif current_section == "tools":
                result["tools"] = cls._parse_list_items(text)
            elif current_section == "guidelines":
                result["guidelines"] = cls._parse_list_items(text)
            elif current_section == "capabilities":
                result["capabilities"] = cls._parse_list_items(text)
            else:
                result[current_section] = text
            section_content = []

        for line in lines:
            section_match = cls.SECTION_PATTERN.match(line)
            if section_match:
                _flush_section()
                section_name = section_match.group(1).lower().strip()
                current_section = section_name.replace(" ", "_")
                continue
            section_content.append(line)

        _flush_section()

        # Parse key-value pairs from preamble if present
        kv_section = result.get("instructions", "")
        parsed_kv, remaining_text = cls._parse_key_values(kv_section)
        result.update(parsed_kv)
        result["instructions"] = remaining_text

        return result

    @classmethod
    def _parse_list_items(cls, text: str) -> List[str]:
        """Parse list items from text."""
        items = []
        for match in cls.LIST_ITEM_PATTERN.finditer(text):
            items.append(match.group(1).strip())
        return items

    @classmethod
    def _parse_key_values(cls, text: str) -> tuple[Dict[str, Any], str]:
        """Separate key-value pairs from prose text."""
        lines = text.split("\n")
        kv_pairs: Dict[str, Any] = {}
        prose_lines: List[str] = []
        in_list = False

        for line in lines:
            kv_match = cls.KEY_VALUE_PATTERN.match(line)
            if kv_match:
                key = kv_match.group(1).strip()
                value = kv_match.group(2).strip()
                # Check if value is a list
                if value.startswith("[") and value.endswith("]"):
                    value = [v.strip() for v in value[1:-1].split(",")]
                kv_pairs[key] = value
                in_list = False
            elif line.strip().startswith(("-", "*")):
                in_list = True
                prose_lines.append(line)
            else:
                if line.strip():
                    in_list = False
                prose_lines.append(line)

        return kv_pairs, "\n".join(prose_lines).strip()

    @classmethod
    def build_system_prompt(cls, config: Dict[str, Any]) -> str:
        """Build a formatted system prompt from AGENTS.md configuration.

        Args:
            config: Configuration dict from load() or parse()

        Returns:
            Formatted system prompt string
        """
        parts = []

        if config.get("instructions"):
            parts.append(config["instructions"])

        if config.get("capabilities"):
            parts.append("\n## Capabilities\n")
            for cap in config["capabilities"]:
                parts.append(f"- {cap}")

        if config.get("tools"):
            parts.append("\n## Available Tools\n")
            for tool in config["tools"]:
                parts.append(f"- {tool}")

        if config.get("guidelines"):
            parts.append("\n## Guidelines\n")
            for guideline in config["guidelines"]:
                parts.append(f"- {guideline}")

        return "\n".join(parts).strip()


def load_agents_md(
    base_path: str | Path | None = None,
) -> Dict[str, Any]:
    """Convenience function to load AGENTS.md.

    Searches for AGENTS.md in common locations:
    - Current working directory
    - Project root (parent of src/)
    - Specified base_path

    Args:
        base_path: Optional explicit path to search

    Returns:
        Parsed AGENTS.md configuration or empty dict if not found
    """
    search_paths = []

    if base_path:
        search_paths.append(Path(base_path))

    search_paths.extend([
        Path.cwd() / "AGENTS.md",
        Path.cwd() / ".." / "AGENTS.md",
        Path(__file__).parent.parent.parent / "AGENTS.md",
    ])

    for path in search_paths:
        if path.exists():
            return AgentsMdLoader.load(path)

    return {}