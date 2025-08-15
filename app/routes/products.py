"""
Product management endpoints.

This module encapsulates endpoints related to product creation and
inventory movements such as bulk entry of products.  Grouping these
operations into a dedicated router simplifies maintenance and
refactoring of product-related code without affecting other parts of
the API.
"""

from __future__ import annotations

from typing import List

import requests
from fastapi import APIRouter, HTTPException

from .. import models
from ..utils import (
    user_context,
    get_base_url,
    get_auth_headers,
    inferir_categoria,
    obtener_o_crear_categoria,
    crear_o_buscar_producto,
)

router = APIRouter()


@router.post("/crear-producto-con-categoria")
def crear_producto_con_categoria(data: models.Producto):
    """Create a new product with an inferred or specified category.

    If the user does not provide a category, the system will attempt to
    infer one based on the product name.  The endpoint requires the
    user to be authenticated and have selected a business; otherwise
    an HTTP 403 error is returned.
    """
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    categoria_nombre = data.categorias[0] if data.categorias else inferir_categoria(data.nombre)
    categoria_id = obtener_o_crear_categoria(categoria_nombre, base_url, headers)
    crear_url = f"{base_url}/api/v1/administration/product"
    crear_payload = {
        "type": data.tipo,
        "name": data.nombre,
        "prices": [
            {"price": data.precio, "codeCurrency": data.moneda}
        ],
        "images": [],
        "salesCategoryId": categoria_id,
    }
    crear_res = requests.post(crear_url, headers=headers, json=crear_payload)
    if crear_res.status_code not in [200, 201]:
        raise HTTPException(status_code=500, detail="No se pudo crear el producto")
    return {
        "status": "ok",
        "mensaje": f"Producto '{data.nombre}' creado en categoría '{categoria_nombre}'",
        "respuesta": crear_res.json(),
    }


@router.post("/entrada-inteligente")
def entrada_inteligente(data: models.EntradaInteligenteRequest):
    """Bulk entry of multiple products into a stock area, creating products on-demand.

    This endpoint accepts a list of products and either returns a list of
    available stock areas (if none was specified) or attempts to insert
    the products into the specified area.  Products that do not exist
    are created automatically.
    """
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    # If no stock area specified, return available stock areas
    if not data.stockAreaId:
        almacenes_url = f"{base_url}/api/v1/administration/area?type=STOCK"
        res = requests.get(almacenes_url, headers=headers)
        if res.status_code != 200:
            raise HTTPException(status_code=500, detail="No se pudieron obtener los almacenes")
        almacenes = res.json().get("items", [])
        return {
            "status": "ok",
            "mensaje": "Seleccione un área de stock",
            "almacenes": [{"id": a["id"], "nombre": a["name"]} for a in almacenes],
        }
    procesados: List[str] = []
    for prod in data.productos:
        producto_id = crear_o_buscar_producto(prod, base_url, headers)
        entrada_url = f"{base_url}/api/v1/administration/movement/bulk/entry"
        entrada_payload = {
            "products": [
                {"productId": producto_id, "quantity": prod.cantidad}
            ],
            "stockAreaId": data.stockAreaId,
            "continue": False,
        }
        entrada_res = requests.post(entrada_url, headers=headers, json=entrada_payload)
        if entrada_res.status_code not in [200, 201]:
            raise HTTPException(status_code=500, detail=f"No se pudo dar entrada a '{prod.nombre}'")
        procesados.append(prod.nombre)
    return {
        "status": "ok",
        "mensaje": "Productos procesados correctamente",
        "productos_procesados": procesados,
    }