# Build Your Own Coding Agent Harness

A hands-on course on building a coding agent from scratch using Grok.

## Course Overview

Learn to build a coding agent harness step by step, understanding the core concepts that power modern AI coding assistants.

## Lessons

---

### 01 Minimal Agent Loop

**Objectives:**
- Understand the core agent loop pattern (input -> reasoning -> output)
- Create a basic harness that sends a prompt to Grok and processes the response
- Learn to structure conversations with system prompts and message history

**Prerequisites:**
- Grok API key configured
- Basic familiarity with Python and async/await syntax
- `openai` Python package installed

**Step-by-Step Implementation:**

1. Create the project directory structure:
```
agent-harness/
  lesson_01/
    agent.py
    requirements.txt
```

2. Set up a minimal Python script that initializes the Grok client

3. Build a simple loop: collect user input, send to model, display response

4. Add a basic message history list to maintain conversation context

**Code Snippets:**

```python
# lesson_01/agent.py
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("GROK_API_KEY"),
    base_url="https://api.x.ai/v1"
)

def create_message(role: str, content: str) -> dict:
    return {"role": role, "content": content}

def run_agent_loop():
    messages = [
        create_message("system", "You are a helpful coding assistant.")
    ]
    
    print("Agent loop started. Type 'exit' to quit.\n")
    
    while True:
        user_input = input("You: ")
        if user_input.lower() == "exit":
            print("Goodbye!")
            break
        
        messages.append(create_message("user", user_input))
        
        response = client.chat.completions.create(
            model="grok-3",
            messages=messages,
            max_tokens=1024
        )
        
        assistant_reply = response.choices[0].message.content
        print(f"Agent: {assistant_reply}\n")
        
        messages.append(create_message("assistant", assistant_reply))

if __name__ == "__main__":
    run_agent_loop()
```

```text
# lesson_01/requirements.txt
openai>=1.12.0
```

**Expected Output:**
```
Agent loop started. Type 'exit' to quit.

You: Hello
Agent: Hello! How can I help you with your code today?

You: What is a function?
Agent: A function is a reusable block of code that performs a specific task...

You: exit
Goodbye!
```

**Verification Command:**
```bash
cd lesson_01
pip install -r requirements.txt
export GROK_API_KEY="your-api-key"
python agent.py
```

---

### 02 Tool Call

**Objectives:**
- Learn how to define tools using a schema format
- Parse tool calls from model responses
- Execute tools and return results to the model

**Prerequisites:**
- Completed Lesson 01 (working agent loop)
- Understanding of JSON schema for tool definitions

**Step-by-Step Implementation:**

1. Define a simple tool (e.g., a calculator or date utility)

2. Modify the agent loop to include tools in the API request

3. Parse the model's function call from the response

4. Execute the function and send results back to the model

**Code Snippets:**

```python
# lesson_02/agent.py
import os
import json
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("GROK_API_KEY"),
    base_url="https://api.x.ai/v1"
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a mathematical expression",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Math expression to evaluate (e.g., '2 + 2')"
                    }
                },
                "required": ["expression"]
            }
        }
    }
]

def execute_tool(name: str, arguments: dict) -> str:
    if name == "calculate":
        try:
            result = eval(arguments["expression"])
            return f"Result: {result}"
        except Exception as e:
            return f"Error: {e}"
    return "Unknown tool"

def run_agent_with_tools():
    messages = [
        {"role": "system", "content": "You have access to tools. Use them when needed."}
    ]
    
    while True:
        user_input = input("You: ")
        if user_input.lower() == "exit":
            break
        
        messages.append({"role": "user", "content": user_input})
        
        response = client.chat.completions.create(
            model="grok-3",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto"
        )
        
        response_message = response.choices[0].message
        
        if response_message.tool_calls:
            messages.append(response_message.model_dump(exclude_none=True))
            
            for tool_call in response_message.tool_calls:
                tool_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                result = execute_tool(tool_name, args)
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })
            
            # Get final response after tool results
            follow_up = client.chat.completions.create(
                model="grok-3",
                messages=messages
            )
            print(f"Agent: {follow_up.choices[0].message.content}\n")
        else:
            print(f"Agent: {response_message.content}\n")
            messages.append({"role": "assistant", "content": response_message.content})

if __name__ == "__main__":
    run_agent_with_tools()
```

**Expected Output:**
```
You: What is 15 * 23?
Agent: 15 multiplied by 23 equals 345.

You: Calculate (100 - 50) / 5
Agent: (100 - 50) / 5 = 10

You: exit
```

**Verification Command:**
```bash
cd lesson_02
python agent.py
# Then type: What is 25 + 37?
# Expected: The agent will call the calculate tool and return 62
```

---

### 03 Read/Edit/Execute

**Objectives:**
- Implement file read operations to inspect source code
- Add file editing capabilities (create, modify, append)
- Build command execution for testing code
- Integrate all three into a cohesive workflow

**Prerequisites:**
- Completed Lessons 01-02
- Familiarity with file I/O in Python

**Step-by-Step Implementation:**

1. Create a file reader tool to read source files
2. Create a file editor tool with line-based editing
3. Create a bash executor tool for running commands
4. Wire them into the agent loop

**Code Snippets:**

```python
# lesson_03/agent.py
import os
import json
import subprocess
from pathlib import Path
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("GROK_API_KEY"),
    base_url="https://api.x.ai/v1"
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read contents of a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file with content",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file"},
                    "content": {"type": "string", "description": "Content to write"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_command",
            "description": "Execute a bash command and return output",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to execute"},
                    "cwd": {"type": "string", "description": "Working directory"}
                },
                "required": ["command"]
            }
        }
    }
]

def execute_tool(name: str, arguments: dict) -> str:
    if name == "read_file":
        try:
            content = Path(arguments["path"]).read_text()
            return f"File content:\n{content[:2000]}"  # Limit output
        except Exception as e:
            return f"Error reading file: {e}"
    
    elif name == "write_file":
        try:
            Path(arguments["path"]).write_text(arguments["content"])
            return f"Successfully wrote to {arguments['path']}"
        except Exception as e:
            return f"Error writing file: {e}"
    
    elif name == "execute_command":
        try:
            cwd = arguments.get("cwd", os.getcwd())
            result = subprocess.run(
                arguments["command"],
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30
            )
            output = f"Exit code: {result.returncode}\n"
            if result.stdout:
                output += f"STDOUT:\n{result.stdout[:2000]}\n"
            if result.stderr:
                output += f"STDERR:\n{result.stderr[:2000]}\n"
            return output
        except Exception as e:
            return f"Error executing command: {e}"
    
    return "Unknown tool"
```

**Expected Output:**
```
You: Create a file called hello.py that prints Hello World
Agent: I'll create that file for you.
Tool: write_file(path="/path/to/hello.py", content="print('Hello World')")
Agent: Created hello.py successfully.

You: Run it
Agent: Executing hello.py...
Tool: execute_command(command="python hello.py")
Agent: Exit code: 0
STDOUT:
Hello World
```

**Verification Command:**
```bash
cd lesson_03
# Create a test file first
echo 'def add(a, b): return a + b' > test_math.py
python agent.py
# Then ask: Read test_math.py and run it with pytest
```

---

### 04 Permissions

**Objectives:**
- Design a permission system with different security levels
- Implement allow/deny rules for tools and file paths
- Add user confirmation prompts for sensitive operations
- Log all agent actions for auditing

**Prerequisites:**
- Completed Lessons 01-03
- Understanding of security principles

**Step-by-Step Implementation:**

1. Define permission levels (read-only, read-write, execute, admin)
2. Create a PermissionManager class with rules
3. Wrap tool execution with permission checks
4. Add interactive confirmation for dangerous operations

**Code Snippets:**

```python
# lesson_04/agent.py
import os
import json
from enum import Enum
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from openai import OpenAI

class PermissionLevel(Enum):
    NONE = 0
    READ = 1
    WRITE = 2
    EXECUTE = 3
    ADMIN = 4

@dataclass
class PermissionRule:
    pattern: str  # Glob pattern for paths
    level: PermissionLevel
    requires_confirmation: bool = False

class PermissionManager:
    def __init__(self):
        self.rules: list[PermissionRule] = [
            PermissionRule("*.py", PermissionLevel.WRITE),
            PermissionRule("*.txt", PermissionLevel.WRITE),
            PermissionRule("**/*", PermissionLevel.READ),
            PermissionRule("/bin/**", PermissionLevel.EXECUTE),
            PermissionRule("rm **", PermissionLevel.ADMIN, requires_confirmation=True),
            PermissionRule("sudo **", PermissionLevel.ADMIN, requires_confirmation=True),
        ]
        self.confirmed_once: set[str] = set()
    
    def check_permission(self, tool: str, path: Optional[str] = None) -> tuple[bool, str]:
        # Check tool-level permissions
        dangerous_tools = {"execute_command", "delete_file", "system_info"}
        if tool in dangerous_tools:
            for rule in self.rules:
                if "**" in rule.pattern and tool in rule.pattern:
                    if rule.level == PermissionLevel.ADMIN:
                        if tool not in self.confirmed_once:
                            return False, f"CONFIRM_REQUIRED:{tool}"
                        return True, "allowed"
        
        # Check path-level permissions
        if path:
            for rule in self.rules:
                if Path(path).match(rule.pattern) or Path(path).name.match(rule.pattern.split("/")[-1]):
                    if rule.requires_confirmation and path not in self.confirmed_once:
                        return False, f"CONFIRM_REQUIRED:path:{path}"
                    return True, f"allowed (level: {rule.level.name})"
        
        return False, "denied: no matching rule"
    
    def confirm(self, item: str):
        self.confirmed_once.add(item)
        print(f"[PERMISSION] Confirmed: {item}")

def confirm_action(message: str) -> bool:
    response = input(f"\n[CONFIRM] {message} (yes/no): ")
    return response.lower() in ("yes", "y")
```

**Expected Output:**
```
You: Delete the file /tmp/test.log
Agent: I'll attempt to delete that file...
[PERMISSION] Checking permission for execute_command matching "rm **"
[CONFIRM] This is a potentially dangerous command. Proceed? (yes/no): yes
[PERMISSION] Confirmed: execute_command
Agent: Successfully deleted /tmp/test.log
```

**Verification Command:**
```bash
cd lesson_04
python agent.py
# Try: Read /etc/passwd (should work with READ level)
# Try: rm -rf / (should require admin confirmation)
```

---

### 05 Compaction

**Objectives:**
- Understand the context window limit problem
- Implement conversation summarization to compress history
- Define trigger conditions for compaction (token count, message count)
- Preserve critical information (system prompt, tool definitions) during compaction

**Prerequisites:**
- Completed Lessons 01-04
- Basic understanding of token-based pricing

**Step-by-Step Implementation:**

1. Create a token counter utility
2. Implement a summarization prompt that condenses conversation
3. Add compaction trigger logic to the agent loop
4. Test with long conversations to verify context management

**Code Snippets:**

```python
# lesson_05/agent.py
import os
import tiktoken
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("GROK_API_KEY"),
    base_url="https://api.x.ai/v1"
)

# Estimate tokens (rough approximation)
def count_tokens(messages: list[dict], model: str = "grok-3") -> int:
    encoding = tiktoken.encoding_for_model("gpt-4")  # Approximate
    total = 0
    for msg in messages:
        total += len(encoding.encode(str(msg)))
    return total

def summarize_history(messages: list[dict], client: OpenAI) -> list[dict]:
    """Compress conversation history by summarizing old messages."""
    # Keep system prompt and first few messages
    system = [m for m in messages if m["role"] == "system"]
    rest = [m for m in messages if m["role"] != "system"]
    
    if len(rest) <= 4:
        return system + rest
    
    to_summarize = rest[:-4]  # Keep last 4 exchanges
    remaining = rest[-4:]
    
    summary_prompt = f"""Summarize this conversation concisely, preserving key facts, 
    decisions, and any code or technical details that were discussed:
    
    {to_summarize}"""
    
    response = client.chat.completions.create(
        model="grok-3",
        messages=[
            {"role": "system", "content": "You summarize conversations accurately."},
            {"role": "user", "content": summary_prompt}
        ],
        max_tokens=500
    )
    
    summary = response.choices[0].message.content
    
    return system + [
        {"role": "system", "content": f"[CONVERSATION SUMMARY]\n{summary}"}
    ] + remaining

MAX_TOKENS = 30000
COMPACTION_THRESHOLD = 25000

def check_and_compact(messages: list[dict]) -> list[dict]:
    token_count = count_tokens(messages)
    print(f"[COMPACTION] Current tokens: ~{token_count}")
    
    if token_count > COMPACTION_THRESHOLD:
        print(f"[COMPACTION] Threshold exceeded. Compressing conversation...")
        return summarize_history(messages, client)
    
    return messages
```

**Expected Output:**
```
[COMPACTION] Current tokens: ~24100
You: Let's continue with the next task...
[COMPACTION] Current tokens: ~28900
[COMPACTION] Threshold exceeded. Compressing conversation...
[COMPACTION] Summary created: 12 messages condensed to 1
[COMPACTION] New token count: ~4500
Agent: Sure, continuing from where we left off...
```

**Verification Command:**
```bash
cd lesson_05
pip install tiktoken
python agent.py
# Run a long conversation (10+ exchanges) and watch compaction triggers
```

---

### 06 Checkpoint

**Objectives:**
- Implement state serialization for pause/resume functionality
- Save agent state (messages, tool history, session data) to disk
- Load and restore state from checkpoint files
- Add auto-save and checkpoint naming conventions

**Prerequisites:**
- Completed Lessons 01-05
- Familiarity with Python pickle or JSON serialization

**Step-by-Step Implementation:**

1. Define the agent state structure
2. Create checkpoint save/load functions
3. Add checkpoint commands to the agent interface
4. Implement auto-save on a timer or after N operations

**Code Snippets:**

```python
# lesson_06/agent.py
import os
import json
import shutil
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("GROK_API_KEY"),
    base_url="https://api.x.ai/v1"
)

@dataclass
class AgentState:
    messages: list[dict]
    tool_call_count: int
    session_id: str
    created_at: str
    last_updated: str

class CheckpointManager:
    def __init__(self, checkpoint_dir: str = "./checkpoints"):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(exist_ok=True)
    
    def save(self, state: AgentState, name: Optional[str] = None) -> Path:
        if name is None:
            name = f"checkpoint_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        path = self.checkpoint_dir / f"{name}.json"
        path.write_text(json.dumps(asdict(state), indent=2))
        
        # Also save as 'latest' for quick restore
        latest = self.checkpoint_dir / "latest.json"
        shutil.copy(path, latest)
        
        print(f"[CHECKPOINT] Saved to {path}")
        return path
    
    def load(self, name: str = "latest") -> AgentState:
        path = self.checkpoint_dir / f"{name}.json"
        if not path.exists():
            path = self.checkpoint_dir / f"{name}"  # Try without extension
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint '{name}' not found")
        
        data = json.loads(path.read_text())
        print(f"[CHECKPOINT] Loaded from {path}")
        return AgentState(**data)
    
    def list_checkpoints(self) -> list[str]:
        return [p.stem for p in self.checkpoint_dir.glob("*.json") 
                if p.stem != "latest"]

# Usage in agent loop
def run_agent_with_checkpointing():
    checkpoint_mgr = CheckpointManager()
    state = AgentState(
        messages=[{"role": "system", "content": "You are a coding assistant."}],
        tool_call_count=0,
        session_id=datetime.now().strftime("%Y%m%d%H%M%S"),
        created_at=datetime.now().isoformat(),
        last_updated=datetime.now().isoformat()
    )
    
    while True:
        user_input = input("You (checkpoint/save/load/list/exit): ").strip()
        
        if user_input == "exit":
            state.last_updated = datetime.now().isoformat()
            checkpoint_mgr.save(state)
            break
        
        elif user_input == "save":
            state.last_updated = datetime.now().isoformat()
            checkpoint_mgr.save(state)
        
        elif user_input == "load":
            state = checkpoint_mgr.load()
        
        elif user_input == "list":
            print(f"Available checkpoints: {checkpoint_mgr.list_checkpoints()}")
        
        elif user_input == "checkpoint":
            name = input("Checkpoint name: ").strip()
            state.last_updated = datetime.now().isoformat()
            checkpoint_mgr.save(state, name)
        
        else:
            state.messages.append({"role": "user", "content": user_input})
            
            response = client.chat.completions.create(
                model="grok-3",
                messages=state.messages
            )
            
            reply = response.choices[0].message.content
            state.messages.append({"role": "assistant", "content": reply})
            state.tool_call_count += 1
            state.last_updated = datetime.now().isoformat()
            
            print(f"Agent: {reply}\n")
            
            # Auto-save every 10 interactions
            if state.tool_call_count % 10 == 0:
                checkpoint_mgr.save(state)
```

**Expected Output:**
```
You: Let's work on the login feature
Agent: Sure, I'll help you implement the login feature...

You: save
[CHECKPOINT] Saved to checkpoints/checkpoint_20260119_143022.json
[CHECKPOINT] Saved to checkpoints/latest.json

You: exit
[CHECKPOINT] Saved final state

# In a new session:
> load
[CHECKPOINT] Loaded from checkpoints/latest.json
Agent: Welcome back! How can I help you continue?
```

**Verification Command:**
```bash
cd lesson_06
python agent.py
# Interact for a few turns, save, exit, run again, and use 'load'
```

---

### 07 Subagent

**Objectives:**
- Design a parent-child agent architecture
- Implement task delegation from parent to subagents
- Handle communication between parent and child agents
- Manage subagent lifecycle (spawn, monitor, terminate)

**Prerequisites:**
- Completed Lessons 01-06
- Understanding of multi-process or multi-threaded programming

**Step-by-Step Implementation:**

1. Define a Subagent class with its own message context
2. Create a TaskDispatcher in the parent agent
3. Implement result collection from subagents
4. Add timeout handling and error recovery

**Code Snippets:**

```python
# lesson_07/agent.py
import os
import json
import threading
from queue import Queue, Empty
from dataclasses import dataclass
from typing import Optional
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("GROK_API_KEY"),
    base_url="https://api.x.ai/v1"
)

@dataclass
class SubagentTask:
    task_id: str
    description: str
    context: list[dict]
    tools: list[dict]

@dataclass
class SubagentResult:
    task_id: str
    success: bool
    output: str
    error: Optional[str] = None

class Subagent:
    def __init__(self, name: str, system_prompt: str, tools: list[dict]):
        self.name = name
        self.system_prompt = system_prompt
        self.tools = tools
        self.messages = [{"role": "system", "content": system_prompt}]
    
    def execute(self, task: SubagentTask, result_queue: Queue, timeout: int = 60):
        self.messages.extend(task.context)
        self.messages.append({"role": "user", "content": task.description})
        
        try:
            response = client.chat.completions.create(
                model="grok-3",
                messages=self.messages,
                tools=self.tools,
                timeout=timeout
            )
            result = SubagentResult(
                task_id=task.task_id,
                success=True,
                output=response.choices[0].message.content
            )
        except Exception as e:
            result = SubagentResult(
                task_id=task.task_id,
                success=False,
                output="",
                error=str(e)
            )
        
        result_queue.put(result)

class TaskDispatcher:
    def __init__(self):
        self.active_subagents: dict[str, threading.Thread] = {}
        self.result_queues: dict[str, Queue] = {}
    
    def spawn_subagent(self, name: str, system_prompt: str, tools: list[dict]) -> str:
        agent = Subagent(name, system_prompt, tools)
        # Store in registry (simplified)
        print(f"[DISPATCHER] Spawned subagent: {name}")
        return name
    
    def dispatch_task(self, agent_name: str, task: SubagentTask, timeout: int = 60) -> SubagentResult:
        result_queue = Queue()
        self.result_queues[task.task_id] = result_queue
        
        # In production, this would run in a separate process
        # For simplicity, running synchronously here
        agent = Subagent(agent_name, "", [])
        agent.execute(task, result_queue, timeout)
        
        return result_queue.get(timeout=timeout + 5)

def run_with_subagents():
    dispatcher = TaskDispatcher()
    
    # Define specialized subagents
    dispatcher.spawn_subagent(
        "code_review",
        "You are an expert code reviewer. Analyze code for bugs, style, and improvements.",
        []
    )
    
    dispatcher.spawn_subagent(
        "test_writer",
        "You write comprehensive unit tests. Focus on edge cases and coverage.",
        []
    )
    
    messages = [{"role": "system", "content": "You coordinate specialized subagents to complete complex tasks."}]
    
    while True:
        user_input = input("You: ")
        if user_input.lower() == "exit":
            break
        
        messages.append({"role": "user", "content": user_input})
        
        # For demo: show how delegation would work
        if "review" in user_input.lower() or "test" in user_input.lower():
            task_type = "code_review" if "review" in user_input.lower() else "test_writer"
            
            task = SubagentTask(
                task_id=f"task_{len(messages)}",
                description=user_input,
                context=[],
                tools=[]
            )
            
            print(f"[DISPATCHER] Delegating to {task_type}...")
            result = dispatcher.dispatch_task(task_type, task)
            
            if result.success:
                print(f"[{task_type}] Result: {result.output}")
            else:
                print(f"[{task_type}] Error: {result.error}")
```

**Expected Output:**
```
You: Review this code for potential bugs
[DISPATCHER] Delegating to code_review...
[DISPATCHER] Spawned subagent: code_review
[code_review] Result: I found 3 issues:
1. Possible null pointer on line 42
2. Memory leak in the connection handler
3. Missing error handling...

You: Write tests for the login function
[DISPATCHER] Delegating to test_writer...
[test_writer] Result: Here are the unit tests...
```

**Verification Command:**
```bash
cd lesson_07
python agent.py
# Ask: Review this login function
# Ask: Write tests for the registration feature
```

---

### 08 MCP (Model Context Protocol)

**Objectives:**
- Understand the MCP protocol and its architecture
- Implement an MCP client to connect to external servers
- Create custom MCP tools that integrate with the agent
- Build a multi-tool MCP workflow

**Prerequisites:**
- Completed Lessons 01-07
- Understanding of JSON-RPC protocol
- Familiarity with MCP server setup (or available MCP server)

**Step-by-Step Implementation:**

1. Understand MCP protocol (JSON-RPC 2.0 over stdio or HTTP)
2. Implement MCP client class with connection management
3. Create adapters to convert MCP tools to agent tools
4. Handle MCP responses and errors

**Code Snippets:**

```python
# lesson_08/agent.py
import os
import json
import subprocess
from typing import Any, Optional
from dataclasses import dataclass
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("GROK_API_KEY"),
    base_url="https://api.x.ai/v1"
)

@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict

class MCPClient:
    """Minimal MCP client for connecting to MCP servers."""
    
    def __init__(self, command: list[str], env: Optional[dict] = None):
        self.command = command
        self.env = env or os.environ.copy()
        self.process: Optional[subprocess.Popen] = None
    
    def connect(self):
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            text=True
        )
        print(f"[MCP] Connected to server: {' '.join(self.command)}")
    
    def send_request(self, method: str, params: dict = None) -> dict:
        if not self.process:
            raise RuntimeError("Not connected to MCP server")
        
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {}
        }
        
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        
        response_line = self.process.stdout.readline()
        return json.loads(response_line)
    
    def list_tools(self) -> list[MCPTool]:
        result = self.send_request("tools/list")
        tools = []
        for tool in result.get("result", []):
            tools.append(MCPTool(
                name=tool["name"],
                description=tool.get("description", ""),
                input_schema=tool.get("inputSchema", {})
            ))
        return tools
    
    def call_tool(self, name: str, arguments: dict) -> str:
        result = self.send_request("tools/call", {
            "name": name,
            "arguments": arguments
        })
        if "error" in result:
            return f"Error: {result['error']}"
        return result.get("result", {}).get("content", "No result")
    
    def disconnect(self):
        if self.process:
            self.process.terminate()
            print("[MCP] Disconnected from server")


def run_with_mcp():
    # Example: Connect to a filesystem MCP server
    # This assumes an MCP server is available at the specified path
    mcp_client = MCPClient([
        "npx", "-y", "@modelcontextprotocol/server-filesystem",
        "/tmp"
    ])
    
    try:
        mcp_client.connect()
        mcp_tools = mcp_client.list_tools()
        
        print(f"[MCP] Available tools: {[t.name for t in mcp_tools]}")
        
        # Convert MCP tools to OpenAI format
        agent_tools = [
            {
                "type": "function",
                "function": {
                    "name": f"mcp_{tool.name}",
                    "description": f"[MCP] {tool.description}",
                    "parameters": tool.input_schema
                }
            }
            for tool in mcp_tools
        ]
        
        messages = [{"role": "system", "content": "You have access to MCP tools for file operations."}]
        
        while True:
            user_input = input("You: ")
            if user_input.lower() == "exit":
                break
            
            messages.append({"role": "user", "content": user_input})
            
            response = client.chat.completions.create(
                model="grok-3",
                messages=messages,
                tools=agent_tools
            )
            
            response_message = response.choices[0].message
            
            if response_message.tool_calls:
                messages.append(response_message.model_dump(exclude_none=True))
                
                for tool_call in response_message.tool_calls:
                    tool_name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    
                    # Extract MCP tool name (strip mcp_ prefix)
                    mcp_tool_name = tool_name.replace("mcp_", "")
                    result = mcp_client.call_tool(mcp_tool_name, args)
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(result)
                    })
                
                # Get final response
                follow_up = client.chat.completions.create(
                    model="grok-3",
                    messages=messages
                )
                print(f"Agent: {follow_up.choices[0].message.content}\n")
            else:
                print(f"Agent: {response_message.content}\n")
    
    finally:
        mcp_client.disconnect()
```

**Expected Output:**
```
[MCP] Connected to server: npx -y @modelcontextprotocol/server-filesystem /tmp
[MCP] Available tools: ['read_file', 'write_file', 'list_directory', 'create_directory']
You: List the files in /tmp
Agent: I'll check the /tmp directory for you...
[MCP Tool: list_directory] Files found:
- project_files/
- test_output.log
- cache/
Agent: The /tmp directory contains 3 items: a project_files folder, test_output.log, and a cache folder.
```

**Verification Command:**
```bash
cd lesson_08
# Install npx if needed (typically available with Node.js)
npx -y @modelcontextprotocol/server-filesystem /tmp &
python agent.py
# Try: List files in /tmp
# Try: Read the contents of a file
```

---

## Getting Started

Each lesson builds on the previous one. Start with lesson 01 and work your way through to build a complete coding agent harness.

### Quick Start

```bash
# Clone the repository
git clone <repository-url>
cd learn-grok-build/course

# Set your API key
export GROK_API_KEY="your-api-key-here"

# Start with Lesson 01
cd lesson_01
pip install -r requirements.txt
python agent.py
```

### Lesson Progression

| Lesson | Topic | Key Concepts |
|--------|-------|--------------|
| 01 | Minimal Agent Loop | Basic loop, message history, API calls |
| 02 | Tool Call | Tool definitions, function calling, execution |
| 03 | Read/Edit/Execute | File I/O, command execution, integrated workflow |
| 04 | Permissions | Security levels, allow/deny rules, confirmation |
| 05 | Compaction | Token management, summarization, context optimization |
| 06 | Checkpoint | State serialization, save/restore, session persistence |
| 07 | Subagent | Task delegation, child agents, parallel execution |
| 08 | MCP | Model Context Protocol, external tool integration |

### Troubleshooting

- **API Key Error**: Ensure `GROK_API_KEY` is set correctly in your environment
- **Import Errors**: Install required packages with `pip install -r requirements.txt`
- **Timeout Issues**: Increase timeout values for slow operations
- **Permission Denied**: Check file path permissions and working directory