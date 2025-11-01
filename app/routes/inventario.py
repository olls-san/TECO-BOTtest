"""
routes/inventario.py
--------------------

Route for totalling inventory and optionally emailing the report.
Provides query parameters to control emailing and output format.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

# Logging utilities
from app.logging_config import logger, log_call
import json
from typing import Optional
from app.clients.http_client import HTTPClient
from app.services.inventario_service import totalizar_inventario


router = APIRouter()


def get_http_client(request: Request) -> HTTPClient:
    return request.app.state.http_client


@router.get("/totalizar-inventario")
@log_call
def get_totalizar_inventario(
    usuario: str,
    enviar_por_correo: bool = Query(False),
    destinatario: Optional[str] = Query(None),
    formato: str = Query("excel", regex="^(excel|pdf)$"),
    http_client: HTTPClient = Depends(get_http_client),
) -> dict:
    """Totaliza el inventario del usuario y opcionalmente envía el reporte por correo."""
    try:
        logger.info(json.dumps({
            "event": "totalizar_inventario_request",
            "usuario": usuario,
            "enviar_por_correo": enviar_por_correo,
            "destinatario": bool(destinatario),
            "formato": formato,
        }))
    except Exception:
        pass
    try:
        resp = totalizar_inventario(usuario, enviar_por_correo, destinatario, formato, http_client)
        logger.info(json.dumps({
            "event": "totalizar_inventario_response",
            "usuario": usuario,
            "total_productos": resp.get("total"),
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "totalizar_inventario_error",
            "usuario": usuario,
            "detalle": str(e),
        }), exc_info=True)
        raise

