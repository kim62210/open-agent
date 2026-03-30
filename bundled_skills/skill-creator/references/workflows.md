# Workflow Patterns

## Sequential Workflows

Complex tasks are broken into clear sequential steps. Providing a process overview at the beginning of SKILL.md is effective:

```markdown
PDF form filling procedure:

1. Analyze form (run analyze_form.py)
2. Create field mapping (edit fields.json)
3. Validate mapping (run validate_fields.py)
4. Fill form (run fill_form.py)
5. Verify output (run verify_output.py)
```

## Conditional Workflows

For tasks with branching logic, guide the decision points:

```markdown
1. Determine modification type:
   **Creating new content?** -> Proceed to "Creation workflow" below
   **Editing existing content?** -> Proceed to "Editing workflow" below

2. Creation workflow: [steps]
3. Editing workflow: [steps]
```
