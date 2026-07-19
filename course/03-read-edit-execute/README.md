# Lesson 03: Read/Edit/Execute

Now that you have a working agent loop and understand tool calling, it's time to give your agent real capabilities: reading files, editing them, and executing commands. This is the foundation of any coding agent that can actually help with software development tasks.

## Objectives

By the end of this lesson, you will be able to:

- Implement file read operations to inspect source code
- Add file editing capabilities (create, modify, append)
- Build command execution for testing code
- Integrate all three into a cohesive workflow

## Prerequisites

- Completed Lessons 01 and 02
- Familiarity with file I/O in Python
- Basic understanding of subprocess execution

## Step-by-Step Implementation

### Step 1: Create the Project Structure

Create a new directory for this lesson:

```
learn-grok-build/
  lesson_03/
    agent.py
    requirements.txt
    tools.py        # Tool definitions and execution logic
    test_file.py    # A sample file for testing
```

### Step 2: Define the Tool Schemas

First, let's define three core tools: `read_file`, `write_file`, and `execute_command`.

```python
# lesson_03/tools.py
from pathlib import Path

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file from the filesystem. Use this when you need to inspect existing code or read file contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the file to read"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a new file or overwrite an existing file with the given content. Use this for creating new source files or updating existing ones.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path where the file should be created"
                    },
                    "content": {
                        "type": "string",
                        "description": "The complete content to write to the file"
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_command",
            "description": "Execute a shell command and return its output. Use this to run tests, build code, or perform other shell operations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute"
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Working directory for the command (optional, defaults to current directory)"
                    }
                },
                "required": ["command"]
            }
        }
    }
]
```

### Step 3: Implement Tool Execution

Now create the execution logic for each tool:

```python
# lesson_03/tools.py (continued)
import os
import subprocess

def execute_tool(name: str, arguments: dict) -> str:
    """
    Execute a tool by name with the provided arguments.
    Returns the result as a string.
    """
    
    if name == "read_file":
        return _read_file(arguments["path"])
    
    elif name == "write_file":
        return _write_file(arguments["path"], arguments["content"])
    
    elif name == "execute_command":
        return _execute_command(
            arguments["command"],
            arguments.get("cwd", os.getcwd())
        )
    
    return f"Unknown tool: {name}"


def _read_file(path: str) -> str:
    """Read a file and return its contents."""
    file_path = Path(path)
    
    if not file_path.exists():
        return f"Error: File not found: {path}"
    
    if not file_path.is_file():
        return f"Error: Path is not a file: {path}"
    
    try:
        content = file_path.read_text(encoding="utf-8")
        # Truncate very long files to avoid token limits
        if len(content) > 5000:
            content = content[:5000] + "\n... [truncated]"
        return f"File: {path}\n```\n{content}\n```"
    except Exception as e:
        return f"Error reading file: {e}"


def _write_file(path: str, content: str) -> str:
    """Write content to a file, creating it if necessary."""
    file_path = Path(path)
    
    try:
        # Create parent directories if they don't exist
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def _execute_command(command: str, cwd: str) -> str:
    """Execute a shell command and return its output."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60  # 60 second timeout
        )
        
        output_lines = [
            f"Exit code: {result.returncode}",
        ]
        
        if result.stdout:
            # Truncate output to avoid token limits
            stdout = result.stdout[:3000]
            if len(result.stdout) > 3000:
                stdout += "\n... [stdout truncated]"
            output_lines.append(f"STDOUT:\n{stdout}")
        
        if result.stderr:
            # Truncate stderr too
            stderr = result.stderr[:1000]
            if len(result.stderr) > 1000:
                stderr += "\n... [stderr truncated]"
            output_lines.append(f"STDERR:\n{stderr}")
        
        return "\n".join(output_lines)
        
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 60 seconds"
    except Exception as e:
        return f"Error executing command: {e}"
```

### Step 4: Build the Complete Agent

Now create the main agent file that ties everything together:

```python
# lesson_03/agent.py
import os
import json
from openai import OpenAI
from tools import TOOLS, execute_tool

# Initialize the Grok client
client = OpenAI(
    api_key=os.environ.get("GROK_API_KEY"),
    base_url="https://api.x.ai/v1"
)

SYSTEM_PROMPT = """You are a coding assistant with the ability to read files, write files, and execute shell commands.

Available tools:
- read_file: Read the contents of a file
- write_file: Create or overwrite a file
- execute_command: Run a shell command

When given a coding task:
1. First read existing files to understand the codebase
2. Write or modify files as needed
3. Execute commands to test or build the code
4. Report results back to the user

Always provide clear feedback about what you're doing and the results of operations."""


def run_agent():
    """Main agent loop with file and command tools."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
    
    print("Agent started. Type 'exit' to quit.\n")
    
    while True:
        user_input = input("You: ")
        if user_input.lower() == "exit":
            print("Goodbye!")
            break
        
        messages.append({"role": "user", "content": user_input})
        
        # Call the model with tools
        response = client.chat.completions.create(
            model="grok-3",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto"
        )
        
        response_message = response.choices[0].message
        
        # Handle tool calls
        if response_message.tool_calls:
            # Add the assistant's message with tool calls
            messages.append(response_message.model_dump(exclude_none=True))
            
            # Execute each tool call
            for tool_call in response_message.tool_calls:
                tool_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                
                print(f"[Calling tool: {tool_name}]")
                
                # Execute the tool
                result = execute_tool(tool_name, args)
                
                # Add the tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })
            
            # Get the final response after tool execution
            follow_up = client.chat.completions.create(
                model="grok-3",
                messages=messages
            )
            
            assistant_reply = follow_up.choices[0].message.content
            print(f"Agent: {assistant_reply}\n")
            messages.append({"role": "assistant", "content": assistant_reply})
        
        else:
            # No tool calls, just a regular response
            print(f"Agent: {response_message.content}\n")
            messages.append({"role": "assistant", "content": response_message.content})


if __name__ == "__main__":
    run_agent()
```

### Step 5: Create a Test File

Create a sample Python file to test with:

```python
# lesson_03/test_math.py
def add(a, b):
    """Add two numbers."""
    return a + b

def subtract(a, b):
    """Subtract b from a."""
    return a - b

def multiply(a, b):
    """Multiply two numbers."""
    return a * b

def divide(a, b):
    """Divide a by b. Returns None if b is zero."""
    if b == 0:
        return None
    return a / b

if __name__ == "__main__":
    print("Testing math functions:")
    print(f"add(5, 3) = {add(5, 3)}")
    print(f"subtract(10, 4) = {subtract(10, 4)}")
    print(f"multiply(6, 7) = {multiply(6, 7)}")
    print(f"divide(20, 4) = {divide(20, 4)}")
```

### Step 6: Add Requirements

```text
# lesson_03/requirements.txt
openai>=1.12.0
```

## Complete Code

Here is the complete, runnable implementation:

```python
# lesson_03/agent.py
import os
import json
import subprocess
from pathlib import Path
from openai import OpenAI

# Initialize the Grok client
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
            return f"File content:\n{content[:2000]}"
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

def run_agent():
    messages = [
        {"role": "system", "content": "You are a coding assistant with file read/write and command execution capabilities."}
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
            
            follow_up = client.chat.completions.create(
                model="grok-3",
                messages=messages
            )
            print(f"Agent: {follow_up.choices[0].message.content}\n")
        else:
            print(f"Agent: {response_message.content}\n")
            messages.append({"role": "assistant", "content": response_message.content})

if __name__ == "__main__":
    run_agent()
```

## Expected Output

Here's an example interaction:

```
You: Create a file called hello.py that prints Hello World
Agent: I'll create that file for you.
[Calling tool: write_file]
Successfully wrote to hello.py

You: Run it
Agent: Executing hello.py...
[Calling tool: execute_command]
Exit code: 0
STDOUT:
Hello World

You: Read the hello.py file I just created
Agent: I'll read that file for you.
[Calling tool: read_file]
File content:
print("Hello World")
```

## Verification Command

```bash
cd lesson_03
pip install -r requirements.txt

# Create a test file first
echo 'def add(a, b): return a + b' > test_math.py

# Run the agent
python agent.py

# Try these interactions:
# 1. "Read test_math.py"
# 2. "Create a new file called multiply.py with functions for multiply and divide"
# 3. "Run pytest to test the multiply.py file"
# 4. "Exit"
```

## Key Concepts

### File Operations
- Always use absolute paths to avoid ambiguity
- Create parent directories with `mkdir(parents=True, exist_ok=True)`
- Handle errors gracefully (file not found, permission denied)

### Command Execution
- Use `subprocess.run()` for safe command execution
- Always set a timeout to prevent hanging
- Capture both stdout and stderr
- Truncate output to avoid token limits

### Tool Chaining
- The agent can call multiple tools in sequence
- Each tool result is fed back to the model
- The model decides whether to continue with more tools or respond to the user

## What's Next

In the next lesson, you'll add a permission system to control what the agent can do. This is critical for security when your agent has file system and command execution capabilities.

## Troubleshooting

- **File not found**: Ensure you're using absolute paths, not relative paths
- **Permission denied**: Check file/directory permissions on your system
- **Command timeout**: The default timeout is 60 seconds; adjust if needed for longer operations
- **API errors**: Verify your `GROK_API_KEY` environment variable is set correctly