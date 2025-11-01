"""
services/carga_service.py
------------------------

Implements the inventory carga workflows: creating a new carga with a
set of products, adding products to an existing carga, listing
available cargas and verifying product existence. The functions here
perform the necessary Tecopos API calls and transform request
payloads into the expected formats.
"""

from __future__ import annotations

from typing import Dict, Any, List
from datetime import datetime
from fastapi import HTTPException

from app.core.context import get_user_context
from app.core.auth import get_base_url, build_auth_headers
from app.clients.http_client import HTTPClient
from app.logging_config import logger, log_call
import json
from app.schemas.carga import (
    CrearCargaConProductosRequest,
    ProductoCarga,
    EntradaProductosEnCargaRequest,
    VerificarProductosRequest,
    ProductosFaltantesResponse,
    ProductoEntradaCarga,
)


def buscar_producto(ctx: Dict[str, Any], code: str, http_client: HTTPClient) -> Dict[str, Any] | None:
    url = f"{get_base_url(ctx['region'])}/api/v1/administration/product/search?code={code}"
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    r = http_client.request("GET", url, headers=headers)
    if r.status_code == 200 and r.json():
        return r.json()[0]
    return None


def crear_categoria_si_no_existe(ctx: Dict[str, Any], nombre_categoria: str, http_client: HTTPClient) -> int:
    url = f"{get_base_url(ctx['region'])}/api/v1/administration/salescategory"
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    # try create
    r = http_client.request("POST", url, json={"name": nombre_categoria}, headers=headers)
    if r.status_code == 200:
        return r.json()["id"]
    elif r.status_code == 409:
        return r.json()["id"]
    else:
        raise HTTPException(status_code=r.status_code, detail=r.text)


def crear_producto(ctx: Dict[str, Any], producto: ProductoCarga, categoria_id: int, http_client: HTTPClient) -> int:
    url = f"{get_base_url(ctx['region'])}/api/v1/administration/product"
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    payload = {
        "name": producto.name,
        "code": producto.code,
        "price": producto.price,
        "codeCurrency": producto.codeCurrency,
        "cost": producto.cost,
        "unit": producto.unit,
        "iva": producto.iva,
        "barcode": producto.barcode,
        "categoryId": categoria_id,
    }
    r = http_client.request("POST", url, json=payload, headers=headers)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()["id"]


@log_call
def crear_carga_con_productos(data: CrearCargaConProductosRequest, http_client: HTTPClient) -> Dict[str, Any]:
    ctx = get_user_context(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    batches: List[Dict[str, Any]] = []
    for prod in data.productos:
        encontrado = buscar_producto(ctx, prod.code, http_client)
        if encontrado:
            product_id = encontrado["id"]
        else:
            categoria_id = crear_categoria_si_no_existe(ctx, prod.category or "Sin categoría", http_client)
            product_id = crear_producto(ctx, prod, categoria_id, http_client)
        batches.append({
            "productId": product_id,
            "quantity": prod.quantity,
            "cost": {"amount": prod.cost, "codeCurrency": prod.codeCurrency},
            "expirationAt": prod.expirationAt,
            "noPackages": prod.noPackages,
            "uniqueCode": prod.lote,
        })
    payload = {
        "name": data.name,
        "observations": data.observations,
        "batches": batches,
        "listDocuments": [],
        "operationsCosts": [],
    }
    url = f"{base_url}/api/v1/administration/buyedreceipt/v2"
    r = http_client.request("POST", url, json=payload, headers=headers)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return {
        "mensaje": "Carga creada con éxito y productos registrados",
        "respuesta": r.json(),
    }


def buscar_producto_por_nombre(ctx: Dict[str, Any], nombre: str, http_client: HTTPClient) -> Dict[str, Any] | None:
    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    url = f"{base_url}/api/v1/administration/product?search={nombre}"
    r = http_client.request("GET", url, headers=headers)
    if r.status_code == 200:
        data = r.json()
        productos = data.get("items", []) if isinstance(data, dict) else []
        for p in productos:
            if isinstance(p, dict) and p.get("name", "").strip().lower() == nombre.strip().lower():
                return p
    return None


def registrar_producto_en_carga(ctx: Dict[str, Any], carga_id: int, product_id: int, prod: ProductoEntradaCarga, http_client: HTTPClient) -> None:
    url = f"{get_base_url(ctx['region'])}/api/v1/administration/buyedReceipt/batch/{carga_id}"
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    lote = getattr(prod, "lote", None) or f"LOTE-{product_id}"
    code_currency = getattr(prod, "codeCurrency", "USD")
    amount = getattr(prod, "price", 0)
    expiration = prod.expirationAt.isoformat() if isinstance(prod.expirationAt, datetime) else prod.expirationAt
    payload = {
        "productId": product_id,
        "quantity": getattr(prod, "quantity", 1),
        "expirationAt": expiration,
        "noPackages": getattr(prod, "noPackages", 1),
        "registeredPrice": {"amount": amount, "codeCurrency": code_currency},
        "uniqueCode": lote,
    }
    response = http_client.request("POST", url, json=payload, headers=headers)
    if response.status_code not in [200, 201]:
        raise Exception(f"Error al registrar '{getattr(prod, 'name', 'Desconocido')}': {response.status_code} - {response.text}")


@log_call
def entrada_productos_en_carga(data: EntradaProductosEnCargaRequest, http_client: HTTPClient) -> Dict[str, Any]:
    ctx = get_user_context(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    productos_faltantes: List[str] = []
    productos_validos: List[tuple] = []
    for prod in data.productos:
        existente = buscar_producto_por_nombre(ctx, prod.name, http_client)
        if not existente:
            productos_faltantes.append(prod.name)
        else:
            productos_validos.append((existente["id"], prod))
    if productos_faltantes:
        raise HTTPException(status_code=400, detail={
            "mensaje": "Algunos productos no existen en el sistema.",
            "productos_faltantes": productos_faltantes,
        })
    errores: List[str] = []
    exitosos: List[str] = []
    for product_id, prod in productos_validos:
        try:
            registrar_producto_en_carga(ctx, data.carga_id, product_id, prod, http_client)
            exitosos.append(prod.name)
        except Exception as e:
            errores.append(str(e))
    return {
        "mensaje": "Proceso completado",
        "registrados": exitosos,
        "errores": errores,
    }


@log_call
def listar_cargas_disponibles(usuario: str, http_client: HTTPClient) -> Dict[str, Any]:
    ctx = get_user_context(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    cargas: List[Dict[str, Any]] = []
    pagina = 1
    while True:
        url = f"{base_url}/api/v1/administration/buyedreceipt?page={pagina}"
        r = http_client.request("GET", url, headers=headers)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        data = r.json()
        items = data.get("items", [])
        for carga in items:
            cargas.append({
                "id": carga["id"],
                "name": carga["name"],
                "status": carga["status"],
                "createdAt": carga["createdAt"],
            })
        if pagina >= data.get("totalPages", 1):
            break
        pagina += 1
    return {"cargas_disponibles": cargas}


def verificar_productos_existen(data: VerificarProductosRequest, http_client: HTTPClient) -> ProductosFaltantesResponse:
    ctx = get_user_context(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    nombres_faltantes: List[str] = []
    for nombre in data.nombres_productos:
        producto = buscar_producto_por_nombre(ctx, nombre, http_client)
        if not producto:
            nombres_faltantes.append(nombre)
    return ProductosFaltantesResponse(productos_faltantes=nombres_faltantes)