from __future__ import annotations

from google.cloud.firestore import Client


def tenant_doc(db: Client, tenant_id: str, *segments: str):
    """
    Build a tenant-scoped document reference.

    Example:
      tenant_doc(db, tenant_id="t1", "profiles", "uid123")
      => /tenants/t1/profiles/uid123
    """
    if not segments:
        raise ValueError("tenant_doc requires at least one path segment")
    return db.document(f"tenants/{tenant_id}/" + "/".join(segments))


def tenant_collection(db: Client, tenant_id: str, collection_name: str):
    """
    Build a tenant-scoped collection reference.

    Example:
      tenant_collection(db, tenant_id="t1", collection_name="strategies")
      => /tenants/t1/strategies
    """
    return db.collection("tenants").document(tenant_id).collection(collection_name)

