# Error Report Template

> **What this is:** A structured record of every issue encountered during a step's execution. Written by the developer after the coding agent finishes. Sent to the planning model (Opus) for review, then findings flow into the next step's pre-fixes and guiding docs.
>
> **Where it lives:** `~/your-prompts/Error_Report_Step[ID].md`

---

## Template

```markdown
# Error Report — Step [ID]: [Step Name]

**Date:** [YYYY-MM-DD]
**Agent:** [coding agent / model used]
**Branch:** [branch name]
**Final test result:** [X passed, Y failed, Z skipped]

---

## Issues

### Issue [ID]-1: [Descriptive Title]

**What happened:** [Factual description of the problem — what broke, what error appeared, what behavior was wrong]

**Resolution:** [What was done to fix it — specific file changes, pattern changes, workarounds]

**Viability:** [LOW / MEDIUM / HIGH CONCERN]
- LOW = minor fix, no architectural impact
- MEDIUM = workaround applied, tech debt introduced
- HIGH CONCERN = architectural risk, recurring pattern, needs future attention

**Status:** [Resolved / Deferred to Step X / Workaround applied]

---

### Issue [ID]-2: [Descriptive Title]

[Same structure]

---

### Issue [ID]-3: [Descriptive Title]

[Same structure]

---

## Latent Issues

[Issues discovered but not yet triggered — potential problems noticed during code review]

| # | Issue | Severity | Notes |
|---|-------|----------|-------|
| [ID]-L1 | [description] | [Low/Medium/High] | [when this would surface] |
| [ID]-L2 | [description] | [severity] | [notes] |

---

## Guiding Doc Updates Made

[List which guiding files were updated during this step and what changed]

- **[Agent orientation file]:** [what was added/changed]
- **docs/PHASES.md:** [what was added/changed]
- **docs/[other]:** [what was added/changed]

---

## Step Viability Summary

| Category | Status |
|----------|--------|
| [Category 1, e.g., "Database migrations"] | [Strong / Functional / Needs attention] |
| [Category 2, e.g., "API endpoints"] | [Strong / Functional with debt / Needs attention] |
| [Category 3, e.g., "Test coverage"] | [Strong / Gaps identified / Needs attention] |
| [Category 4, e.g., "Frontend components"] | [Strong / Functional / Needs attention] |
```

---

## Writing Guidelines

### Be Specific, Not Narrative
Bad: "There was a problem with the database tests."
Good: "Importing the database module in the router file triggered an eager database connection at import time. Every test tried to connect to the production database before the test config could override the connection string."

### Include the Fix
Every issue should document what was done about it — even if the resolution was "deferred to Phase N."

### Viability Ratings Matter
These tell the planning model which issues are safe to carry forward and which need immediate attention.

### Latent Issues are Predictions
Things you noticed that haven't caused a problem yet but will. These are gold for pre-flags in future steps.

---

## Review Protocol

When sending the error report to the planning model (Opus):

1. Paste the error report
2. Ask for: "Review this — good / bad / what can be improved"
3. The planning model will:
   - Identify issues that should become pre-fixes in the next step
   - Identify issues that should update guiding docs
   - Flag architectural concerns that need design attention
   - Recommend whether `/simplify` is warranted
4. Incorporate the review into the next version of the prompt package

---

## Consolidation

At phase end, merge all step error reports into:
`Consolidated_Error_Report_Phase_N.md`

Structure:
1. Table of contents with anchors to each step
2. Each step's full error report (preserved verbatim)
3. Cross-phase themes section (recurring patterns across steps)
4. Master issue tracker (table of all issues with final status)

This becomes a reference document for future phases — patterns that recurred in Phase N are pre-flagged in Phase N+1.
