---
name: coding-pipeline
description: >
  Systematic pipeline for complex coding or documentation tasks that modify 3 or more files.
  Used when large-scale changes spanning multiple modules are needed, not simple feature additions.
  Triggered by requests like "large-scale refactoring", "build a new module system",
  "redesign the entire API", "add cross-cutting features", "migration work",
  "restructure all documentation", etc.
  For single-file changes or modifications to 2 or fewer files, use the impl skill.
  For bug fixes, use the debug skill.
allowed-tools:
  - search
  - read_file
  - write_file
  - edit_file
  - bash
  - list_files
  - apply_patch
---

# Coding Pipeline

An Orchestrator -> Developer -> Verifier single-agent pipeline for complex coding tasks.

## Step 1: Analysis (Orchestrator)

1. Run `run_skill_script("coding-pipeline", "analyze_project.py", [workspace_root_absolute_path])` to understand the project structure
2. Use `read_file` to read key files and understand the architecture
3. Use `search` to find all code related to the change target
4. Organize analysis results:
   - Project language/framework
   - Directory structure and naming conventions
   - Existing patterns (imports, error handling, types, etc.)
   - Impact scope

## Step 2: Plan and Task Decomposition (Orchestrator)

1. Break the overall task into independent subtasks
2. When decomposing tasks, read and apply the decomposition guide with `read_skill_reference("coding-pipeline", "task-decomposition.md")`
3. Include for each subtask:
   - **ID**: T1, T2, T3, ...
   - **Goal**: What this task will achieve
   - **Target files**: List of files to modify/create
   - **Dependencies**: Prerequisite task IDs
   - **Verification criteria**: How to confirm this task's success
4. Determine execution order based on dependencies
5. Report the plan to the user and get approval

## Step 3: Sequential Execution (Developer + Verifier)

Repeat the following for each subtask:

### Developer Phase
1. Read target files for the task and understand the context
2. Write/modify code following existing patterns
3. Apply changes with `edit_file` or `write_file`

### Verifier Phase
1. Run `run_skill_script("coding-pipeline", "verify_task.py", [workspace_root_absolute_path, "--files", "changed_file1", "changed_file2"])` to verify only the files changed in that subtask
2. Check for syntax errors and lint errors
3. Run existing tests related to the changed files
4. On verification failure:
   - Analyze the error content
   - Return to the Developer phase for fixes
   - **Always track failure count** (e.g., "T1 verification failed 2/3 times")
   - After 3 failures, stop that task, report to the user, and await instructions
5. On verification pass, proceed to the next subtask

## Step 4: Final Verification (Orchestrator)

1. Confirm all subtasks are completed
2. Run the full build/test suite with `bash`
3. Review all changed files:
   - Consistent style
   - Missing imports
   - Unnecessary debug code
4. Report final results to the user:
   - Completed task list
   - List of changed files
   - Verification results

## Auto-Transition After Completion

After pipeline completion, automatically proceed to the next steps without user confirmation:

1. **Auto-test**: If changed modules lack related tests, load the test workflow with `read_skill("test")` and write tests for key changes
2. **Auto-review**: After testing is complete, load the review workflow with `read_skill("review")` and self-review all changes
3. **Final report**: After the review is complete, report the full results (completed tasks, changed files, test results, review verdict) to the user

## When Skill Modifications Are Included

If the pipeline includes **skill modifications**: load the skill-creator workflow with `read_skill("skill-creator")` to handle that subtask. Skill files cannot be accessed via workspace tools.

## Notes

- Each subtask must be independently verifiable
- Ensure subtask failures do not propagate to other tasks
- Report progress to the user periodically during large-scale changes
