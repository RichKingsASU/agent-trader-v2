from __future__ import annotations

import unittest
from pathlib import Path


class TestOperationalReadinessArtifacts(unittest.TestCase):
    """
    Guardrail: ensure required operational readiness artifacts exist and retain
    the critical sections/links that operators rely on.
    """

    @property
    def repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _read(self, rel: str) -> str:
        p = self.repo_root / rel
        self.assertTrue(p.exists(), f"Missing required artifact: {rel}")
        data = p.read_text(encoding="utf-8")
        self.assertTrue(data.strip(), f"Artifact is empty: {rel}")
        return data

    def test_required_artifact_files_exist(self) -> None:
        required = [
            "DEPLOYMENT.md",
            "RUNBOOK.md",
            "docs/KILL_SWITCH.md",
            "docs/INGEST_ENABLED_KILL_SWITCH_FLOW.md",
            "docs/ops/rollback.md",
            "docs/ops/incident_response.md",
            "docs/ops/runbooks/paper_trading.md",
            "docs/ops/runbooks/live_trading.md",
        ]
        for rel in required:
            with self.subTest(rel=rel):
                p = self.repo_root / rel
                self.assertTrue(p.exists(), f"Missing required artifact: {rel}")
                self.assertTrue(p.is_file(), f"Required artifact is not a file: {rel}")

    def test_deployment_doc_links_rollbacks_killswitch_runbooks(self) -> None:
        txt = self._read("DEPLOYMENT.md")
        self.assertIn("Rollback", txt)
        self.assertIn("docs/ops/rollback.md", txt)
        self.assertIn("docs/KILL_SWITCH.md", txt)
        self.assertIn("docs/INGEST_ENABLED_KILL_SWITCH_FLOW.md", txt)
        self.assertIn("docs/ops/runbooks/paper_trading.md", txt)
        self.assertIn("docs/ops/runbooks/live_trading.md", txt)
        self.assertIn("docs/ops/incident_response.md", txt)

    def test_root_runbook_mentions_paper_vs_live_separation(self) -> None:
        txt = self._read("RUNBOOK.md")
        self.assertIn("Paper vs Live", txt)
        self.assertIn("docs/ops/runbooks/paper_trading.md", txt)
        self.assertIn("docs/ops/runbooks/live_trading.md", txt)

    def test_kill_switch_docs_have_required_controls(self) -> None:
        txt = self._read("docs/KILL_SWITCH.md")
        self.assertIn("EXECUTION_HALTED", txt)
        self.assertIn("EXECUTION_HALTED_FILE", txt)

        ingest = self._read("docs/INGEST_ENABLED_KILL_SWITCH_FLOW.md")
        self.assertIn("INGEST_ENABLED", ingest)

    def test_rollback_doc_mentions_k8s_lkg_and_cloud_run(self) -> None:
        txt = self._read("docs/ops/rollback.md")
        self.assertIn("Kubernetes rollback", txt)
        self.assertIn("restore_lkg.sh", txt)
        self.assertIn("Cloud Run rollback", txt)

    def test_incident_response_doc_links_primary_runbooks(self) -> None:
        txt = self._read("docs/ops/incident_response.md")
        self.assertIn("RUNBOOK.md", txt)
        self.assertIn("docs/ops/rollback.md", txt)
        self.assertIn("docs/KILL_SWITCH.md", txt)

    def test_paper_vs_live_runbooks_are_distinct(self) -> None:
        paper = self._read("docs/ops/runbooks/paper_trading.md")
        live = self._read("docs/ops/runbooks/live_trading.md")

        self.assertIn("observe-only", paper.lower())
        self.assertIn("controlled unlock", live.lower())
        self.assertNotEqual(paper.strip(), live.strip(), "Paper and live runbooks must be separate documents.")

