# Conversation Summary Template

> **What this is:** A structured record of what happened in a coding agent session. Captures decisions made, files created/modified, test results, and learnings. Complements the error report (which focuses on problems) with a broader picture of the session.
>
> **Where it lives:** `~/your-prompts/Step_[ID]_Conversation_Summary.md`

---

## Template

```markdown
# Step [ID] — Conversation Summary

| Field | Value |
|-------|-------|
| **Date** | [YYYY-MM-DD] |
| **Sessions** | [N] (note if context exhausted) |
| **Agent** | [coding agent / model used] |
| **Branch** | [branch name] |
| **PR** | #[N] [merged/open] |
| **Tests** | [X passed, Y xfailed, Z integration] |
| **Source** | [This conversation summary] |

---

## What Was Built

**Backend:**
- [Bullet list of backend deliverables: endpoints, services, models, migrations]
- [Include counts: N new endpoints, N new tests, migration head at XXXX]

**Frontend:**
- [Bullet list of frontend deliverables: pages, components, hooks, stores]
- [Include counts: N new components, N new tests]

**Infrastructure:**
- [CI/CD changes, config changes, dependency additions]

---

## Key Decisions Made

| Decision | Rationale | Alternative Considered |
|----------|-----------|----------------------|
| [e.g., "Dictionary-based state machine"] | [e.g., "Steps are DB-loaded, no persistent in-memory state"] | [e.g., "`transitions` library"] |
| [decision] | [rationale] | [alternative] |

---

## Files Created

| File | Purpose |
|------|---------|
| [path] | [one-line description] |
| ... | ... |

## Files Modified

| File | Changes |
|------|---------|
| [path] | [one-line description of changes] |
| ... | ... |

---

## Learnings

[Things discovered during this step that should influence future steps.
These get promoted to pre-fixes or pre-flags in the prompt package.]

- **L1:** [Learning — e.g., "State management persistence layer requires different mock pattern in tests"]
- **L2:** [Learning — e.g., "Hosting provider injects PORT dynamically — don't hardcode values"]
- **L3:** [Learning — e.g., "Context window exhausted at ~15 new files — split steps earlier"]

---

## Guiding Doc Updates

[What was updated in guiding files during this step's FINAL section]

- **[Agent orientation file]:** [changes]
- **docs/PHASES.md:** [changes]
- **docs/[other]:** [changes]

---

## Open Items

[Things that weren't completed or need follow-up]

- [ ] [Item — deferred to Step X]
- [ ] [Item — needs design decision before implementation]
```

---

## When Context Exhausts Mid-Session

If the agent runs out of context window during a step:

1. Document what was completed in Session 1
2. Start Session 2 with a fresh prompt that references the partially-completed work
3. Note in the summary: "Sessions: 2 (context exhausted in session 1)"
4. This is a signal that the step was too large — consider splitting future steps of similar size

---

## Consolidation

At phase end, merge all conversation summaries into:
`Consolidated_Conversation_Summaries_Phase_N.md`

Structure:
1. Phase overview (dates, total sessions, final numbers)
2. Each step's summary (preserved verbatim)
3. Phase reflection section:
   - What worked well (process, patterns, tools)
   - What didn't work (where time was wasted, recurring problems)
   - Recommendations for next phase

The reflection section is especially valuable — it's where process improvements originate.
