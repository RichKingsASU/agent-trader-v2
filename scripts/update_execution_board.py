#!/usr/bin/env python3
"""
Deterministic updater for ops/EXECUTION_BOARD.md.

Supported operations:
- Update a task by ID: --id AT-001 --status DONE [--evidence "..."]
- Suggest next tasks: --suggest-next

This script is intentionally dependency-free (stdlib only).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


BOARD_PATH = Path("ops/EXECUTION_BOARD.md")

TASKS_START = "<!-- TASKS_START -->"
TASKS_END = "<!-- TASKS_END -->"

ALLOWED_STATUSES = {"TODO", "IN_PROGRESS", "BLOCKED", "DONE"}


@dataclass(frozen=True)
class TaskRow:
    line_index: int
    cells: List[str]

    @property
    def id(self) -> str:
        return self.cells[0]

    @property
    def tier(self) -> str:
        return self.cells[1]

    @property
    def status(self) -> str:
        return self.cells[4]

    @property
    def dependencies(self) -> str:
        return self.cells[5]


def _die(msg: str, code: int = 2) -> "None":
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _read_text(path: Path) -> Tuple[str, List[str]]:
    if not path.exists():
        _die(f"missing board file: {path}")
    text = path.read_text(encoding="utf-8")
    # Preserve original newline style as much as practical.
    lines = text.splitlines(keepends=True)
    return text, lines


def _find_region(lines: Sequence[str], start_marker: str, end_marker: str) -> Tuple[int, int]:
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if start_marker in line:
            start_idx = i
        if end_marker in line:
            end_idx = i
    if start_idx is None or end_idx is None:
        _die(f"could not find task table markers {start_marker!r} and {end_marker!r}")
    if end_idx <= start_idx:
        _die("task table markers are out of order")
    return start_idx, end_idx


def _is_separator_row(line: str) -> bool:
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return False
    # A markdown separator row is basically pipes and dashes.
    inner = s.strip("|").replace(" ", "")
    return inner and all(ch in "-|:" for ch in inner)


def _parse_table_row(line: str) -> List[str]:
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        _die(f"malformed table row (expected leading/trailing '|'): {line.rstrip()}")
    parts = [p.strip() for p in s.strip("|").split("|")]
    return parts


def _format_table_row(cells: Sequence[str], newline: str) -> str:
    # Deterministic spacing: single spaces around cell content.
    return "| " + " | ".join(cells) + " |" + newline


def _load_tasks(lines: List[str], start_idx: int, end_idx: int) -> Tuple[List[str], Dict[str, TaskRow], List[str]]:
    """
    Returns: (header_cells, tasks_by_id, ordered_ids)
    """
    header_cells: Optional[List[str]] = None
    tasks_by_id: Dict[str, TaskRow] = {}
    ordered_ids: List[str] = []

    for i in range(start_idx + 1, end_idx):
        line = lines[i]
        if not line.lstrip().startswith("|"):
            continue
        if _is_separator_row(line):
            continue

        cells = _parse_table_row(line)
        if header_cells is None:
            header_cells = cells
            continue

        if len(cells) != len(header_cells):
            _die(
                f"row column count mismatch at line {i + 1}: "
                f"expected {len(header_cells)} got {len(cells)}"
            )

        task_id = cells[0]
        if task_id in tasks_by_id:
            _die(f"duplicate task id {task_id!r} at line {i + 1}")

        tasks_by_id[task_id] = TaskRow(line_index=i, cells=cells)
        ordered_ids.append(task_id)

    if header_cells is None:
        _die("could not find task table header row")

    return header_cells, tasks_by_id, ordered_ids


def _parse_deps(dep_cell: str) -> List[str]:
    dep_cell = dep_cell.strip()
    if not dep_cell or dep_cell == "-":
        return []
    return [d.strip() for d in dep_cell.split(",") if d.strip()]


def _tier_sort_key(tier_value: str) -> Tuple[int, str]:
    # Prefer numeric tiers (1/2/3), fall back to lexical.
    try:
        return (int(tier_value), tier_value)
    except ValueError:
        return (999, tier_value)


def suggest_next(tasks_by_id: Dict[str, TaskRow]) -> List[TaskRow]:
    # Validate dependency references.
    for t in tasks_by_id.values():
        for dep in _parse_deps(t.dependencies):
            if dep not in tasks_by_id:
                _die(f"task {t.id} depends on unknown id {dep}")

    candidates: List[TaskRow] = []
    for t in tasks_by_id.values():
        if t.status != "TODO":
            continue
        deps = _parse_deps(t.dependencies)
        if all(tasks_by_id[d].status == "DONE" for d in deps):
            candidates.append(t)

    candidates.sort(key=lambda t: (_tier_sort_key(t.tier), t.id))
    return candidates


def update_task_line(
    lines: List[str],
    header_cells: List[str],
    tasks_by_id: Dict[str, TaskRow],
    task_id: str,
    new_status: str,
    evidence: Optional[str],
) -> None:
    if task_id not in tasks_by_id:
        _die(f"unknown task id: {task_id}")
    if new_status not in ALLOWED_STATUSES:
        _die(f"invalid status {new_status!r}; allowed: {', '.join(sorted(ALLOWED_STATUSES))}")

    task = tasks_by_id[task_id]
    cells = list(task.cells)

    # Required update
    cells[4] = new_status

    # Optional evidence update
    if evidence is not None:
        ev = evidence.strip()
        if ev == "-":
            cells[7] = "-"
        elif ev:
            existing = cells[7].strip()
            if not existing or existing == "-":
                cells[7] = ev
            elif ev not in existing:
                cells[7] = f"{existing}; {ev}"

    # Preserve the newline style of the original line.
    newline = "\n"
    if lines[task.line_index].endswith("\r\n"):
        newline = "\r\n"
    elif lines[task.line_index].endswith("\n"):
        newline = "\n"
    else:
        newline = ""

    lines[task.line_index] = _format_table_row(cells, newline)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Update ops/EXECUTION_BOARD.md deterministically.")
    parser.add_argument(
        "--board",
        default=str(BOARD_PATH),
        help="Path to execution board markdown (default: ops/EXECUTION_BOARD.md).",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--suggest-next", action="store_true", help="Print dependency-satisfied TODO tasks.")
    group.add_argument("--id", help="Task ID to update (e.g., AT-001).")

    parser.add_argument("--status", choices=sorted(ALLOWED_STATUSES), help="New status for the task.")
    parser.add_argument("--evidence", help="Evidence to append/set (file path, PR link, artifact).")

    args = parser.parse_args(argv)

    board_path = Path(args.board)
    _, lines = _read_text(board_path)
    start_idx, end_idx = _find_region(lines, TASKS_START, TASKS_END)
    header_cells, tasks_by_id, _ = _load_tasks(lines, start_idx, end_idx)

    if args.suggest_next:
        next_tasks = suggest_next(tasks_by_id)
        if not next_tasks:
            print("No eligible TODO tasks (all TODOs are blocked by dependencies or already in progress).")
            return 0
        for t in next_tasks:
            deps = _parse_deps(t.dependencies)
            dep_str = ", ".join(deps) if deps else "-"
            print(f"{t.id} (Tier {t.tier}) — deps: {dep_str}")
        return 0

    # Update mode
    if not args.status:
        _die("--status is required when using --id")
    update_task_line(
        lines=lines,
        header_cells=header_cells,
        tasks_by_id=tasks_by_id,
        task_id=args.id,
        new_status=args.status,
        evidence=args.evidence,
    )
    board_path.write_text("".join(lines), encoding="utf-8")
    print(f"Updated {args.id}: status={args.status}" + (f", evidence={args.evidence!r}" if args.evidence else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

