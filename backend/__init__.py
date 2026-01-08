"""
backend package

This package is imported by most container entrypoints. We install lightweight
container lifecycle logging here so SIGTERM receipt, shutdown duration, and exit
reason are captured consistently across services, without adding any delay.
"""

try:
    from backend.common.lifecycle import install_container_lifecycle_logging as _install_container_lifecycle_logging

    _install_container_lifecycle_logging()
    del _install_container_lifecycle_logging
except Exception:
    # Never block imports if lifecycle hooks fail.
    pass
