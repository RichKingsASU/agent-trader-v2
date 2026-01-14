"""
Analytics API endpoints for trade analysis and system monitoring.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from backend.analytics.trade_parser import (
    compute_daily_pnl,
    compute_trade_analytics,
    compute_win_loss_ratio,
)
from backend.analytics.metrics import get_metrics_tracker
from backend.analytics.heartbeat import check_heartbeat
from backend.ledger.firestore import ledger_trades_collection
from backend.ledger.models import LedgerTrade


router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# Response models
class DailyPnLResponse(BaseModel):
    date: str
    total_pnl: float
    gross_pnl: float
    fees: float
    trades_count: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    symbols_traded: List[str]


class TradeAnalyticsResponse(BaseModel):
    daily_summaries: List[DailyPnLResponse]
    total_pnl: float
    total_trades: int
    overall_win_rate: float
    total_winning_trades: int
    total_losing_trades: int
    avg_daily_pnl: float
    best_day: Optional[DailyPnLResponse]
    worst_day: Optional[DailyPnLResponse]
    most_traded_symbols: List[tuple]
    max_drawdown_pct: float


class WinLossRatioResponse(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    loss_rate: float
    win_loss_ratio: float


class APILatencyResponse(BaseModel):
    service: str
    avg_ms: float
    min_ms: float
    max_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    count: int
    error_rate: float


class HeartbeatStatusResponse(BaseModel):
    service_id: str
    status: str
    last_heartbeat: Optional[str]
    seconds_since_heartbeat: Optional[float]
    is_stale: bool


class TokenUsageResponse(BaseModel):
    user_id: str
    total_requests: int
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    total_cost: float
    avg_tokens_per_request: float


class SystemHealthResponse(BaseModel):
    timestamp: str
    alpaca_latency: APILatencyResponse
    gemini_latency: APILatencyResponse
    heartbeat_status: HeartbeatStatusResponse
    token_usage_top_users: List[TokenUsageResponse]


class StressTestRequest(BaseModel):
    strategy_name: str = "sector_rotation"
    strategy_config: Optional[dict] = None
    num_simulations: int = 1000
    num_days: int = 252
    black_swan_probability: float = 0.10
    save_to_firestore: bool = True


class StressTestResponse(BaseModel):
    success: bool
    passes_stress_test: bool
    var_95: float
    var_99: float
    cvar_95: float
    survival_rate: float
    mean_sharpe: float
    worst_drawdown: float
    mean_return: float
    failure_reasons: List[str]
    report: dict
    timestamp: str


def get_tenant_id_from_header(tenant_id: Optional[str] = Query(None)) -> str:
    """Extract tenant ID from query parameter (in production, use auth token)"""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id query parameter required")
    return tenant_id


@router.get("/trade-analytics", response_model=TradeAnalyticsResponse)
async def get_trade_analytics(
    tenant_id: str = Depends(get_tenant_id_from_header),
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
):
    """
    Get comprehensive trade analytics including daily P&L and win/loss ratios.
    """
    try:
        # Fetch trades from Firestore
        trades_ref = ledger_trades_collection(tenant_id=tenant_id)
        start_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Query trades within date range
        docs = trades_ref.where("ts", ">=", start_date).stream()
        
        # Convert to LedgerTrade objects
        trades = []
        for doc in docs:
            data = doc.to_dict()
            trade = LedgerTrade(
                tenant_id=tenant_id,
                uid=data.get("uid", ""),
                strategy_id=data.get("strategy_id", ""),
                run_id=data.get("run_id", ""),
                symbol=data.get("symbol", ""),
                side=data.get("side", "buy"),
                qty=float(data.get("qty", 0)),
                price=float(data.get("price", 0)),
                ts=data.get("ts").to_datetime() if hasattr(data.get("ts"), 'to_datetime') else datetime.now(timezone.utc),
                fees=float(data.get("fees", 0)),
            )
            trades.append(trade)
        
        # Compute analytics
        analytics = compute_trade_analytics(trades, start_date=start_date)
        
        # Convert to response model
        daily_summaries = [
            DailyPnLResponse(**summary.__dict__) for summary in analytics.daily_summaries
        ]
        
        return TradeAnalyticsResponse(
            daily_summaries=daily_summaries,
            total_pnl=analytics.total_pnl,
            total_trades=analytics.total_trades,
            overall_win_rate=analytics.overall_win_rate,
            total_winning_trades=analytics.total_winning_trades,
            total_losing_trades=analytics.total_losing_trades,
            avg_daily_pnl=analytics.avg_daily_pnl,
            best_day=DailyPnLResponse(**analytics.best_day.__dict__) if analytics.best_day else None,
            worst_day=DailyPnLResponse(**analytics.worst_day.__dict__) if analytics.worst_day else None,
            most_traded_symbols=analytics.most_traded_symbols,
            max_drawdown_pct=analytics.max_drawdown_pct,
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compute analytics: {str(e)}")


@router.get("/win-loss-ratio", response_model=WinLossRatioResponse)
async def get_win_loss_ratio(
    tenant_id: str = Depends(get_tenant_id_from_header),
    days: int = Query(30, ge=1, le=365),
):
    """
    Get win/loss ratio and related metrics.
    """
    try:
        trades_ref = ledger_trades_collection(tenant_id=tenant_id)
        start_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        docs = trades_ref.where("ts", ">=", start_date).stream()
        
        trades = []
        for doc in docs:
            data = doc.to_dict()
            trade = LedgerTrade(
                tenant_id=tenant_id,
                uid=data.get("uid", ""),
                strategy_id=data.get("strategy_id", ""),
                run_id=data.get("run_id", ""),
                symbol=data.get("symbol", ""),
                side=data.get("side", "buy"),
                qty=float(data.get("qty", 0)),
                price=float(data.get("price", 0)),
                ts=data.get("ts").to_datetime() if hasattr(data.get("ts"), 'to_datetime') else datetime.now(timezone.utc),
                fees=float(data.get("fees", 0)),
            )
            trades.append(trade)
        
        result = compute_win_loss_ratio(trades)
        return WinLossRatioResponse(**result)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compute win/loss ratio: {str(e)}")


@router.get("/api-latency/{service}", response_model=APILatencyResponse)
async def get_api_latency(
    service: str,
    minutes: int = Query(15, ge=1, le=60),
):
    """
    Get API latency statistics for a service (alpaca or gemini).
    """
    tracker = get_metrics_tracker()
    stats = tracker.get_api_latency_stats(service, minutes=minutes)
    
    return APILatencyResponse(
        service=service,
        **stats,
    )


@router.get("/heartbeat/{service_id}", response_model=HeartbeatStatusResponse)
async def get_heartbeat_status(
    service_id: str,
    tenant_id: str = Depends(get_tenant_id_from_header),
):
    """
    Check heartbeat status for a service.
    """
    heartbeat = check_heartbeat(tenant_id, service_id)
    
    return HeartbeatStatusResponse(
        service_id=heartbeat.service_id,
        status=heartbeat.status,
        last_heartbeat=heartbeat.last_heartbeat.isoformat() if heartbeat.last_heartbeat else None,
        seconds_since_heartbeat=heartbeat.seconds_since_heartbeat,
        is_stale=heartbeat.is_stale,
    )


@router.get("/token-usage", response_model=TokenUsageResponse)
async def get_token_usage(
    user_id: str,
    hours: int = Query(24, ge=1, le=168),
):
    """
    Get token usage for a specific user.
    """
    tracker = get_metrics_tracker()
    usage = tracker.get_token_usage_by_user(user_id, hours=hours)
    
    return TokenUsageResponse(
        user_id=user_id,
        **usage,
    )


@router.get("/token-usage/all", response_model=List[TokenUsageResponse])
async def get_all_users_token_usage(
    hours: int = Query(24, ge=1, le=168),
):
    """
    Get token usage for all users, sorted by cost.
    """
    tracker = get_metrics_tracker()
    all_usage = tracker.get_all_users_token_usage(hours=hours)
    
    return [TokenUsageResponse(**usage) for usage in all_usage]


@router.get("/system-health", response_model=SystemHealthResponse)
async def get_system_health(
    tenant_id: str = Depends(get_tenant_id_from_header),
    service_id: str = Query("market_ingest", description="Service to check heartbeat"),
):
    """
    Get comprehensive system health metrics.
    """
    tracker = get_metrics_tracker()
    
    # Get API latencies
    alpaca_stats = tracker.get_api_latency_stats("alpaca", minutes=15)
    gemini_stats = tracker.get_api_latency_stats("gemini", minutes=15)
    
    # Get heartbeat status
    heartbeat = check_heartbeat(tenant_id, service_id)
    
    # Get top token users
    top_users = tracker.get_all_users_token_usage(hours=24)[:5]
    
    return SystemHealthResponse(
        timestamp=datetime.now(timezone.utc).isoformat(),
        alpaca_latency=APILatencyResponse(service="alpaca", **alpaca_stats),
        gemini_latency=APILatencyResponse(service="gemini", **gemini_stats),
        heartbeat_status=HeartbeatStatusResponse(
            service_id=heartbeat.service_id,
            status=heartbeat.status,
            last_heartbeat=heartbeat.last_heartbeat.isoformat() if heartbeat.last_heartbeat else None,
            seconds_since_heartbeat=heartbeat.seconds_since_heartbeat,
            is_stale=heartbeat.is_stale,
        ),
        token_usage_top_users=[TokenUsageResponse(**usage) for usage in top_users],
    )


@router.post("/stress-test", response_model=StressTestResponse)
async def run_stress_test_endpoint(
    request: StressTestRequest,
    tenant_id: str = Depends(get_tenant_id_from_header),
):
    """
    Run Monte Carlo stress test on a trading strategy.
    
    This endpoint generates 1,000+ market scenarios using Geometric Brownian Motion,
    injects Black Swan events, and calculates comprehensive risk metrics including:
    - Value at Risk (VaR) at 95% and 99% confidence
    - Conditional VaR (Expected Shortfall)
    - Maximum Drawdown
    - Sharpe Ratio
    - Recovery Time from drawdowns
    
    The stress test determines if the strategy is safe for live trading based on
    predefined failure criteria.
    """
    try:
        # Import stress test runner
        from functions.stress_test_runner import run_stress_test
        
        # Build simulation parameters
        simulation_params = {
            "num_simulations": request.num_simulations,
            "num_days": request.num_days,
            "black_swan_probability": request.black_swan_probability,
        }
        
        # Run stress test
        results = run_stress_test(
            strategy_name=request.strategy_name,
            strategy_config=request.strategy_config or {},
            simulation_params=simulation_params,
            save_to_firestore=request.save_to_firestore,
            tenant_id=tenant_id,
        )
        
        if not results.get("success"):
            raise HTTPException(
                status_code=500,
                detail=results.get("error", "Stress test failed")
            )
        
        # Extract risk metrics
        risk_metrics = results.get("risk_metrics", {})
        report = results.get("report", {})
        
        return StressTestResponse(
            success=True,
            passes_stress_test=risk_metrics.get("passes_stress_test", False),
            var_95=risk_metrics.get("var_95", 0.0),
            var_99=risk_metrics.get("var_99", 0.0),
            cvar_95=risk_metrics.get("cvar_95", 0.0),
            survival_rate=risk_metrics.get("survival_rate", 0.0),
            mean_sharpe=risk_metrics.get("mean_sharpe", 0.0),
            worst_drawdown=risk_metrics.get("worst_drawdown", 0.0),
            mean_return=risk_metrics.get("mean_return", 0.0),
            failure_reasons=risk_metrics.get("failure_reasons", []),
            report=report,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to run stress test: {str(e)}"
        )
