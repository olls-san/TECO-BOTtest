"""
Route aggregation package for the Tecopos API wrapper.

This package exposes each functional area of the API (authentication,
product management, reporting, inventory, and dispatch) as its own
module.  Each module defines an ``APIRouter`` instance that groups
related endpoints together.  The main application imports these
routers and includes them in the global FastAPI instance.

Having a dedicated package for routes helps isolate endpoint logic,
making it easier to maintain and extend individual features without
affecting unrelated parts of the codebase.  When adding a new
endpoint, prefer placing it in the appropriate module or creating
a new one under ``app/routes``.
"""

from fastapi import APIRouter

__all__ = [
    "auth",
    "products",
    "reports",
    "currency",
    "dispatch",
    "inventory",
]

# Import submodules so their routers can be registered by main.py
from . import auth, products, reports, currency, dispatch, inventory  # noqa: E402,F401