# Interaction Patterns

Patterns for when user interaction is needed during skill execution.

## Auto-Proceed vs User Confirmation Criteria

| Situation | Auto-proceed | User confirmation needed |
|-----------|-------------|------------------------|
| Read-only tasks (analysis, search) | O | - |
| Creating new files (no impact on existing files) | O | - |
| Modifying/overwriting existing files | - | O |
| External API calls (potential cost) | - | O |
| Choosing among multiple options | - | O |
| Hard-to-reverse operations | - | O |

## Confirmation Request Pattern

Specify when user confirmation is needed in the SKILL.md body:

```markdown
## Procedure
1. Analyze target files (automatic)
2. Present conversion options -- **Present the following options to the user and get their selection:**
   - A: Full conversion (preserve original)
   - B: Selective conversion (specify items to convert)
3. Execute conversion with the selected option
```

## Progress Reporting Pattern

Intermediate progress reporting for long-running tasks (3+ step pipelines):

```markdown
## Procedure
1. Data collection -> Report collected count on completion
2. Data processing -> Report processing result summary on completion
3. Final output -> Provide output path and summary
```

## Input Requirements Pattern

When the skill requires external resources (API keys, file paths, etc.):

```markdown
## Prerequisites
This skill requires the following information. Request from the user if missing:
- **Target file path**: Absolute path of the file to convert
- **Output directory**: Directory to save results (defaults to same directory as source if not specified)
```
