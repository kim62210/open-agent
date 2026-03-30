# Task Decomposition Patterns

Reference patterns for decomposing complex coding tasks into subtasks.

## Principles

1. **Independence**: Each subtask must be independently verifiable
2. **Minimize dependencies**: Linear or tree structure without circular dependencies
3. **Appropriate size**: Each subtask modifies 1-3 files
4. **Clear boundaries**: Inputs and outputs are clearly defined

## Pattern 1: Frontend Feature Addition

```
T1: Define data models/types
    Target: types.ts, models/
    Verification: TypeScript compilation passes

T2: Write API client functions
    Target: lib/api/
    Dependencies: T1
    Verification: Type check passes

T3: Implement UI components
    Target: components/
    Dependencies: T1
    Verification: Build passes

T4: Page/route integration
    Target: app/ or pages/
    Dependencies: T2, T3
    Verification: Build passes + manual verification

T5: Styling and responsive design
    Target: Component CSS/classes
    Dependencies: T3, T4
    Verification: Build passes
```

## Pattern 2: API Endpoint Addition

```
T1: Define data models
    Target: models/
    Verification: Import test

T2: Business logic / service layer
    Target: core/ or services/
    Dependencies: T1
    Verification: Unit tests

T3: Implement API endpoints
    Target: api/endpoints/
    Dependencies: T1, T2
    Verification: Server starts + route registration confirmed

T4: Router registration and server configuration
    Target: server.py or app.py
    Dependencies: T3
    Verification: Server starts + /docs check

T5: Frontend integration (if needed)
    Target: Frontend API client + UI
    Dependencies: T3
    Verification: Build passes
```

## Pattern 3: Refactoring

```
T1: Design interfaces/abstractions
    Target: New module files
    Verification: Type check

T2: Migrate existing code to new interfaces (per file)
    Target: Each target file
    Dependencies: T1
    Verification: Existing tests pass

T3: Remove legacy code
    Target: Fully migrated files
    Dependencies: T2 (all)
    Verification: Full test suite passes

T4: Update documentation/configuration
    Target: Config, README, etc.
    Dependencies: T3
    Verification: Build passes
```

## Decomposition Checklist

- [ ] Does each task modify only 1-3 files?
- [ ] Are there no circular dependencies?
- [ ] Are verification criteria clear for each task?
- [ ] Is the rollback scope limited on task failure?
- [ ] Can tasks without dependencies run in parallel?
