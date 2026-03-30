---
name: plan
description: >
  Read-only workflow for task planning.
  Used when the user needs to create a plan before implementation, analyze task scope, or decide on an approach.
  Triggered by requests like "how should I implement this?", "create a plan", "design this",
  "suggest an approach", "what do I need to do for this?", "break down the task",
  "set up the architecture", etc.
allowed-tools:
  - search
  - read_file
  - list_files
  - list_files
---

# Plan

A 5-step read-only workflow for task planning.

**This skill is read-only. Do not modify any code. Only create plans.**

## Step 1: Restate

1. Restate the user's request as specific goals
2. Clearly define the criteria for "success"
3. Ask the user about unclear points

## Tool Selection Guide

If the target is a **skill**, use skill tools instead of workspace tools:
- `read_file` -> `read_skill` / `list_files` -> `read_skill` to check script lists / `search` -> `read_skill` to search content

## Step 2: Scope Analysis

1. Use `list_files` to understand the project structure (use `read_skill` for skill targets)
2. Use `search` to find related code
3. Use `read_file` to read and analyze key files
4. Identify the impact scope:
   - List of files requiring modification
   - Affected existing functionality
   - External dependencies

## Step 3: Risk Assessment

1. Identify technical risk factors:
   - Compatibility issues
   - Performance impact
   - Security considerations
2. Explicitly state uncertain areas
3. Propose mitigation strategies for each risk

## Step 4: Step-by-Step Plan

1. Break the task into independent steps
2. Include for each step:
   - **Goal**: What this step will achieve
   - **Target files**: Files to modify/create
   - **Changes**: Specific work items
   - **Verification**: How to confirm this step's success
3. Specify dependencies between steps
4. Provide an estimate of the overall effort

## Step 5: Request Approval

1. Present the complete plan to the user in a structured format
2. If alternatives exist, present them with pros and cons
3. Accept user feedback and adjust the plan
4. **This skill ends here.** Do not start implementation directly

## Post-Completion Transition Guide

**Plan is the only workflow that requires user approval.** Present the plan and get approval.

Once the user approves, suggest the next step based on task scope:

- **2 or fewer files to modify** -> "Shall I start implementation?" (transition to impl workflow)
- **3 or more files to modify** -> "This is a large-scale task. Shall I proceed with coding-pipeline?" (transition to coding-pipeline workflow)
