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

from typing import Dict, Any, List, Optional, Tuple, Literal
from fastapi import HTTPException

from app.core.auth import get_base_url, build_auth_headers
from app.core.context import get_user_context
from app.clients.http_client import HTTPClient
from app.schemas.products import Producto, ProductoEntradaInteligente, EntradaInteligenteRequest

from collections import defaultdict
import unicodedata
import re

# =======================
# Mapeos de categorías
# =======================

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

# Tipos confirmados de Tecopos
TipoProducto = Literal["RAW", "MANUFACTURED", "ADDON", "MENU", "COMBO", "SERVICE", "STOCK"]


# =======================
# Helpers generales
# =======================

def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def normalizar(texto: str) -> str:
    if not texto:
        return ""
    t = _strip_accents(texto).lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t


def inferir_categoria(nombre: str) -> str:
    nombre_norm = normalizar(nombre)
    for categoria, palabras_clave in CATEGORIA_KEYWORDS.items():
        if any(normalizar(p) in nombre_norm for p in palabras_clave):
            return categoria
    return "Mercado"


def _get_ctx_headers(usuario: str) -> Tuple[Dict[str, Any], str, Dict[str, str]]:
    """
    Valida el contexto del usuario y devuelve (ctx, base_url, headers).
    """
    ctx = get_user_context(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    return ctx, base_url, headers


# --- Tipos Tecopos y mapeo “amigable” ---
TIPOS_TECOPOS = {"RAW", "MANUFACTURED", "ADDON", "MENU", "COMBO", "SERVICE", "STOCK"}

FRIENDLY_TO_TECOPOS = {
    # nombres “humanos” → type Tecopos (tras normalizar)
    "elaborado": "MENU",
    "procesado": "MANUFACTURED",
    "almacen": "STOCK",
    "materia prima": "RAW",
    "combo": "COMBO",
    # opcionales/sinónimos:
    "menu": "MENU",
    "manufactured": "MANUFACTURED",
    "raw": "RAW",
    "service": "SERVICE",
    "servicio": "SERVICE",
    "addon": "ADDON",
}

def coerce_tipo(valor: Optional[str], *, default_: Optional[str] = None) -> str:
    """
    Acepta: 'tipo' o 'type' con variantes humanas (Elaborado, Procesado, Almacén...).
    Devuelve el enum Tecopos válido en MAYÚSCULAS. Lanza 422 si no reconoce el valor.
    """
    if not valor:
        if default_:
            return default_.upper()
        raise HTTPException(status_code=422, detail="Campo 'tipo'/'type' es obligatorio.")
    v_raw = str(valor).strip()
    v_norm = normalizar(v_raw)
    # ¿ya es un enum válido?
    if v_raw.upper() in TIPOS_TECOPOS:
        return v_raw.upper()
    # ¿está en el diccionario amigable?
    mapped = FRIENDLY_TO_TECOPOS.get(v_norm)
    if mapped:
        return mapped
    raise HTTPException(
        status_code=422,
        detail={
            "message": f"Tipo desconocido: '{valor}'",
            "permitidos": sorted(list(TIPOS_TECOPOS)),
            "alias": sorted(list(FRIENDLY_TO_TECOPOS.keys())),
        },
    )

# =======================
# Categorías (existente)
# =======================

def obtener_o_crear_categoria(nombre_categoria: str, base_url: str, headers: Dict[str, str], http_client: HTTPClient) -> int:
    """Retrieve or create a sales category by name."""
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


# =======================
# Productos (existente)
# =======================

def crear_o_buscar_producto(producto: ProductoEntradaInteligente, base_url: str, headers: Dict[str, str], http_client: HTTPClient) -> int:
    """Find an existing product by name or create a new one."""
    nombre_norm = normalizar(producto.nombre)
    search_url = f"{base_url}/api/v1/administration/product?search={producto.nombre}"
    res = http_client.request("GET", search_url, headers=headers)
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail=f"No se pudo buscar '{producto.nombre}'")
    items = res.json().get("items", [])
    existente = next((p for p in items if normalizar(p.get("name", "")) == nombre_norm), None)
    if existente:
        return existente["id"]
    # create new product (tipo STOCK conservado según tu base actual)
    categoria_id = obtener_o_crear_categoria(inferir_categoria(producto.nombre), base_url, headers, http_client)
    crear_url = f"{base_url}/api/v1/administration/product"}
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
    """Create a new product under a specific or inferred category."""
    ctx = get_user_context(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])

    # Acepta tipo humano o enum y lo normaliza (default STOCK)
    tipo = coerce_tipo(getattr(data, "tipo", None) or "STOCK", default_="STOCK")

    categoria_nombre = data.categorias[0] if data.categorias else inferir_categoria(data.nombre)
    categoria_id = obtener_o_crear_categoria(categoria_nombre, base_url, headers, http_client)
    crear_url = f"{base_url}/api/v1/administration/product"
    crear_payload = {
        "type": tipo,
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


# =======================
# Entrada Inteligente (existente)
# =======================

def entrada_inteligente(data: EntradaInteligenteRequest, http_client: HTTPClient) -> Dict[str, Any]:
    """Process an intelligent stock entry (bulk entry)."""
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


# =========================================================
# NUEVO: Áreas MANUFACTURER (listar + resolver por nombre)
# =========================================================

def listar_areas_manufacturer(usuario: str, http_client: HTTPClient) -> List[Dict[str, Any]]:
    """
    Lista TODAS las áreas de tipo MANUFACTURER con paginación explícita.
    Devuelve cada ítem tal como viene de Tecopos (id, name, ...).
    """
    _, base_url, headers = _get_ctx_headers(usuario)
    items: List[Dict[str, Any]] = []
    page = 1
    while True:
        url = f"{base_url}/api/v1/administration/area"
        params = {"page": page, "per_page": 50, "type": "MANUFACTURER"}
        res = http_client.request("GET", url, headers=headers, params=params)
        if res.status_code < 200 or res.status_code >= 300:
            raise HTTPException(status_code=res.status_code, detail=res.text)
        data = res.json() or {}
        batch = data.get("items") or []
        if not batch:
            break
        items.extend(batch)
        total_pages = int(data.get("totalPages") or 1)
        if page >= total_pages:
            break
        page += 1
    return items


def resolver_area_ids_por_nombre(usuario: str, nombres: List[str], http_client: HTTPClient) -> List[int]:
    """
    Convierte nombres → IDs (match exacto case-insensitive).
    Lanza 404 si alguno no existe; devuelve en detail los disponibles.
    """
    if not nombres:
        return []
    catalog = listar_areas_manufacturer(usuario, http_client)
    idx = {str(it.get("name", "")).strip().lower(): int(it["id"]) for it in catalog if it.get("id") is not None}
    result: List[int] = []
    faltantes: List[str] = []
    for n in nombres:
        key = (n or "").strip().lower()
        _id = idx.get(key)
        if _id:
            result.append(_id)
        else:
            faltantes.append(n)
    # dedupe manteniendo orden
    seen = set()
    result = [x for x in result if not (x in seen or seen.add(x))]
    if faltantes:
        disponibles = list(idx.keys())
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Algunas áreas no se encontraron",
                "faltantes": faltantes,
                "disponibles": disponibles,
            },
        )
    return result


# =========================================================
# NUEVO: Construcción de payload por tipo (productos Tecopos)
# =========================================================

def _build_payload_teco(
    *,
    type: TipoProducto,
    name: str,
    images: Optional[List[str]] = None,
    # RAW/MANUFACTURED
    measure: Optional[str] = None,
    # Venta
    salesCategoryId: Optional[int] = None,
    prices: Optional[List[Dict[str, Any]]] = None,  # [{price, codeCurrency}]
    # Áreas
    productionAreaNames: Optional[List[str]] = None,
    listProductionAreas: Optional[List[int]] = None,
    # SERVICE opcionales
    color: Optional[str] = None,
    hasDuration: Optional[bool] = None,
    # Contexto
    usuario: Optional[str] = None,
    http_client: Optional[HTTPClient] = None,
) -> Dict[str, Any]:
    """
    Construye el payload EXACTO para /api/v1/administration/product
    según los tipos confirmados. No envía systemPriceId.
    """
    # Resolver nombres → IDs si corresponde
    list_prod_areas_ids: Optional[List[int]] = listProductionAreas
    if productionAreaNames:
        if not usuario or not http_client:
            raise HTTPException(status_code=400, detail="Se requieren 'usuario' y http_client para resolver áreas por nombre.")
        list_prod_areas_ids = resolver_area_ids_por_nombre(usuario, productionAreaNames, http_client)

    # Reglas por tipo
    if type in ("RAW", "MANUFACTURED"):
        if not measure:
            raise HTTPException(status_code=422, detail="Para type in {'RAW','MANUFACTURED'} es obligatorio 'measure'.")
        payload = {
            "type": type,
            "name": name,
            "measure": measure,
            "images": images or [],
        }
        if list_prod_areas_ids:
            payload["listProductionAreas"] = list_prod_areas_ids
        return payload

    # Tipos de venta
    if salesCategoryId is None:
        raise HTTPException(status_code=422, detail=f"Para type='{type}' es obligatorio 'salesCategoryId'.")
    precios = prices or []
    if not precios:
        raise HTTPException(status_code=422, detail=f"Para type='{type}' es obligatorio 'prices' (>=1).")

    payload: Dict[str, Any] = {
        "type": type,
        "name": name,
        "salesCategoryId": salesCategoryId,
        "prices": precios,
        "images": images or [],
    }

    if list_prod_areas_ids:
        payload["listProductionAreas"] = list_prod_areas_ids

    if type == "SERVICE":
        if color is not None:
            x = color.strip()
            if not x.startswith("#") or len(x) not in (4, 7):
                raise HTTPException(status_code=422, detail="color debe ser HEX (#RGB o #RRGGBB).")
            payload["color"] = x
        if hasDuration is not None:
            payload["hasDuration"] = bool(hasDuration)

    # Limpiar None
    return {k: v for k, v in payload.items() if v is not None}


# =========================================================
# NUEVO: Crear producto (uno y batch iterando)
# =========================================================

def crear_producto_teco(usuario: str, data: Dict[str, Any], http_client: HTTPClient) -> Dict[str, Any]:
    """
    Crea un producto en Tecopos (tipos confirmados) y retorna {id, name, type}.
    Soporta 'productionAreaNames' (nombres) o 'listProductionAreas' (IDs).
    Acepta claves 'type' o 'tipo', y 'name' o 'nombre'.
    """
    _, base_url, headers = _get_ctx_headers(usuario)
    crear_url = f"{base_url}/api/v1/administration/product"

    # Acepta 'type' o 'tipo'
    raw_tipo = data.get("type") or data.get("tipo")
    tipo = coerce_tipo(raw_tipo)

    # Acepta 'name' o 'nombre'
    _name = data.get("name") or data.get("nombre")
    if not _name:
        raise HTTPException(status_code=422, detail="Campo 'name'/'nombre' es obligatorio.")

    payload = _build_payload_teco(
        type=tipo,  # type: ignore[arg-type]
        name=_name,
        images=data.get("images"),
        measure=data.get("measure"),
        salesCategoryId=data.get("salesCategoryId"),
        prices=data.get("prices"),
        productionAreaNames=data.get("productionAreaNames"),
        listProductionAreas=data.get("listProductionAreas"),
        color=data.get("color"),
        hasDuration=data.get("hasDuration"),
        usuario=usuario,
        http_client=http_client,
    )

    res = http_client.request("POST", crear_url, headers=headers, json=payload)
    if res.status_code < 200 or res.status_code >= 300:
        raise HTTPException(status_code=res.status_code, detail=res.text)
    body = res.json() or {}
    return {
        "id": int(body.get("id") or body.get("productId") or 0),
        "name": str(body.get("name") or _name),
        "type": str(body.get("type") or tipo),
    }


def crear_productos_teco_batch(usuario: str, items: List[Dict[str, Any]], http_client: HTTPClient) -> Dict[str, Any]:
    """
    Batch **cliente**: itera la lista y crea cada producto de forma secuencial.
    - Si un ítem falla, continúa con el resto.
    - Devuelve {'creados': [...], 'errores': [...]}
    Acepta por ítem 'type' o 'tipo', y 'name' o 'nombre'.
    """
    creados: List[Dict[str, Any]] = []
    errores: List[Dict[str, Any]] = []

    valid_items: List[Dict[str, Any]] = []
    for idx, it in enumerate(items, start=1):
        # Prevalidación flexible
        raw_tipo = it.get("type") or it.get("tipo")
        raw_name = it.get("name") or it.get("nombre")
        if not raw_tipo or not raw_name:
            errores.append({
                "index": idx,
                "name": raw_name,
                "type": raw_tipo,
                "status": 422,
                "error": "Faltan campos mínimos: 'type'/'tipo' y/o 'name'/'nombre'."
            })
            continue
        # Deja que crear_producto_teco haga la coerción y validación profunda
        valid_items.append(it)

    # Crear uno a uno
    for it in valid_items:
        try:
            res = crear_producto_teco(usuario, it, http_client)
            creados.append(res)
        except HTTPException as e:
            errores.append({
                "name": it.get("name") or it.get("nombre"),
                "type": it.get("type") or it.get("tipo"),
                "status": e.status_code,
                "error": e.detail,
            })
        except Exception as e:
            errores.append({
                "name": it.get("name") or it.get("nombre"),
                "type": it.get("type") or it.get("tipo"),
                "status": 500,
                "error": str(e),
            })

    return {"creados": creados, "errores": errores}
