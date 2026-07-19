# Upstream Git Commit vs SOURCE_REV

This document clarifies the distinction between `upstream_git_commit` and `SOURCE_REV` in the build system.

## Definitions

| Variable | Purpose | Format |
|----------|---------|--------|
| `upstream_git_commit` | References the upstream x-cpcc repository commit | Full 40-character SHA hash |
| `SOURCE_REV` | Short form for build versioning | 7-character short hash (default: `7cfcb20`) |

## Current Values

**Active SOURCE_REV:** `7cfcb20`

This corresponds to upstream commit: (fetch from remote if needed)

```bash
git rev-parse 7cfcb20
git log -1 --format="%H %s" 7cfcb20
```

## Verification Instructions

### 1. Verify SOURCE_REV matches upstream

```bash
cd /path/to/x-cpcc
git fetch origin
git rev-parse --short=7 7cfcb20
```

### 2. Confirm full SHA

```bash
git rev-parse 7cfcb20
```

Expected output: 40-character hex string.

### 3. Check if commit is in local history

```bash
git cat-file -t 7cfcb20
```

If commit exists locally, this returns `commit`. Otherwise, fetch from remote.

### 4. Cross-reference with upstream

```bash
git fetch origin
git branch -r --contains 7cfcb20
```

This lists remote branches containing the commit.

## Updating SOURCE_REV

When updating to a new upstream commit:

1. Fetch latest upstream: `git fetch origin`
2. Identify target commit hash
3. Update `SOURCE_REV` in build configuration (typically `Makefile`, `build.sh`, or config file)
4. Run verification steps above
5. Document new value in this file