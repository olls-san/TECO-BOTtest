"""
routes/rendimiento.py
----------------------

API routes for computing yields of ice cream and yogurt production.
These endpoints call the corresponding service functions and return
structured responses.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

# Logging utilities
from app.logging_config import logger, log_call
import json
from app.clients.http_client import HTTPClient
from app.schemas.rendimiento import (
    RendimientoHeladoRequest,
    RendimientoYogurtRequest,
    RendimientoYogurtResponse,
)
from app.services.rendimiento_service import rendimiento_helado, rendimiento_yogurt


router = APIRouter()


def get_http_client(request: Request) -> HTTPClient:
    return request.app.state.http_client


@router.post("/rendimiento-helado")
@log_call
def post_rendimiento_helado(data: RendimientoHeladoRequest, http_client: HTTPClient = Depends(get_http_client)):
    """Calcula el rendimiento de producción de helado. Registra eventos de inicio y fin."""
    try:
        logger.info(json.dumps({
            "event": "rendimiento_helado_request",
            "usuario": data.usuario,
            "area_id": data.area_id,
            "cantidad_litros": data.cantidad_litros,
        }))
    except Exception:
        pass
    try:
        resp = rendimiento_helado(data, http_client)
        logger.info(json.dumps({
            "event": "rendimiento_helado_response",
            "usuario": data.usuario,
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "rendimiento_helado_error",
            "usuario": getattr(data, 'usuario', None),
            "detalle": str(e),
        }), exc_info=True)
        raise


@router.post("/rendimiento-yogurt", response_model=RendimientoYogurtResponse)
@log_call
def post_rendimiento_yogurt(data: RendimientoYogurtRequest, http_client: HTTPClient = Depends(get_http_client)):
    """Calcula el rendimiento de yogurt y registra eventos de inicio y fin."""
    try:
        logger.info(json.dumps({
            "event": "rendimiento_yogurt_request",
            "usuario": data.usuario,
            "area_id": data.area_id,
            "litros": data.litros,
            "porcentaje_solidos": data.porcentaje_solidos,
        }))
    except Exception:
        pass
    try:
        resp = rendimiento_yogurt(data, http_client)
        logger.info(json.dumps({
            "event": "rendimiento_yogurt_response",
            "usuario": data.usuario,
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "rendimiento_yogurt_error",
            "usuario": getattr(data, 'usuario', None),
            "detalle": str(e),
        }), exc_info=True)
        raise

