---
name: test
description: >
  Workflow for writing and running test code.
  Used when the user asks to write tests, increase test coverage, or add tests to existing code.
  Triggered by requests like "write tests", "add tests", "create test code",
  "test this function", "create unit tests", "increase coverage", etc.
allowed-tools:
  - search
  - read_file
  - write_file
  - edit_file
  - bash
  - list_files
---

# Test

A 5-step workflow for writing tests.

## Step 1: Analyze Target

1. Use `read_file` to read the target code
2. Identify the public interface (functions, methods, API)
3. Analyze input types, return types, and side effects
4. Identify branching conditions and error handling paths

## Step 2: Research Existing Tests

1. Use `search` and `list_files` to find existing test files
   - Patterns: `*.test.*`, `*.spec.*`, `test_*.py`, `*_test.go`, etc.
2. If existing tests are found, use `read_file` to read and analyze them:
   - Test framework in use (pytest, jest, vitest, etc.)
   - Test structure (describe/it, class-based, etc.)
   - Mock/Stub patterns
   - Fixture/Factory patterns
3. Always follow existing test patterns and style

## Step 3: Design Test Cases

1. Design happy path cases first
2. Design boundary value cases:
   - Empty input, null, undefined
   - Minimum, maximum, boundary values
   - Empty arrays, single-element arrays
3. Design error cases:
   - Invalid input
   - External dependency failures
   - Timeouts, network errors
4. Give each case a clear descriptive name

## Step 4: Write Tests

1. If an existing test file exists, use `edit_file` to add tests
2. For new test files, use `write_file` to create them
3. Test writing principles:
   - AAA pattern: Arrange -> Act -> Assert
   - Each test should verify only one behavior
   - Do not create dependencies between tests
   - Use mocks minimally
   - Express intent clearly through test names

## Skill Tests

If the target is a **skill script**: use `run_skill_script` to run tests, `read_skill` to check content. If modifications are needed, delegate to skill-creator workflow via `read_skill("skill-creator")`.

## Step 5: Run and Iterate

1. Use `bash` to run tests (use `run_skill_script` for skill targets)
2. Analyze failed tests:
   - Determine if it's a test code error or a target code bug
   - If test error, fix and re-run
   - If target code bug, **follow the bug handling procedure in the Auto-Transition section**
3. Test code fixes should be repeated **at most 3 times**. After 3 attempts, report the situation to the user and await instructions
4. Report results to the user:
   - Number of tests written
   - Coverage change (if measurable)
   - Bugs discovered (if any)

## Auto-Transition After Completion

After testing is complete, automatically proceed to the next steps without user confirmation:

1. **Auto-debug on bug discovery**: If a bug is found in the target code, load the debug workflow with `read_skill("debug")` and immediately diagnose and fix it. Re-run tests after the fix to confirm they pass
2. **When all tests pass**: If there was a prior workflow (impl, debug, etc.) before this one, return to the remaining steps of that workflow. If this was a standalone execution, report results to the user
