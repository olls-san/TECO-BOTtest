"""
routes/carga.py
----------------

Routes for managing inventory cargas (buy receipts) including creating
a carga with products, adding products to an existing carga, listing
available cargas and verifying product existence.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

# Logging utilities
from app.logging_config import logger, log_call
import json
from app.clients.http_client import HTTPClient
from app.schemas.carga import (
    CrearCargaConProductosRequest,
    EntradaProductosEnCargaRequest,
    VerificarProductosRequest,
    ProductosFaltantesResponse,
)
from app.services.carga_service import (
    crear_carga_con_productos,
    entrada_productos_en_carga,
    listar_cargas_disponibles,
    verificar_productos_existen,
)


router = APIRouter()


def get_http_client(request: Request) -> HTTPClient:
    return request.app.state.http_client


@router.post("/crear-carga-con-productos")
@log_call
def post_crear_carga_con_productos(data: CrearCargaConProductosRequest, http_client: HTTPClient = Depends(get_http_client)):
    """Crea una nueva carga con productos incluidos. Registra eventos de inicio y finalización."""
    try:
        logger.info(json.dumps({
            "event": "crear_carga_request",
            "usuario": data.usuario,
            "num_productos": len(data.productos) if data.productos else 0,
        }))
    except Exception:
        pass
    try:
        resp = crear_carga_con_productos(data, http_client)
        # Resumen de la respuesta
        logger.info(json.dumps({
            "event": "crear_carga_response",
            "usuario": data.usuario,
            "mensaje": resp.get("mensaje"),
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "crear_carga_error",
            "usuario": getattr(data, 'usuario', None),
            "detalle": str(e),
        }), exc_info=True)
        raise


@router.post("/entrada-productos-en-carga")
@log_call
def post_entrada_productos_en_carga(data: EntradaProductosEnCargaRequest, http_client: HTTPClient = Depends(get_http_client)):
    """Registra productos dentro de una carga existente. Registra eventos para trazabilidad."""
    try:
        logger.info(json.dumps({
            "event": "entrada_productos_en_carga_request",
            "usuario": data.usuario,
            "carga_id": data.carga_id,
            "num_productos": len(data.productos) if data.productos else 0,
        }))
    except Exception:
        pass
    try:
        resp = entrada_productos_en_carga(data, http_client)
        logger.info(json.dumps({
            "event": "entrada_productos_en_carga_response",
            "usuario": data.usuario,
            "registrados": len(resp.get("registrados", [])) if isinstance(resp.get("registrados"), list) else None,
            "errores": len(resp.get("errores", [])) if isinstance(resp.get("errores"), list) else None,
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "entrada_productos_en_carga_error",
            "usuario": getattr(data, 'usuario', None),
            "detalle": str(e),
        }), exc_info=True)
        raise


@router.get("/listar-cargas-disponibles")
@log_call
def get_listar_cargas_disponibles(usuario: str, http_client: HTTPClient = Depends(get_http_client)):
    """Lista cargas disponibles para el usuario y registra eventos de inicio y fin."""
    try:
        logger.info(json.dumps({
            "event": "listar_cargas_request",
            "usuario": usuario,
        }))
    except Exception:
        pass
    try:
        resp = listar_cargas_disponibles(usuario, http_client)
        logger.info(json.dumps({
            "event": "listar_cargas_response",
            "usuario": usuario,
            "num_cargas": len(resp.get("cargas_disponibles", [])) if isinstance(resp.get("cargas_disponibles"), list) else None,
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "listar_cargas_error",
            "usuario": usuario,
            "detalle": str(e),
        }), exc_info=True)
        raise


@router.post("/verificar-productos-existen", response_model=ProductosFaltantesResponse)
@log_call
def post_verificar_productos_existen(data: VerificarProductosRequest, http_client: HTTPClient = Depends(get_http_client)):
    """Verifica que una lista de productos exista en el sistema. Registra eventos clave."""
    try:
        logger.info(json.dumps({
            "event": "verificar_productos_request",
            "usuario": data.usuario,
            "num_nombres": len(data.nombres_productos) if data.nombres_productos else 0,
        }))
    except Exception:
        pass
    try:
        resp = verificar_productos_existen(data, http_client)
        logger.info(json.dumps({
            "event": "verificar_productos_response",
            "usuario": data.usuario,
            "productos_faltantes": len(resp.productos_faltantes),
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "verificar_productos_error",
            "usuario": getattr(data, 'usuario', None),
            "detalle": str(e),
        }), exc_info=True)
        raise

