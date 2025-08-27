"""
main.py
-------

Application entrypoint. Creates the FastAPI instance, configures
lifespan events to instantiate the shared HTTP client and registers
all routers. The default response class uses ORJSON for faster
serialization. Middlewares can be added here as necessary.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app.clients.http_client import HTTPClient
from app.routes.auth import router as auth_router
from app.routes.products import router as products_router
from app.routes.reports import router as reports_router
from app.routes.currency import router as currency_router
from app.routes.dispatch import router as dispatch_router
from app.routes.carga import router as carga_router
from app.routes.rendimiento import router as rendimiento_router
from app.routes.inventario import router as inventario_router
from app.routes import rendimiento_descomposicion as rendimiento_descomposicion_routes

def create_app() -> FastAPI:
    app = FastAPI(default_response_class=ORJSONResponse)
    # create http client during startup and close on shutdown
    @app.on_event("startup")
    def startup_event() -> None:
        app.state.http_client = HTTPClient()  # CHANGED: reuse connections via singleton

    @app.on_event("shutdown")
    def shutdown_event() -> None:
        client: HTTPClient = app.state.http_client
        client.close()

    # register routers
    app.include_router(auth_router)
    app.include_router(products_router)
    app.include_router(reports_router)
    app.include_router(currency_router)
    app.include_router(dispatch_router)
    app.include_router(carga_router)
    app.include_router(rendimiento_router)
    app.include_router(inventario_router)
    app.include_router(rendimiento_descomposicion_routes.router)
    return app


app = create_app()
