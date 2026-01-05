"""
Integration helpers to track metrics in existing API calls.

These wrappers should be used around Alpaca and Gemini API calls to automatically
track latency and token usage.
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, Optional, TypeVar

from backend.analytics.metrics import get_metrics_tracker


T = TypeVar("T")


def track_alpaca_api(endpoint: str):
    """
    Decorator to track Alpaca API call metrics.
    
    Usage:
        @track_alpaca_api("/v2/account")
        def get_account():
            return alpaca_client.get_account()
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            tracker = get_metrics_tracker()
            start_time = time.time()
            error_msg = None
            status = "success"
            
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                error_msg = str(e)
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000
                tracker.record_api_call(
                    service="alpaca",
                    endpoint=endpoint,
                    duration_ms=duration_ms,
                    status=status,
                    error_message=error_msg,
                )
        
        return wrapper
    return decorator


def track_gemini_api(
    user_id: str,
    model: str = "gemini-2.5-flash",
    request_type: str = "signal_generation",
):
    """
    Decorator to track Gemini API call metrics and token usage.
    
    The decorated function should return a response object that has
    'usage_metadata' attribute with 'prompt_token_count' and 'candidates_token_count'.
    
    Usage:
        @track_gemini_api(user_id="user123")
        def generate_signal(prompt: str):
            return gemini_model.generate_content(prompt)
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            tracker = get_metrics_tracker()
            start_time = time.time()
            error_msg = None
            status = "success"
            
            try:
                result = func(*args, **kwargs)
                
                # Extract token usage from response if available
                if hasattr(result, 'usage_metadata'):
                    usage = result.usage_metadata
                    prompt_tokens = getattr(usage, 'prompt_token_count', 0)
                    completion_tokens = getattr(usage, 'candidates_token_count', 0)
                    
                    tracker.record_token_usage(
                        user_id=user_id,
                        model=model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        request_type=request_type,
                    )
                
                return result
            except Exception as e:
                status = "error"
                error_msg = str(e)
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000
                tracker.record_api_call(
                    service="gemini",
                    endpoint=request_type,
                    duration_ms=duration_ms,
                    status=status,
                    error_message=error_msg,
                )
        
        return wrapper
    return decorator


def record_alpaca_call(
    endpoint: str,
    duration_ms: float,
    success: bool = True,
    error_message: Optional[str] = None,
) -> None:
    """
    Manually record an Alpaca API call metric.
    
    Use this when you can't use the decorator (e.g., async code, callbacks).
    """
    tracker = get_metrics_tracker()
    tracker.record_api_call(
        service="alpaca",
        endpoint=endpoint,
        duration_ms=duration_ms,
        status="success" if success else "error",
        error_message=error_message,
    )


def record_gemini_call(
    user_id: str,
    endpoint: str,
    duration_ms: float,
    prompt_tokens: int,
    completion_tokens: int,
    model: str = "gemini-2.5-flash",
    request_type: str = "signal_generation",
    success: bool = True,
    error_message: Optional[str] = None,
) -> None:
    """
    Manually record a Gemini API call metric and token usage.
    
    Use this when you can't use the decorator (e.g., async code, callbacks).
    """
    tracker = get_metrics_tracker()
    
    # Record API latency
    tracker.record_api_call(
        service="gemini",
        endpoint=endpoint,
        duration_ms=duration_ms,
        status="success" if success else "error",
        error_message=error_message,
    )
    
    # Record token usage
    if success and prompt_tokens > 0:
        tracker.record_token_usage(
            user_id=user_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            request_type=request_type,
        )


# Example integration patch for existing code
def patch_alpaca_signal_trader():
    """
    Example of how to patch existing alpaca_signal_trader.py to track metrics.
    
    Add this to the top of alpaca_signal_trader.py:
    
        from backend.analytics.integrations import record_gemini_call
        import time
        
    Then in generate_ai_signal_with_affordability_gate():
    
        start = time.time()
        try:
            response = model.generate_content(...)
            duration_ms = (time.time() - start) * 1000
            
            # Extract token usage
            usage = response.usage_metadata
            prompt_tokens = usage.prompt_token_count
            completion_tokens = usage.candidates_token_count
            
            # Record the call
            record_gemini_call(
                user_id=tenant_id,  # or uid if available
                endpoint="generate_signal",
                duration_ms=duration_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model="gemini-2.5-flash",
                request_type="signal_generation",
            )
            
            return signal
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            record_gemini_call(
                user_id=tenant_id,
                endpoint="generate_signal",
                duration_ms=duration_ms,
                prompt_tokens=0,
                completion_tokens=0,
                success=False,
                error_message=str(e),
            )
            raise
    """
    pass
