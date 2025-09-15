"""
routes/products.py
-------------------

API routes related to product creation and intelligent entries. These
routes orchestrate calls to the product service and preserve the
original API contracts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Request

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
def post_crear_producto_con_categoria(payload: dict, http_client: HTTPClient = Depends(get_http_client)):
    """
    Modo mixto:
    - Si 'items' existe y es lista -> crea múltiples productos (batch cliente).
    - Si 'items' no está -> crea un único producto (modo clásico con Producto).
    """
    usuario = payload.get("usuario")
    if not usuario:
        raise HTTPException(status_code=422, detail="Falta 'usuario'.")

    items = payload.get("items")
    if isinstance(items, list):
        # ---- Batch (iteramos uno a uno en el servicio) ----
        return crear_productos_teco_batch(usuario, items, http_client)

    # ---- Single (clásico) ----
    # Mapeamos alias comunes para mantener compatibilidad:
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
    return crear_producto_con_categoria(data, http_client)


@router.post("/entrada-inteligente")
def post_entrada_inteligente(data: EntradaInteligenteRequest, http_client: HTTPClient = Depends(get_http_client)):
    return entrada_inteligente(data, http_client)



@router.post("/entrada-inteligente")
def post_entrada_inteligente(data: EntradaInteligenteRequest, http_client: HTTPClient = Depends(get_http_client)):
    return entrada_inteligente(data, http_client)

