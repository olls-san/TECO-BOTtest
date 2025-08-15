"""
Root application entry point for Tecopos API wrapper
===================================================

This module exposes the FastAPI application instance defined in
``app/main.py`` so that deployment tools like Uvicorn can import
``main:app`` without needing to treat the repository as a Python
package.  By delegating to ``app.main``, the application setup and
router registration remain centralized in one place, and relative
imports continue to work correctly within the ``app`` package.

Usage
-----

When running the API with Uvicorn, point the application to this
module.  For example:

.. code-block:: bash

    uvicorn main:app --host 0.0.0.0 --port 8000

This configuration will import the FastAPI instance defined in
``app/main.py`` without raising ``ImportError`` for relative imports.
"""

from app.main import app  # noqa: F401 re-export for Uvicorn

__all__ = ["app"]