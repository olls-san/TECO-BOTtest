"""
routes/dispatch.py
-------------------

API routes for dispatch operations, including replicating products
between stock areas. This route follows the multiâ€‘step flow of
soliciting business IDs, stock areas and then performing the
replication.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

# Logging utilities
from app.logging_config import logger, log_call
import json
from app.clients.http_client import HTTPClient
from app.schemas.dispatch import ReplicarProductosRequest
from app.services.dispatch_service import replicar_productos


router = APIRouter()


def get_http_client(request: Request) -> HTTPClient:
    return request.app.state.http_client


@router.post("/replicar-productos", summary="Replicar productos entre negocios mediante despacho Tecopos", tags=["Despachos"])
@log_call
def post_replicar_productos(data: ReplicarProductosRequest, http_client: HTTPClient = Depends(get_http_client)):
    """Inicia la replicación de productos entre negocios mediante un despacho Tecopos."""
    try:
        logger.info(json.dumps({
            "event": "replicar_productos_request",
            "usuario": data.usuario,
            "negocio_origen_id": data.negocio_origen_id,
            "negocio_destino_id": data.negocio_destino_id,
            "area_origen_nombre": data.area_origen_nombre,
            "area_destino_nombre": data.area_destino_nombre,
            "filtro_categoria": data.filtro_categoria,
        }))
    except Exception:
        pass
    try:
        resp = replicar_productos(data, http_client)
        logger.info(json.dumps({
            "event": "replicar_productos_response",
            "usuario": data.usuario,
            "mensaje": resp.get("mensaje"),
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "replicar_productos_error",
            "usuario": getattr(data, 'usuario', None),
            "detalle": str(e),
        }), exc_info=True)
        raise

