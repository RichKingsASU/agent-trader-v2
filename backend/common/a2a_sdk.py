from __future__ import annotations

from typing import Optional

import httpx

from backend.contracts.risk import RiskCheckResult, TradeCheckRequest

class RiskAgentClient:
    """A client for communicating with the Risk Agent service."""

    def __init__(self, base_url: str):
        self._base_url = base_url

    async def check_trade(
        self,
        payload: TradeCheckRequest,
        *,
        authorization: Optional[str] = None,
        timeout_s: float = 10.0,
    ) -> RiskCheckResult:
        """
        Sends a trade check request to the Risk Agent.

        Contract:
        - Request/response MUST conform to `backend.contracts.risk`.
        - Callers should pass through an Authorization header when available.
        """
        headers: dict[str, str] = {}
        auth = str(authorization or "").strip()
        if auth:
            headers["Authorization"] = auth

        async with httpx.AsyncClient(headers=headers) as client:
            response = await client.post(
                f"{self._base_url}/risk/check-trade",
                json=payload.model_dump(mode="json"),
                timeout=float(timeout_s),
            )
            response.raise_for_status()
            decoded = response.json()
            return RiskCheckResult.model_validate(decoded)

# You can add similar clients for other agents here.


class RiskAgentSyncClient:
    """
    Synchronous variant for non-async call sites.
    """

    def __init__(self, base_url: str):
        self._base_url = base_url

    def check_trade(
        self,
        payload: TradeCheckRequest,
        *,
        authorization: Optional[str] = None,
        timeout_s: float = 10.0,
    ) -> RiskCheckResult:
        headers: dict[str, str] = {}
        auth = str(authorization or "").strip()
        if auth:
            headers["Authorization"] = auth

        with httpx.Client(headers=headers) as client:
            response = client.post(
                f"{self._base_url}/risk/check-trade",
                json=payload.model_dump(mode="json"),
                timeout=float(timeout_s),
            )
            response.raise_for_status()
            return RiskCheckResult.model_validate(response.json())
