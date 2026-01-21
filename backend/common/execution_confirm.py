from backend.common.secrets import get_secret
from backend.common.lifecycle import get_agent_lifecycle_details
from backend.common.agent_mode import read_agent_mode
from backend.common.runtime_fingerprint import get_runtime_fingerprint

import os
import asyncio
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, TypeVar

from fastapi import FastAPI, HTTPException, Request, Response
from google.cloud import firestore

from backend.common.logging import init_structured_logging, log_standard_event
from backend.observability.correlation import bind_correlation_id, get_or_create_correlation_id

# --- Shared constants ---
# Used for confirming execution via token.
expected = str(get_secret("EXECUTION_CONFIRM_TOKEN", fail_if_missing=False)).strip()


def is_execution_confirmed(token: str) -> bool:
    """Checks if the provided token matches the expected token."""
    return token == expected
