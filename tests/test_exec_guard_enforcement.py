from __future__ import annotations

from pathlib import Path

import scripts.lib.exec_guard as exec_guard


def test_high_and_must_lock_scripts_invoke_guard_exactly_once():
    repo_root = Path(__file__).resolve().parents[1]

    missing: list[str] = []
    bad_count: list[str] = []

    needle = "enforce_execution_policy(__file__, sys.argv)"

    for rel in exec_guard.iter_guarded_scripts():
        path = repo_root / rel
        assert path.exists(), f"guarded script missing from repo: {rel}"

        txt = path.read_text(encoding="utf-8", errors="replace")
        count = txt.count(needle)
        if count == 0:
            missing.append(rel)
        elif count != 1:
            bad_count.append(f"{rel} (count={count})")

        # Ensure we import the guard module (contract requirement).
        assert "import scripts.lib.exec_guard" in txt, f"{rel} must import scripts.lib.exec_guard"

    assert not missing, f"Missing exec_guard invocation in: {missing}"
    assert not bad_count, f"exec_guard invocation count != 1 in: {bad_count}"

