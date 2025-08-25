"""
core/context.py
----------------

In‑memory session store for authenticated users. The ``user_context``
dictionary preserves the Tecopos token, current business ID and
region for each user. This state allows multiple requests from the
same user to reuse authentication information without forcing the
client to supply credentials on each call. Note that this store
resides in process memory; in a multi‑worker deployment the state
will not be shared across workers.
"""

from __future__ import annotations

from typing import Dict, Any

user_context: Dict[str, Dict[str, Any]] = {}


def set_user_context(username: str, ctx: Dict[str, Any]) -> None:
    """Persist session context for a user."""
    user_context[username] = ctx


def get_user_context(username: str) -> Dict[str, Any] | None:
    """Retrieve session context for a user if it exists."""
    return user_context.get(username)


def clear_user_context(username: str) -> None:
    """Remove session context for a user."""
    user_context.pop(username, None)