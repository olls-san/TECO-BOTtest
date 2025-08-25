"""
routes/products.py
-------------------

API routes related to product creation and intelligent entries. These
routes orchestrate calls to the product service and preserve the
original API contracts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi import Request

from app.clients.http_client import HTTPClient
from app.schemas.products import Producto, EntradaInteligenteRequest
from app.services.product_service import crear_producto_con_categoria, entrada_inteligente


router = APIRouter()


def get_http_client(request: Request) -> HTTPClient:
    return request.app.state.http_client


@router.post("/crear-producto-con-categoria")
def post_crear_producto_con_categoria(data: Producto, http_client: HTTPClient = Depends(get_http_client)):
    return crear_producto_con_categoria(data, http_client)


@router.post("/entrada-inteligente")
def post_entrada_inteligente(data: EntradaInteligenteRequest, http_client: HTTPClient = Depends(get_http_client)):
    return entrada_inteligente(data, http_client)
