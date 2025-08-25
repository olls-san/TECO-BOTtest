"""
routes/carga.py
----------------

Routes for managing inventory cargas (buy receipts) including creating
a carga with products, adding products to an existing carga, listing
available cargas and verifying product existence.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
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
def post_crear_carga_con_productos(data: CrearCargaConProductosRequest, http_client: HTTPClient = Depends(get_http_client):
    return crear_carga_con_productos(data, http_client)


@router.post("/entrada-productos-en-carga")
def post_entrada_productos_en_carga(data: EntradaProductosEnCargaRequest, http_client: HTTPClient = Depends(get_http_client):
    return entrada_productos_en_carga(data, http_client)


@router.get("/listar-cargas-disponibles")
def get_listar_cargas_disponibles(usuario: str, http_client: HTTPClient = Depends(get_http_client):
    return listar_cargas_disponibles(usuario, http_client)


@router.post("/verificar-productos-existen", response_model=ProductosFaltantesResponse)
def post_verificar_productos_existen(data: VerificarProductosRequest, http_client: HTTPClient = Depends(get_http_client):
    return verificar_productos_existen(data, http_client)

