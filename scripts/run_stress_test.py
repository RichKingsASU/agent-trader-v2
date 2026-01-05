#!/usr/bin/env python3
"""
Example script to run Monte Carlo stress test on the Sector Rotation Strategy.

This demonstrates how to:
1. Configure simulation parameters
2. Run the stress test
3. Analyze results
4. Generate reports

Usage:
    python scripts/run_stress_test.py
"""

import sys
import os
import json
import logging
from pathlib import Path

# Add functions directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'functions'))

from functions.stress_test_runner import run_stress_test, generate_stress_test_html_report
from functions.utils.monte_carlo import SimulationParameters

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Run stress test and display results."""
    
    logger.info("=" * 80)
    logger.info("MONTE CARLO STRESS TEST - Sector Rotation Strategy")
    logger.info("=" * 80)
    
    # Configure strategy
    strategy_config = {
        "lookback_days": 20,
        "num_top_sectors": 3,
        "crash_threshold": -0.05,
        "rebalance_frequency_days": 5,
        "min_momentum": 0.0,
    }
    
    # Configure simulation parameters
    simulation_params = {
        "num_simulations": 1000,  # Run 1,000 simulations
        "num_days": 252,  # One year of trading days
        "initial_capital": 100000.0,
        "base_drift": 0.10,  # 10% expected annual return
        "base_volatility": 0.20,  # 20% annual volatility
        "black_swan_probability": 0.10,  # 10% of simulations have crashes
        "crash_magnitude_min": -0.10,
        "crash_magnitude_max": -0.20,
    }
    
    logger.info("\nSimulation Configuration:")
    logger.info(f"  Strategy: Sector Rotation")
    logger.info(f"  Simulations: {simulation_params['num_simulations']}")
    logger.info(f"  Trading Days: {simulation_params['num_days']}")
    logger.info(f"  Initial Capital: ${simulation_params['initial_capital']:,.0f}")
    logger.info(f"  Black Swan Probability: {simulation_params['black_swan_probability']:.1%}")
    logger.info("")
    
    # Run stress test
    logger.info("Running stress test...")
    logger.info("This may take several minutes...\n")
    
    results = run_stress_test(
        strategy_name="sector_rotation",
        strategy_config=strategy_config,
        simulation_params=simulation_params,
        save_to_firestore=False,  # Don't save to Firestore for demo
    )
    
    if not results.get("success"):
        logger.error(f"Stress test failed: {results.get('error')}")
        return 1
    
    # Display results
    report = results.get("report", {})
    risk_metrics = results.get("risk_metrics", {})
    
    logger.info("=" * 80)
    logger.info("STRESS TEST RESULTS")
    logger.info("=" * 80)
    logger.info("")
    
    # Pass/Fail Status
    status = report.get("status", "UNKNOWN")
    passes = report.get("passes_stress_test", False)
    
    if passes:
        logger.info("✅ STATUS: PASSED")
        logger.info("The strategy meets all stress test criteria and is ready for live trading.")
    else:
        logger.info("❌ STATUS: FAILED")
        logger.info("The strategy failed one or more stress test criteria.")
        
        failure_reasons = report.get("failure_reasons", [])
        if failure_reasons:
            logger.info("\nFailure Reasons:")
            for reason in failure_reasons:
                logger.info(f"  • {reason}")
    
    logger.info("")
    logger.info("-" * 80)
    logger.info("RISK METRICS")
    logger.info("-" * 80)
    
    # Display risk metrics
    risk_summary = report.get("risk_summary", {})
    
    if risk_summary:
        # VaR
        var_95 = risk_summary.get("var_95", {})
        logger.info(f"\nValue at Risk (95%):")
        logger.info(f"  Value: {var_95.get('value', 'N/A')}")
        logger.info(f"  Limit: {var_95.get('limit', 'N/A')}")
        logger.info(f"  Status: {'✅ Pass' if var_95.get('pass') else '❌ Fail'}")
        
        # Survival Rate
        survival = risk_summary.get("survival_rate", {})
        logger.info(f"\nSurvival Rate:")
        logger.info(f"  Value: {survival.get('value', 'N/A')}")
        logger.info(f"  Limit: {survival.get('limit', 'N/A')}")
        logger.info(f"  Status: {'✅ Pass' if survival.get('pass') else '❌ Fail'}")
        
        # Max Drawdown
        drawdown = risk_summary.get("max_drawdown", {})
        logger.info(f"\nMaximum Drawdown:")
        logger.info(f"  Value: {drawdown.get('value', 'N/A')}")
        logger.info(f"  Limit: {drawdown.get('limit', 'N/A')}")
        logger.info(f"  Status: {'✅ Pass' if drawdown.get('pass') else '❌ Fail'}")
        
        # Sharpe Ratio
        sharpe = risk_summary.get("sharpe_ratio", {})
        logger.info(f"\nSharpe Ratio:")
        logger.info(f"  Mean: {sharpe.get('mean', 'N/A')}")
        logger.info(f"  Median: {sharpe.get('median', 'N/A')}")
        logger.info(f"  Limit: {sharpe.get('limit', 'N/A')}")
        logger.info(f"  Status: {'✅ Pass' if sharpe.get('pass') else '❌ Fail'}")
    
    logger.info("")
    logger.info("-" * 80)
    logger.info("PERFORMANCE METRICS")
    logger.info("-" * 80)
    
    perf_summary = report.get("performance_summary", {})
    if perf_summary:
        logger.info(f"\nMean Return: {perf_summary.get('mean_return', 'N/A')}")
        logger.info(f"Median Return: {perf_summary.get('median_return', 'N/A')}")
        logger.info(f"Return Volatility: {perf_summary.get('return_volatility', 'N/A')}")
        logger.info(f"Mean Drawdown: {perf_summary.get('mean_drawdown', 'N/A')}")
    
    # Recovery metrics
    recovery = report.get("recovery_summary", {})
    if recovery:
        logger.info("")
        logger.info("-" * 80)
        logger.info("RECOVERY METRICS")
        logger.info("-" * 80)
        logger.info(f"\nMean Recovery Days: {recovery.get('mean_recovery_days', 'N/A')}")
        logger.info(f"Median Recovery Days: {recovery.get('median_recovery_days', 'N/A')}")
        logger.info(f"Paths Without Recovery: {recovery.get('paths_without_recovery', 'N/A')}")
    
    # Distribution percentiles
    percentiles = report.get("final_equity_percentiles", {})
    if percentiles:
        logger.info("")
        logger.info("-" * 80)
        logger.info("FINAL EQUITY DISTRIBUTION")
        logger.info("-" * 80)
        logger.info(f"\n1st Percentile (Worst):  ${percentiles.get('p1', 0):,.2f}")
        logger.info(f"5th Percentile:          ${percentiles.get('p5', 0):,.2f}")
        logger.info(f"25th Percentile:         ${percentiles.get('p25', 0):,.2f}")
        logger.info(f"50th Percentile (Median):${percentiles.get('p50', 0):,.2f}")
        logger.info(f"75th Percentile:         ${percentiles.get('p75', 0):,.2f}")
        logger.info(f"95th Percentile:         ${percentiles.get('p95', 0):,.2f}")
        logger.info(f"99th Percentile (Best):  ${percentiles.get('p99', 0):,.2f}")
    
    # Interpretation
    interpretation = report.get("interpretation", "")
    if interpretation:
        logger.info("")
        logger.info("-" * 80)
        logger.info("INTERPRETATION")
        logger.info("-" * 80)
        logger.info(f"\n{interpretation}")
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("STRESS TEST COMPLETE")
    logger.info("=" * 80)
    
    # Save results to JSON
    output_file = Path("stress_test_results.json")
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"\nFull results saved to: {output_file}")
    
    # Generate HTML report
    try:
        from functions.utils.monte_carlo import RiskMetrics
        
        # Reconstruct risk metrics from dict
        risk_metrics_obj = RiskMetrics(**risk_metrics)
        params = SimulationParameters(**simulation_params)
        
        html_report = generate_stress_test_html_report(risk_metrics_obj, params)
        
        html_file = Path("stress_test_report.html")
        with open(html_file, "w") as f:
            f.write(html_report)
        logger.info(f"HTML report saved to: {html_file}")
        logger.info(f"Open {html_file} in your browser to view the interactive report.")
    except Exception as e:
        logger.warning(f"Failed to generate HTML report: {e}")
    
    return 0 if passes else 1


if __name__ == "__main__":
    sys.exit(main())
