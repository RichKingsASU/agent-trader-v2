# Execution Board (Institutional Hardening)

This repo tracks hardening work in `ops/EXECUTION_BOARD.md` as the single source of truth (no external SaaS required).

## Weekly standup (recommended cadence)
Use the board as the agenda:
- **Review summary**: confirm current Tier, manual % complete, and sprint goals.
- **Walk the board in order** (Tier → ID):
  - Confirm **DONE** tasks have evidence links.
  - For **IN_PROGRESS**, confirm owner and next action.
  - For **BLOCKED**, record the blocking dependency or decision needed.
- **Commit to the sprint**:
  - Pick the next 3–8 tasks that are eligible (dependencies satisfied).
  - Assign owners and define acceptance criteria if unclear.
- **Close-out**:
  - Update statuses + evidence links in the board.

## How to update task status
Use the helper script to update the board deterministically:

- Update a task to DONE with evidence:
  - `python scripts/update_execution_board.py --id AT-001 --status DONE --evidence "docs/agents.md"`

- Update a task to IN_PROGRESS (no evidence yet):
  - `python scripts/update_execution_board.py --id AT-002 --status IN_PROGRESS`

Notes:
- The updater **refuses unknown IDs**.
- Evidence is stored in the **Evidence** column (file paths, PR links, artifacts).
- To clear evidence, set it to `-`:
  - `python scripts/update_execution_board.py --id AT-001 --status TODO --evidence "-"`

## How agents should pick the next task (dependency-aware)
Agents should only pick tasks that are:
- **Status**: `TODO`
- **Dependencies**: all dependencies are `DONE`
- **Tier**: prefer Tier 1 first, then Tier 2, then Tier 3

To list eligible tasks:
- `python scripts/update_execution_board.py --suggest-next`

## Task writing standard
For new tasks or larger work items, use:
- `ops/templates/TASK_TEMPLATE.md`

Ensure each task has:
- Clear **acceptance criteria**
- Clear **verification steps**
- A safe **rollback plan**
- Evidence recorded in `ops/EXECUTION_BOARD.md`

