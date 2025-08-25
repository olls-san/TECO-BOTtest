"""
app package
-----------

This package contains the FastAPI application and its supporting
modules. Importing ``app`` will load the :mod:`main` module and
expose the ``app`` instance for ASGI servers.
"""

from .main import app  # noqa: F401