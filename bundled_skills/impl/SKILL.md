---
name: impl
description: >
  Systematic workflow for implementing new features and writing/editing documentation.
  Used when the user asks to add new features, extend existing features, or write code and documents.
  Covers not only code writing but also creating/modifying/editing READMEs, guides, config files, and markdown documents.
  Triggered by requests like "build this feature", "add this", "implement this",
  "write documentation", "update the README", "create a guide",
  "write code that does X", "create an API endpoint", etc.
  For complex tasks requiring changes to 3 or more files, use the coding-pipeline skill instead.
allowed-tools:
  - search
  - read_file
  - write_file
  - edit_file
  - bash
  - list_files
  - list_files
---

# Impl

A 6-step workflow for feature implementation.

**Core rule: Always follow existing code style and patterns.**

## Step 1: Understand Requirements

1. Break down the user's request into specific requirements
2. Ask the user about unclear points before implementation
3. Define inputs, outputs, and edge cases

## Step 2: Research Existing Patterns

1. Use `search` and `list_files` to find similar existing implementations
2. Use `read_file` to analyze patterns in existing code:
   - Naming conventions (camelCase, snake_case, etc.)
   - File/directory structure
   - Import style
   - Error handling approach
   - Type definition approach
3. Use `list_files` to understand directory structure
4. Do not deviate from existing patterns

## Step 3: Plan Changes

1. List files to modify/create
2. Summarize changes for each file
3. Determine change order (dependency order)
4. Report the plan to the user and get confirmation

## Step 4: Implement

1. Write/modify code in the planned order
2. Use `edit_file` to modify existing files
3. Use `write_file` to create new files
4. Verify no syntax errors after each file modification
5. Follow existing code style exactly

## Step 5: Test

1. Use `bash` to check for build/compile errors
2. Run existing tests if available
3. Manually verify newly added functionality

## Step 6: Verify and Report

1. Review the overall changes
2. Ensure no unnecessary or debug code remains
3. Summarize changes and report to the user

## Auto-Transition After Completion

After implementation is complete, automatically proceed to the next steps without user confirmation:

1. **Auto-test**: If a new feature was added and no related tests exist, load the test workflow with `read_skill("test")` and write tests immediately
2. **Auto-review**: After testing is complete (or if tests are unnecessary), load the review workflow with `read_skill("review")` and self-review the changes
3. **Final report**: After the review is complete, report the full results to the user

If the scope expands to 3+ files during implementation, ask the user: "Should I switch to coding-pipeline?"  (scope expansion requires user judgment)

**Chain depth limit**: If auto-transitions exceed 3, report intermediate results to the user and confirm whether to proceed with the next step.

## Skill Modifications Are Out of Scope

If the target is a **skill**, do not use this workflow (impl). Load the skill-creator workflow with `read_skill("skill-creator")` instead. Impl is for workspace/page files only.

## Notes

- Do not perform unsolicited refactoring, optimization, or style changes
- Do not create excessive abstractions — implement only what is currently needed
- Do not break existing tests
