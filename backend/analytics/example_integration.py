"""
Example integration of analytics tracking with existing services.

This file demonstrates how to integrate the analytics engine with existing
Alpaca and Gemini API calls in the codebase.
"""

# Example 1: Integrating with alpaca_signal_trader.py
# ======================================================

"""
In backend/alpaca_signal_trader.py, add tracking to the signal generation:

```python
import time
from backend.analytics.integrations import record_gemini_call

def generate_ai_signal_with_affordability_gate(
    uid: str,
    tenant_id: str,
    symbol: str,
    market_quote: dict,
    ...
) -> Optional[TradeSignal]:
    # ... existing validation code ...
    
    # Track the Gemini API call
    start_time = time.time()
    success = False
    prompt_tokens = 0
    completion_tokens = 0
    
    try:
        # Build prompt
        prompt = build_ai_prompt(symbol, market_quote, ...)
        
        # Call Gemini
        response = model.generate_content(prompt, generation_config=config)
        
        # Extract token usage
        if hasattr(response, 'usage_metadata'):
            usage = response.usage_metadata
            prompt_tokens = getattr(usage, 'prompt_token_count', 0)
            completion_tokens = getattr(usage, 'candidates_token_count', 0)
        
        # Parse response
        signal = parse_signal_from_response(response)
        success = True
        
        # Record the successful call
        duration_ms = (time.time() - start_time) * 1000
        record_gemini_call(
            user_id=uid,
            endpoint="generate_signal",
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model="gemini-2.5-flash",
            request_type="signal_generation",
            success=True,
        )
        
        return signal
        
    except Exception as e:
        # Record the failed call
        duration_ms = (time.time() - start_time) * 1000
        record_gemini_call(
            user_id=uid,
            endpoint="generate_signal",
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model="gemini-2.5-flash",
            request_type="signal_generation",
            success=False,
            error_message=str(e),
        )
        raise
```
"""


# Example 2: Integrating with Alpaca REST API calls
# ===================================================

"""
In backend/brokers/alpaca/account_sync.py or similar:

```python
import time
from backend.analytics.integrations import record_alpaca_call

def get_account_info(api_key: str, api_secret: str) -> dict:
    from alpaca.trading.client import TradingClient
    
    client = TradingClient(api_key, api_secret)
    
    start_time = time.time()
    success = True
    
    try:
        account = client.get_account()
        duration_ms = (time.time() - start_time) * 1000
        
        record_alpaca_call(
            endpoint="/v2/account",
            duration_ms=duration_ms,
            success=True,
        )
        
        return account.dict()
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        
        record_alpaca_call(
            endpoint="/v2/account",
            duration_ms=duration_ms,
            success=False,
            error_message=str(e),
        )
        
        raise


def submit_order(client, symbol: str, qty: int, side: str) -> dict:
    start_time = time.time()
    
    try:
        order = client.submit_order(
            symbol=symbol,
            qty=qty,
            side=side,
            type="market",
            time_in_force="day",
        )
        
        duration_ms = (time.time() - start_time) * 1000
        record_alpaca_call(
            endpoint="/v2/orders",
            duration_ms=duration_ms,
            success=True,
        )
        
        return order.dict()
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        record_alpaca_call(
            endpoint="/v2/orders",
            duration_ms=duration_ms,
            success=False,
            error_message=str(e),
        )
        raise
```
"""


# Example 3: Adding heartbeat to market ingest service
# =====================================================

"""
In backend/ingestion/market_data_ingest.py or similar:

```python
from backend.analytics.heartbeat import write_heartbeat
import time
import threading

def run_market_ingest_loop(tenant_id: str):
    service_id = "market_ingest"
    shutdown_event = threading.Event()
    
    loop_iter = 0
    while not shutdown_event.is_set():
        loop_iter += 1
        try:
            # Fetch and process market data
            quotes = fetch_latest_quotes()
            write_quotes_to_firestore(quotes)
            
            # Write heartbeat
            write_heartbeat(
                tenant_id=tenant_id,
                service_id=service_id,
                status="running",
                metadata={
                    "quotes_processed": len(quotes),
                    "last_symbol": quotes[-1].symbol if quotes else None,
                }
            )
            
            shutdown_event.wait(timeout=30)  # Wait 30 seconds (interruptible)
            
        except Exception as e:
            # Write degraded status
            write_heartbeat(
                tenant_id=tenant_id,
                service_id=service_id,
                status="degraded",
                metadata={
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
            )
            
            shutdown_event.wait(timeout=30)
```
"""


# Example 4: Using decorators for cleaner code
# =============================================

"""
For new services, use decorators:

```python
from backend.analytics.integrations import track_alpaca_api, track_gemini_api

class AlpacaService:
    @track_alpaca_api("/v2/account")
    def get_account(self):
        return self.client.get_account()
    
    @track_alpaca_api("/v2/orders")
    def place_order(self, symbol: str, qty: int):
        return self.client.submit_order(
            symbol=symbol,
            qty=qty,
            side="buy",
            type="market",
            time_in_force="day",
        )


class GeminiService:
    @track_gemini_api(user_id="system", request_type="analysis")
    def analyze_market(self, market_data: dict):
        prompt = self.build_prompt(market_data)
        return self.model.generate_content(prompt)
    
    @track_gemini_api(user_id="system", request_type="signal_generation")
    def generate_signal(self, symbol: str, indicators: dict):
        prompt = self.build_signal_prompt(symbol, indicators)
        return self.model.generate_content(prompt)
```
"""


# Example 5: FastAPI middleware for automatic tracking
# ====================================================

"""
Add automatic tracking for all API endpoints:

```python
from fastapi import FastAPI, Request
import time
from backend.analytics.metrics import get_metrics_tracker

app = FastAPI()

@app.middleware("http")
async def track_request_metrics(request: Request, call_next):
    start_time = time.time()
    
    try:
        response = await call_next(request)
        duration_ms = (time.time() - start_time) * 1000
        
        # Record API endpoint latency
        tracker = get_metrics_tracker()
        tracker.record_api_call(
            service="api",
            endpoint=request.url.path,
            duration_ms=duration_ms,
            status="success" if response.status_code < 400 else "error",
        )
        
        return response
        
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        
        tracker = get_metrics_tracker()
        tracker.record_api_call(
            service="api",
            endpoint=request.url.path,
            duration_ms=duration_ms,
            status="error",
            error_message=str(e),
        )
        
        raise
```
"""


# Example 6: Scheduled analytics computation
# ===========================================

"""
Create a scheduled job to compute and cache daily analytics:

```python
from backend.analytics import compute_trade_analytics
from backend.ledger.firestore import ledger_trades_collection
from backend.ledger.models import LedgerTrade
from datetime import datetime, timezone, timedelta

def compute_and_cache_daily_analytics(tenant_id: str):
    '''Run this daily via Cloud Scheduler'''
    
    # Fetch yesterday's trades
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    start_of_day = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    
    # Query Firestore
    trades_ref = ledger_trades_collection(tenant_id=tenant_id)
    docs = trades_ref.where("ts", ">=", start_of_day).where("ts", "<", end_of_day).stream()
    
    # Convert to LedgerTrade objects
    trades = []
    for doc in docs:
        data = doc.to_dict()
        trade = LedgerTrade(
            tenant_id=tenant_id,
            uid=data["uid"],
            strategy_id=data["strategy_id"],
            run_id=data["run_id"],
            symbol=data["symbol"],
            side=data["side"],
            qty=float(data["qty"]),
            price=float(data["price"]),
            ts=data["ts"].to_datetime(),
            fees=float(data.get("fees", 0)),
        )
        trades.append(trade)
    
    # Compute analytics
    analytics = compute_trade_analytics(trades, start_date=start_of_day, end_date=end_of_day)
    
    # Cache results in Firestore
    from google.cloud import firestore
    db = firestore.Client()
    
    cache_doc = db.collection("tenants").document(tenant_id)\
                  .collection("analytics_cache")\
                  .document(start_of_day.strftime("%Y-%m-%d"))
    
    cache_doc.set({
        "date": start_of_day.strftime("%Y-%m-%d"),
        "total_pnl": analytics.total_pnl,
        "total_trades": analytics.total_trades,
        "win_rate": analytics.overall_win_rate,
        "computed_at": firestore.SERVER_TIMESTAMP,
    })
    
    print(f"Cached analytics for {start_of_day.strftime('%Y-%m-%d')}: ${analytics.total_pnl:.2f}")
```
"""


# Example 7: Real-time dashboard updates with WebSocket
# =====================================================

"""
For real-time monitoring, add WebSocket support:

```python
from fastapi import WebSocket, WebSocketDisconnect
from backend.analytics.metrics import get_metrics_tracker
import asyncio
import json

@app.websocket("/ws/system-health")
async def system_health_websocket(websocket: WebSocket, tenant_id: str):
    await websocket.accept()
    
    try:
        stop_event = asyncio.Event()
        loop_iter = 0
        while not stop_event.is_set():
            loop_iter += 1
            tracker = get_metrics_tracker()
            
            # Gather current metrics
            health_data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "alpaca_latency": tracker.get_api_latency_stats("alpaca", minutes=5),
                "gemini_latency": tracker.get_api_latency_stats("gemini", minutes=5),
                "heartbeat": check_heartbeat(tenant_id, "market_ingest").__dict__,
            }
            
            # Send to client
            await websocket.send_json(health_data)
            
            # Update every 5 seconds (shutdown-friendly).
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
            
    except WebSocketDisconnect:
        print(f"Client disconnected from system health feed")
```

Frontend usage:
```typescript
useEffect(() => {
  const ws = new WebSocket(`ws://localhost:8080/ws/system-health?tenant_id=${tenantId}`);
  
  ws.onmessage = (event) => {
    const healthData = JSON.parse(event.data);
    setSystemHealth(healthData);
  };
  
  return () => ws.close();
}, [tenantId]);
```
"""


# Example 8: Cost alerts and budget tracking
# ===========================================

"""
Add cost monitoring and alerts:

```python
from backend.analytics.metrics import get_metrics_tracker

def check_token_budget_alerts(tenant_id: str, monthly_budget_usd: float = 100.0):
    '''Check if token usage is approaching budget limits'''
    
    tracker = get_metrics_tracker()
    
    # Get all users for this tenant
    all_usage = tracker.get_all_users_token_usage(hours=24 * 30)  # Last 30 days
    
    # Sum total cost
    total_cost = sum(u["total_cost"] for u in all_usage)
    
    budget_pct = (total_cost / monthly_budget_usd) * 100
    
    if budget_pct > 90:
        send_alert(
            tenant_id=tenant_id,
            level="critical",
            message=f"Token budget at {budget_pct:.1f}% (${total_cost:.2f} / ${monthly_budget_usd:.2f})"
        )
    elif budget_pct > 75:
        send_alert(
            tenant_id=tenant_id,
            level="warning",
            message=f"Token budget at {budget_pct:.1f}% (${total_cost:.2f} / ${monthly_budget_usd:.2f})"
        )
    
    return {
        "total_cost": total_cost,
        "budget": monthly_budget_usd,
        "budget_pct": budget_pct,
        "status": "ok" if budget_pct < 75 else "warning" if budget_pct < 90 else "critical",
    }
```
"""


if __name__ == "__main__":
    print("This file contains example integrations for the analytics engine.")
    print("Copy the relevant examples into your actual service files.")
