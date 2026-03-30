---
name: skill-creator
description: >
  Guide for designing and creating effective skills.
  Used when the user wants to create a new skill or modify/improve/merge existing skills.
  Also used for designing complex tasks as multi-module systems or benchmarking and improving existing skills.
  Triggered by requests like "make this into a skill", "create a skill", "save this logic",
  "improve this skill", "merge skills", etc.
---

# Skill Creator

A guide for creating effective skills.

## What is a Skill

A skill is a modular package that extends an AI agent's capabilities. It provides domain-specific procedural knowledge, workflows, and tools to transform a general-purpose agent into a specialized one. Like an "onboarding guide," it provides procedural knowledge that no model can fully possess.

### What Skills Provide

1. **Specialized workflows** — Multi-step procedures for specific domains
2. **Tool integration** — Scripts for specific file formats or API operations
3. **Domain expertise** — Schemas, business logic, internal rules
4. **Bundled resources** — Scripts, reference documents, and assets for repetitive tasks

### Skill Structure

```
skill-name/
├── SKILL.md              (Required) YAML frontmatter + Markdown instructions
├── scripts/              (Optional) Executable code (Python/Bash/JS, etc.)
├── references/           (Optional) Reference documents loaded into context as needed
└── assets/               (Optional) Files used in output (templates, images, etc.)
```

#### SKILL.md (Required)

- **Frontmatter (YAML)**: `name` and `description` are required.
  - `name`: kebab-case (e.g., `document-reader`)
  - `description`: The skill's **trigger mechanism** — describe "what it does and when to use it" specifically. Write this here, not in the body. The body is only loaded after triggering, so putting a "When to Use" section in the body does not help with triggering.
- **Body (Markdown)**: Instructions for using the skill. Write in imperative form.

#### scripts/ (Optional)

Use when the same code would be written repeatedly or when deterministic accuracy is needed.

- **Example**: `scripts/rotate_pdf.py` — PDF rotation processing (this skill's `scripts/json2html.py` is also a design reference)
- **Benefits**: Token savings, deterministic, can be executed without loading into context
- Added scripts must be tested with `run_skill_script`
- **Path rules**: Scripts run from the skill directory. When referencing external files, always design them to accept **absolute paths** as arguments
- **Internal module convention**: Support modules that are only imported by other scripts and not executed directly should use a `_` prefix (e.g., `_utils.py`, `_data_processor.py`). Files with `_` prefix are automatically excluded from the script list in the system prompt, preventing the LLM from calling them directly.

##### Script Requirements

When writing scripts, **always** follow these rules. For detailed boilerplate, refer to `read_skill_reference("skill-creator", "script-boilerplate.md")`.

1. **Use only standard library** — pip installation is not possible. Use only stdlib: `urllib`, `json`, `sys`, `os`, `re`, `pathlib`, `ssl`, etc.
2. **SSL certificate bypass required** — HTTP request scripts must set `check_hostname=False` and `verify_mode=ssl.CERT_NONE` on `ssl.create_default_context()`. Required for corporate proxy/self-signed certificate environments
3. **Print errors to stderr** — `print(..., file=sys.stderr)`. Do not swallow exceptions (`except: pass` is forbidden). Exit with `sys.exit(1)` on failure
4. **Validate arguments** — Check `sys.argv` length and print usage then `sys.exit(1)` if insufficient
5. **Execution limits** — **60-second timeout** per script (force-killed if exceeded). stdout **100K character** truncation. Keep output concise
6. **Encoding** — Specify `encoding='utf-8'` for file I/O. Prevents character corruption
7. **Environment variable blocking** — Sensitive variables like API keys are automatically removed from the environment. Accept them as arguments if needed

#### references/ (Optional)

Documents to reference during work via `read_skill_reference`.

- **Examples**: DB schemas, API documentation, domain knowledge, internal policies
- Keep SKILL.md concise while separating detailed information
- If over 10k words, include grep search patterns in SKILL.md
- **Do not duplicate content between SKILL.md and references** — detailed info in references, core procedures only in SKILL.md
- **[Key] Always specify when and under what conditions to read references in the SKILL.md body.** The LLM will not automatically read references based on filenames alone. You must explicitly state "`read_skill_reference` to read X.md" in the body for it to actually load.

**Wrong example (just listing filenames):**
```markdown
## Reference
- references/schema.md
- references/api-guide.md
```
-> LLM is unlikely to read these files

**Correct example (specifying timing and conditions):**
```markdown
## Procedure
1. Understand data structure: check schema with `read_skill_reference("my-skill", "schema.md")`
2. If API calls are needed: check endpoints with `read_skill_reference("my-skill", "api-guide.md")`
```
-> LLM automatically loads references at the appropriate step

#### assets/ (Optional)

Files used in output without loading into context.

- **Examples**: Logos, slide templates, frontend boilerplate, fonts

#### What Not to Include

Do not create supplementary documents like README.md, INSTALLATION_GUIDE.md, CHANGELOG.md, etc. Skills should contain only the information needed for an AI agent to perform its task.

## Core Principles

### Conciseness is Key

The context window is a shared resource. The system prompt, conversation history, other skill metadata, and user requests all share the same space.

**Default assumption: AI is already smart enough.** Do not re-explain what AI already knows. For every piece of content, ask yourself: "Does this paragraph justify its token cost?"

Prefer concise examples over verbose explanations.

### Setting Appropriate Freedom

Determine the level of specificity based on the task's fragility and variability:

- **High freedom (text instructions)**: When multiple approaches are valid, or when judgment varies by context
- **Medium freedom (pseudocode or parameterized scripts)**: When there's a preferred pattern, but some variation is acceptable
- **Low freedom (fixed scripts)**: When the task is fragile and error-sensitive, or when consistency is critical

Guardrails on a narrow bridge (low freedom) vs. multiple paths across an open field (high freedom).

## Progressive Disclosure

Skills manage context efficiently through 3-tier loading:

1. **Metadata (name + description)** — Always present in context (~100 words)
2. **SKILL.md body** — Loaded when the skill is triggered (recommended under 500 lines)
3. **Bundled resources** — Loaded on demand (scripts can be executed without reading)

### Splitting Pattern

Keep SKILL.md body under 500 lines. When approaching this limit, split into references/. When splitting, always reference them in SKILL.md and specify when to read them.

**Core principle:** When a skill supports multiple variants/frameworks/options, keep only the core workflow and selection guide in SKILL.md and move variant-specific details to references/.

**Pattern 1: Top-level guide + reference documents**
```markdown
# PDF Processing
## Quick start
[Core example]
## Advanced features
- **Form filling**: See references/forms.md
- **API reference**: See references/api.md
```

**Pattern 2: Domain-specific separation**
```
bigquery-skill/
├── SKILL.md (overview + navigation)
└── references/
    ├── finance.md
    ├── sales.md
    └── product.md
```
-> When the user asks about sales, only sales.md is loaded.

**Pattern 3: Conditional details**
```markdown
## Creating documents
Uses docx-js. See references/docx-js.md.
## Editing documents
For simple edits, modify XML directly.
**If tracked changes are needed**: See references/redlining.md
```

**Guidelines:**
- Connect references from SKILL.md at only 1 level deep
- Include a table of contents at the top for reference files over 100 lines
- **All references must specify `read_skill_reference` call timing in the SKILL.md body** — simple listings become dead documents

## Skill Creation Process

Proceed in order. Skip only steps that do not apply.

**[Important] Path and tool constraints:**
- Skills are created in `~/.open-agent/skills/`. This path is automatically managed by the `create_skill` tool.
- **Never create or modify skill files with workspace tools like `workspace_write_file`, `workspace_edit_file`.** Creating in the workspace means the skill won't be registered in the skill system and won't appear in the list.
- Always use the `create_skill` tool to create skills.
- Always use the `add_skill_script` tool to add scripts.
- Always use the `update_skill` tool to modify skills.

### Step 1: Understand Through Specific Examples

Skip only if the usage pattern is already clear.

Understand how the skill will be used through specific examples:
- "What features should this skill support?"
- "Give me examples of how this skill would be used."
- "What phrases should trigger this skill?"

Do not ask too many questions at once. Start with the core questions.

### Step 2: Plan Reusable Resources

Analyze each example:
1. How would you perform this task from scratch?
2. What scripts, references, and assets would be useful for repeated execution?

**Freedom level decision criteria:**

| Condition | Pure instructions (SKILL.md only) | Script needed (scripts/) |
|-----------|----------------------------------|------------------------|
| AI can perform directly | O | - |
| External library needed | - | O |
| File conversion/parsing is core | - | O |
| Prompt engineering is core | O | - |
| Deterministic accuracy needed | - | O |

**Resource planning examples:**

- `pdf-editor` skill — "Rotate this PDF" -> same code written every time -> `scripts/rotate_pdf.py` script needed
- `big-query` skill — "How many users connected today?" -> table schema explored every time -> `references/schema.md` reference document needed
- `frontend-builder` skill — "Make a TODO app" -> same boilerplate every time -> `assets/template/` assets needed

### Step 3: Create Skill

Create with the `create_skill` tool:

```
create_skill(
  name="my-skill",
  description="Describe specifically what the skill does and when to use it",
  instructions="# My Skill\n\n## Procedure\n1. ...\n2. ..."
)
```

**Frontmatter writing rules:**
- `name`: kebab-case (e.g., `document-reader`)
- `description`: Trigger mechanism. Include both "what it does and when to use it". Write here, not in the body.
  - Example: "Skill for creating, editing, and analyzing documents. Used when the user asks to create or modify .docx files, handle tracked changes, add comments, or perform other document tasks."

**Body writing rules:**
- Write in imperative form ("do X", "check Y")
- If scripts accept external files as arguments, always specify "pass absolute paths"
- Concise examples > verbose explanations
- **If references exist, specify `read_skill_reference` call timing in the body** (LLM won't read without timing specification)
- **If scripts exist, specify `run_skill_script` call timing, arguments, and expected results in the body**

### Step 4: Add Resources and Edit

#### Adding Scripts

Add with the `add_skill_script` tool:

```
add_skill_script(
  skill_name="my-skill",
  filename="process.py",
  content="#!/usr/bin/env python3\n..."
)
```

- Always test with `run_skill_script` after adding
- For multiple similar scripts, test only representative samples to save time
- Check with the user if user input is needed (e.g., brand assets, template files)

#### Modifying Skills

Modify with the `update_skill` tool:

```
update_skill(
  name="my-skill",
  description="Improved description",
  instructions="# Improved instructions\n..."
)
```

Delete unnecessary example files or directories.

#### Design Pattern Reference

If the skill needs the following patterns, **always read the reference with `read_skill_reference`** and apply:

- **Multi-step processes**: `read_skill_reference("skill-creator", "workflows.md")` — Sequential/conditional workflow design patterns
- **Important output formats**: `read_skill_reference("skill-creator", "output-patterns.md")` — Template/example patterns
- **Script failure handling**: `read_skill_reference("skill-creator", "error-handling.md")` — Error handling/fallback patterns
- **Tasks requiring user confirmation**: `read_skill_reference("skill-creator", "interaction-patterns.md")` — Auto-proceed vs. user confirmation criteria
- **Designing complex multi-step skills**: `read_skill_reference("skill-creator", "bundled-patterns.md")` — Bundled workflow-based structural patterns

### Step 5: Verify

1. Check saved content with `read_skill`
2. Test scripts with `run_skill_script` if present
3. **If references exist, verify that loading timing is specified in the body** — update with `update_skill` if missing
4. **Error scenario check**: Verify that fallback instructions exist in the body for script failures
5. Report results to the user: skill name, description, included files, usage instructions

### Step 6: Iterative Improvement

Improve after real-world use:
1. Use the skill in actual tasks
2. Discover inefficiencies or issues
3. Modify SKILL.md with `update_skill`, add/modify scripts with `add_skill_script`
4. Test again

## Modifying Existing Skills

Follow this ReAct loop (Reason -> Act -> Observe -> Repeat):

1. **Analyze (Reason)**: Check current content with `read_skill`. Determine the scope of changes (description? instructions? scripts?)
2. **Test before modification (Observe)**: If scripts exist, check current behavior with `run_skill_script` and record input/output (pre-modification baseline)
3. **Modify (Act)**: Modify instructions with `update_skill`, modify/add scripts with `add_skill_script`. Apply "Script Requirements"
4. **Verify (Observe)**: Test with `run_skill_script` using the same inputs. Compare with pre-modification results
5. **Iterate (Loop)**: On test failure -> analyze error -> return to step 3 for re-modification. **Maximum 3 iterations**. After 3, report to user
6. **Regression check**: Test with different inputs to ensure existing functionality outside the modification target works correctly
7. **Complete**: Check final state with `read_skill` and report changes to the user

## Multi-Module Design

For complex tasks, **split into multiple modules** instead of a single large script. Each module should be independently executable and testable.

### Pipeline Pattern

Suitable for tasks that transform data step-by-step:

```
my-pipeline-skill/
├── SKILL.md
└── scripts/
    ├── step1_collect.py     # Data collection -> stdout or file output
    ├── step2_process.py     # Process step1 results as input
    └── step3_report.py      # Generate final output
```

**Specify execution order in SKILL.md:**
```markdown
## Execution Procedure
1. `run_skill_script("my-pipeline", "step1_collect.py", [args])` -> Check intermediate results
2. `run_skill_script("my-pipeline", "step2_process.py", [args])` -> Check processed results
3. `run_skill_script("my-pipeline", "step3_report.py", [args])` -> Final output
After each step, verify results and if issues are found, modify and re-run only the relevant script.
```

**Design principles:**
- Data transfer between modules via file paths (arguments) or stdout
- Add `--help` flag to each module for usage verification
- On issues, modify only the relevant module with `add_skill_script` — no need to rebuild everything

### Utility Pattern

When grouping multiple functions sharing common logic into a single skill:

```
data-utils/
├── SKILL.md
└── scripts/
    ├── csv_to_json.py
    ├── json_to_csv.py
    └── validate.py
```

## Improving and Merging Existing Skills

### Improve

If an existing skill meets 70%+ of requirements, **improve it rather than creating a new one**. Follow the "Modifying Existing Skills" ReAct loop, plus:

1. Check current skill instructions and scripts with `read_skill`
2. Analyze what's lacking (feature addition? bug fix? performance improvement?)
3. **Apply "Script Requirements" when modifying scripts** — also reinforce existing scripts missing SSL bypass, stderr error output, argument validation, etc.
4. Record pre-modification baseline with `run_skill_script`
5. Modify with `update_skill` + `add_skill_script`
6. Test with same inputs using `run_skill_script` -> on failure, analyze and re-modify (max 3 times)
7. Compare pre/post improvement results (benchmark)

### Merge

When consolidating 2 or more similar skills into one:

1. Read all target skills with `read_skill`
2. Separate common logic from unique logic
3. Create unified skill: common logic consolidated, unique features as separate modules
4. Update the original skills' descriptions to point to the unified skill for discoverability

### Reference Use

Even if an existing skill is only ~30% related, **use it as a hint**:

1. Check related skill code/patterns with `read_skill`
2. Identify reusable code, libraries, and approaches
3. Adopt validated patterns when creating new skills

## Benchmarking

When improving skills, compare before and after results:

1. **Run existing script** -> Record results (output, execution time, accuracy)
2. **Run improved script** -> Execute under the same conditions
3. **Compare**: Output quality, errors, execution time, etc.
4. **Decide**: Apply if improvement is confirmed, rollback if not

Benchmarking applies only to skills with scripts. Skills with instructions only are improved through real-world usage feedback.
