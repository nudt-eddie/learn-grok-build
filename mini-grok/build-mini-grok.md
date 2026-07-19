export const meta = { name: "build-mini-grok", description: "Build Python implementation" }

phase("Core Modules")
await parallel([
  () => agent("Create D:/Desktop/code/learn-grok-build/mini-grok/src/agent_loop.py. Python implementation of ChatStateActor pattern: 1) Actor class with message queue 2) conversation state management 3) command handlers 4) event emission. Add SOURCE comments referencing xai-chat-state/src/actor/mod.rs. Return {done: true}", {schema: {type:"object",properties:{done:{type:"boolean"}}}}),
  () => agent("Create D:/Desktop/code/learn-grok-build/mini-grok/src/tool_system.py. Tool system: 1) Tool base class 2) Tool registry 3) Tool dispatcher 4) Read/Edit/Execute tool implementations. Reference xai-grok-tools/src. Return {done: true}", {schema: {type:"object",properties:{done:{type:"boolean"}}}}),
  () => agent("Create D:/Desktop/code/learn-grok-build/mini-grok/src/context.py. Context assembly: 1) System prompt builder 2) Message history 3) Token budget management 4) Request builder. Reference xai-chat-state/src/actor/request_builder.rs. Return {done: true}", {schema: {type:"object",properties:{done:{type:"boolean"}}}}),
])

phase("Session & More")
await parallel([
  () => agent("Create D:/Desktop/code/learn-grok-build/mini-grok/src/session.py. Session lifecycle: 1) Session state 2) Turn management 3) Capability model 4) Permission check. Reference xai-grok-shell/src/agent. Return {done: true}", {schema: {type:"object",properties:{done:{type:"boolean"}}}}),
  () => agent("Create D:/Desktop/code/learn-grok-build/mini-grok/src/compaction.py. Context compaction: 1) Token counting 2) Message summarization 3) Threshold triggers 4) Rewind support. Reference xai-chat-state/src/compaction_*.rs. Return {done: true}", {schema: {type:"object",properties:{done:{type:"boolean"}}}}),
  () => agent("Create D:/Desktop/code/learn-grok-build/mini-grok/src/__init__.py. Package init with exports. Return {done: true}", {schema: {type:"object",properties:{done:{type:"boolean"}}}}),
])

phase("Examples")
await parallel([
  () => agent("Create D:/Desktop/code/learn-grok-build/mini-grok/examples/minimal_loop.py. Minimal example showing agent loop working with a mock model. Include comments explaining source mapping. Return {done: true}", {schema: {type:"object",properties:{done:{type:"boolean"}}}}),
  () => agent("Create D:/Desktop/code/learn-grok-build/mini-grok/examples/tool_call.py. Example showing tool execution flow. Return {done: true}", {schema: {type:"object",properties:{done:{type:"boolean"}}}}),
  () => agent("Create D:/Desktop/code/learn-grok-build/mini-grok/examples/compaction_demo.py. Example showing context compaction. Return {done: true}", {schema: {type:"object",properties:{done:{type:"boolean"}}}}),
])

return { status: "mini-grok built" }
