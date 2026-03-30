# Error Handling Patterns

Error handling patterns for skills with scripts or external dependencies.

## Script Failure Handling

Skills where scripts can fail should specify fallback procedures in the SKILL.md body:

```markdown
## Procedure
1. Run `run_skill_script("my-skill", "convert.py", [input_path, output_path])`
2. **On failure**: Analyze the error message and handle as follows:
   - File format error -> Guide the user to the correct format
   - Missing dependency -> Only standard library is available (pip install not possible). Use alternative stdlib module or redesign script
   - Timeout -> Retry with reduced input size
3. **On success**: Verify output file exists, then proceed to the next step
```

## Retry Pattern

When the same script can be retried with different arguments:

```markdown
## Conversion Procedure
1. Run with default options: `run_skill_script("converter", "run.py", [file, "--format", "auto"])`
2. On failure, retry with explicit format: `run_skill_script("converter", "run.py", [file, "--format", "utf-8"])`
3. On second failure: Request the user to verify file encoding
```

## Step-by-Step Verification Pattern

Pattern for pipeline skills to avoid restarting everything on intermediate step failure:

```markdown
## Execution Procedure
1. Data collection: `run_skill_script("pipeline", "step1_collect.py", [source])`
   -> On failure: Check source access permissions, verify network status
2. Data processing: `run_skill_script("pipeline", "step2_process.py", [intermediate_file])`
   -> On failure: Verify step1 output format, re-run only step2
3. Report generation: `run_skill_script("pipeline", "step3_report.py", [processed_result])`
   -> On failure: Create manual summary using step2 output (fallback)
```

## Guardrail Pattern

Explicitly state what the skill must not do to prevent accidents:

```markdown
## Constraints
- **No deletion**: Do not delete or overwrite original files. Always output to new files
- **Path restriction**: Do not create files outside the user-specified directory
- **Size limit**: Do not process files over 100MB; guide the user to split them
```
