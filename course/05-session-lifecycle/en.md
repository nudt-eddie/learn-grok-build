# Lesson 05: Session Lifecycle

## Introduction

A session represents a conversation between a user and an AI model. Understanding the session lifecycle helps you build applications that maintain context, handle state transitions, and manage resources efficiently.

## Session Lifecycle Stages

A typical session goes through the following stages:

### 1. Creation
When a new conversation begins, a session is initialized with:
- A unique session ID
- Empty message history
- Default configuration (model, temperature, etc.)

```python
session = Session(
    session_id="unique-123",
    model="gpt-4",
    temperature=0.7
)
```

### 2. Active State
During active use, the session:
- Accumulates message history
- Maintains context window
- Processes user requests

```python
# Add user message
session.add_message(role="user", content="Hello!")

# Generate response
response = session.generate()

# Add assistant response
session.add_message(role="assistant", content=response)
```

### 3. Context Compaction
When the context window approaches its limit, older messages may be summarized or removed to free space for new interactions.

### 4. Termination
A session ends when:
- User explicitly ends the conversation
- Session timeout is reached
- Maximum turn limit is exceeded

```python
session.close()  # Clean up resources
```

## State Diagram

```
[Created] --> [Active] --> [Compacting] --> [Terminated]
                |                            ^
                |                            |
                +------- (timeout) --------+
```

## Managing Session State

### Persisting Sessions
Save session state for later use:

```python
# Save session to disk
session.save("session_backup.json")

# Restore session
restored = Session.load("session_backup.json")
```

### Session Timeout Handling

```python
class Session:
    def __init__(self, timeout_seconds=3600):
        self.timeout = timeout_seconds
        self.last_activity = time.time()

    def is_expired(self):
        return (time.time() - self.last_activity) > self.timeout
```

## Best Practices

- Always close sessions to release resources
- Implement timeout handling to prevent resource leaks
- Use session IDs for tracking and debugging
- Consider context compaction for long conversations
- Store important context before session termination

## Common Patterns

### Stateless Requests
For simple queries without conversation history:

```python
def single_query(prompt):
    session = Session()
    try:
        return session.generate(prompt)
    finally:
        session.close()
```

### Stateful Conversations
Maintaining context across multiple exchanges:

```python
def conversational_flow(messages):
    session = Session()
    for msg in messages:
        session.add_message(**msg)
        response = session.generate()
        session.add_message(role="assistant", content=response)
    return session.get_history()
```

## Key Takeaways

- Sessions track conversation state from creation to termination
- Proper resource management prevents memory leaks
- Context compaction ensures long conversations remain functional
- Session persistence enables恢复 across application restarts
- Timeout handling maintains system stability

## Practice Exercise

Create a session manager class that:
1. Handles session creation with configurable parameters
2. Implements automatic cleanup on timeout
3. Persists session state to a database

## Next Lesson

In the next lesson, we will explore advanced session patterns including multi-agent coordination.