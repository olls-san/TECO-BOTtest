"""
routes/currency.py
------------------

API route for bulk currency updates. Delegates to the currency
service and maintains the original behaviour of simulating changes
before applying them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

# Logging utilities
from app.logging_config import logger  # import only logger
import json
from app.clients.http_client import HTTPClient
from app.schemas.currency import CambioMonedaRequest
from app.services.currency_service import actualizar_monedas


router = APIRouter()


def get_http_client(request: Request) -> HTTPClient:
    return request.app.state.http_client


@router.post("/actualizar-monedas")
def post_actualizar_monedas(data: CambioMonedaRequest, http_client: HTTPClient = Depends(get_http_client)):
    """Actualiza o simula la actualización de monedas de forma masiva."""
    try:
        logger.info(json.dumps({
            "event": "actualizar_monedas_request",
            "usuario": data.usuario,
            "moneda_actual": data.moneda_actual,
            "moneda_deseada": data.moneda_deseada,
            "system_price_id": data.system_price_id,
            "confirmar": data.confirmar,
        }))
    except Exception:
        pass
    try:
        resp = actualizar_monedas(data, http_client)
        logger.info(json.dumps({
            "event": "actualizar_monedas_response",
            "usuario": data.usuario,
            "status": resp.get("status"),
            "mensaje": resp.get("mensaje"),
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "actualizar_monedas_error",
            "usuario": getattr(data, 'usuario', None),
            "detalle": str(e),
        }), exc_info=True)
        raise

