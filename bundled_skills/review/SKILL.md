---
name: review
description: >
  Read-only workflow for code and documentation review.
  Used when the user asks to review code or document changes, evaluate quality, or find issues.
  Triggered by requests like "review the code", "check these changes", "see if the code is okay",
  "review the documentation", "check for problems", "review the PR", "look at the diff", etc.
allowed-tools:
  - search
  - read_file
  - bash
  - list_files
---

# Review

A 6-step workflow for code review.

**This skill does not modify code. Only find and report issues.**

## Step 1: Identify Changes

1. Use `bash` to run `git diff` and identify the scope of changes
   - Staged changes: `git diff --cached`
   - All changes: `git diff HEAD`
   - Specific commit comparison: `git diff <commit1> <commit2>`
2. Check the list of changed files and the size of changes in each file
3. Use `read_file` to read the full context of changed files

## Step 2: Bug Check

1. Review for logic errors:
   - Missing or inverted conditionals
   - Off-by-one errors
   - Unhandled null/undefined
   - Type mismatches
2. Review resource management:
   - Memory leaks (uncleared event listeners, timers)
   - Unreleased files/connections
3. Review concurrency issues:
   - Race conditions
   - Potential deadlocks

## Step 3: Edge Cases

1. Review input boundary values: empty values, null, maximum values, negatives
2. Check for missing error handling
3. Check handling of external dependency failures (network, timeouts)

## Step 4: Integration Check

1. Use `search` to find all usage sites of changed functions/types
2. Verify no impact on existing callers
3. Verify API contracts (function signatures, return types) are maintained
4. Verify existing tests remain valid

## Step 5: Security

1. Check input validation
2. Review for injection vulnerabilities (SQL, XSS, command injection)
3. Check for missing authentication/authorization
4. Check for exposure of sensitive information (passwords, API keys)

## Skill Review

If the target is a **skill**: check content with `read_skill`, review reference documents with `read_skill_reference`. Skill files cannot be accessed via workspace tools (read_file, search).

## Step 6: Verdict

Report results in the following format:

```
## Review Result

### Issues by Severity
- Critical: [Bugs/security issues requiring immediate fix]
- Warning: [Potential issues, recommended fix]
- Info: [Improvement suggestions, style comments]

### Summary
- Overall assessment: [Approved / Conditionally approved / Changes requested]
- Key feedback: [1-2 most important points]
```

## Auto-Transition After Completion

After review completion, automatically handle based on issue severity:

1. **Auto-fix Critical issues**: If Critical bugs/security issues are found, load the debug workflow with `read_skill("debug")` and fix immediately
2. **Approved or Info-only**: Report final results to the user and terminate
3. **Warning-level issues**: Present the issue list and ask the user "Should I apply the recommended fixes?" (Warnings are optional, requiring user judgment)
