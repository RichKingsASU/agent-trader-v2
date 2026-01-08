"""
Firebase Callable Function for Historical Backtesting.

This module provides a Cloud Function endpoint for running backtests
on trading strategies using historical data.
"""

import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict

import firebase_admin
from firebase_admin import firestore
from firebase_functions import https_fn, options

logger = logging.getLogger(__name__)


def _get_firestore() -> firestore.Client:
    """Get Firestore client, initializing Firebase if needed."""
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    return firestore.client()


def _get_user_alpaca_keys(db: firestore.Client, user_id: str) -> Dict[str, str]:
    """
    Fetch user-specific Alpaca API keys from Firestore.
    
    Returns:
        Dict with key_id, secret_key, and base_url
    
    Raises:
        ValueError if keys are not configured
    """
    try:
        secrets_ref = db.collection("users").document(user_id).collection("secrets").document("alpaca")
        secrets_doc = secrets_ref.get()
        
        if not secrets_doc.exists:
            raise ValueError(f"No Alpaca keys configured for user {user_id}")
        
        secrets = secrets_doc.to_dict() or {}
        key_id = secrets.get("key_id") or secrets.get("api_key_id")
        secret_key = secrets.get("secret_key") or secrets.get("api_secret_key")
        base_url = secrets.get("base_url", "https://api.alpaca.markets")
        
        if not key_id or not secret_key:
            raise ValueError(f"Incomplete Alpaca keys for user {user_id}")
        
        return {
            "key_id": key_id,
            "secret_key": secret_key,
            "base_url": base_url
        }
    except Exception as e:
        logger.error(f"Error fetching Alpaca keys for user {user_id}: {e}")
        raise


@https_fn.on_call(
    cors=options.CorsOptions(cors_origins="*", cors_methods=["POST"]),
    secrets=["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"]
)
def run_backtest(req: https_fn.CallableRequest) -> Dict[str, Any]:
    """
    Run a historical backtest on a trading strategy.
    
    This function:
    1. Validates user authentication
    2. Loads the specified strategy
    3. Fetches historical data from Alpaca
    4. Runs the backtest simulation
    5. Calculates performance metrics
    6. Saves results to Firestore
    7. Returns comprehensive backtest results
    
    Usage from frontend:
        const runBacktest = httpsCallable(functions, 'run_backtest');
        const result = await runBacktest({ 
            strategy: "GammaScalper",
            config: { threshold: 0.15 },
            backtest_config: {
                symbol: "SPY",
                lookback_days: 30,
                start_capital: 100000
            }
        });
    
    Args:
        req: Callable request with required data:
            - strategy: Strategy class name (e.g., "GammaScalper")
            - config: Strategy configuration dict (optional)
            - backtest_config: Backtest parameters (optional)
                - symbol: Stock symbol (default: "SPY")
                - lookback_days: Days of historical data (default: 30)
                - start_capital: Starting capital (default: 100000)
                - slippage_bps: Slippage in basis points (default: 1)
                - regime: Market regime to test (optional)
    
    Returns:
        Dictionary with backtest results, metrics, and equity curve
    """
    # Require authentication
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Authentication required",
        )
    
    user_id = req.auth.uid
    
    try:
        logger.info(f"User {user_id}: Starting backtest...")
        
        # Parse request data
        data = req.data or {}
        strategy_name = data.get("strategy")
        strategy_config = data.get("config", {})
        backtest_config_dict = data.get("backtest_config", {})
        
        if not strategy_name:
            raise https_fn.HttpsError(
                code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
                message="'strategy' parameter is required",
            )
        
        # Import strategy modules
        from strategies.loader import instantiate_strategy
        from strategies.backtester import Backtester, BacktestConfig
        from strategies.metrics_calculator import MetricsCalculator
        
        # Instantiate strategy
        try:
            strategy = instantiate_strategy(
                strategy_name=strategy_name,
                name=f"{strategy_name}_backtest",
                config=strategy_config
            )
            logger.info(f"Loaded strategy: {strategy_name}")
        except ValueError as e:
            raise https_fn.HttpsError(
                code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
                message=str(e),
            )
        
        # Create backtest configuration
        config = BacktestConfig(
            symbol=backtest_config_dict.get("symbol", "SPY"),
            start_capital=Decimal(str(backtest_config_dict.get("start_capital", 100000))),
            lookback_days=backtest_config_dict.get("lookback_days", 30),
            slippage_bps=backtest_config_dict.get("slippage_bps", 1)
        )
        
        # Get Alpaca credentials
        alpaca_key = os.environ.get("APCA_API_KEY_ID")
        alpaca_secret = os.environ.get("APCA_API_SECRET_KEY")
        
        if not alpaca_key or not alpaca_secret:
            # Try to get user-specific keys from Firestore
            db = _get_firestore()
            try:
                keys = _get_user_alpaca_keys(db, user_id)
                alpaca_key = keys["key_id"]
                alpaca_secret = keys["secret_key"]
                logger.info(f"Using user-specific Alpaca keys for {user_id}")
            except ValueError:
                raise https_fn.HttpsError(
                    code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
                    message="Alpaca credentials not configured. Please configure your API keys in Settings.",
                )
        
        # Create backtester
        backtester = Backtester(
            strategy=strategy,
            config=config,
            alpaca_api_key=alpaca_key,
            alpaca_secret_key=alpaca_secret
        )
        
        logger.info(f"Running backtest for {config.lookback_days} days on {config.symbol}...")
        
        # Run backtest
        regime = backtest_config_dict.get("regime")
        results = backtester.run(regime=regime)
        
        # Calculate performance metrics
        logger.info("Calculating performance metrics...")
        metrics_calc = MetricsCalculator()
        
        # Convert equity curve for metrics calculation
        equity_curve_tuples = [
            (datetime.fromisoformat(point["timestamp"]), Decimal(str(point["equity"])))
            for point in results["equity_curve"]
        ]
        
        metrics = metrics_calc.calculate_all_metrics(
            equity_curve=equity_curve_tuples,
            trades=results["trades"],
            start_capital=config.start_capital
        )
        
        # Format metrics report
        report = metrics_calc.format_metrics_report(metrics)
        logger.info(f"\n{report}")
        
        # Prepare response
        response = {
            "success": True,
            "backtest_id": f"{user_id}_{strategy_name}_{int(datetime.now().timestamp())}",
            "strategy": strategy_name,
            "config": {
                "symbol": config.symbol,
                "start_capital": float(config.start_capital),
                "lookback_days": config.lookback_days,
                "slippage_bps": config.slippage_bps,
                "regime": regime
            },
            "results": results,
            "metrics": metrics,
            "report": report
        }
        
        # Save backtest results to Firestore
        db = _get_firestore()
        backtest_ref = (
            db.collection("users")
            .document(user_id)
            .collection("backtests")
            .add({
                "strategy": strategy_name,
                "strategy_config": strategy_config,
                "backtest_config": {
                    "symbol": config.symbol,
                    "start_capital": str(config.start_capital),
                    "lookback_days": config.lookback_days,
                    "slippage_bps": config.slippage_bps,
                    "regime": regime
                },
                "metrics": metrics,
                "final_equity": float(config.start_capital) + metrics["net_profit"],
                "total_return_pct": metrics["total_return_pct"],
                "sharpe_ratio": metrics["sharpe_ratio"],
                "max_drawdown_pct": metrics["max_drawdown_pct"],
                "win_rate_pct": metrics["win_rate_pct"],
                "total_trades": metrics["total_trades"],
                "created_at": firestore.SERVER_TIMESTAMP,
                "status": "completed"
            })
        )
        
        response["firestore_id"] = backtest_ref[1].id
        
        logger.info(f"User {user_id}: Backtest completed successfully. ID: {backtest_ref[1].id}")
        
        return response
        
    except https_fn.HttpsError:
        raise
    except Exception as e:
        logger.exception(f"User {user_id}: Error running backtest: {e}")
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INTERNAL,
            message=f"Backtest failed: {str(e)}",
        )
