# ADR 0003: Early publication and cloud execution

- Status: Accepted
- Date: 2026-11-16
- Related: RFC 0001, ADR 0001, #12, #18, #29, #38, #47

## Context

RFC 0001 and ADR 0001 placed three steps in Phase 2 (Epic #8): making the
repository public, adding a ruleset on the default branch, and moving the coding
agent to cloud execution. During Phase 1 the local runner meant keeping the Mac on,
within the runner's time window, for an agent to pick up an Issue.

Cloud execution runs the coding agent in a cloud scheduled task triggered by label
events, with no local machine. It needs a ruleset on `main` (no deletion, no force
push, changes only through pull requests), and GitHub Free does not apply rulesets
to private repositories.

## Options

### Where the coding agent runs

- **Cloud execution on a public repository (chosen).** No local machine; a label
  starts work within a minute or two. Requires going public now.
- **Stay private with the local runner.** Nothing is public before Phase 2, but the
  Mac must be on and the runner only works in its time window.
- **A paid plan so that a private repository gets a ruleset.** Keeps the repository
  private with cloud execution, but adds a recurring cost for a toolkit that is
  meant to be public anyway.

### Deduplication when the same Issue is dispatched again

- **Compare only start comments after the latest `agent:ready` (chosen).**
- **The workflow template's rule as is:** stop if another session's start comment
  is within 30 minutes before one's own. A second dispatch within 30 minutes of the
  first was stopped by the first, already finished, session's comment.
- **Change `docs/workflow/agent-workflow.md` in this repository.** Fixes it here,
  but makes the file differ from the template and complicates later template
  upgrades.

## Decision

1. **The repository went public on 2026-11-16**, after the pre-publish checklist
   steps 2–4 found nothing, the MIT `LICENSE` was added in #18, and commits in this
   repository use a noreply email.
2. **Cloud execution (trial) replaces the local runner.** Two scheduled tasks:
   `mpc-code-agent-issue` (an Issue gets `agent:ready`) and `mpc-code-agent-fix`
   (a pull request gets `changes-requested`). `main` is protected by the ruleset
   `protect-default-branch`. Both triggers were tested: `agent:ready` on #13 and
   #20–#23, `changes-requested` on #31, #33 and #34. `AGENTS.md` lists the module
   since #38. The local runner stays available for manual use (`--now`) but has no
   schedule installed.
3. **Deduplication exception.** Before starting, a cloud session compares only the
   start comments posted after the latest `agent:ready` was added; earlier start
   comments belong to a previous dispatch. The exception is written in the prompts
   of both scheduled tasks, not in `docs/workflow/agent-workflow.md`. It is removed
   when the workflow template fixes the rule; the feedback has been passed on to the
   template.

## Consequences

Benefits:

- No local machine is needed. Dispatched Issues were picked up within one or two
  minutes, and change requests were handled in two to three minutes.
- Issues, pull requests and discussions are public from the start, so the
  community can trace how the toolkit was built.

Costs:

- Everything on GitHub is public: no emails, personal paths, or names of other
  projects or clients in Issues, pull requests, comments or commits.
- Cloud sessions have no local list of denied names; `check-sensitive.mjs` and a
  local pre-publish check catch what they can.
- Cloud sessions share the plan's usage quota with the decision centre's
  conversations.
- The scheduled-task prompts can only be edited by the decision maker in the web
  interface, so the deduplication exception lives outside the repository.

Follow-up work:

- Mark "Switch the repository to public" and "Add the default-branch ruleset and
  move to cloud execution" as done in Epic #8, with a link to this ADR.
- Remove the deduplication exception from both prompts once the template is fixed.
