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
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime

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