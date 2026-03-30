# Output Patterns

Patterns to use when a skill needs to produce consistent, high-quality output.

## Template Pattern

Provide a template for the output format. Adjust strictness to match requirements.

**Strict format (API responses, data formats, etc.):**

```markdown
## Report Structure

Always follow this template structure:

# [Analysis Title]

## Summary
[1-paragraph overview of key findings]

## Key Findings
- Finding 1 (include supporting data)
- Finding 2 (include supporting data)

## Recommendations
1. Specific and actionable recommendation
2. Specific and actionable recommendation
```

**Flexible format (when adaptation by context is useful):**

```markdown
## Report Structure

Below is a reasonable default format, but adjust as needed:

# [Analysis Title]
## Summary
## Key Findings
[Adjust sections based on findings]
## Recommendations
[Adjust to fit context]
```

## Examples Pattern

When output quality depends on examples, provide input/output pairs:

```markdown
## Commit Message Format

Generate following these examples:

**Example 1:**
Input: Add user authentication with JWT tokens
Output: feat(auth): implement JWT-based authentication

**Example 2:**
Input: Fix bug where dates display incorrectly in reports
Output: fix(reports): correct date format in timezone conversion
```

Examples demonstrate style and detail levels that are difficult to convey through explanation alone.
