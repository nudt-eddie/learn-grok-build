# Context Compaction

Context compaction is a critical technique for maintaining efficient communication between an AI coding agent and a language model. As conversations grow longer, the context window fills up with historical messages, tool calls, and responses. Without compaction, the agent would eventually run out of context space or incur excessive token costs. Grok Build addresses this through a sophisticated compaction system built on the `xai-grok-compaction` crate.

## The Compaction Core

The `xai-grok-compaction` crate serves as a **transport-agnostic compaction core**. This design philosophy means the compaction logic is decoupled from any specific communication protocol or transport layer, making it reusable and maintainable. The core handles the essential question: how do we summarize or compress a long conversation history into a more compact form while preserving critical information?

The transport-agnostic nature is important because Grok Build supports multiple interaction modes: the interactive TUI, headless operation, and embedding via the Agent Client Protocol (ACP). Each mode handles context management differently, but all rely on the same underlying compaction engine.

## Whole-Session Full-Replace Strategy

Grok Build employs a **whole-session full-replace** compaction strategy. Rather than incrementally compressing individual messages or using lossy differential updates, the system builds a fresh prompt from scratch, incorporates summarized content, and replaces the entire conversation history with this new compact representation.

### The Four-Phase Compaction Process

The full-replace strategy unfolds across four distinct phases:

**Phase 1: Build Prompt**

The first phase constructs a comprehensive prompt that includes all the necessary context for the agent to continue working effectively. This includes the system prompt, the current codebase state, any relevant file contents, and summarized versions of past conversation history. The prompt builder must make intelligent decisions about what to include, balancing completeness against context length.

**Phase 2: Sample and Retry**

After building the initial prompt, the system samples the conversation and attempts to generate a compaction. If the result does not meet quality criteria or validation rules, the process retries with adjusted parameters. This iterative approach ensures that the compaction captures essential information accurately.

**Phase 3: Clean and Validate**

The generated compaction undergoes thorough validation. This includes checking that critical information is preserved, that the summary is coherent and accurate, and that no important decisions or tool results have been lost. Validation may involve comparing the compaction against the original conversation to detect omissions or hallucinations.

**Phase 4: Assemble Fresh History**

Once validated, the system assembles a new conversation history containing the compaction result. This fresh history replaces the original long conversation, effectively "rewinding" the context to a manageable size while maintaining continuity. The agent can now continue working with this compact representation.

![Compaction Full Replace Flow](figures/07_compaction_full_replace.png)

## Host Responsibilities

An important architectural principle of Grok Build's compaction system is that **triggering, persistence, replay/rollback, state commitment, and metrics are all handled by the host**. The `xai-grok-compaction` crate provides the core compaction logic, but the surrounding infrastructure depends on the embedding application.

### Triggering Compaction

The host decides when to initiate compaction. Common triggers include:

- Reaching a threshold number of messages in the conversation
- Approaching the maximum context length
- Explicit user requests
- Idle periods that suggest natural conversation breaks

### Persistence and Replay

When compaction occurs, the host must persist the original conversation history (at least temporarily) and implement replay functionality. This allows the system to reconstruct the full conversation if needed, such as when reviewing past work or recovering from errors.

### State Commitment

After successful compaction, the host commits the new compacted state. This involves updating internal conversation tracking, adjusting token counts, and ensuring that all dependent systems reflect the new conversation state.

### Metrics Collection

The host collects metrics about compaction operations, including:

- Compression ratios achieved
- Time spent in each compaction phase
- Validation success rates
- Token savings from compaction
- Quality scores for generated compactions

## Checkpoint and Rewind

Grok Build incorporates a **checkpoint and rewind mechanism** that works in concert with compaction. Before performing significant operations (including compaction), the system can capture the current state. If something goes wrong, the agent can rewind to a known good state.

![Checkpoint Rewind Mechanism](figures/06_checkpoint_rewind.png)

This is particularly valuable during compaction because the process involves generating summaries and potentially losing information. If a compaction results in quality degradation or lost context, the system can revert to the checkpoint and try a different approach.

## Architectural Considerations

### Separation of Concerns

By separating the compaction core from host responsibilities, Grok Build achieves several benefits:

1. **Testability**: The compaction logic can be tested in isolation without requiring a full host environment.
2. **Flexibility**: Different hosts can implement different triggering strategies based on their use cases.
3. **Maintainability**: Changes to compaction algorithms do not require changes to every host implementation.
4. **Reusability**: The same compaction core can be used across all Grok Build variants.

### Transport Agnosticism

The transport-agnostic design means that whether the agent is communicating over stdio (headless mode), through the TUI, or via ACP, the underlying compaction mechanism remains the same. The transport layer handles message formatting and delivery, while compaction operates on the conversation abstraction layer.

## Practical Implications

Understanding compaction is essential for effectively using and extending Grok Build:

- **For users**: Be aware that very long conversations may be compacted. Review compaction summaries to ensure critical context is preserved.
- **For integrators**: Implement appropriate triggering strategies and ensure robust persistence for replay capabilities.
- **For contributors**: When modifying compaction behavior, maintain the transport-agnostic interface and ensure validation catches quality degradation.

## Summary

Context compaction in Grok Build represents a well-designed solution to one of the fundamental challenges of long-running AI conversations. The whole-session full-replace strategy, combined with a clean separation between the compaction core and host responsibilities, provides both flexibility and reliability. The four-phase process of building, sampling, validating, and assembling ensures that compacted conversations maintain essential information while dramatically reducing context requirements.

The transport-agnostic architecture of `xai-grok-compaction` enables this compaction system to serve all Grok Build interaction modes consistently, while host-level responsibilities for triggering, persistence, and metrics allow deployment-specific optimization.