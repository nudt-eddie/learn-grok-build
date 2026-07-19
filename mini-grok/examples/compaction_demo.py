"""
Context Compaction Demo

Demonstrates how the compaction module handles context window management
through token counting, threshold triggers, and multiple compaction strategies.
"""

import sys
sys.path.insert(0, "D:/Desktop/code/learn-grok-build/mini-grok/src")

from compaction import (
    Message,
    CompactionConfig,
    CompactionStrategy,
    ContextCompactor,
    TokenCounter,
    CompactionTrigger,
)


def create_sample_messages(count: int = 20) -> list[Message]:
    """Create sample messages for testing."""
    messages = []
    topics = [
        "Project planning discussion",
        "Architecture decisions",
        "Implementation details",
        "Code review feedback",
        "Testing strategy",
    ]

    for i in range(count):
        topic = topics[i % len(topics)]
        messages.append(Message(
            role="user" if i % 2 == 0 else "assistant",
            content=f"{topic} - Message {i+1}: This is a detailed message about {topic} with specific content to increase token count for demonstration purposes. " * 3
        ))
    return messages


def demo_token_counting():
    """Demo 1: Token counting functionality."""
    print("=" * 60)
    print("DEMO 1: Token Counting")
    print("=" * 60)

    counter = TokenCounter(model="gpt-4")

    # Count tokens in sample text
    sample_text = "This is a sample conversation message for token counting demonstration."
    token_count = counter.count(sample_text)
    print(f"Text: '{sample_text}'")
    print(f"Token count: {token_count}")

    # Count tokens in messages
    messages = create_sample_messages(5)
    total_tokens = counter.count_messages(messages)
    print(f"\n{len(messages)} messages contain {total_tokens} tokens")

    print()


def demo_threshold_triggers():
    """Demo 2: Threshold-based compaction triggers."""
    print("=" * 60)
    print("DEMO 2: Threshold Triggers")
    print("=" * 60)

    # Use a smaller max_tokens for demonstration
    config = CompactionConfig(max_tokens=5000, warning_threshold=0.7, compaction_threshold=0.85)
    trigger = CompactionTrigger(config)

    # Test with different message counts
    for count in [5, 15, 25]:
        messages = create_sample_messages(count)
        should_compact, ratio, status = trigger.check_threshold(messages)
        remaining = trigger.get_remaining_capacity(messages)

        print(f"\n{count} messages:")
        print(f"  - Token ratio: {ratio:.1%}")
        print(f"  - Status: {status}")
        print(f"  - Remaining capacity: {remaining} tokens")
        print(f"  - Should compact: {should_compact}")

    print()


def demo_analyze():
    """Demo 3: Full context analysis."""
    print("=" * 60)
    print("DEMO 3: Context Analysis")
    print("=" * 60)

    config = CompactionConfig(max_tokens=10000)
    compactor = ContextCompactor(config)

    messages = create_sample_messages(12)
    analysis = compactor.analyze(messages)

    print("Context Analysis:")
    for key, value in analysis.items():
        if isinstance(value, float) and "ratio" in key:
            print(f"  - {key}: {value:.1%}")
        else:
            print(f"  - {key}: {value}")

    print()


def demo_summarize_strategy():
    """Demo 4: Summarize compaction strategy."""
    print("=" * 60)
    print("DEMO 4: Summarize Strategy")
    print("=" * 60)

    config = CompactionConfig(
        max_tokens=5000,
        preserve_recent_messages=2,
        strategy=CompactionStrategy.SUMMARIZE
    )
    compactor = ContextCompactor(config)

    messages = create_sample_messages(10)
    print(f"Before compaction: {len(messages)} messages")
    print(f"Analysis before: {compactor.analyze(messages)['status']}")

    # Custom summarizer that creates a simple summary
    def mock_summarize(conversation: str) -> str:
        line_count = conversation.count("\n") + 1
        return f"[AI Summary]: This conversation contains {line_count} lines covering project planning, architecture, implementation, code review, and testing topics."

    result = compactor.compact(messages, api_call_fn=mock_summarize)

    print(f"\nAfter compaction ({result.strategy_used.value}):")
    print(f"  - Original messages: {result.original_count}")
    print(f"  - New messages: {result.new_count}")
    print(f"  - Tokens saved: {result.original_tokens - result.new_tokens}")
    print(f"  - Summary generated: {result.summary[:80]}...")

    print()


def demo_rewind_strategy():
    """Demo 5: Rewind compaction strategy."""
    print("=" * 60)
    print("DEMO 5: Rewind Strategy")
    print("=" * 60)

    config = CompactionConfig(
        max_rewind_messages=5,
        strategy=CompactionStrategy.REWIND
    )
    compactor = ContextCompactor(config)

    messages = create_sample_messages(15)
    print(f"Before rewind: {len(messages)} messages")

    result = compactor.compact(messages)

    print(f"\nAfter rewind ({result.strategy_used.value}):")
    print(f"  - Rewound to index: {result.rewound_to_index}")
    print(f"  - Messages remaining: {result.new_count}")
    print(f"  - Original tokens: {result.original_tokens}")
    print(f"  - New tokens: {result.new_tokens}")

    print()


def demo_truncate_strategy():
    """Demo 6: Truncate compaction strategy."""
    print("=" * 60)
    print("DEMO 6: Truncate Strategy")
    print("=" * 60)

    config = CompactionConfig(
        summary_target_tokens=2000,
        strategy=CompactionStrategy.TRUNCATE
    )
    compactor = ContextCompactor(config)

    messages = create_sample_messages(20)
    print(f"Before truncation: {len(messages)} messages")
    print(f"Analysis: {compactor.analyze(messages)['status']}")

    result = compactor.compact(messages)

    print(f"\nAfter truncation ({result.strategy_used.value}):")
    print(f"  - Original messages: {result.original_count}")
    print(f"  - New messages: {result.new_count}")
    print(f"  - Tokens reduced: {result.original_tokens} -> {result.new_tokens}")

    print()


def demo_automatic_compaction_workflow():
    """Demo 7: Automatic compaction workflow."""
    print("=" * 60)
    print("DEMO 7: Automatic Compaction Workflow")
    print("=" * 60)

    config = CompactionConfig(
        max_tokens=3000,
        compaction_threshold=0.8,
        warning_threshold=0.6
    )
    compactor = ContextCompactor(config)

    def mock_summarize(text: str) -> str:
        return f"[Auto-summary of {text.count(chr(10))} lines of conversation]"

    # Simulate adding messages one at a time
    all_messages = create_sample_messages(15)
    print("Simulating message additions with automatic compaction:\n")

    current_messages = []
    for i, msg in enumerate(all_messages):
        current_messages.append(msg)

        # Check threshold
        should_compact, ratio, status = compactor.trigger.check_threshold(current_messages)
        print(f"Message {i+1}: ratio={ratio:.1%}, status={status}")

        # Auto-compact if needed
        if should_compact:
            print(f"  -> Triggering automatic compaction...")
            result = compactor.compact(current_messages, api_call_fn=mock_summarize)
            current_messages = compactor.summarizer.summarize_conversation(
                current_messages, mock_summarize
            )[1]
            print(f"  -> Compaction complete: {result.original_count} -> {result.new_count} messages")
        print()

    print(f"Final state: {len(current_messages)} messages")


def demo_config_customization():
    """Demo 8: Configuration options."""
    print("=" * 60)
    print("DEMO 8: Configuration Customization")
    print("=" * 60)

    # Different config presets
    configs = [
        ("Low memory", CompactionConfig(max_tokens=32000, compaction_threshold=0.7)),
        ("Standard", CompactionConfig(max_tokens=128000, compaction_threshold=0.9)),
        ("Aggressive", CompactionConfig(max_tokens=128000, compaction_threshold=0.6, preserve_recent_messages=5)),
    ]

    for name, config in configs:
        print(f"\n{name} config:")
        print(f"  - Max tokens: {config.max_tokens:,}")
        print(f"  - Warning threshold: {config.warning_threshold:.0%}")
        print(f"  - Compaction threshold: {config.compaction_threshold:.0%}")
        print(f"  - Preserve recent: {config.preserve_recent_messages} messages")

    print()


def main():
    """Run all demos."""
    print("\n" + "=" * 60)
    print("CONTEXT COMPACTION DEMO")
    print("=" * 60)
    print()

    demo_token_counting()
    demo_threshold_triggers()
    demo_analyze()
    demo_summarize_strategy()
    demo_rewind_strategy()
    demo_truncate_strategy()
    demo_automatic_compaction_workflow()
    demo_config_customization()

    print("=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()