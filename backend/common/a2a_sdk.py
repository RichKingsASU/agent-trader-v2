import httpx
from typing import Any, Dict, Optional

class RiskAgentClient:
    """A client for communicating with the Risk Agent service."""

    def __init__(self, base_url: str):
        self._base_url = base_url

    async def check_trade(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Sends a trade check request to the Risk Agent.

        Args:
            payload: The trade check payload.

        Returns:
            The risk check result from the Risk Agent.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{self._base_url}/risk/check-trade", json=payload)
            response.raise_for_status()
            return response.json()

# You can add similar clients for other agents here.
