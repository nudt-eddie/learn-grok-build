# Evidence Levels

This document defines the three evidence tiers used throughout the codebase to establish confidence in claims, fixes, and architectural decisions.

---

## Level 1: SOURCE (Code Proof)

The highest confidence tier. Evidence is derived directly from the source code.

**Criteria:**
- References specific lines or functions in source files
- Includes file paths and optionally line numbers
- Quotes exact code snippets when needed

**Format:**
```
SOURCE: `<file_path>:<line_number>` — <description>
```

**Example:**
```
SOURCE: src/core/parser.rs:42 — validates UTF-8 before processing
SOURCE: src/utils/assertions.ts:15-20 — checks nullability contract
```

---

## Level 2: OBSERVED (Run Test)

Evidence from execution. Confidence comes from running tests or benchmarks.

**Criteria:**
- Runs the actual test suite
- Executes a script or binary to observe behavior
- Captures command output or test results

**Format:**
```
OBSERVED: `<command>` — <expected_result>
```

**Example:**
```
OBSERVED: `npm test -- --grep "parser"` — 12 tests pass
OBSERVED: `cargo run --example basic` — outputs "Hello, World!"
```

---

## Level 3: INFERENCE (Engineering Judgment)

The lowest confidence tier. Used when code proof or direct testing is not feasible.

**Criteria:**
- Relies on documented behavior, API contracts, or implicit patterns
- Cites prior art or established conventions
- Explains reasoning based on domain knowledge

**Format:**
```
INFERENCE: <rationale> — <conclusion>
```

**Example:**
```
INFERENCE: similar patterns in src/core/* validate input this way — this function likely does too
INFERENCE: the library docs state X, so we can assume behavior Y
```

---

## Linking to Upstream Commits

When evidence depends on or references a specific upstream commit, link it using the following format:

```
Upstream: <repo>@<commit_hash> — <summary>
```

**Example:**
```
Upstream: golang/go@abc1234 — fixed nil pointer in gofmt
Upstream: rust-lang/rust@d4e8f91 — stabilized async trait bounds
```

For inline references within any evidence level:
```
(<repo>@<commit_hash>)
```

**Full example combining evidence levels with commit links:**
```
SOURCE: upstream/fmt@v1.2.0:src/format.go:88 — handles edge case
  Upstream: golang/go@a1b2c3d — commit that introduced this behavior
```

---

## Evidence Level Quick Reference

| Level     | Source      | Confidence | When to Use                          |
| --------- | ----------- | ---------- | ------------------------------------ |
| SOURCE    | Code        | Highest    | Direct proof from source files       |
| OBSERVED  | Tests/Run   | Medium     | Behavior confirmed by execution      |
| INFERENCE | Reasoning   | Lowest     | No direct proof; use sparingly       |

---

## Guidelines

1. **Prefer higher tiers.** Always attempt SOURCE before OBSERVED, and OBSERVED before INFERENCE.
2. **Be explicit.** State the file, command, or reasoning clearly so others can verify.
3. **Link upstream commits.** When citing external code, include commit hashes for traceability.
4. **No emoji.** Use plain text formatting only.
5. **Update with code changes.** Evidence references become stale if code moves; update accordingly.