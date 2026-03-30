---
name: debug
description: >
  Systematic debugging workflow for diagnosing and fixing bugs.
  Used when the user reports a bug, asks to fix an error, or wants to investigate unexpected behavior.
  Triggered by requests like "why doesn't this work?", "fix this error", "find the bug",
  "why does it behave like this?", "I'm getting an error", "debug this", etc.
allowed-tools:
  - search
  - read_file
  - bash
  - edit_file
  - list_files
---

# Debug

A 6-step workflow for diagnosing and fixing bugs.

**Core rule: Do not modify any code until Step 4 (root cause confirmed).**

## Step 1: Reproduce

1. Accurately identify the symptoms reported by the user
2. Confirm error messages, stack traces, and reproduction steps
3. If possible, reproduce directly using `bash`
4. If reproduction fails, request additional information from the user

## Step 2: Gather Evidence

1. Use `search` to look for error messages, related function names, and variable names
2. Use `read_file` to read related files
3. Use `bash` to collect logs, status, and environment information
4. Compile the list of related files

## Step 3: Trace Data Flow

1. Trace the path data flows from input to output
2. Compare expected vs. actual values at each step
3. Check branching points (conditionals, error handlers)
4. Check the state of external dependencies (API, DB, filesystem)

## Step 4: Confirm Root Cause

1. Formulate hypotheses based on collected evidence
2. Run tests to verify hypotheses
3. Clearly state the root cause in one sentence
4. **Do not proceed to the fix step unless the root cause is confirmed**

## Step 5: Minimal Fix

1. Apply the minimum change that addresses only the root cause
2. Use `edit_file` to make corrections
3. Do not touch unrelated code — no refactoring or style changes
4. Explain the fix to the user

## Step 6: Verify

1. Use `bash` to run reproduction tests after the fix
2. Confirm the original symptoms are resolved
3. Verify no side effects on existing functionality
4. Report results to the user

## Skill Debugging

If the target is a **skill script**: check content with `read_skill`, then load the skill-creator workflow with `read_skill("skill-creator")` for modifications. Skill files cannot be accessed via workspace tools (read_file, edit_file).

## Notes

- Do not modify code based on guesses. Always make evidence-based decisions
- Verify only one hypothesis at a time
- If a fix fails, revert and examine a different hypothesis
- **If 3 hypotheses are tested without finding the cause**, report the analysis so far to the user and request additional information
- For vague requests (e.g., "fix it" alone), first confirm "What should be fixed?"

## Auto-Transition After Completion

After the bug fix is complete, automatically proceed to the next steps without user confirmation:

1. **Auto-write regression test**: If no related tests exist for the fixed code, load the test workflow with `read_skill("test")` and immediately write a regression test to prevent recurrence
2. **Auto-review**: After testing is complete, load the review workflow with `read_skill("review")` and self-review the changes
3. **Final report**: After the review is complete, report the full results (cause, fix, tests, review) to the user

If structural issues are discovered during the fix, ask the user: "Should I create a refactoring plan?" (large-scale changes require user judgment)

**Chain depth limit**: If auto-transitions exceed 3, report intermediate results to the user and confirm whether to proceed with the next step.
