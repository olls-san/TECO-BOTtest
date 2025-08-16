"""
Punto de entrada FastAPI (modular).
Registra routers y añade integración para ChatGPT Actions:
- CORS para chat.openai.com
- Servir /.well-known/ai-plugin.json
- /healthz
- OpenAPI con un solo 'server' = dominio público
"""
from __future__ import annotations
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi

# Routers existentes (modular)
from .routes.auth import router as auth_router
from .routes.products import router as products_router
from .routes.reports import router as reports_router
from .routes.currency import router as currency_router
from .routes.dispatch import router as dispatch_router
from .routes.inventory import router as inventory_router

# === Config ===
PUBLIC_SERVER_URL = "https://teco-bottest.onrender.com"  # <— cambia si usas otro dominio

app = FastAPI(
    title="Tecopos Product API",
    version="1.1.0",
    description="TECO-BOT modular API"
)

# 1) CORS para ChatGPT
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://chat.openai.com", "https://*.openai.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2) Servir /.well-known/ai-plugin.json
ROOT_DIR = Path(__file__).resolve().parents[1]   # carpeta raíz del repo
WELLKNOWN_DIR = ROOT_DIR / ".well-known"
app.mount("/.well-known", StaticFiles(directory=str(WELLKNOWN_DIR)), name="wellknown")

# 3) Health check (útil para provocar el prompt "Allow")
@app.get("/healthz", include_in_schema=True, summary="Health check")
def healthz():
    return {"ok": True}

# 4) OpenAPI con UN solo server (coincidir con tu dominio público)
def custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema["servers"] = [{"url": PUBLIC_SERVER_URL}]
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi  # type: ignore

# 5) Registrar routers (se mantiene modular)
app.include_router(auth_router)
app.include_router(products_router)
app.include_router(reports_router)
app.include_router(currency_router)
app.include_router(dispatch_router)
app.include_router(inventory_router)
