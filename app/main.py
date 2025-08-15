"""
Main application entry point for the modular Tecopos API wrapper.

This module defines the FastAPI instance and registers all route
groups defined under ``app.routes``.  Each functional area of the API
has been extracted into its own module, so this file no longer
contains endpoint logic.  To add a new endpoint, define it in a
corresponding router module under ``app/routes`` and include the
router here.
"""

from fastapi import FastAPI

from .routes.auth import router as auth_router
from .routes.products import router as products_router
from .routes.reports import router as reports_router
from .routes.currency import router as currency_router
from .routes.dispatch import router as dispatch_router
from .routes.inventory import router as inventory_router


app = FastAPI()

# Register routers for each functional area.  Prefixes are kept flat to
# preserve the original endpoint paths.  When adding a new router,
# import it above and include it here.
app.include_router(auth_router)
app.include_router(products_router)
app.include_router(reports_router)
app.include_router(currency_router)
app.include_router(dispatch_router)
app.include_router(inventory_router)