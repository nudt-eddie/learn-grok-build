# Lesson 02: Tool Call

## Overview

Tool calling allows AI assistants to interact with external systems, execute code, read/write files, search the web, and perform various actions beyond text generation.

## Key Concepts

### Available Tools

| Tool | Purpose |
|------|---------|
| Read | Read files from the filesystem |
| Write | Create or overwrite files |
| Edit | Modify specific parts of a file |
| Bash | Execute shell commands |
| Grep | Search file contents using regex |
| Glob | Find files matching a pattern |
| WebFetch | Fetch and analyze web pages |
| WebSearch | Search the web for information |

### Tool Call Pattern

1. **Identify the need** - Determine when external action is required
2. **Select the tool** - Choose the appropriate tool for the task
3. **Provide parameters** - Pass required and optional arguments
4. **Execute and validate** - Verify the tool completed successfully
5. **Use results** - Incorporate tool output into the response

## Implementation Examples

### Reading Files

```javascript
// Read a single file
Read({ file_path: "/path/to/file.txt" })

// Read with line limits
Read({ 
  file_path: "/path/to/file.txt",
  limit: 100,
  offset: 0
})
```

### Writing Files

```javascript
// Create or overwrite a file
Write({
  content: "File contents here",
  file_path: "/path/to/output.txt"
})
```

### Editing Files

```javascript
// Replace specific text in a file
Edit({
  file_path: "/path/to/file.txt",
  old_string: "old text to replace",
  new_string: "new text"
})
```

### Running Commands

```javascript
// Execute shell commands
Bash({
  command: "ls -la",
  description: "List directory contents"
})
```

### Searching

```javascript
// Search file contents
Grep({
  output_mode: "content",
  path: "/path/to/search",
  pattern: "search term"
})

// Find files by pattern
Glob({
  path: "/path",
  pattern: "**/*.js"
})
```

## Best Practices

1. **Use absolute paths** - Always use absolute paths for file operations
2. **Validate before edit** - Read files before attempting edits
3. **Error handling** - Handle missing files and permission errors
4. **Batch operations** - Combine multiple reads when possible
5. **Timeout management** - Set appropriate timeouts for long operations

## Common Pitfalls

- Forgetting to read a file before editing it
- Using relative paths instead of absolute paths
- Not handling file-not-found errors
- Overwriting files without confirmation
- Missing parameters in tool calls

## Exercise

Create a simple project structure:
1. Use `Write` to create a config.json file
2. Use `Read` to verify the file was created
3. Use `Edit` to modify specific values
4. Use `Bash` to list the created files

## Next Steps

- Lesson 03: Multi-step workflows
- Lesson 04: Error handling and recovery