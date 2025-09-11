# main.py
from __future__ import annotations

from contextlib import asynccontextmanager
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    # crear y compartir el cliente HTTP
    app.state.http_client = HTTPClient()  # conexiones reutilizadas
    try:
        yield
    finally:
        app.state.http_client.close()

def create_app() -> FastAPI:
    app = FastAPI(default_response_class=ORJSONResponse, lifespan=lifespan)

    # registrar routers
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

