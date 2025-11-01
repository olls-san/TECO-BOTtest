"""
routes/auth.py
---------------

API routes for authentication and business selection. These routes
delegate business logic to the corresponding service functions and
ensure the correct response models are returned. They mirror the
paths and HTTP methods of the original monolithic application.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.clients.http_client import HTTPClient
from app.logging_config import logger  # import logger for explicit logging; decorators removed
import json
from app.schemas.auth import LoginData, SeleccionNegocio
from app.services.auth_service import login_user, seleccionar_negocio

router = APIRouter()


from fastapi import Request


def get_http_client(request: Request) -> HTTPClient:
    """Dependency to retrieve the shared HTTP client from the application state."""
    return request.app.state.http_client


@router.post("/login-tecopos")
def login_tecopos(data: LoginData, http_client: HTTPClient = Depends(get_http_client)):
    # Log entry into the endpoint
    try:
        logger.info(json.dumps({
            "event": "login_tecopos_request",
            "usuario": data.usuario,
            "region": data.region,
        }))
    except Exception:
        # Ensure logging does not break functionality
        logger.info(json.dumps({"event": "login_tecopos_request"}))
    return login_user(data, http_client)


@router.post("/seleccionar-negocio")
def post_seleccionar_negocio(data: SeleccionNegocio, http_client: HTTPClient = Depends(get_http_client)):
    # Log entry into the endpoint
    try:
        logger.info(json.dumps({
            "event": "seleccionar_negocio_request",
            "usuario": data.usuario,
            "negocio": data.nombre_negocio,
        }))
    except Exception:
        logger.info(json.dumps({"event": "seleccionar_negocio_request"}))
    return seleccionar_negocio(data, http_client)

