from __future__ import annotations

import logging
from typing import Iterable, Optional

from backend.persistence.firebase_client import get_firestore_client
from backend.persistence.firestore_retry import with_firestore_retry

from .models import NewsFeatureRecord

logger = logging.getLogger(__name__)


def write_feature_records(
    records: Iterable[NewsFeatureRecord],
    *,
    project_id: Optional[str] = None,
    collection: str = "news_features",
    merge: bool = True,
) -> int:
    """
    Persist feature records to Firestore.

    Storage format:
      {collection}/{feature_id}

    Deterministic ids make this idempotent.
    """
    recs = list(records)
    if not recs:
        return 0
    db = get_firestore_client(project_id=project_id)
    col = db.collection(collection)

    def _commit():
        batch = db.batch()
        for r in recs:
            batch.set(col.document(r.feature_id), r.to_dict(), merge=merge)
        return batch.commit()

    with_firestore_retry(_commit)
    logger.info("news_analysis: wrote %s feature records to %s", len(recs), collection)
    return len(recs)

