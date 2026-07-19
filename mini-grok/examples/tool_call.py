"""
Example showing tool execution flow.

This example demonstrates how tools are defined and executed in the Grok framework.
"""

# Tool definition example
def multiply_tool(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b


def search_tool(query: str) -> dict:
    """Search for information."""
    # Placeholder for actual search implementation
    return {"query": query, "results": ["result1", "result2"]}


# Tool execution flow
if __name__ == "__main__":
    # Example 1: Direct tool call
    result = multiply_tool(5, 3)
    print(f"multiply_tool(5, 3) = {result}")  # Output: 15

    # Example 2: Search tool usage
    search_result = search_tool("Python tutorial")
    print(f"search_tool result: {search_result}")

    # Example 3: Tool with structured output pattern
    def execute_tool(tool_name: str, params: dict):
        """Execute a tool by name with given parameters."""
        tools = {
            "multiply": multiply_tool,
            "search": search_tool,
        }
        tool = tools.get(tool_name)
        if tool:
            return tool(**params)
        return {"error": f"Tool '{tool_name}' not found"}

    # Execute multiply tool via string name
    result = execute_tool("multiply", {"a": 7, "b": 8})
    print(f"execute_tool('multiply', {{'a': 7, 'b': 8}}) = {result}")  # Output: 56

    print("\nTool execution flow demonstration complete!")