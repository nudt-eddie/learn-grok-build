"""
Tool System Module
Provides base class, registry, dispatcher, and standard tool implementations.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, Type
import inspect
import os


class Tool(ABC):
    """Base class for all tools."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def execute(self, **kwargs) -> Dict[str, Any]:
        """Execute the tool with given arguments."""
        pass

    def validate(self, **kwargs) -> bool:
        """Validate tool arguments before execution."""
        return True

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """Return JSON schema for the tool's parameters."""
        return {
            "name": cls.name,
            "description": cls.description,
            "parameters": {}
        }


class ToolRegistry:
    """Registry for managing available tools."""

    _tools: Dict[str, Type[Tool]] = {}
    _instances: Dict[str, Tool] = {}

    @classmethod
    def register(cls, tool_class: Type[Tool]) -> None:
        """Register a tool class."""
        instance = tool_class()
        cls._tools[instance.name] = tool_class
        cls._instances[instance.name] = instance

    @classmethod
    def get(cls, name: str) -> Optional[Tool]:
        """Get a tool instance by name."""
        return cls._instances.get(name)

    @classmethod
    def list_tools(cls) -> Dict[str, Dict[str, Any]]:
        """List all registered tools with their schemas."""
        return {
            name: instance.get_schema()
            for name, instance in cls._instances.items()
        }

    @classmethod
    def unregister(cls, name: str) -> bool:
        """Unregister a tool by name."""
        if name in cls._tools:
            del cls._tools[name]
            del cls._instances[name]
            return True
        return False


class ToolDispatcher:
    """Dispatches tool execution requests."""

    def __init__(self):
        self.registry = ToolRegistry

    def dispatch(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Dispatch execution to the appropriate tool."""
        if arguments is None:
            arguments = {}

        tool = self.registry.get(tool_name)
        if tool is None:
            return {
                "success": False,
                "error": f"Tool '{tool_name}' not found"
            }

        try:
            if not tool.validate(**arguments):
                return {
                    "success": False,
                    "error": f"Validation failed for tool '{tool_name}'"
                }
            result = tool.execute(**arguments)
            return {"success": True, "result": result}
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "tool": tool_name
            }


# --- Tool Implementations ---


class ReadTool(Tool):
    """Tool for reading files."""

    name = "read"
    description = "Read contents from a file"

    def execute(self, file_path: str, limit: Optional[int] = None, offset: int = 0, **kwargs) -> Dict[str, Any]:
        """Read file contents."""
        try:
            if not os.path.exists(file_path):
                return {"error": f"File not found: {file_path}", "exists": False}

            with open(file_path, "r", encoding="utf-8") as f:
                if offset > 0:
                    for _ in range(offset):
                        f.readline()
                content = f.read()
                if limit:
                    lines = content.splitlines()
                    content = "\n".join(lines[:limit])

            return {
                "success": True,
                "content": content,
                "file_path": file_path
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        return {
            "name": cls.name,
            "description": cls.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to read"},
                    "limit": {"type": "integer", "description": "Maximum number of lines to read"},
                    "offset": {"type": "integer", "description": "Number of lines to skip"}
                },
                "required": ["file_path"]
            }
        }


class EditTool(Tool):
    """Tool for editing files."""

    name = "edit"
    description = "Edit content in a file using string replacement"

    def execute(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Edit file content by replacing string."""
        try:
            if not os.path.exists(file_path):
                return {"success": False, "error": f"File not found: {file_path}"}

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            if old_string not in content:
                return {"success": False, "error": "String not found in file"}

            if replace_all:
                new_content = content.replace(old_string, new_string)
            else:
                new_content = content.replace(old_string, new_string, 1)

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            return {
                "success": True,
                "file_path": file_path,
                "replaced": True
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def validate(self, file_path: str, old_string: str, new_string: str, **kwargs) -> bool:
        return bool(file_path and old_string is not None and new_string is not None)

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        return {
            "name": cls.name,
            "description": cls.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to edit"},
                    "old_string": {"type": "string", "description": "Text to find and replace"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                    "replace_all": {"type": "boolean", "description": "Replace all occurrences"}
                },
                "required": ["file_path", "old_string", "new_string"]
            }
        }


class ExecuteTool(Tool):
    """Tool for executing shell commands."""

    name = "execute"
    description = "Execute a shell command"

    def execute(self, command: str, cwd: Optional[str] = None, timeout: int = 120000, **kwargs) -> Dict[str, Any]:
        """Execute a shell command."""
        import subprocess
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout / 1000  # Convert to seconds
            )
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Command timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        return {
            "name": cls.name,
            "description": cls.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "cwd": {"type": "string", "description": "Working directory"},
                    "timeout": {"type": "integer", "description": "Timeout in milliseconds"}
                },
                "required": ["command"]
            }
        }


class WriteTool(Tool):
    """Tool for writing files."""

    name = "write"
    description = "Write content to a file (creates or overwrites)"

    def execute(self, file_path: str, content: str, **kwargs) -> Dict[str, Any]:
        """Write content to a file."""
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"success": True, "file_path": file_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        return {
            "name": cls.name,
            "description": cls.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to write"},
                    "content": {"type": "string", "description": "Content to write"}
                },
                "required": ["file_path", "content"]
            }
        }


class GlobTool(Tool):
    """Tool for pattern matching files."""

    name = "glob"
    description = "Find files matching a glob pattern"

    def execute(self, pattern: str, path: str = ".", **kwargs) -> Dict[str, Any]:
        """Find files matching pattern."""
        import glob as glob_module
        try:
            matches = glob_module.glob(os.path.join(path, pattern), recursive=True)
            return {"success": True, "matches": matches, "count": len(matches)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        return {
            "name": cls.name,
            "description": cls.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g., **/*.py)"},
                    "path": {"type": "string", "description": "Root directory to search"}
                },
                "required": ["pattern"]
            }
        }


# Register default tools
def register_default_tools():
    """Register all built-in tools."""
    ToolRegistry.register(ReadTool)
    ToolRegistry.register(EditTool)
    ToolRegistry.register(ExecuteTool)
    ToolRegistry.register(WriteTool)
    ToolRegistry.register(GlobTool)


# Auto-register on module load
register_default_tools()