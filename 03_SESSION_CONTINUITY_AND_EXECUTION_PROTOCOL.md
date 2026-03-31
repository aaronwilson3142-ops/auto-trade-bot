# SESSION_CONTINUITY_AND_EXECUTION_PROTOCOL.md
Version: 2.0
Project: Autonomous Portfolio Intelligence System (APIS)
Status: Mandatory operating protocol for every session

## 1. Purpose

This file governs how the build agent must operate on APIS in every session.

It exists to preserve continuity, prevent drift, enforce repeatable execution, and minimize loss of project state across new sessions.

This protocol is mandatory.

## 2. Authority Order

When working on APIS, obey in this order:
1. This file
2. `APIS_MASTER_SPEC.md`
3. Other APIS project markdown files in `/docs`, `/state`, or explicitly provided by the user
4. Explicit user instructions for the current task
5. Assumptions only when unavoidable

## 3. Mandatory Session Start Procedure

At the beginning of every new session, before doing meaningful work, the agent must:

1. Read and follow:
   - `APIS_MASTER_SPEC.md`
   - `SESSION_CONTINUITY_AND_EXECUTION_PROTOCOL.md`
   - `state/ACTIVE_CONTEXT.md`
   - `state/NEXT_STEPS.md`
   - `state/DECISION_LOG.md`
   - the most recent entries of `state/SESSION_HANDOFF_LOG.md`

2. Produce a short re-anchoring summary for itself that captures:
   - current objective
   - current build stage
   - completed work
   - open items
   - active constraints
   - known risks

3. Update `state/ACTIVE_CONTEXT.md` if the current truth has changed.

4. Continue work only after that re-anchoring step is complete.

No session is allowed to proceed without this startup review.

## 4. Mandatory Session Capacity Checkpoints

The agent must not wait until the session is nearly unusable before logging continuity state.

Mandatory checkpoints:
- at session start
- at estimated 50% remaining effective session capacity
- then again at every 10% incremental threshold after that:
  - 40% remaining
  - 30% remaining
  - 20% remaining
  - 10% remaining
- at session end
- immediately before any major context switch
- immediately after any major architecture decision
- immediately after any major implementation milestone
- immediately when confusion, drift, repetition, or degradation is detected

Operational interpretation:
- once the session crosses the 50% remaining threshold, continuity logging becomes mandatory at each next 10% reduction
- do not skip checkpoints

## 5. Mandatory Continuity Rule

The agent must treat continuity preservation as a hard requirement.

Required behavior:
- never rely on unstored session memory for critical project state
- write important facts to project state files
- append every major milestone to the handoff log
- preserve architecture decisions in the decision log
- preserve exact next actions in NEXT_STEPS
- preserve current truth in ACTIVE_CONTEXT

The project must be resumable by a future session with minimal ambiguity.

## 6. Realistic Constraint Note

Absolute zero-loss memory cannot be guaranteed by any session-based tool environment.

Therefore the mandatory standard for APIS is:
- preserve all critical project knowledge in state files
- keep state files current
- make every session resumable
- prevent avoidable loss of continuity by disciplined logging

The agent is not allowed to act as if unstored context will always persist.

## 7. Required State Files and Their Rules

### 7.1 `state/ACTIVE_CONTEXT.md`
Must always represent the latest ground truth.

It should include:
- what APIS is
- what stage the build is in
- what major components already exist
- what is currently being worked on
- current constraints
- current architecture truth
- current broker/data assumptions
- latest known risks

Update whenever the truth changes.

### 7.2 `state/NEXT_STEPS.md`
Must contain:
- ordered next actions
- blockers
- prerequisites
- what to build next
- what to verify next

Update whenever priorities change.

### 7.3 `state/DECISION_LOG.md`
Must capture:
- major design decisions
- tradeoffs considered
- why the chosen direction was selected
- date/time of each decision
- impact on future work

### 7.4 `state/CHANGELOG.md`
Must record concrete changes made:
- files created
- files modified
- modules added
- rules changed
- tests added
- configs updated

### 7.5 `state/SESSION_HANDOFF_LOG.md`
Must be appended at each mandatory checkpoint.

## 8. Handoff Log Entry Requirements

Every handoff entry must include:

### A. Objective and Current State
- what the project is trying to do
- where the build currently stands

### B. Completed Work
- what was finished in this segment
- exact files or modules touched
- key design choices made

### C. Inputs and References
- markdown files consulted
- other files used
- data sources or docs referenced
- assumptions

### D. Open Items
- the next ordered actions
- unresolved issues
- risks and blockers

### E. Verification Status
- tests run
- QA status
- what passed
- what failed
- what still needs validation

### F. Continuity Notes
- details another session would need to resume immediately
- anything easy to forget but important

## 9. Required Handoff Template

Append entries in this format:

```md
### [YYYY-MM-DD HH:MM TZ] Session Checkpoint
- Capacity Trigger:
- Objective:
- Current Stage:
- Current Status:
- Files Reviewed:
- Files Changed:
- Decisions:
- Completed Work:
- Open Items (Next Steps):
- Blockers:
- Risks:
- Verification / QA:
- Continuity Notes:
- Confidence:
```

## 10. Execution Loop for Every Meaningful Task

For each meaningful task, the agent must follow:

1. Re-anchor to current project state
2. Read relevant state/spec files
3. Plan the smallest correct next move
4. Make the change
5. Run verification and QA
6. Update state files
7. Append checkpoint if required
8. Then continue

Do not make major changes without updating state.

## 11. Quality Review Loop

After any meaningful change, the agent must run a quality review.

Minimum checklist:
- requirements compliance
- architecture consistency
- code correctness
- risk-rule consistency
- test coverage relevance
- performance sanity
- output usability
- continuity-file updates completed

Output format:
- QA Status: PASS / FAIL
- Findings:
- Fixes Applied:
- Remaining Risks:
- Confidence:

If a revision is made, rerun QA.

## 12. Anti-Drift Rules

The agent must not:
- forget previously logged project decisions
- contradict APIS_MASTER_SPEC without explicitly recording a revision
- silently change scope
- silently expand from paper trading to live trading
- silently weaken safety or risk controls
- keep important facts only in temporary session reasoning
- declare work complete without updating state files

## 13. Project-Specific Build Guardrails

For APIS specifically:
- prioritize long-only U.S. equities first
- keep no-margin, no-leverage, no-options in MVP
- keep max 10 positions in MVP unless explicitly revised
- keep paper trading first
- keep self-improvement controlled and benchmarked
- separate rumors from verified facts
- prefer second-order thematic analysis when justified
- grade performance daily using both return and risk metrics
- do not optimize solely for raw daily gains

## 14. Session-End Procedure

Before ending a session, the agent must:

1. update ACTIVE_CONTEXT
2. update NEXT_STEPS
3. update DECISION_LOG if any major decisions occurred
4. update CHANGELOG
5. append final handoff entry to SESSION_HANDOFF_LOG
6. verify that another session could resume from the logs alone

Do not end the session without completing this.

## 15. Final Directive

This protocol is mandatory for every session working on APIS.

The agent must act as though future continuity depends entirely on the quality of the project’s markdown state files.

Because in practice, it does.


## 16. Mandatory Tool and Plugin Usage Rule

The agent must actively use all relevant tools available in its environment when those tools materially improve the work.

Required behavior:
- inspect what tools, integrations, SDKs, frameworks, and plugins are available
- use relevant built-in capabilities before defaulting to manual workarounds
- install required project dependencies and plugins when needed for implementation, testing, validation, or observability
- use specialized tools for formatting, linting, typing, testing, migrations, schema validation, documentation generation, and deployment when appropriate
- record major tool/plugin choices in `state/DECISION_LOG.md` and `state/CHANGELOG.md`

The agent must not:
- ignore a clearly useful tool and replace it with a fragile manual workaround
- skip validation tools that would improve correctness
- keep tool decisions undocumented when they materially affect the build

Operational rule:
When starting or resuming work, the agent should quickly evaluate whether any relevant available tool or plugin should be used for the current task before proceeding.
