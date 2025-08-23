"""
Utility functions and constants for the Tecopos API wrapper.

This module provides reusable helpers for interacting with the Tecopos
administration API, such as building authentication headers, mapping
business types to recommended forecasting models, and normalising
strings. Centralising these functions avoids duplication across
endpoints and improves maintainability.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# Use the shared HTTP client with retries and timeouts instead of direct requests
from app.core.http_sync import teco_request
from fastapi import HTTPException


# Import the shared user_context from the session module.  Do not
# define a local user_context here otherwise multiple modules will end
# up with distinct dictionaries.  Centralising the context in
# ``app/session.py`` ensures that all routes and helpers share the
# same in-memory session store.
from .session import user_context  # noqa: F401  re-export for backwards compatibility

# Note: ``user_context`` is now provided by ``app.session``.  The
# import above re-exports it under this module for backwards
# compatibility with existing imports (e.g. ``from ..utils import
# user_context``).  When modifying this file please do not assign
# directly to ``user_context``; instead import it from ``app.session``.


# -----------------------------------------------------------------------------
# Configuration for projections and category inference
# -----------------------------------------------------------------------------

# Recommended forecasting models and history windows for each business type.
TIPOS_NEGOCIO: Dict[str, Dict[str, object]] = {
    "Punto de Venta (Minorista de barrio)": {
        "historial_recomendado_dias": 30,
        "proyeccion_recomendada": "media_movil",
        "descripcion_modelo": "Promedio de ventas recientes. Ideal para productos de consumo diario."
    },
    "Restaurante o Bar": {
        "historial_recomendado_dias": 15,
        "proyeccion_recomendada": "suavizado_exponencial",
        "descripcion_modelo": "Pone más peso en ventas recientes. Útil para demanda variable."
    },
    "Mayorista": {
        "historial_recomendado_dias": 60,
        "proyeccion_recomendada": "tendencia_lineal",
        "descripcion_modelo": "Detecta crecimiento o caída en ventas y lo proyecta hacia adelante."
    },
    "Mercado": {
        "historial_recomendado_dias": 30,
        "proyeccion_recomendada": "media_movil",
        "descripcion_modelo": "Promedia ventas frecuentes. Útil para productos de rotación rápida."
    },
    "Refrigerados (Cárnicos)": {
        "historial_recomendado_dias": 45,
        "proyeccion_recomendada": "lineal",
        "descripcion_modelo": "Proyección basada en tendencia lineal simple. Requiere historial estable."
    },
}

# Keywords used to infer product categories from names.  If a product name
# contains any of the keywords associated with a category the first
# matching category will be chosen.
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


# -----------------------------------------------------------------------------
# URL helpers
# -----------------------------------------------------------------------------

def get_origin_url(region: str) -> str:
    """Return the appropriate origin URL for the given region.

    The origin is used as part of the request headers when making API calls.
    If the region is not recognised an HTTPException will be raised.
    """
    region_clean = region.lower().strip()
    if region_clean == "apidev":
        return "https://admindev.tecopos.com"
    if region_clean == "api1":
        return "https://admin.tecopos.com"
    if region_clean in [f"api{i}" for i in range(5)] or region_clean == "api0":
        return "https://admin.tecopos.com"
    raise HTTPException(status_code=400, detail="Región inválida")


def get_base_url(region: str) -> str:
    """Return the base API URL for a region.

    If the region is unrecognised an HTTPException is raised.
    """
    region_clean = region.lower().strip()
    if region_clean == "apidev":
        return "https://apidev.tecopos.com"
    if region_clean == "api1":
        return "https://api.tecopos.com"
    if region_clean in [f"api{i}" for i in range(5)] or region_clean == "api0":
        return f"https://{region_clean}.tecopos.com"
    raise HTTPException(status_code=400, detail="Región inválida")


def get_auth_headers(token: str, business_id: int, region: str) -> Dict[str, str]:
    """Construct authentication and metadata headers for API requests."""
    origin = get_origin_url(region)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": origin,
        "Referer": origin + "/",
        "x-app-businessid": str(business_id),
        "x-app-origin": "Tecopos-Admin",
        "User-Agent": "Mozilla/5.0",
    }


# -----------------------------------------------------------------------------
# String and category helpers
# -----------------------------------------------------------------------------

def normalizar(texto: str) -> str:
    """Normalise text by stripping whitespace and converting to lowercase."""
    return texto.strip().lower()


def inferir_categoria(nombre: str) -> str:
    """Infer the sales category from a product name using CATEGORIA_KEYWORDS."""
    nombre_norm = normalizar(nombre)
    for categoria, palabras in CATEGORIA_KEYWORDS.items():
        if any(p in nombre_norm for p in palabras):
            return categoria
    return "Mercado"


def obtener_o_crear_categoria(nombre_categoria: str, base_url: str, headers: Dict[str, str]) -> int:
    """Ensure a sales category exists and return its identifier.

    If the category is not present it is created via the API. Any errors
    during creation or retrieval will raise an HTTPException.
    """
    cat_url = f"{base_url}/api/v1/administration/salescategory"
    # Use teco_request for GET requests
    res = teco_request("GET", cat_url, headers=headers)
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudieron consultar las categorías")
    categorias = res.json().get("items", [])
    existente = next((c for c in categorias if normalizar(c.get("name", "")) == normalizar(nombre_categoria)), None)
    if existente:
        return existente["id"]
    crear_res = teco_request("POST", cat_url, headers=headers, json={"name": nombre_categoria})
    if crear_res.status_code not in [200, 201]:
        raise HTTPException(status_code=500, detail="No se pudo crear la categoría")
    # Re-fetch categories to obtain the new id
    res = teco_request("GET", cat_url, headers=headers)
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudieron volver a consultar las categorías")
    categorias = res.json().get("items", [])
    creada = next((c for c in categorias if normalizar(c.get("name", "")) == normalizar(nombre_categoria)), None)
    if not creada:
        raise HTTPException(status_code=500, detail="Categoría creada pero no encontrada")
    return creada["id"]


# -----------------------------------------------------------------------------
# Forecasting helpers
# -----------------------------------------------------------------------------

def aplicar_modelo_proyeccion(ventas_diarias: List[Dict[str, object]], modelo: str) -> List[Dict[str, object]]:
    """Compute sales projections for each product based on daily sales data.

    The ``ventas_diarias`` argument should be a list where each element has
    a ``productos`` key containing a list of dictionaries with keys
    ``productId`` and ``quantitySales``. The projection method is selected
    by the ``modelo`` argument.
    """
    from collections import defaultdict

    ventas_por_producto: Dict[int, List[float]] = defaultdict(list)
    for dia in ventas_diarias:
        for p in dia.get("productos", []):
            ventas_por_producto[p["productId"]].append(p["quantitySales"])
    proyecciones: List[Dict[str, object]] = []
    for product_id, cantidades in ventas_por_producto.items():
        if modelo == "media_movil":
            proy = sum(cantidades[-7:]) / min(len(cantidades), 7)
        elif modelo == "lineal":
            proy = (cantidades[-1] - cantidades[0]) / max(len(cantidades) - 1, 1)
        elif modelo == "tendencia_lineal":
            proy = (cantidades[-1] - cantidades[0]) / max(len(cantidades) - 1, 1) + cantidades[-1]
        elif modelo == "suavizado_exponencial":
            alpha = 0.3
            s = cantidades[0]
            for y in cantidades[1:]:
                s = alpha * y + (1 - alpha) * s
            proy = s
        else:
            proy = cantidades[-1]
        proyecciones.append({"productId": product_id, "cantidad_proyectada": round(proy, 2)})
    return proyecciones


def enriquecer_proyeccion_con_nombres(usuario: str, proyeccion: List[Dict[str, object]], base_url: str, headers: Dict[str, str]) -> List[Dict[str, object]]:
    """Add product names to a projection result.

    This helper retrieves all products for the given business and maps
    product IDs to names. The resulting list is returned with an added
    ``nombre`` key per item.
    """
    productos_map: Dict[int, str] = {}
    pagina = 1
    while True:
        url = f"{base_url}/api/v1/administration/product?page={pagina}"
        resp = teco_request("GET", url, headers=headers)
        resp_json = resp.json()
        productos = resp_json.get("items", [])
        if not productos:
            break
        for p in productos:
            productos_map[p["id"]] = p["name"]
        pagina += 1
    for item in proyeccion:
        pid = item["productId"]
        item["nombre"] = productos_map.get(pid, f"Producto {pid}")
    return proyeccion


# -----------------------------------------------------------------------------
# Product helpers
# -----------------------------------------------------------------------------

def crear_o_buscar_producto(producto: "ProductoEntradaInteligente", base_url: str, headers: Dict[str, str]) -> int:
    """Find a product by name or create it if it doesn't exist.

    This helper searches for an existing product by its name using the
    ``search`` parameter of the API. If it is not found a new product is
    created with an inferred category.
    """
    nombre_norm = normalizar(producto.nombre)
    search_url = f"{base_url}/api/v1/administration/product?search={producto.nombre}"
    res = teco_request("GET", search_url, headers=headers)
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail=f"No se pudo buscar '{producto.nombre}'")
    items = res.json().get("items", [])
    existente = next((p for p in items if normalizar(p.get("name", "")) == nombre_norm), None)
    if existente:
        return existente["id"]
    # If not found, create the product
    categoria_id = obtener_o_crear_categoria(inferir_categoria(producto.nombre), base_url, headers)
    crear_url = f"{base_url}/api/v1/administration/product"
    crear_payload = {
        "type": "STOCK",
        "name": producto.nombre,
        "prices": [
            {"price": producto.precio, "codeCurrency": producto.moneda}
        ],
        "images": [],
        "salesCategoryId": categoria_id,
    }
    crear_res = teco_request("POST", crear_url, headers=headers, json=crear_payload)
    if crear_res.status_code not in [200, 201]:
        raise HTTPException(status_code=500, detail=f"No se pudo crear '{producto.nombre}'")
    return crear_res.json().get("id")


# -----------------------------------------------------------------------------
# Reporting and analysis helpers
# -----------------------------------------------------------------------------

def analizar_desempeño_ventas(productos: List[Dict[str, object]]) -> Dict[str, object]:
    """Generate a performance summary from a list of product sales."""
    if not productos:
        return {"mensaje": "No hubo ventas en el rango seleccionado."}
    total_ventas = sum(p["total_ventas"] for p in productos)
    total_unidades = sum(p["cantidad_vendida"] for p in productos)
    ticket_promedio = total_ventas / len(productos) if productos else 0
    top_cantidad = sorted(productos, key=lambda p: p["cantidad_vendida"], reverse=True)[:5]
    top_ingreso = sorted(productos, key=lambda p: p["total_ventas"], reverse=True)[:5]
    productos_con_ganancia = []
    for p in productos:
        total_cost = p.get("total_cost", 0) or 0
        ganancia = p["total_ventas"] - total_cost
        productos_con_ganancia.append({"nombre": p["nombre"], "ganancia": ganancia, "moneda": p["moneda"]})
    top_ganancia = sorted(productos_con_ganancia, key=lambda x: x["ganancia"], reverse=True)[:5]
    return {
        "resumen": {
            "total_vendido": f"{total_ventas:.2f} {productos[0]['moneda']}",
            "total_unidades_vendidas": total_unidades,
            "ticket_promedio_por_producto": f"{ticket_promedio:.2f} {productos[0]['moneda']}",
            "top_5_mas_vendidos": [
                {"nombre": p["nombre"], "cantidad": p["cantidad_vendida"]} for p in top_cantidad
            ],
            "top_5_mayor_ingreso": [
                {"nombre": p["nombre"], "ingreso": f"{p['total_ventas']} {p['moneda']}"} for p in top_ingreso
            ],
            "top_5_mayor_ganancia": [
                {"nombre": p["nombre"], "ganancia": f"{p['ganancia']} {p['moneda']}"} for p in top_ganancia
            ],
        }
    }


# -----------------------------------------------------------------------------
# Misc helpers
# -----------------------------------------------------------------------------

def extraer_sabor(nombre_producto: str) -> str:
    """Extract the flavour name from a mix product name.

    For example, "Mezcla 🍓🍦" becomes an empty string and
    "Mezcla Fresa" becomes "Fresa". If no flavour is detected the original
    string is returned. This helper is used by ice cream and yogurt
    efficiency endpoints.
    """
    partes = nombre_producto.split("Mezcla")
    if len(partes) > 1:
        return partes[1].strip(" 🍓🍦").strip()
    return nombre_producto


def buscar_producto(ctx: Dict[str, object], code: str) -> Optional[Dict[str, object]]:
    """Search for a product by its code. Returns the first match or None."""
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    url = f"{base_url}/api/v1/administration/product/search?code={code}"
    r = teco_request("GET", url, headers=headers)
    if r.status_code == 200 and r.json():
        return r.json()[0]
    return None


def crear_categoria_si_no_existe(ctx: Dict[str, object], nombre_categoria: str) -> int:
    """Ensure a sales category exists for the current business and return its id."""
    url = f"{get_base_url(ctx['region'])}/api/v1/administration/salescategory"
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    r = teco_request("POST", url, headers=headers, json={"name": nombre_categoria})
    if r.status_code == 200:
        return r.json()["id"]
    elif r.status_code == 409:
        return r.json()["id"]
    else:
        raise HTTPException(status_code=r.status_code, detail=r.text)


def crear_producto(ctx: Dict[str, object], producto: "ProductoCarga", categoria_id: int) -> int:
    """Create a new product with the given category id and return its identifier."""
    url = f"{get_base_url(ctx['region'])}/api/v1/administration/product"
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
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
    r = teco_request("POST", url, headers=headers, json=payload)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()["id"]


def buscar_producto_por_nombre(ctx: Dict[str, object], nombre: str) -> Optional[Dict[str, object]]:
    """Search for a product by its exact name (case-insensitive)."""
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    url = f"{base_url}/api/v1/administration/product?search={nombre}"
    r = teco_request("GET", url, headers=headers)
    if r.status_code == 200:
        data = r.json()
        productos = data.get("items", []) if isinstance(data, dict) else []
        for p in productos:
            if isinstance(p, dict) and p.get("name", "").strip().lower() == nombre.strip().lower():
                return p
    return None


def registrar_producto_en_carga(ctx: Dict[str, object], carga_id: int, product_id: int, prod: object) -> None:
    """Register a product within a purchase receipt batch.

    If an error occurs during registration an exception is raised with
    detailed information.
    """
    url = f"{get_base_url(ctx['region'])}/api/v1/administration/buyedReceipt/batch/{carga_id}"
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
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
    response = teco_request("POST", url, headers=headers, json=payload)
    if response.status_code not in [200, 201]:
        raise Exception(
            f"Error al registrar '{getattr(prod, 'name', 'Desconocido')}': "
            f"{response.status_code} - {response.text}"
        )
