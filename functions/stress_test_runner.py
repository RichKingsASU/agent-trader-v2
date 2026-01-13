"""
Stress Test Runner

Provides an easy interface to run Monte Carlo stress tests on trading strategies.
Includes integration with Firestore for storing results and generating reports.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from functions.strategies.base_strategy import BaseStrategy
from functions.strategies.sector_rotation import SectorRotationStrategy
from functions.utils.monte_carlo import (
    MonteCarloSimulator,
    SimulationParameters,
    SimulationPath,
    RiskMetrics,
)

logger = logging.getLogger(__name__)


def run_stress_test(
    strategy_name: str = "sector_rotation",
    strategy_config: Optional[Dict[str, Any]] = None,
    simulation_params: Optional[Dict[str, Any]] = None,
    save_to_firestore: bool = False,
    tenant_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run a Monte Carlo stress test on a trading strategy.
    
    Args:
        strategy_name: Name of the strategy to test
        strategy_config: Configuration for the strategy
        simulation_params: Parameters for the Monte Carlo simulation
        save_to_firestore: Whether to save results to Firestore
        tenant_id: Tenant ID for multi-tenant deployments
        
    Returns:
        Dictionary with stress test results
    """
    logger.info(f"Starting stress test for strategy: {strategy_name}")
    
    # Load strategy
    strategy = _load_strategy(strategy_name, strategy_config or {})
    
    if not strategy:
        return {
            "success": False,
            "error": f"Unknown strategy: {strategy_name}",
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    # Create simulation parameters
    sim_params = SimulationParameters()
    
    if simulation_params:
        # Override defaults with provided parameters
        for key, value in simulation_params.items():
            if hasattr(sim_params, key):
                setattr(sim_params, key, value)
    
    # Create simulator
    simulator = MonteCarloSimulator(params=sim_params)
    
    # Run simulation
    logger.info(f"Running {sim_params.num_simulations} simulations over {sim_params.num_days} days...")
    
    try:
        paths, risk_metrics = simulator.simulate_strategy(
            strategy_evaluate_fn=strategy.evaluate,
            strategy_config=strategy_config or {},
            save_all_paths=False  # Save memory by not storing all path details
        )
        
        # Export results
        results = simulator.export_results(paths, risk_metrics)
        
        # Add strategy info
        results["strategy"] = {
            "name": strategy_name,
            "config": strategy_config or {},
            "class": strategy.__class__.__name__,
        }
        
        results["success"] = True
        
        # Generate summary report
        report = _generate_stress_test_report(risk_metrics, sim_params)
        results["report"] = report
        
        # Save to Firestore if requested
        if save_to_firestore:
            _save_to_firestore(results, tenant_id)
        
        logger.info(f"Stress test complete. Pass: {risk_metrics.passes_stress_test}")
        
        return results
    
    except Exception as e:
        logger.exception(f"Stress test failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


def _load_strategy(
    strategy_name: str,
    config: Dict[str, Any]
) -> Optional[BaseStrategy]:
    """Load a strategy by name."""
    strategies = {
        "sector_rotation": SectorRotationStrategy,
    }
    
    strategy_class = strategies.get(strategy_name)
    
    if strategy_class:
        return strategy_class(config=config)
    
    return None


def _generate_stress_test_report(
    risk_metrics: RiskMetrics,
    params: SimulationParameters
) -> Dict[str, Any]:
    """
    Generate a human-readable stress test report.
    
    Args:
        risk_metrics: Risk metrics from simulation
        params: Simulation parameters
        
    Returns:
        Report dictionary
    """
    # Pass/Fail status
    status = "✅ PASS" if risk_metrics.passes_stress_test else "❌ FAIL"
    
    # Build detailed report
    report = {
        "status": status,
        "passes_stress_test": risk_metrics.passes_stress_test,
        "timestamp": datetime.utcnow().isoformat(),
        
        # Risk metrics
        "risk_summary": {
            "var_95": {
                "value": f"{risk_metrics.var_95:.2%}",
                "limit": f"{params.max_var_95:.2%}",
                "pass": risk_metrics.var_95 <= params.max_var_95,
            },
            "var_99": {
                "value": f"{risk_metrics.var_99:.2%}",
            },
            "cvar_95": {
                "value": f"{risk_metrics.cvar_95:.2%}",
                "description": "Average loss in worst 5% of scenarios"
            },
            "survival_rate": {
                "value": f"{risk_metrics.survival_rate:.2%}",
                "limit": f"{params.min_survival_rate:.2%}",
                "pass": risk_metrics.survival_rate >= params.min_survival_rate,
            },
            "max_drawdown": {
                "value": f"{risk_metrics.worst_drawdown:.2%}",
                "limit": f"{params.max_drawdown:.2%}",
                "pass": risk_metrics.worst_drawdown <= params.max_drawdown,
            },
            "sharpe_ratio": {
                "mean": f"{risk_metrics.mean_sharpe:.2f}",
                "median": f"{risk_metrics.median_sharpe:.2f}",
                "limit": f"{params.min_sharpe:.2f}",
                "pass": risk_metrics.mean_sharpe >= params.min_sharpe,
            },
        },
        
        # Performance summary
        "performance_summary": {
            "mean_return": f"{risk_metrics.mean_return:.2%}",
            "median_return": f"{risk_metrics.median_return:.2%}",
            "return_volatility": f"{risk_metrics.std_return:.2%}",
            "mean_drawdown": f"{risk_metrics.mean_max_drawdown:.2%}",
        },
        
        # Recovery metrics
        "recovery_summary": {
            "mean_recovery_days": risk_metrics.mean_recovery_days,
            "median_recovery_days": risk_metrics.median_recovery_days,
            "paths_without_recovery": risk_metrics.paths_without_recovery,
        },
        
        # Distribution
        "final_equity_percentiles": risk_metrics.final_equity_distribution,
        
        # Failure reasons (if any)
        "failure_reasons": risk_metrics.failure_reasons,
        
        # Interpretation
        "interpretation": _interpret_results(risk_metrics, params),
    }
    
    return report


def _interpret_results(
    risk_metrics: RiskMetrics,
    params: SimulationParameters
) -> str:
    """Generate a plain-English interpretation of the stress test results."""
    
    if risk_metrics.passes_stress_test:
        interpretation = (
            f"✅ The strategy PASSES all stress test criteria. "
            f"In the worst 5% of scenarios, losses are limited to {risk_metrics.var_95:.1%}, "
            f"which is within the acceptable threshold of {params.max_var_95:.1%}. "
            f"The strategy survives in {risk_metrics.survival_rate:.1%} of paths with a "
            f"mean Sharpe ratio of {risk_metrics.mean_sharpe:.2f}. "
            f"Maximum observed drawdown is {risk_metrics.worst_drawdown:.1%}, "
            f"below the {params.max_drawdown:.1%} limit."
        )
    else:
        interpretation = (
            f"❌ The strategy FAILS stress test criteria. "
            f"Failure reasons: {'; '.join(risk_metrics.failure_reasons)}. "
            f"This strategy requires refinement before live trading."
        )
    
    # Add recovery analysis
    if risk_metrics.mean_recovery_days:
        interpretation += (
            f" On average, the strategy recovers from drawdowns in "
            f"{risk_metrics.mean_recovery_days:.0f} trading days."
        )
    
    return interpretation


def _save_to_firestore(
    results: Dict[str, Any],
    tenant_id: Optional[str] = None
) -> None:
    """
    Save stress test results to Firestore.
    
    Args:
        results: Stress test results
        tenant_id: Tenant ID (optional)
    """
    try:
        from google.cloud import firestore

        from functions.utils.firestore_guard import require_firestore_emulator_or_allow_prod
        require_firestore_emulator_or_allow_prod(caller="functions.stress_test_runner._save_to_firestore")

        db = firestore.Client()
        
        # Determine collection path
        if tenant_id:
            collection_path = f"tenants/{tenant_id}/stress_tests"
        else:
            collection_path = "stress_tests"
        
        # Create document ID from timestamp and strategy
        timestamp = results.get("metadata", {}).get("simulation_timestamp", "")
        strategy_name = results.get("strategy", {}).get("name", "unknown")
        doc_id = f"{strategy_name}_{timestamp}"
        
        # Save to Firestore
        db.collection(collection_path).document(doc_id).set(results)
        
        logger.info(f"Stress test results saved to Firestore: {collection_path}/{doc_id}")
    
    except Exception as e:
        logger.exception(f"Failed to save stress test results to Firestore: {e}")


def generate_stress_test_html_report(
    risk_metrics: RiskMetrics,
    params: SimulationParameters
) -> str:
    """
    Generate an HTML report for stress test results.
    
    Args:
        risk_metrics: Risk metrics from simulation
        params: Simulation parameters
        
    Returns:
        HTML string
    """
    report = _generate_stress_test_report(risk_metrics, params)
    
    # Build HTML
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Stress Test Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; }}
            h1 {{ color: #333; }}
            .pass {{ color: green; font-weight: bold; }}
            .fail {{ color: red; font-weight: bold; }}
            .metric {{ margin: 20px 0; padding: 15px; background: #f5f5f5; border-radius: 5px; }}
            .metric-name {{ font-weight: bold; color: #666; }}
            .metric-value {{ font-size: 1.2em; color: #333; }}
            table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
            th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
            th {{ background-color: #4CAF50; color: white; }}
        </style>
    </head>
    <body>
        <h1>Monte Carlo Stress Test Report</h1>
        <p class="{'pass' if report['passes_stress_test'] else 'fail'}">{report['status']}</p>
        
        <div class="metric">
            <p class="metric-name">Interpretation:</p>
            <p>{report['interpretation']}</p>
        </div>
        
        <h2>Risk Metrics</h2>
        <table>
            <tr>
                <th>Metric</th>
                <th>Value</th>
                <th>Limit</th>
                <th>Status</th>
            </tr>
            <tr>
                <td>VaR (95%)</td>
                <td>{report['risk_summary']['var_95']['value']}</td>
                <td>{report['risk_summary']['var_95']['limit']}</td>
                <td class="{'pass' if report['risk_summary']['var_95']['pass'] else 'fail'}">
                    {'✅' if report['risk_summary']['var_95']['pass'] else '❌'}
                </td>
            </tr>
            <tr>
                <td>Survival Rate</td>
                <td>{report['risk_summary']['survival_rate']['value']}</td>
                <td>{report['risk_summary']['survival_rate']['limit']}</td>
                <td class="{'pass' if report['risk_summary']['survival_rate']['pass'] else 'fail'}">
                    {'✅' if report['risk_summary']['survival_rate']['pass'] else '❌'}
                </td>
            </tr>
            <tr>
                <td>Max Drawdown</td>
                <td>{report['risk_summary']['max_drawdown']['value']}</td>
                <td>{report['risk_summary']['max_drawdown']['limit']}</td>
                <td class="{'pass' if report['risk_summary']['max_drawdown']['pass'] else 'fail'}">
                    {'✅' if report['risk_summary']['max_drawdown']['pass'] else '❌'}
                </td>
            </tr>
            <tr>
                <td>Mean Sharpe Ratio</td>
                <td>{report['risk_summary']['sharpe_ratio']['mean']}</td>
                <td>{report['risk_summary']['sharpe_ratio']['limit']}</td>
                <td class="{'pass' if report['risk_summary']['sharpe_ratio']['pass'] else 'fail'}">
                    {'✅' if report['risk_summary']['sharpe_ratio']['pass'] else '❌'}
                </td>
            </tr>
        </table>
        
        <h2>Performance Summary</h2>
        <table>
            <tr>
                <th>Metric</th>
                <th>Value</th>
            </tr>
            <tr>
                <td>Mean Return</td>
                <td>{report['performance_summary']['mean_return']}</td>
            </tr>
            <tr>
                <td>Median Return</td>
                <td>{report['performance_summary']['median_return']}</td>
            </tr>
            <tr>
                <td>Return Volatility</td>
                <td>{report['performance_summary']['return_volatility']}</td>
            </tr>
            <tr>
                <td>Mean Drawdown</td>
                <td>{report['performance_summary']['mean_drawdown']}</td>
            </tr>
        </table>
        
        <p style="margin-top: 40px; color: #666; font-size: 0.9em;">
            Generated: {report['timestamp']}
        </p>
    </body>
    </html>
    """
    
    return html
