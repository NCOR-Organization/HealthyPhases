<!-- fleet-ops:start -->
## Fleet working agreement
At the start of any task, read `.fleet/MISSION.md` — goals, authority, guardrails, prior
decisions, and the backlog. Treat it as the source of truth; its Authority & Guardrails
section is human-owned — never edit it. If you were started as a named agent and
`.fleet/agents/<name>.md` exists, that charter is your standing objective and scope —
read it next (charters are human-owned too). Check `.fleet/INBOX.md` for entries the human
has answered: apply the call, graduate it into the MISSION Decisions Log, and unblock
the backlog item. Skim `.fleet/JOURNAL.md` for recent work so you don't repeat or undo
it. Record progress in `.fleet/JOURNAL.md`; escalate only true ambiguity or red-line
items to `.fleet/INBOX.md` with a recommended default, then continue with the next
unblocked item. Partitioning: do code work on a task branch in a worktree under
`.fleet/worktrees/` — never in the primary checkout, which stays on the default branch
and carries the `.fleet/` state.
<!-- fleet-ops:end -->
