"""
routes/products.py
-------------------

API routes related to product creation and intelligent entries. These
routes orchestrate calls to the product service and preserve the
original API contracts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

# Logger y utilidades de logging
from app.logging_config import logger, log_call
import json

from app.clients.http_client import HTTPClient
from app.schemas.products import Producto, EntradaInteligenteRequest
from app.services.product_service import (
    crear_producto_con_categoria,
    entrada_inteligente,
    crear_productos_teco_batch,   # <-- NUEVO: batch cliente
)

router = APIRouter()


def get_http_client(request: Request) -> HTTPClient:
    return request.app.state.http_client


@router.post("/crear-producto-con-categoria")
@log_call
def post_crear_producto_con_categoria(payload: dict, http_client: HTTPClient = Depends(get_http_client)):
    """
    Modo mixto:
    - Si ``items`` existe y es lista → crea múltiples productos (batch cliente).
    - Si ``items`` no existe → crea un único producto (modo clásico con Producto).
    Esta función registra eventos de inicio y fin para facilitar trazabilidad.
    """
    usuario = payload.get("usuario")
    if not usuario:
        raise HTTPException(status_code=422, detail="Falta 'usuario'.")
    items = payload.get("items")
    try:
        logger.info(json.dumps({
            "event": "crear_producto_con_categoria_request",
            "usuario": usuario,
            "modo": "batch" if isinstance(items, list) else "single",
            "num_items": len(items) if isinstance(items, list) else 1,
        }))
    except Exception:
        pass
    # Branch for batch creation
    if isinstance(items, list):
        try:
            resultado = crear_productos_teco_batch(usuario, items, http_client)
            logger.info(json.dumps({
                "event": "crear_producto_con_categoria_response",
                "usuario": usuario,
                "modo": "batch",
                "total_creados": len(resultado) if isinstance(resultado, list) else None,
            }))
            return resultado
        except Exception as e:
            logger.error(json.dumps({
                "event": "crear_producto_con_categoria_error",
                "usuario": usuario,
                "detalle": str(e),
            }), exc_info=True)
            raise
    # Branch for single creation
    nombre = payload.get("nombre") or payload.get("name")
    if not nombre:
        raise HTTPException(status_code=422, detail="Falta 'nombre' (o 'name').")
    data = Producto(
        usuario=usuario,
        nombre=nombre,
        precio=payload.get("precio") or 0,
        costo=payload.get("costo"),
        moneda=payload.get("moneda") or "USD",
        tipo=payload.get("tipo") or payload.get("type") or "STOCK",
        categorias=payload.get("categorias") or [],
    )
    try:
        respuesta = crear_producto_con_categoria(data, http_client)
        logger.info(json.dumps({
            "event": "crear_producto_con_categoria_response",
            "usuario": usuario,
            "modo": "single",
            "producto": nombre,
        }))
        return respuesta
    except Exception as e:
        # el servicio ya registra detalles; aquí solo anotamos la excepción
        logger.error(json.dumps({
            "event": "crear_producto_con_categoria_error",
            "usuario": usuario,
            "modo": "single",
            "detalle": str(e),
        }), exc_info=True)
        raise


@router.post("/entrada-inteligente")
@log_call
def post_entrada_inteligente(data: EntradaInteligenteRequest, http_client: HTTPClient = Depends(get_http_client)):
    """
    Endpoint para procesar una entrada inteligente de productos en stock.
    Registra eventos de inicio y finalización para diagnosticar cuántos
    productos se procesaron y si se solicitó la selección de área de stock.
    """
    try:
        logger.info(json.dumps({
            "event": "entrada_inteligente_request",
            "usuario": data.usuario,
            "stockAreaId": data.stockAreaId,
            "num_productos": len(data.productos) if data.productos else 0,
        }))
    except Exception:
        pass
    try:
        respuesta = entrada_inteligente(data, http_client)
        # resumir la respuesta para evitar log de grandes estructuras
        resumen = {
            "status": respuesta.get("status"),
            "mensaje": respuesta.get("mensaje"),
            "productos_procesados": len(respuesta.get("productos_procesados", [])) if isinstance(respuesta.get("productos_procesados"), list) else None,
        }
        logger.info(json.dumps({
            "event": "entrada_inteligente_response",
            "usuario": data.usuario,
            **resumen,
        }))
        return respuesta
    except Exception as e:
        logger.error(json.dumps({
            "event": "entrada_inteligente_error",
            "usuario": getattr(data, 'usuario', None),
            "detalle": str(e),
        }), exc_info=True)
        raise

