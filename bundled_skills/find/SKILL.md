---
name: find
description: >
  Read-only workflow for codebase and documentation exploration and analysis.
  Used when the user wants to find code or documents, understand project structure,
  or comprehend specific implementations or configurations.
  Triggered by requests like "where is this function?", "how is this feature implemented?",
  "show me the code structure", "where is this called?", "find related files",
  "find usage sites", "where is the documentation?", "find the config file", etc.
allowed-tools:
  - search
  - read_file
  - list_files
  - list_files
---

# Find

A 4-step read-only workflow for codebase exploration.

**This skill is read-only. Do not modify any code.**

If the exploration target is a **skill**: check skill content/scripts with `read_skill`, explore reference documents with `read_skill_reference`. Skill directories cannot be accessed via workspace tools (read_file, search, list_files).

## Step 1: Understand Structure

1. Use `list_files` to understand the overall project structure
2. Use `list_files` to find related file patterns
3. Identify the project's language, framework, and directory structure

## Step 2: Search

1. Use `search` to look for keywords, function names, class names, and variable names
2. Search strategy:
   - Search by exact name first
   - If no results, expand to substrings and regex
   - Also search for related imports and type definitions
3. Use `list_files` to search by filename patterns

## Step 3: Deep Analysis

1. Use `read_file` to read the content of related files
2. Trace the call chain: caller -> target function -> called functions
3. Map the data flow: input -> transformation -> output
4. Identify dependency relationships

## Step 4: Synthesize

1. Organize findings in a structured format
2. Provide a list of key files and functions (file path + line number)
3. Clearly explain how the code works
4. Suggest additional exploration directions if relevant
