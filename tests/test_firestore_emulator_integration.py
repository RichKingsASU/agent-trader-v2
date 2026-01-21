from __future__ import annotations

import os
import uuid

import pytest
try:
    from google.cloud import firestore
except Exception as e:  # pragma: no cover
    pytestmark = pytest.mark.xfail(
        reason=f"Optional dependency for Firestore emulator tests missing: {type(e).__name__}: {e}",
        strict=False,
    )


def test_firestore_emulator_roundtrip() -> None:
    """
    Integration gate: verify our Firestore client stack can talk to the local emulator.

    This test is intended to run under:
      firebase-tools emulators:exec --only firestore ...
    """

    if not os.getenv("FIRESTORE_EMULATOR_HOST"):
        pytest.skip("FIRESTORE_EMULATOR_HOST is not set; run under Firestore emulator")

    project = (
        os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCLOUD_PROJECT")
        or os.getenv("GCP_PROJECT")
        or "demo-agenttrader-ci"
    )

    client = firestore.Client(project=project)
    doc_id = str(uuid.uuid4())
    ref = client.collection("ci_firestore_emulator").document(doc_id)

    ref.set({"ok": True, "n": 1, "doc_id": doc_id})
    snap = ref.get()

    assert snap.exists
    data = snap.to_dict() or {}
    assert data.get("ok") is True
    assert data.get("doc_id") == doc_id

