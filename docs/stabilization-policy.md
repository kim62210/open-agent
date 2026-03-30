# Stabilization Policy

This document describes how Open Agent should be stabilized during the v1.0 release phase.

The intent is to prevent the project from continuing to expand while critical release guarantees remain incomplete.

## Stabilization principles

1. **No broad feature expansion during stabilization.**
2. **Every user-visible change must have verification evidence.**
3. **Operational honesty beats optimistic behavior.**
4. **Support boundaries must be documented before they are relied on.**

## What changes are allowed during stabilization

Allowed:

- bug fixes
- security hardening
- ownership or auth boundary fixes
- startup/readiness correctness fixes
- regression tests
- release and deployment workflow improvements
- documentation that reduces ambiguity for contributors or operators

Disallowed unless explicitly re-scoped:

- new major subsystems
- large UI redesigns
- distributed runtime architecture work
- speculative plugin framework work

## Stabilization gates

Before a release candidate is considered ready, all of the following must be true:

### Repository and release gates

- CI is green on the default branch
- `uv build` succeeds
- `CHANGELOG.md` is updated
- deployment and upgrade guides are up to date

### Runtime gates

- `/api/settings/health` responds successfully
- `/api/settings/readiness` reflects current startup state honestly
- async run control APIs behave correctly
- workspace and job ownership boundaries are enforced

### Verification gates

- targeted regression suites pass
- touched files are Ruff-clean
- touched files have no new diagnostics

## Release freeze rule

Once a v1.0 release candidate is declared, only the following should land:

- blocker bug fixes
- documentation corrections
- release workflow corrections
- compatibility fixes needed for installation or startup

Any change that broadens the supported feature set should be deferred to a post-v1 milestone.
