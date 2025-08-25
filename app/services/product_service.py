"""
services/product_service.py
---------------------------

Contains business logic for creating products, intelligent entries and
categorisation. These functions leverage the shared HTTP client and
centralised authentication helpers to perform API calls. The goal is
to keep the route handlers thin and delegate complex flows to this
module.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
from fastapi import HTTPException

from app.core.auth import get_base_url, build_auth_headers
from app.core.context import get_user_context
from app.clients.http_client import HTTPClient
from app.schemas.products import Producto, ProductoEntradaInteligente, EntradaInteligenteRequest

from collections import defaultdict


# Keyword mappings used to infer sales categories
CATEGORIA_KEYWORDS: Dict[str, List[str]] = {
    "Alimentos Básicos": ["arroz", "frijol", "azúcar", "sal", "aceite", "granos"],
    "Panadería y Confitería": ["galleta", "pan", "pastel", "bizcocho", "dulce", "biscocho"],
    "Lácteos": ["leche", "queso", "yogurt", "mantequilla", "nata"],
    "Carnes y Embutidos": ["pollo", "carne", "res", "cerdo", "salchicha", "jamón", "embutido"],
    "Bebidas Alcohólicas": ["cerveza", "ron", "vino", "whisky", "tequila"],
    "Refrescos": ["refresco", "soda", "jugos", "cola", "malta", "fanta"],
    "Limpieza": ["detergente", "cloro", "jabón", "desinfectante", "limpiador"],
    "Higiene Personal": ["shampoo", "cepillo", "crema dental", "pasta", "afeitar", "pañal"],
}


def normalizar(texto: str) -> str:
    return texto.strip().lower()


def inferir_categoria(nombre: str) -> str:
    nombre_norm = normalizar(nombre)
    for categoria, palabras_clave in CATEGORIA_KEYWORDS.items():
        if any(p in nombre_norm for p in palabras_clave):
            return categoria
    return "Mercado"


def obtener_o_crear_categoria(nombre_categoria: str, base_url: str, headers: Dict[str, str], http_client: HTTPClient) -> int:
    """Retrieve or create a sales category by name.

    Performs a GET to list categories and tries to find a match; if not
    present, sends a POST to create the category and returns the new
    ID. A final GET confirms the creation. Errors during API calls
    result in HTTP exceptions.
    """
    cat_url = f"{base_url}/api/v1/administration/salescategory"
    res = http_client.request("GET", cat_url, headers=headers)
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudieron consultar las categorías")
    categorias = res.json().get("items", [])
    existente = next((c for c in categorias if normalizar(c.get("name", "")) == normalizar(nombre_categoria)), None)
    if existente:
        return existente["id"]
    # create category
    crear_res = http_client.request("POST", cat_url, headers=headers, json={"name": nombre_categoria})
    if crear_res.status_code not in [200, 201]:
        raise HTTPException(status_code=500, detail="No se pudo crear la categoría")
    # fetch again to confirm
    res = http_client.request("GET", cat_url, headers=headers)
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudieron volver a consultar las categorías")
    categorias = res.json().get("items", [])
    creada = next((c for c in categorias if normalizar(c.get("name", "")) == normalizar(nombre_categoria)), None)
    if not creada:
        raise HTTPException(status_code=500, detail="Categoría creada pero no encontrada")
    return creada["id"]


def crear_o_buscar_producto(producto: ProductoEntradaInteligente, base_url: str, headers: Dict[str, str], http_client: HTTPClient) -> int:
    """Find an existing product by name or create a new one.

    Searches for a product with the same normalised name. If found,
    returns its ID. Otherwise, infers a category, creates the product
    and returns the newly created ID.
    """
    nombre_norm = normalizar(producto.nombre)
    search_url = f"{base_url}/api/v1/administration/product?search={producto.nombre}"
    res = http_client.request("GET", search_url, headers=headers)
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail=f"No se pudo buscar '{producto.nombre}'")
    items = res.json().get("items", [])
    existente = next((p for p in items if normalizar(p.get("name", "")) == nombre_norm), None)
    if existente:
        return existente["id"]
    # create new product
    categoria_id = obtener_o_crear_categoria(inferir_categoria(producto.nombre), base_url, headers, http_client)
    crear_url = f"{base_url}/api/v1/administration/product"
    crear_payload = {
        "type": "STOCK",
        "name": producto.nombre,
        "prices": [{"price": producto.precio, "codeCurrency": producto.moneda}],
        "images": [],
        "salesCategoryId": categoria_id,
    }
    crear_res = http_client.request("POST", crear_url, headers=headers, json=crear_payload)
    if crear_res.status_code not in [200, 201]:
        raise HTTPException(status_code=500, detail=f"No se pudo crear '{producto.nombre}'")
    return crear_res.json().get("id")


def crear_producto_con_categoria(data: Producto, http_client: HTTPClient) -> Dict[str, Any]:
    """Create a new product under a specific or inferred category.

    :param data: product definition submitted by the client
    :param http_client: shared HTTP client
    :raises HTTPException: if the user is not authenticated or API calls fail
    :return: response payload
    """
    ctx = get_user_context(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    categoria_nombre = data.categorias[0] if data.categorias else inferir_categoria(data.nombre)
    categoria_id = obtener_o_crear_categoria(categoria_nombre, base_url, headers, http_client)
    crear_url = f"{base_url}/api/v1/administration/product"
    crear_payload = {
        "type": data.tipo,
        "name": data.nombre,
        "prices": [
            {
                "price": data.precio,
                "codeCurrency": data.moneda,
            }
        ],
        "images": [],
        "salesCategoryId": categoria_id,
    }
    crear_res = http_client.request("POST", crear_url, headers=headers, json=crear_payload)
    if crear_res.status_code not in [200, 201]:
        raise HTTPException(status_code=500, detail="No se pudo crear el producto")
    return {
        "status": "ok",
        "mensaje": f"Producto '{data.nombre}' creado en categoría '{categoria_nombre}'",
        "respuesta": crear_res.json(),
    }


def entrada_inteligente(data: EntradaInteligenteRequest, http_client: HTTPClient) -> Dict[str, Any]:
    """Process an intelligent stock entry (bulk entry).

    If ``stockAreaId`` is not provided, the list of available stock areas
    is returned. Otherwise, each product is looked up or created and
    then a bulk entry is posted. Errors during the process raise
    HTTP exceptions.
    """
    ctx = get_user_context(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    # If no stockAreaId provided, list available warehouses
    if not data.stockAreaId:
        almacenes_url = f"{base_url}/api/v1/administration/area?type=STOCK"
        res = http_client.request("GET", almacenes_url, headers=headers)
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
        producto_id = crear_o_buscar_producto(prod, base_url, headers, http_client)
        entrada_url = f"{base_url}/api/v1/administration/movement/bulk/entry"
        entrada_payload = {
            "products": [
                {"productId": producto_id, "quantity": prod.cantidad}
            ],
            "stockAreaId": data.stockAreaId,
            "continue": False,
        }
        entrada_res = http_client.request("POST", entrada_url, headers=headers, json=entrada_payload)
        if entrada_res.status_code not in [200, 201]:
            raise HTTPException(status_code=500, detail=f"No se pudo dar entrada a '{prod.nombre}'")
        procesados.append(prod.nombre)
    return {
        "status": "ok",
        "mensaje": "Productos procesados correctamente",
        "productos_procesados": procesados,
    }