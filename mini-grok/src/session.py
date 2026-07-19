"""
Session Module

Implements session lifecycle management for the agent:
1) Session state management (SessionState, SessionLiveState)
2) Turn management (turn numbers, prompt handling)
3) Capability model (session capabilities, permissions)
4) Permission checks (permission modes, access control)

References:
    xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs - Session lifecycle
    xai-grok-shell/src/agent/mvp_agent/mod.rs - MvpAgent session handling
    xai-grok-shell/src/agent/handlers/session.rs - Session handlers
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
import threading

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """Coarse state of a session actor."""
    # SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - SessionState patterns
    IDLE = "idle"
    ACTIVE = "active"
    WAITING = "waiting"
    TERMINATED = "terminated"


class SessionLiveState(Enum):
    """Coarse lifecycle state for session roster/dashboard.

    SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs
    """
    IdleResident = "idle_resident"
    Dormant = "dormant"
    Completed = "completed"
    DeadFailed = "dead_failed"


class PermissionMode(Enum):
    """Permission mode for session operations.

    SOURCE: xai-grok-shell/src/extensions/permission.rs - PermissionMode patterns
    """
    MANUAL = "manual"           # Always prompt for permission
    AUTO_APPROVE = "auto_approve"  # Auto-approve without prompting (YOLO)
    RESTRICTED = "restricted"   # Restricted subset of operations


class ClientType(Enum):
    """Type of client connected to the session.

    SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - ClientType patterns
    """
    Unknown = "unknown"
    Web = "web"
    Desktop = "desktop"
    CLI = "cli"


@dataclass
class TurnContext:
    """Context for a single turn (prompt -> response).

    SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Turn tracking patterns
    """
    turn_index: int = 0
    prompt_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cancelled: bool = False
    cancellation_category: Optional[str] = None
    cancel_trigger: Optional[str] = None


@dataclass
class SessionCapabilities:
    """Capabilities available to a session.

    SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Session capabilities patterns
    """
    # File system capabilities
    fs_read: bool = False
    fs_write: bool = False

    # Terminal capabilities
    terminal_enabled: bool = False

    # Code navigation
    code_nav_enabled: bool = False

    # MCP (Model Context Protocol) servers
    mcp_servers: List[Dict[str, Any]] = field(default_factory=list)

    # Available tools
    tools: List[str] = field(default_factory=list)

    # Reasoning effort (None = auto, or specific effort level)
    reasoning_effort: Optional[str] = None

    # YOLO mode (auto-approve dangerous operations)
    yolo_mode: bool = False

    # Worktree support
    worktree_enabled: bool = False

    # MCP managed config
    managed_mcp: bool = False

    # Plugin support
    plugins: List[str] = field(default_factory=list)

    # Structured output support
    structured_output: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert capabilities to dictionary for serialization."""
        return {
            "fs_read": self.fs_read,
            "fs_write": self.fs_write,
            "terminal_enabled": self.terminal_enabled,
            "code_nav_enabled": self.code_nav_enabled,
            "mcp_servers": self.mcp_servers,
            "tools": self.tools,
            "reasoning_effort": self.reasoning_effort,
            "yolo_mode": self.yolo_mode,
            "worktree_enabled": self.worktree_enabled,
            "managed_mcp": self.managed_mcp,
            "plugins": self.plugins,
            "structured_output": self.structured_output,
        }


@dataclass
class PermissionCheck:
    """Result of a permission check.

    SOURCE: xai-grok-shell/src/extensions/permission.rs - Permission checking patterns
    """
    granted: bool
    mode: PermissionMode
    reason: Optional[str] = None
    requires_interaction: bool = False
    interaction_deadline: Optional[datetime] = None


@dataclass
class SessionInfo:
    """Session metadata.

    SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - SessionInfo patterns
    """
    session_id: str
    cwd: str
    model_id: str
    model_display_name: Optional[str] = None
    agent_name: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    turns: int = 0
    auto_mode: bool = False

    # Client information
    client_type: ClientType = ClientType.Unknown
    origin_client: Optional[Dict[str, Any]] = None

    # Display cwd (for worktree sessions)
    display_cwd: Optional[str] = None

    # Initial total tokens (from session load)
    initial_total_tokens: int = 0


@dataclass
class SessionContext:
    """Complete context for a session.

    SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Session context patterns
    """
    info: SessionInfo
    state: SessionState = SessionState.IDLE
    live_state: SessionLiveState = SessionLiveState.IdleResident
    capabilities: SessionCapabilities = field(default_factory=SessionCapabilities)
    permission_mode: PermissionMode = PermissionMode.MANUAL
    turn_context: TurnContext = field(default_factory=TurnContext)

    # History
    history: List[Dict[str, Any]] = field(default_factory=list)

    # Pending interactions (permission requests, etc.)
    pending_interactions: List[Dict[str, Any]] = field(default_factory=list)

    # MCP configuration
    mcp_config: Dict[str, Any] = field(default_factory=dict)

    # Persisted state
    persisted_signals: Optional[Dict[str, Any]] = None
    persisted_plan_mode: Optional[Dict[str, Any]] = None


class PermissionChecker:
    """Checks permissions based on session permission mode.

    SOURCE: xai-grok-shell/src/extensions/permission.rs - Permission checking logic
    """

    # Operations that require permission in MANUAL mode
    DANGEROUS_OPERATIONS: Set[str] = {
        "execute_command",
        "write_file",
        "delete_file",
        "create_directory",
        "delete_directory",
        "system_command",
    }

    # Operations allowed in RESTRICTED mode
    RESTRICTED_ALLOWED_OPERATIONS: Set[str] = {
        "read_file",
        "list_directory",
        "glob",
        "grep",
    }

    def __init__(self, permission_mode: PermissionMode = PermissionMode.MANUAL):
        """Initialize permission checker.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Permission mode initialization
        """
        self.permission_mode = permission_mode
        self._approved_operations: Set[str] = set()

    def set_mode(self, mode: PermissionMode) -> None:
        """Update permission mode.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Permission mode switching
        """
        self.permission_mode = mode

    def check(self, operation: str, details: Optional[Dict[str, Any]] = None) -> PermissionCheck:
        """Check if an operation is permitted.

        SOURCE: xai-grok-shell/src/extensions/permission.rs - Permission check implementation

        Args:
            operation: The operation to check (e.g., "execute_command", "write_file")
            details: Optional details about the operation (command, path, etc.)

        Returns:
            PermissionCheck with granted status and metadata
        """
        # YOLO/AUTO_APPROVE mode: grant all operations
        if self.permission_mode == PermissionMode.AUTO_APPROVE:
            return PermissionCheck(
                granted=True,
                mode=self.permission_mode,
                reason="auto_approved"
            )

        # RESTRICTED mode: only allow safe operations
        if self.permission_mode == PermissionMode.RESTRICTED:
            if operation in self.RESTRICTED_ALLOWED_OPERATIONS:
                return PermissionCheck(
                    granted=True,
                    mode=self.permission_mode,
                    reason="restricted_allowed"
                )
            return PermissionCheck(
                granted=False,
                mode=self.permission_mode,
                reason="operation_not_allowed_in_restricted_mode",
                requires_interaction=False
            )

        # MANUAL mode: check dangerous operations
        if operation in self.DANGEROUS_OPERATIONS:
            # Check if already pre-approved
            approval_key = self._make_approval_key(operation, details)
            if approval_key in self._approved_operations:
                return PermissionCheck(
                    granted=True,
                    mode=self.permission_mode,
                    reason="previously_approved"
                )

            # Requires interactive approval
            return PermissionCheck(
                granted=False,
                mode=self.permission_mode,
                reason=f"manual_approval_required_for_{operation}",
                requires_interaction=True
            )

        # Default: allow non-dangerous operations
        return PermissionCheck(
            granted=True,
            mode=self.permission_mode,
            reason="default_allowed"
        )

    def _make_approval_key(self, operation: str, details: Optional[Dict[str, Any]]) -> str:
        """Create a unique key for operation approval caching."""
        if not details:
            return operation
        return f"{operation}:{hash(frozenset(details.items()))}"

    def approve(self, operation: str, details: Optional[Dict[str, Any]] = None,
                duration_seconds: Optional[int] = None) -> None:
        """Approve an operation for future checks.

        SOURCE: xai-grok-shell/src/extensions/permission.rs - Approval patterns

        Args:
            operation: The operation to approve
            details: Optional details for specific approval
            duration_seconds: Optional approval duration (not currently enforced)
        """
        approval_key = self._make_approval_key(operation, details)
        self._approved_operations.add(approval_key)
        logger.debug(f"Approved operation: {operation}")

    def revoke_approvals(self, operations: Optional[List[str]] = None) -> None:
        """Revoke approved operations.

        SOURCE: xai-grok-shell/src/extensions/permission.rs - Revocation patterns

        Args:
            operations: Specific operations to revoke, or None to revoke all
        """
        if operations is None:
            self._approved_operations.clear()
        else:
            for op in operations:
                self._approved_operations.discard(op)


class SessionEventEmitter(ABC):
    """Abstract base for session event emission.

    SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Event emission patterns
    """

    @abstractmethod
    async def emit(self, event: 'SessionEvent') -> None:
        """Emit a session event."""
        pass

    @abstractmethod
    async def subscribe(self, event_type: 'SessionEventType',
                       handler: Callable[['SessionEvent'], Any]) -> None:
        """Subscribe to session events."""
        pass


class SessionEventType(Enum):
    """Event types for session lifecycle.

    SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - SessionEvent patterns
    """
    STATE_CHANGED = "state_changed"
    TURN_STARTED = "turn_started"
    TURN_COMPLETED = "turn_completed"
    TURN_CANCELLED = "turn_cancelled"
    PERMISSION_REQUIRED = "permission_required"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_DENIED = "permission_denied"
    SESSION_CLOSED = "session_closed"
    ERROR = "error"


@dataclass
class SessionEvent:
    """Event emitted by a session.

    SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Event struct patterns
    """
    type: SessionEventType
    session_id: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class SimpleSessionEventEmitter(SessionEventEmitter):
    """Simple session event emitter with in-memory subscriptions.

    SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - EventEmitter implementation
    """

    def __init__(self):
        self._subscribers: Dict[SessionEventType, List[Callable]] = {}
        self._all_subscribers: List[Callable] = []
        self._lock = threading.Lock()

    async def emit(self, event: SessionEvent) -> None:
        """Emit an event to all subscribers.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - emit method
        """
        with self._lock:
            # Notify specific type subscribers
            for handler in self._subscribers.get(event.type, []):
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                except Exception as e:
                    logger.error(f"Session event handler error: {e}")

            # Notify global subscribers
            for handler in self._all_subscribers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                except Exception as e:
                    logger.error(f"Global session event handler error: {e}")

    async def subscribe(self, event_type: SessionEventType,
                       handler: Callable[[SessionEvent], Any]) -> None:
        """Subscribe to a specific event type.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - subscribe method
        """
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(handler)

    def subscribe_all(self, handler: Callable[[SessionEvent], Any]) -> None:
        """Subscribe to all session events."""
        with self._lock:
            self._all_subscribers.append(handler)


class Session:
    """Session representing a conversation context.

    SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - MvpAgent session management

    This class manages:
    - Session state and lifecycle
    - Turn tracking and management
    - Capability enforcement
    - Permission checking
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        cwd: str = ".",
        model_id: str = "default",
        capabilities: Optional[SessionCapabilities] = None,
    ):
        """Create a new session.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Session creation patterns

        Args:
            session_id: Optional session ID (auto-generated if not provided)
            cwd: Working directory for the session
            model_id: Model ID for the session
            capabilities: Session capabilities (defaults to empty)
        """
        self.session_id = session_id or f"session_{uuid.uuid4().hex[:12]}"
        self.cwd = cwd

        # Session info
        self.info = SessionInfo(
            session_id=self.session_id,
            cwd=cwd,
            model_id=model_id,
        )

        # State
        self._state = SessionState.IDLE
        self._live_state = SessionLiveState.IdleResident
        self._turn_context = TurnContext()

        # Capabilities
        self.capabilities = capabilities or SessionCapabilities()

        # Permission checking
        self.permission_checker = PermissionChecker(
            permission_mode=PermissionMode.MANUAL
        )

        # Event emitter
        self._event_emitter = SimpleSessionEventEmitter()

        # History
        self._history: List[Dict[str, Any]] = []

        # Pending interactions (permission requests, etc.)
        self._pending_interactions: List[Dict[str, Any]] = []

        # Lock for thread safety
        self._lock = threading.RLock()

        logger.info(f"Session created: {self.session_id}")

    # State management
    # SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs

    @property
    def state(self) -> SessionState:
        """Get current session state."""
        return self._state

    @property
    def live_state(self) -> SessionLiveState:
        """Get current live state (for roster/dashboard)."""
        return self._live_state

    def set_state(self, new_state: SessionState) -> None:
        """Update session state.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs - set_session_live_state
        """
        with self._lock:
            old_state = self._state
            self._state = new_state
            logger.debug(f"Session {self.session_id} state: {old_state.value} -> {new_state.value}")

    def set_live_state(self, new_live_state: SessionLiveState) -> None:
        """Update session live state (for roster tracking).

        SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs - set_session_live_state
        """
        with self._lock:
            self._live_state = new_live_state

    def is_active(self) -> bool:
        """Check if session is currently active (has running turn)."""
        return self._state == SessionState.ACTIVE

    def is_waiting(self) -> bool:
        """Check if session is waiting for interaction."""
        return self._state == SessionState.WAITING

    # Turn management
    # SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs - turn tracking

    @property
    def turn_index(self) -> int:
        """Get current turn index."""
        return self._turn_context.turn_index

    @property
    def current_prompt_id(self) -> Optional[str]:
        """Get current running prompt ID (if any)."""
        return self._turn_context.prompt_id

    def start_turn(self, prompt_id: Optional[str] = None) -> TurnContext:
        """Start a new turn.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs - turn start patterns

        Args:
            prompt_id: Optional prompt ID for tracking

        Returns:
            The TurnContext for this turn
        """
        with self._lock:
            self._turn_context.turn_index += 1
            self._turn_context.prompt_id = prompt_id or f"prompt_{uuid.uuid4().hex[:8]}"
            self._turn_context.started_at = datetime.now()
            self._turn_context.completed_at = None
            self._turn_context.cancelled = False
            self._turn_context.cancellation_category = None
            self._turn_context.cancel_trigger = None
            self._state = SessionState.ACTIVE
            self.info.turns = self._turn_context.turn_index
            return self._turn_context

    def complete_turn(self,
                     total_tokens: int = 0,
                     prompt_tokens: int = 0,
                     completion_tokens: int = 0,
                     reasoning_tokens: int = 0) -> None:
        """Complete the current turn.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs - turn completion

        Args:
            total_tokens: Total tokens used in this turn
            prompt_tokens: Tokens in the prompt
            completion_tokens: Tokens in the completion
            reasoning_tokens: Reasoning tokens (if model supports)
        """
        with self._lock:
            self._turn_context.completed_at = datetime.now()
            self._turn_context.total_tokens = total_tokens
            self._turn_context.prompt_tokens = prompt_tokens
            self._turn_context.completion_tokens = completion_tokens
            self._turn_context.reasoning_tokens = reasoning_tokens
            self._state = SessionState.IDLE
            self.info.turns = self._turn_context.turn_index

    def cancel_turn(self, category: Optional[str] = None,
                   trigger: Optional[str] = None) -> None:
        """Cancel the current turn.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs - turn cancellation

        Args:
            category: Cancellation category (e.g., "doom_loop", "user_cancel")
            trigger: What triggered the cancel (e.g., "send_now", "ctrl_c")
        """
        with self._lock:
            self._turn_context.cancelled = True
            self._turn_context.cancellation_category = category
            self._turn_context.cancel_trigger = trigger
            self._turn_context.completed_at = datetime.now()
            self._state = SessionState.IDLE

    def is_busy(self) -> bool:
        """Check if session has live work (running turn or pending work).

        SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs - session_has_live_work

        Returns:
            True if session has active work
        """
        with self._lock:
            # Check if turn is running
            if self._turn_context.prompt_id and not self._turn_context.completed_at:
                return True
            # Check for pending interactions
            if self._pending_interactions:
                return True
            return False

    # Capability model
    # SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - SessionCapabilities patterns

    def get_capabilities(self) -> SessionCapabilities:
        """Get session capabilities."""
        return self.capabilities

    def update_capabilities(self, **kwargs) -> None:
        """Update session capabilities.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Capability updates

        Args:
            fs_read: Enable file system read
            fs_write: Enable file system write
            terminal_enabled: Enable terminal
            code_nav_enabled: Enable code navigation
            tools: List of available tools
            reasoning_effort: Reasoning effort level
            yolo_mode: Enable YOLO (auto-approve) mode
            worktree_enabled: Enable worktree support
            managed_mcp: Enable managed MCP
            plugins: List of plugins
            structured_output: Enable structured output
        """
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.capabilities, key):
                    setattr(self.capabilities, key, value)
            logger.debug(f"Session {self.session_id} capabilities updated")

    def set_yolo_mode(self, enabled: bool) -> None:
        """Enable or disable YOLO mode.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - YOLO mode patterns

        Args:
            enabled: True to enable YOLO (auto-approve dangerous operations)
        """
        with self._lock:
            self.capabilities.yolo_mode = enabled
            if enabled:
                self.permission_checker.set_mode(PermissionMode.AUTO_APPROVE)
            else:
                self.permission_checker.set_mode(PermissionMode.MANUAL)
            logger.info(f"Session {self.session_id} YOLO mode: {enabled}")

    def set_reasoning_effort(self, effort: Optional[str]) -> None:
        """Set reasoning effort level.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Reasoning effort patterns

        Args:
            effort: Reasoning effort (None = auto, or specific level like "high", "medium", "low")
        """
        self.capabilities.reasoning_effort = effort
        logger.debug(f"Session {self.session_id} reasoning_effort: {effort}")

    # Permission checking
    # SOURCE: xai-grok-shell/src/extensions/permission.rs - Permission checking

    def set_permission_mode(self, mode: PermissionMode) -> None:
        """Set permission mode for the session.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Permission mode setting

        Args:
            mode: The permission mode to use
        """
        with self._lock:
            self.permission_checker.set_mode(mode)
            logger.info(f"Session {self.session_id} permission mode: {mode.value}")

    def check_permission(self, operation: str,
                        details: Optional[Dict[str, Any]] = None) -> PermissionCheck:
        """Check if an operation is permitted.

        SOURCE: xai-grok-shell/src/extensions/permission.rs - Permission check

        Args:
            operation: The operation to check (e.g., "execute_command", "write_file")
            details: Optional details (command, path, etc.)

        Returns:
            PermissionCheck with granted status
        """
        result = self.permission_checker.check(operation, details)

        if result.requires_interaction:
            # Track pending interaction
            interaction = {
                "operation": operation,
                "details": details,
                "timestamp": datetime.now().isoformat(),
            }
            with self._lock:
                self._pending_interactions.append(interaction)

        return result

    def grant_permission(self, operation: str,
                        details: Optional[Dict[str, Any]] = None) -> None:
        """Grant permission for an operation.

        SOURCE: xai-grok-shell/src/extensions/permission.rs - Permission grant

        Args:
            operation: The operation to approve
            details: Optional details for specific approval
        """
        self.permission_checker.approve(operation, details)

        # Remove from pending interactions
        with self._lock:
            self._pending_interactions = [
                i for i in self._pending_interactions
                if i.get("operation") != operation
            ]

    def deny_permission(self, operation: str) -> None:
        """Deny permission for an operation.

        SOURCE: xai-grok-shell/src/extensions/permission.rs - Permission denial

        Args:
            operation: The operation to deny
        """
        with self._lock:
            self._pending_interactions = [
                i for i in self._pending_interactions
                if i.get("operation") != operation
            ]

    def has_pending_interactions(self) -> bool:
        """Check if session has pending permission interactions."""
        with self._lock:
            return len(self._pending_interactions) > 0

    def get_pending_interactions(self) -> List[Dict[str, Any]]:
        """Get list of pending interactions."""
        with self._lock:
            return self._pending_interactions.copy()

    # Event handling
    # SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Event emission patterns

    async def emit_event(self, event_type: SessionEventType,
                        data: Optional[Dict[str, Any]] = None) -> None:
        """Emit a session event.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Event emission

        Args:
            event_type: Type of event to emit
            data: Optional event data
        """
        event = SessionEvent(
            type=event_type,
            session_id=self.session_id,
            data=data or {}
        )
        await self._event_emitter.emit(event)

    async def subscribe(self, event_type: SessionEventType,
                       handler: Callable[[SessionEvent], Any]) -> None:
        """Subscribe to session events.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Event subscription

        Args:
            event_type: Type of event to subscribe to
            handler: Handler function
        """
        await self._event_emitter.subscribe(event_type, handler)

    # History management
    # SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - History patterns

    def add_to_history(self, entry: Dict[str, Any]) -> None:
        """Add an entry to session history.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - History tracking

        Args:
            entry: History entry (e.g., {"role": "user", "content": "..."})
        """
        with self._lock:
            entry["timestamp"] = datetime.now().isoformat()
            self._history.append(entry)

    def get_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get session history.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - History retrieval

        Args:
            limit: Optional limit on number of entries to return

        Returns:
            List of history entries
        """
        with self._lock:
            if limit:
                return self._history[-limit:].copy()
            return self._history.copy()

    # Session lifecycle
    # SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs

    def close(self) -> None:
        """Close the session gracefully.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs - close_session_explicit

        This marks the session as completed and emits the appropriate event.
        """
        with self._lock:
            self._state = SessionState.TERMINATED
            self._live_state = SessionLiveState.Completed
            logger.info(f"Session closed: {self.session_id}")

    def mark_dead(self, reason: str = "unknown") -> None:
        """Mark session as dead/failed.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs - reap_dead_session

        Args:
            reason: Reason for the failure
        """
        with self._lock:
            self._live_state = SessionLiveState.DeadFailed
            logger.warning(f"Session marked dead: {self.session_id}, reason: {reason}")

    def make_dormant(self) -> None:
        """Make session dormant (evicted to disk).

        SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs - Dormant state

        Session can be resumed later from disk.
        """
        with self._lock:
            self._live_state = SessionLiveState.Dormant
            logger.info(f"Session made dormant: {self.session_id}")

    # Info and serialization
    # SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - SessionInfo patterns

    def get_info(self) -> SessionInfo:
        """Get session info."""
        return self.info

    def to_dict(self) -> Dict[str, Any]:
        """Serialize session to dictionary.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Session serialization
        """
        return {
            "session_id": self.session_id,
            "cwd": self.cwd,
            "state": self._state.value,
            "live_state": self._live_state.value,
            "turn_index": self.turn_index,
            "capabilities": self.capabilities.to_dict(),
            "permission_mode": self.permission_checker.permission_mode.value,
            "history_length": len(self._history),
            "pending_interactions": len(self._pending_interactions),
            "created_at": self.info.created_at.isoformat(),
            "model_id": self.info.model_id,
            "agent_name": self.info.agent_name,
        }

    def __repr__(self) -> str:
        return f"Session(id={self.session_id}, state={self._state.value}, turns={self.turn_index})"


class SessionRegistry:
    """Registry for managing multiple sessions.

    SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Sessions HashMap patterns
    """

    def __init__(self):
        """Initialize session registry."""
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.RLock()
        logger.info("SessionRegistry initialized")

    def create_session(
        self,
        cwd: str = ".",
        model_id: str = "default",
        capabilities: Optional[SessionCapabilities] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        """Create and register a new session.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs - spawn patterns

        Args:
            cwd: Working directory for the session
            model_id: Model ID for the session
            capabilities: Session capabilities
            session_id: Optional session ID (auto-generated if not provided)

        Returns:
            The created Session
        """
        session = Session(
            session_id=session_id,
            cwd=cwd,
            model_id=model_id,
            capabilities=capabilities,
        )

        with self._lock:
            self._sessions[session.session_id] = session

        logger.info(f"Session registered: {session.session_id}")
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs - get session

        Args:
            session_id: The session ID to look up

        Returns:
            The Session if found, None otherwise
        """
        with self._lock:
            return self._sessions.get(session_id)

    def remove_session(self, session_id: str, finalize: bool = True) -> bool:
        """Remove a session from the registry.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs - remove_session

        Args:
            session_id: The session ID to remove
            finalize: If True, mark as completed; if False, leave as dormant

        Returns:
            True if session was removed, False if not found
        """
        with self._lock:
            if session_id not in self._sessions:
                return False

            session = self._sessions[session_id]

            if finalize:
                session.close()

            del self._sessions[session_id]
            logger.info(f"Session removed from registry: {session_id}")
            return True

    def list_sessions(self) -> List[str]:
        """List all session IDs.

        SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs - roster patterns

        Returns:
            List of session IDs
        """
        with self._lock:
            return list(self._sessions.keys())

    def get_active_sessions(self) -> List[Session]:
        """Get all active sessions (sessions with running turns).

        SOURCE: xai-grok-shell/src/agent/mvp_agent/session_lifecycle.rs - roster patterns

        Returns:
            List of active sessions
        """
        with self._lock:
            return [s for s in self._sessions.values() if s.is_active()]

    def get_session_count(self) -> int:
        """Get total number of sessions."""
        with self._lock:
            return len(self._sessions)

    def clear(self) -> None:
        """Clear all sessions from the registry."""
        with self._lock:
            self._sessions.clear()
            logger.info("SessionRegistry cleared")


# Convenience functions
def create_session(
    cwd: str = ".",
    model_id: str = "default",
    capabilities: Optional[SessionCapabilities] = None,
    session_id: Optional[str] = None,
) -> Session:
    """Create a new session with the given configuration.

    SOURCE: xai-grok-shell/src/agent/mvp_agent/mod.rs - Session creation patterns
    """
    return Session(
        session_id=session_id,
        cwd=cwd,
        model_id=model_id,
        capabilities=capabilities,
    )


# Default registry instance
_default_registry: Optional[SessionRegistry] = None


def get_default_registry() -> SessionRegistry:
    """Get the default session registry instance."""
    global _default_registry
    if _default_registry is None:
        _default_registry = SessionRegistry()
    return _default_registry