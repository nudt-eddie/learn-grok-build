"""
Minimal example: Agent loop working with a mock model.
Demonstrates the core agent loop pattern with source mapping.
"""

import json
from typing import Any


class MockModel:
    """A simple mock model that responds with predefined responses."""

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.call_count = 0

    def generate(self, prompt: str) -> str:
        """Return the next predefined response."""
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return response
        return "Done."


class AgentLoop:
    """
    Minimal agent loop with source mapping support.

    Source mapping connects generated code back to source documents
    that informed its generation (e.g., from a knowledge base or RAG).
    """

    def __init__(self, model: MockModel, max_iterations: int = 10):
        self.model = model
        self.max_iterations = max_iterations
        self.messages: list[dict[str, str]] = []
        self.source_map: dict[str, Any] = {}  # Maps code fragments to sources

    def run(self, task: str) -> dict[str, Any]:
        """Run the agent loop until completion or max iterations."""
        self.messages.append({"role": "user", "content": task})

        for i in range(self.max_iterations):
            # Build prompt from conversation history
            prompt = self._build_prompt()

            # Generate response
            response = self.model.generate(prompt)

            # Parse response (expecting JSON with action + source references)
            try:
                parsed = json.loads(response)
            except json.JSONDecodeError:
                parsed = {"action": "respond", "content": response, "sources": []}

            # Store source mapping for traced content
            if "sources" in parsed:
                self.source_map[i] = parsed["sources"]

            # Handle different actions
            action = parsed.get("action", "respond")
            content = parsed.get("content", "")

            self.messages.append({"role": "assistant", "content": content})

            if action == "done":
                return {
                    "status": "completed",
                    "iterations": i + 1,
                    "final_response": content,
                    "source_map": self.source_map
                }

        return {
            "status": "max_iterations_reached",
            "iterations": self.max_iterations,
            "source_map": self.source_map
        }

    def _build_prompt(self) -> str:
        """Build the prompt from conversation history."""
        lines = ["Conversation history:"]
        for msg in self.messages:
            lines.append(f"{msg['role']}: {msg['content']}")
        return "\n".join(lines)


def main():
    """Run the minimal agent loop example."""
    # Mock responses simulate an agent reasoning through a task
    # Each response includes source references for traceability
    mock_responses = [
        json.dumps({
            "action": "plan",
            "content": "I'll search for relevant code in the codebase.",
            "sources": [
                {"type": "file", "path": "source/core/agent.py", "relevance": 0.95},
                {"type": "function", "name": "AgentLoop.run", "line": 42}
            ]
        }),
        json.dumps({
            "action": "search",
            "content": "Found relevant code in agent.py. Let me analyze it.",
            "sources": [
                {"type": "file", "path": "source/core/agent.py", "relevance": 1.0},
                {"type": "line_range", "start": 40, "end": 60}
            ]
        }),
        json.dumps({
            "action": "done",
            "content": "Task completed successfully.",
            "sources": [
                {"type": "reference", "description": "Based on patterns from agent.py"}
            ]
        })
    ]

    # Initialize mock model and agent loop
    model = MockModel(mock_responses)
    agent = AgentLoop(model, max_iterations=10)

    # Run the agent
    task = "Analyze the agent loop implementation and explain source mapping."
    result = agent.run(task)

    # Display results
    print("=" * 60)
    print("AGENT LOOP RESULT")
    print("=" * 60)
    print(f"Status: {result['status']}")
    print(f"Iterations: {result['iterations']}")
    print(f"Final Response: {result['final_response']}")
    print("\nSOURCE MAP (traces code to source documents):")
    print("-" * 40)
    for iteration, sources in result["source_map"].items():
        print(f"Iteration {iteration}:")
        for source in sources:
            print(f"  - {source.get('type', 'unknown')}: {source.get('path', source.get('name', source.get('description', '')))}")
            if 'relevance' in source:
                print(f"    Relevance: {source['relevance']}")
            if 'line_range' in source:
                print(f"    Lines: {source['line_range']['start']}-{source['line_range']['end']}")


if __name__ == "__main__":
    main()