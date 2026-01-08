"""
Test package marker.

Pytest in some environments imports tests as a package (e.g. `tests.test_foo`).
Providing `__init__.py` ensures imports are resolvable without affecting runtime code.
"""

