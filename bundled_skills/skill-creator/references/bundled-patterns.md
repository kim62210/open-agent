# Bundled Workflow Design Patterns

Design patterns extracted from 7 production-validated bundled workflows.
Reference these when creating complex multi-step skills.

## Pattern Selection Guide

Select a pattern based on the skill's core behavior:

```
Does the skill modify files?
├─ NO -> Pattern A: Read-only Analysis
│        (reference: find, plan, review)
└─ YES
   ├─ Does root cause identification need to come first?
   │  └─ YES -> Pattern C: Investigate Then Fix
   │           (reference: debug)
   ├─ Does it modify 3 or more files?
   │  └─ YES -> Pattern D: Complex Pipeline
   │           (reference: coding-pipeline)
   └─ NO -> Pattern B: Standard Implementation
            (reference: impl, test)
```

---

## Pattern A: Read-only Analysis

**Reference workflows**: find, plan, review
**When to apply**: Tasks without modifications, such as code exploration, design, review

### allowed-tools Configuration
```yaml
allowed-tools: search, read_file, workspace_glob, list_files
```
Excluding `edit_file`, `write_file` prevents accidental modifications.
review includes `bash` to allow status checks like `git diff`.

### Core Rule Example
```markdown
**[Key] This skill is read-only. Never modify any files.**
```
Dual protection with both tool restriction and text rule.

### Step Structure
| Step | find | plan | review |
|------|------|------|--------|
| 1 | Understand structure | Redefine goals | Identify change scope |
| 2 | Search | Impact analysis | Bugs/edge cases |
| 3 | Deep analysis | Risk assessment | Integration/security review |
| 4 | Synthesized report | Step-by-step plan | Verdict report |

### Design Principles
- **Fixed output format**: Structured results such as filepath:line_number, severity classification, Pass/Reject verdict
- **Progressive search**: Exact search -> substring -> regex, expanding in order
- **Call chain tracing**: Caller -> target -> callee flow mapping

---

## Pattern B: Standard Implementation

**Reference workflows**: impl, test
**When to apply**: Clear implementation/writing tasks

### allowed-tools Configuration
```yaml
allowed-tools: search, read_file, write_file, edit_file, bash, workspace_glob, list_files
```
Full read + write + execute access allowed.

### Core Rule Example
```markdown
**[Key] Always follow existing code style and patterns.**
**For changes to 3+ files, use coding-pipeline instead.**
```
Scope limitation rules for responsibility separation between skills.

### Step Structure (impl)
1. **Confirm requirements** -- Break down into specific specs
2. **Research patterns** -- Analyze existing implementations (mandatory before coding)
3. **Report plan** -- Proceed after user approval
4. **Implement** -- Modify files in dependency order
5. **Test** -- Verify build, run existing tests
6. **Verification report** -- Final review and summary

### Design Principles
- **Research first**: Always analyze existing patterns before writing code
- **Approval gate**: Report plan and get user approval before implementation
- **Per-file syntax verification**: Check syntax validity immediately after each modification

---

## Pattern C: Investigate Then Fix

**Reference workflow**: debug
**When to apply**: Tasks where root cause identification must come first

### allowed-tools Configuration
```yaml
allowed-tools: search, read_file, bash, edit_file, workspace_glob
```
Excluding `write_file` -- focus on modifying existing files rather than creating new ones.

### Core Rule Example
```markdown
**[Key] Do not modify any code until Step 4 (root cause confirmed).**
**Verify only one hypothesis at a time.**
```
Core rule enforcing the order of investigation and fix.

### Step Structure
1. **Reproduce** -- Reproduce symptoms with bash
2. **Gather evidence** -- Collect logs, errors, related code
3. **Trace data flow** -- Find discrepancies in the input->output path
4. **Confirm root cause** -- State cause in one sentence (mandatory before fix)
5. **Minimal fix** -- Fix only the root cause, no refactoring
6. **Verify** -- Confirm resolution via re-test

### Design Principles
- **Evidence-based**: Hypothesis -> verification -> confirmation cycle
- **Restricted modification timing**: No code changes until cause is confirmed
- **Minimal invasiveness**: Fix only root cause, no incidental improvements

---

## Pattern D: Complex Pipeline

**Reference workflow**: coding-pipeline
**When to apply**: Large-scale changes modifying 3+ files

### allowed-tools Configuration
```yaml
allowed-tools: search, read_file, write_file, edit_file, bash, workspace_glob, list_files, apply_patch
```
Maximum tool set + `apply_patch` for large-scale change support.

### Core Rule Example
```markdown
**A single agent sequentially performs Orchestrator -> Developer -> Verifier roles.**
**Each subtask must be independently verifiable.**
```

### Step Structure
1. **Analysis** -- Project structure scan, architecture mapping
2. **Decomposition** -- Break into subtasks (T1, T2, T3...), specify dependencies
3. **Sequential execution** -- For each subtask:
   - Developer: Write/modify code
   - Verifier: Syntax check, run tests
   - On failure, return to Developer (max 3 times)
4. **Final verification** -- Full build/test, file review

### Design Principles
- **Task decomposition**: Split large-scale changes into independently verifiable units
- **Verification gates**: Specify pass conditions for each subtask
- **Failure isolation**: Intermediate failures do not propagate to the whole
- **Retry limits**: Report to user after max 3 attempts

---

## Structural Building Blocks

### Frontmatter Required Elements

Frontmatter pattern used by all bundled workflows:

```yaml
---
name: skill-name
description: >
  Describe specifically what the skill does and when it is triggered.
  Include example user phrases like "do X", "I want to Y".
allowed-tools: tool1, tool2, tool3
---
```

`allowed-tools` declaratively limits the skill's capability scope.

### Core Rule Writing Guidelines

Characteristics of effective core rules:
- **Bold + [Key] tag** for visual emphasis
- **Prohibition rules are specific**: "Do not modify" (O) vs "Be careful" (X)
- **Conditional transitions**: "For 3+ file changes -> use coding-pipeline"
- **Timing restrictions**: "Do not do X before step N"

### 3 Tool Access Control Strategies

| Strategy | Method | Application |
|----------|--------|-------------|
| **Remove** | Exclude tools from allowed-tools | Read-only skills (find, plan) |
| **Delay** | "Do not use before step N" text rule | Investigation-first skills (debug) |
| **Full access** | Include all tools | Complex pipelines (coding-pipeline) |

### Verification Design

Include verification steps in all modification workflows:

```markdown
## Verification
1. Verify syntax validity of modified files (bash execution)
2. Run existing tests -> confirm no regressions
3. Summarize and report changes
```

---

## Anti-Patterns to Avoid

### 1. Write-first (modifying without investigation)
- **Problem**: Writing code ignoring existing patterns -> style inconsistency, duplication
- **Mitigation**: Make investigation a mandatory preceding step, like impl's "Research patterns" step

### 2. Unverified completion (reporting done without verification)
- **Problem**: Reporting "complete" without build/test after modification
- **Mitigation**: Mandatory verification gates, like coding-pipeline's Verifier role

### 3. Missing core rule (no text rule despite tool restrictions)
- **Problem**: Tools are restricted but no text rule -> LLM misunderstands intent
- **Mitigation**: Dual protection with allowed-tools restriction + text core rule

### 4. Scope creep (exceeding scope)
- **Problem**: Fix request includes refactoring, comment additions, code cleanup
- **Mitigation**: Explicitly limit scope, like debug's "fix only root cause" rule

### 5. Flat steps (listing without step distinction)
- **Problem**: Just listing "1. Analyze 2. Implement 3. Test" -> unclear input/output for each step
- **Mitigation**: Specify goal, target files, and verification method for each step (plan pattern)

### 6. Unbounded retry (infinite retry)
- **Problem**: Infinite loop on failure -> token waste, repeated same errors
- **Mitigation**: "Report to user after max 3 attempts" pattern from coding-pipeline
