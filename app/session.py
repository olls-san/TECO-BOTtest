"""
Session storage for TECO-BOT (in-memory).

This module centralises the per-user session context used across the API
routes.  It simply exposes a dictionary keyed by the ``usuario`` string.
For production deployments consider replacing this in-memory store with
a persistent and secure alternative (e.g. Redis, database).
"""

from typing import Dict, Any

# Shared session context keyed by "usuario". Each value is a dict that
# contains authentication token, selected business id, region, etc.
user_context: Dict[str, Dict[str, Any]] = {}
