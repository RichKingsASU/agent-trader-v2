"""
Strategies Package

This package contains the BaseStrategy abstract class, a dynamic loader
for discovering and instantiating strategy implementations, and the Maestro
orchestration layer for multi-agent coordination.

Usage:
    from strategies import BaseStrategy, StrategyLoader, MaestroController
    
    # Option 1: Use StrategyLoader with Maestro orchestration (recommended)
    loader = StrategyLoader(db=firestore_client, tenant_id="my-tenant")
    signals, decision = await loader.evaluate_all_strategies_with_maestro(
        market_data, account_snapshot
    )
    
    # Option 2: Use standalone Maestro
    maestro = MaestroController(db=firestore_client)
    orchestrated_signals, decision = await maestro.orchestrate(signals, strategies)
    
    # Option 3: Traditional evaluation (no Maestro)
    loader = StrategyLoader()
    signals = await loader.evaluate_all_strategies(market_data, account_snapshot)
"""

from .base import BaseStrategy
from .loader import (
    StrategyLoader,
    get_strategy_loader,
)
try:
    from .maestro_orchestrator import MaestroOrchestrator
    _HAS_MAESTRO_ORCHESTRATOR = True
except ImportError:
    # Maestro orchestrator not available (e.g., missing firebase_admin in minimal test env)
    MaestroOrchestrator = None
    _HAS_MAESTRO_ORCHESTRATOR = False

try:
    from .maestro_controller import (
        MaestroController,
        MaestroDecision,
        AgentMode,
        AgentIdentity,
        AllocationDecision,
        StrategyPerformanceMetrics
    )
    _HAS_MAESTRO = True
except ImportError:
    # Maestro not available (e.g., missing dependencies)
    _HAS_MAESTRO = False
    MaestroController = None
    MaestroDecision = None
    AgentMode = None
    AgentIdentity = None
    AllocationDecision = None
    StrategyPerformanceMetrics = None

__all__ = [
    'BaseStrategy',
    'StrategyLoader',
    'get_strategy_loader',
]

if _HAS_MAESTRO_ORCHESTRATOR:
    __all__.append('MaestroOrchestrator')

if _HAS_MAESTRO:
    __all__.extend([
        'MaestroController',
        'MaestroDecision',
        'AgentMode',
        'AgentIdentity',
        'AllocationDecision',
        'StrategyPerformanceMetrics'
    ])
