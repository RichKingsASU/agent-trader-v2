"""
Dynamic Strategy Loader with Maestro Orchestration

Automatically discovers and loads all strategy classes that inherit from BaseStrategy.
This allows adding new strategies by simply dropping a file in the strategies/ folder.

This loader supports both sync and async strategies, handles errors gracefully,
and provides a registry for efficient strategy instantiation.

Enhanced with Maestro orchestration for:
- Sharpe-based weight calculation
- Dynamic capital allocation
- Multi-agent coordination
"""

import asyncio
import importlib
import inspect
import logging
import pkgutil
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, Union, Tuple

# Import both base strategy types
try:
    from .base_strategy import BaseStrategy as BaseStrategySync, TradingSignal
    HAS_BASE_STRATEGY = True
except ImportError:
    HAS_BASE_STRATEGY = False
    BaseStrategySync = None
    TradingSignal = None

try:
    from .base import BaseStrategy as BaseStrategyAsync
    HAS_BASE = True
except ImportError:
    HAS_BASE = False
    BaseStrategyAsync = None

try:
    from .maestro_controller import MaestroController, MaestroDecision
    HAS_MAESTRO = True
except ImportError:
    HAS_MAESTRO = False
    MaestroController = None
    MaestroDecision = None


logger = logging.getLogger(__name__)


class StrategyLoader:
    """
    Dynamic Strategy Loader with automatic discovery, parallel execution, and Maestro orchestration.
    
    This class discovers all strategies in the strategies/ directory that inherit
    from BaseStrategy and provides methods to instantiate and execute them.
    
    Features:
    - Automatic strategy discovery using importlib and pkgutil
    - Support for both sync and async strategies
    - Error isolation: one strategy's failure doesn't affect others
    - Global variable reuse for Cloud Functions optimization
    - Registry pattern for efficient lookups
    - Cryptographic agent identity management (Zero-Trust security)
    
    Example:
        loader = StrategyLoader(db=firestore_client)
        strategies = loader.get_all_strategies()
        signals = await loader.evaluate_all_strategies_with_maestro(market_data, account_snapshot)
    """
    
    def __init__(self, db=None):
        """
        Initialize the strategy loader and discover all strategies.
        
        Args:
            db: Optional Firestore client for agent identity registration.
                If provided, each strategy will be registered with a cryptographic
                identity for Zero-Trust signal authentication.
        """
        self.strategies: Dict[str, Any] = {}
        self._strategy_classes: Dict[str, Type] = {}
        self._load_errors: Dict[str, str] = {}
        self._db = db
        
        # Initialize identity manager if Firestore client provided
        self._identity_manager = None
        if db is not None:
            try:
                from utils.identity_manager import get_identity_manager
                self._identity_manager = get_identity_manager(db)
                logger.info("🔐 Agent identity manager initialized for Zero-Trust security")
            except Exception as e:
                logger.warning(
                    f"Failed to initialize identity manager: {e}. "
                    "Strategies will run without cryptographic signing."
                )
        
        # Rate limiting configuration
        config = config or {}
        self._enable_rate_limiting = config.get("enable_rate_limiting", True)
        self.__class__._batch_write_limit = config.get("batch_write_limit", 500)
        self.__class__._doc_write_limit = config.get("doc_write_limit", 50)
        self.__class__._batch_cooldown_sec = config.get("batch_cooldown_sec", 5.0)
        
        # Discover and register all strategies
        self._discover_strategies()
        logger.info(
            f"StrategyLoader initialized: {len(self.strategies)} strategies loaded, "
            f"{len(self._load_errors)} errors, Maestro={'enabled' if self.maestro else 'disabled'}"
        )
    
    def _discover_strategies(self) -> None:
        """
        Discover all strategy classes from the strategies/ directory.
        
        Uses pkgutil to iterate through all .py files and inspects each module
        for classes that inherit from BaseStrategy (excluding base.py and __init__.py).
        """
        # Get the directory containing this file
        strategies_dir = Path(__file__).parent
        
        # Files to exclude from discovery
        excluded_files = {"__init__", "base", "base_strategy", "loader"}
        
        # Iterate through all Python files in the strategies directory
        for filepath in strategies_dir.glob("*.py"):
            module_name = filepath.stem
            
            # Skip excluded files
            if module_name in excluded_files:
                continue
            
            # Try to import the module and discover strategies
            try:
                self._load_module_strategies(module_name)
            except Exception as e:
                error_msg = f"Failed to load module {module_name}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                self._load_errors[module_name] = error_msg
    
    def _load_module_strategies(self, module_name: str) -> None:
        """
        Load all strategy classes from a specific module.
        
        Args:
            module_name: Name of the module to load (without .py extension)
        """
        # Import the module
        module = importlib.import_module(f"strategies.{module_name}")
        
        # Find all classes in the module that inherit from BaseStrategy
        for name, obj in inspect.getmembers(module, inspect.isclass):
            # Check if it's a strategy class
            if not self._is_strategy_class(obj):
                continue
            
            # Check if the class is defined in this module (not imported)
            if obj.__module__ != module.__name__:
                continue
            
            # Register the strategy class
            try:
                # Store the class for later instantiation
                self._strategy_classes[name] = obj
                
                # Instantiate with default config
                # Try both constructor signatures (with and without 'name' parameter)
                try:
                    strategy_instance = obj(name=name.lower(), config={})
                except TypeError:
                    # Try without 'name' parameter (newer interface)
                    strategy_instance = obj(config={})
                
                # Register agent with cryptographic identity if identity manager is available
                if self._identity_manager is not None:
                    try:
                        agent_id = name.lower()
                        
                        # Register agent (generates key pair, stores public key in Firestore)
                        self._identity_manager.register_agent(agent_id)
                        
                        # Configure strategy with identity manager
                        strategy_instance.set_identity_manager(
                            self._identity_manager,
                            agent_id
                        )
                        
                        logger.info(
                            f"🔐 Strategy '{name}' registered with cryptographic identity: {agent_id}"
                        )
                    except Exception as identity_error:
                        logger.warning(
                            f"Failed to register cryptographic identity for '{name}': {identity_error}. "
                            "Strategy will run without signing."
                        )
                
                self.strategies[name] = strategy_instance
                logger.info(f"Loaded strategy: {name} from module {module_name}")
                
            except Exception as e:
                error_msg = f"Failed to instantiate {name}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                self._load_errors[name] = error_msg
    
    def _is_strategy_class(self, obj: Any) -> bool:
        """
        Check if an object is a valid strategy class.
        
        Args:
            obj: Object to check
            
        Returns:
            True if obj is a BaseStrategy subclass (but not BaseStrategy itself)
        """
        if not inspect.isclass(obj):
            return False
        
        # Check against both base strategy types
        is_sync_strategy = (
            HAS_BASE_STRATEGY and 
            BaseStrategySync is not None and
            issubclass(obj, BaseStrategySync) and 
            obj is not BaseStrategySync
        )
        
        is_async_strategy = (
            HAS_BASE and 
            BaseStrategyAsync is not None and
            issubclass(obj, BaseStrategyAsync) and 
            obj is not BaseStrategyAsync
        )
        
        return is_sync_strategy or is_async_strategy
    
    def get_all_strategies(self) -> Dict[str, Any]:
        """
        Get all loaded strategy instances.
        
        Returns:
            Dictionary mapping strategy names to strategy instances
        """
        return self.strategies.copy()
    
    def get_strategy(self, strategy_name: str) -> Optional[Any]:
        """
        Get a specific strategy by name.
        
        Args:
            strategy_name: Name of the strategy to retrieve
            
        Returns:
            Strategy instance or None if not found
        """
        return self.strategies.get(strategy_name)
    
    def get_strategy_names(self) -> List[str]:
        """
        Get list of all loaded strategy names.
        
        Returns:
            List of strategy names
        """
        return list(self.strategies.keys())
    
    def get_load_errors(self) -> Dict[str, str]:
        """
        Get any errors that occurred during strategy loading.
        
        Returns:
            Dictionary mapping module/class names to error messages
        """
        return self._load_errors.copy()
    
    async def evaluate_all_strategies(
        self,
        market_data: Dict[str, Any],
        account_snapshot: Dict[str, Any],
        regime: Optional[str] = None,
        user_count: Optional[int] = None
    ) -> Dict[str, Union[Dict[str, Any], TradingSignal]]:
        """
        Evaluate all strategies in parallel using asyncio.gather with rate limiting.
        
        This method runs all strategy evaluate() methods concurrently,
        catching and logging any errors without stopping other strategies.
        
        SaaS Scale Feature: Implements staggered evaluation when user_count is high
        to prevent Firestore write contention (500/50/5 Rule).
        
        Args:
            market_data: Current market data (prices, indicators, etc.)
            account_snapshot: Current account state (buying power, positions, etc.)
            regime: Optional market regime from GEX engine
            user_count: Optional total number of concurrent users (for rate limiting)
            
        Returns:
            Dictionary mapping strategy names to their signals
            (or error info if strategy failed)
        """
        if not self.strategies:
            logger.warning("No strategies loaded, returning empty results")
            return {}
        
        # Apply rate limiting if enabled and user count is high
        if self._enable_rate_limiting and user_count:
            await self._apply_rate_limiting(user_count)
        
        # Create evaluation tasks for all strategies
        tasks = []
        strategy_names = []
        
        for name, strategy in self.strategies.items():
            task = self._safe_evaluate_strategy(
                strategy_name=name,
                strategy=strategy,
                market_data=market_data,
                account_snapshot=account_snapshot,
                regime=regime
            )
            tasks.append(task)
            strategy_names.append(name)
        
        # Run all evaluations in parallel
        logger.info(f"Evaluating {len(tasks)} strategies in parallel...")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Build results dictionary
        signals = {}
        for name, result in zip(strategy_names, results):
            if isinstance(result, Exception):
                logger.error(f"Strategy {name} raised exception: {result}")
                signals[name] = {
                    "error": str(result),
                    "action": "HOLD",
                    "confidence": 0.0,
                    "reasoning": f"Strategy error: {str(result)}"
                }
            else:
                signals[name] = result
        
        return signals
    
    async def _safe_evaluate_strategy(
        self,
        strategy_name: str,
        strategy: Any,
        market_data: Dict[str, Any],
        account_snapshot: Dict[str, Any],
        regime: Optional[str] = None
    ) -> Union[Dict[str, Any], TradingSignal]:
        """
        Safely evaluate a single strategy with error handling.
        
        Args:
            strategy_name: Name of the strategy
            strategy: Strategy instance
            market_data: Market data
            account_snapshot: Account snapshot
            regime: Optional market regime
            
        Returns:
            Signal from the strategy (dict or TradingSignal)
        """
        try:
            # Check if strategy has evaluate method
            if not hasattr(strategy, 'evaluate'):
                raise AttributeError(f"Strategy {strategy_name} missing evaluate() method")
            
            evaluate_method = strategy.evaluate
            
            # Call evaluate method (async or sync)
            if asyncio.iscoroutinefunction(evaluate_method):
                signal = await evaluate_method(market_data, account_snapshot, regime)
            else:
                signal = evaluate_method(market_data, account_snapshot, regime)
            
            logger.info(f"Strategy {strategy_name} evaluated successfully")
            return signal
            
        except Exception as e:
            logger.exception(f"Error evaluating strategy {strategy_name}: {e}")
            # Return error signal instead of raising
            return {
                "error": str(e),
                "action": "HOLD",
                "confidence": 0.0,
                "reasoning": f"Error in {strategy_name}: {str(e)}"
            }
    
    async def _apply_rate_limiting(self, user_count: int) -> None:
        """
        Apply 500/50/5 rate limiting rule to prevent Firestore contention.
        
        Rule breakdown:
        - 500 writes/sec: Firestore global write limit
        - 50 writes/sec: Per-document write limit
        - 5 seconds: Cooldown between batches during high traffic
        
        This method implements staggered delays when traffic is high to:
        1. Prevent hitting Firestore's 500 writes/sec global limit
        2. Prevent hitting the 50 writes/sec per-document limit
        3. Distribute load over time during traffic spikes
        
        Args:
            user_count: Current number of concurrent users
        """
        current_time = time.time()
        
        # Reset batch counter if cooldown period has passed
        if current_time - self.__class__._last_batch_time >= self.__class__._batch_cooldown_sec:
            self.__class__._current_batch_count = 0
            self.__class__._last_batch_time = current_time
        
        # Check if we're approaching the batch write limit
        if self.__class__._current_batch_count >= self.__class__._batch_write_limit:
            # Calculate time to wait until next batch window
            elapsed = current_time - self.__class__._last_batch_time
            wait_time = max(0, self.__class__._batch_cooldown_sec - elapsed)
            
            if wait_time > 0:
                logger.warning(
                    f"Rate limiting: batch limit reached ({self.__class__._current_batch_count} writes). "
                    f"Waiting {wait_time:.2f}s before next batch..."
                )
                await asyncio.sleep(wait_time)
                
                # Reset for new batch
                self.__class__._current_batch_count = 0
                self.__class__._last_batch_time = time.time()
        
        # Add staggered delay based on user count to distribute load
        # Formula: delay = (user_count / batch_write_limit) * random_jitter
        # This ensures we don't have all users hitting Firestore simultaneously
        if user_count > self.__class__._batch_write_limit / 2:
            # High traffic: add staggered delay
            base_delay = (user_count / self.__class__._batch_write_limit) * 0.1
            jitter = random.uniform(0, base_delay)
            
            logger.info(
                f"Rate limiting: high traffic detected ({user_count} users). "
                f"Adding {jitter:.3f}s jitter delay..."
            )
            await asyncio.sleep(jitter)
        
        # Increment batch counter (estimate 1 write per strategy evaluation)
        self.__class__._current_batch_count += 1
    
    def reload_strategies(self) -> None:
        """
        Reload all strategies from disk.
        
        Useful for development/testing, but generally not needed in production
        due to Cloud Functions' cold start behavior.
        """
        self.strategies.clear()
        self._strategy_classes.clear()
        self._load_errors.clear()
        self._discover_strategies()
        logger.info("Strategies reloaded")
    
    async def calculate_strategy_weights(self) -> Dict[str, Tuple[float, str]]:
        """
        Calculate Sharpe-based weights for all strategies.
        
        This method fetches the last 30 days of performance from Firestore
        and calculates Annualized Sharpe Ratios using the formula:
        
        S = sqrt(252) * (mean(daily_returns) / std(daily_returns))
        
        Returns:
            Dictionary mapping strategy name to (weight_multiplier, mode)
            where weight_multiplier is in [0.0, 1.0] and mode is the agent mode
        """
        if self.maestro is None:
            logger.warning(
                "Maestro not initialized, returning default weights. "
                "Initialize StrategyLoader with a Firestore client to enable Sharpe-based weighting."
            )
            return {name: (1.0, "ACTIVE") for name in self.strategies.keys()}
        
        try:
            # Use Maestro to calculate weights
            weights_with_mode = await self.maestro.calculate_strategy_weights(self.strategies)
            
            # Convert to simpler format (weight, mode_string)
            return {
                name: (weight, mode.value)
                for name, (weight, mode) in weights_with_mode.items()
            }
            
        except Exception as e:
            logger.error(f"Error calculating strategy weights: {e}", exc_info=True)
            # Return default weights on error
            return {name: (1.0, "ACTIVE") for name in self.strategies.keys()}
    
    async def evaluate_all_strategies_with_maestro(
        self,
        market_data: Dict[str, Any],
        account_snapshot: Dict[str, Any],
        regime: Optional[str] = None
    ) -> Tuple[Dict[str, Union[Dict[str, Any], TradingSignal]], Optional[MaestroDecision]]:
        """
        Evaluate all strategies with Maestro orchestration.
        
        This method:
        1. Evaluates all strategies in parallel
        2. Applies Sharpe-based weight adjustments via Maestro
        3. Applies systemic risk overrides
        4. Enriches signals with JIT Identity
        5. Generates AI summaries
        6. Logs all decisions to Firestore
        
        Args:
            market_data: Current market data (prices, indicators, etc.)
            account_snapshot: Current account state (buying power, positions, etc.)
            regime: Optional market regime from GEX engine
            
        Returns:
            Tuple of (orchestrated_signals, maestro_decision)
        """
        # First, evaluate all strategies
        raw_signals = await self.evaluate_all_strategies(
            market_data=market_data,
            account_snapshot=account_snapshot,
            regime=regime
        )
        
        # If Maestro is not available, return raw signals
        if self.maestro is None:
            logger.info("Maestro not available, returning raw signals")
            return raw_signals, None
        
        # Apply Maestro orchestration
        try:
            orchestrated_signals, maestro_decision = await self.maestro.orchestrate(
                signals=raw_signals,
                strategies=self.strategies
            )
            
            return orchestrated_signals, maestro_decision
            
        except Exception as e:
            logger.error(f"Maestro orchestration failed: {e}", exc_info=True)
            # Return raw signals if orchestration fails
            return raw_signals, None


# Global instance for Cloud Functions optimization (Global Variable Reuse)
# This instance will be reused across warm invocations, reducing cold start time
_global_loader: Optional[StrategyLoader] = None


def get_strategy_loader(db: Optional[Any] = None, tenant_id: str = "default", uid: Optional[str] = None) -> StrategyLoader:
    """
    Get the global StrategyLoader instance with Maestro orchestration.
    
    Uses the Singleton pattern to ensure only one loader exists,
    optimizing for Cloud Functions' Global Variable Reuse feature.
    
    Args:
        db: Firestore client (optional, required for Maestro orchestration)
        tenant_id: Tenant identifier for multi-tenancy
        uid: User identifier (optional)
    
    Returns:
        Global StrategyLoader instance with Maestro enabled (if db provided)
    """
    global _global_loader
    
    if _global_loader is None:
        logger.info("Initializing global StrategyLoader with Maestro orchestration...")
        _global_loader = StrategyLoader(db=db, tenant_id=tenant_id, uid=uid)
    
    return _global_loader


def load_strategies() -> Dict[str, Type]:
    """
    Backwards-compatible strategy discovery API.

    Some modules (and tests) expect `strategies.loader.load_strategies()` to return a
    mapping of `{strategy_name: StrategyClass}`.

    This implementation is best-effort: it attempts to import strategy modules and
    collect `BaseStrategy` subclasses, but will gracefully skip modules that fail to
    import (missing optional dependencies, etc.).
    """
    try:
        from strategies.base_strategy import BaseStrategy
    except Exception:
        return {}

    strategies: Dict[str, Type] = {}
    strategies_dir = Path(__file__).parent
    excluded = {"__init__", "base", "base_strategy", "loader"}

    for modinfo in pkgutil.iter_modules([str(strategies_dir)]):
        module_name = modinfo.name
        if module_name in excluded:
            continue
        try:
            module = importlib.import_module(f"strategies.{module_name}")
        except Exception:
            continue

        for name, obj in inspect.getmembers(module, inspect.isclass):
            try:
                if issubclass(obj, BaseStrategy) and obj is not BaseStrategy:
                    strategies[name] = obj
            except Exception:
                continue

    return strategies
