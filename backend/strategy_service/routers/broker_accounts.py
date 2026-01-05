from fastapi import APIRouter, Request
from typing import List
from uuid import UUID

from ..db import get_db
from backend.tenancy.auth import get_tenant_context
from backend.tenancy.context import TenantContext
from backend.tenancy.paths import tenant_collection

router = APIRouter(prefix="/broker-accounts", tags=["broker-accounts"])

COLLECTION_BROKER_ACCOUNTS = "broker_accounts"


@router.get("/", response_model=List[dict])
def list_broker_accounts(request: Request):
    ctx: TenantContext = get_tenant_context(request)
    db = get_db()
    rows: list[dict] = []
    q = tenant_collection(
        db, tenant_id=ctx.tenant_id, collection_name=COLLECTION_BROKER_ACCOUNTS
    ).where("uid", "==", ctx.uid)
    for doc in q.stream():
        d = doc.to_dict() or {}
        d["id"] = d.get("id") or doc.id
        rows.append(d)
    return rows
