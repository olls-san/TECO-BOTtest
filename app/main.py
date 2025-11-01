# main.py
from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse

# Import logging utilities early so that the logger configuration is
# applied before any other modules emit log messages.  The logger is
# used throughout the application for structured JSON logging.
from app.logging_config import logger
import json
import time

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

    # -----------------------------------------------------------------
    # Middleware de logging de requests
    # -----------------------------------------------------------------
    # Este middleware captura cada solicitud entrante y registra el
    # camino, método HTTP, código de respuesta y tiempo de procesado. Al
    # utilizar ``logger.info`` con JSON serializado, se facilita la
    # integración con herramientas de observabilidad en producción.
    @app.middleware("http")  # type: ignore[misc]
    async def log_requests(request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start_time) * 1000
        try:
            logger.info(json.dumps({
                "event": "http_request",
                "path": request.url.path,
                "method": request.method,
                "status": response.status_code,
                "duration_ms": round(duration_ms, 2),
            }))
        except Exception:
            # fallback en caso de que falle la serialización
            logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({round(duration_ms,2)} ms)")
        return response

    return app

app = create_app()

