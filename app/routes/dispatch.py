"""
Dispatch and inventory receipt endpoints.

This module handles product replication between stock areas, creation
and management of purchase receipts (cargas), and verification of
product existence.  Keeping these operations together makes it
straightforward to manage logistics-related functionality.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# Use the shared HTTP client with retries and timeouts
from app.core.http_sync import teco_request
from fastapi import APIRouter, HTTPException

from .. import models
from ..utils import (
    user_context,
    get_base_url,
    get_auth_headers,
    buscar_producto,
    crear_categoria_si_no_existe,
    crear_producto,
    buscar_producto_por_nombre,
    registrar_producto_en_carga,
)

router = APIRouter()


@router.post("/replicar-productos", summary="Replicar productos entre negocios mediante despacho Tecopos")
def replicar_productos(data: models.ReplicarProductosRequest):
    """Replicate products from one business to another via a dispatch."""
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    token = ctx["token"]
    # If missing business IDs, return available branches
    if not data.negocio_origen_id or not data.negocio_destino_id:
        headers = get_auth_headers(token, ctx["businessId"], ctx["region"])
        resp = teco_request("GET", f"{base_url}/api/v1/administration/my-branches", headers=headers)
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail="No se pudieron obtener los negocios disponibles")
        return {"negocios_disponibles": resp.json()}
    # If missing area names, return stock areas for both businesses
    headers_origen = get_auth_headers(token, data.negocio_origen_id, ctx["region"])
    headers_destino = get_auth_headers(token, data.negocio_destino_id, ctx["region"])
    if not data.area_origen_nombre or not data.area_destino_nombre:
        resp_origen = teco_request("GET", f"{base_url}/api/v1/administration/area?page=1&type=STOCK", headers=headers_origen)
        resp_destino = teco_request("GET", f"{base_url}/api/v1/administration/area?page=1&type=STOCK", headers=headers_destino)
        if resp_origen.status_code != 200 or resp_destino.status_code != 200:
            raise HTTPException(status_code=500, detail="No se pudieron obtener las áreas de stock")
        areas_origen = resp_origen.json().get("items", [])
        areas_destino = resp_destino.json().get("items", [])
        def simplificar_area(area: Dict[str, object]) -> Dict[str, object]:
            return {
                "id": area["id"],
                "nombre": area["name"],
                "business_id": area["business"]["id"],
            }
        return {
            "areas_origen": [simplificar_area(a) for a in areas_origen if a["business"]["id"] == data.negocio_origen_id],
            "areas_destino": [simplificar_area(a) for a in areas_destino if a["business"]["id"] == data.negocio_destino_id],
        }
    # Find IDs of specified areas
    resp_origen = teco_request("GET", f"{base_url}/api/v1/administration/area?page=1&type=STOCK", headers=headers_origen)
    resp_destino = teco_request("GET", f"{base_url}/api/v1/administration/area?page=1&type=STOCK", headers=headers_destino)
    areas_origen = resp_origen.json().get("items", [])
    areas_destino = resp_destino.json().get("items", [])
    area_origen = next((a for a in areas_origen if a["name"] == data.area_origen_nombre and a["business"]["id"] == data.negocio_origen_id), None)
    area_destino = next((a for a in areas_destino if a["name"] == data.area_destino_nombre and a["business"]["id"] == data.negocio_destino_id), None)
    if not area_origen or not area_destino:
        raise HTTPException(status_code=404, detail="No se encontraron las áreas indicadas o no pertenecen al negocio correcto")
    # Gather products in origin area
    productos_ids: List[int] = []
    pagina = 1
    while True:
        resp = teco_request("GET", f"{base_url}/api/v1/administration/product/area/{area_origen['id']}?page={pagina}", headers=headers_origen)
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Error al obtener productos del área de stock en la página {pagina}")
        resultado = resp.json()
        productos = resultado.get("items", [])
        if not productos:
            break
        for p in productos:
            prod_info = p.get("product")
            if not prod_info or "id" not in prod_info:
                continue
            categoria = (prod_info.get("salesCategory") or {}).get("name")
            if data.filtro_categoria and categoria != data.filtro_categoria:
                continue
            productos_ids.append(prod_info["id"])
        pagina += 1
    if not productos_ids:
        raise HTTPException(status_code=404, detail="No se encontraron productos para replicar en el área origen")
    despacho_payload = {
        "stockAreaFromId": area_origen["id"],
        "stockAreaToId": area_destino["id"],
        "mode": "MOVEMENT",
        "products": [{"productId": pid, "quantity": 0} for pid in productos_ids],
    }
    resp_despacho = teco_request("POST", f"{base_url}/api/v1/administration/dispatch/v3", headers=headers_origen, json=despacho_payload)
    if resp_despacho.status_code != 201:
        raise HTTPException(status_code=500, detail=f"Error al crear el despacho: {resp_despacho.text}")
    return {
        "mensaje": "Despacho creado exitosamente para replicación",
        "despacho": resp_despacho.json(),
    }


@router.post("/crear-carga-con-productos")
def crear_carga_con_productos(data: models.CrearCargaConProductosRequest):
    """Create a purchase receipt with the specified products, creating missing products on-demand."""
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    batches: List[Dict[str, object]] = []
    for prod in data.productos:
        encontrado = buscar_producto(ctx, prod.code)
        if encontrado:
            product_id = encontrado["id"]
        else:
            categoria_id = crear_categoria_si_no_existe(ctx, prod.category)
            product_id = crear_producto(ctx, prod, categoria_id)
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
    r = teco_request("POST", url, headers=headers, json=payload)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return {
        "mensaje": "Carga creada con éxito y productos registrados",
        "respuesta": r.json(),
    }


@router.post("/entrada-productos-en-carga")
def entrada_productos_en_carga(data: models.EntradaProductosEnCargaRequest):
    """Insert products into an existing purchase receipt batch."""
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    productos_faltantes: List[str] = []
    productos_validos: List[Tuple[int, object]] = []
    for prod in data.productos:
        existente = buscar_producto_por_nombre(ctx, prod.name)
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
            registrar_producto_en_carga(ctx, data.carga_id, product_id, prod)
            exitosos.append(prod.name)
        except Exception as e:
            errores.append(str(e))
    return {
        "mensaje": "Proceso completado",
        "registrados": exitosos,
        "errores": errores,
    }


@router.get("/listar-cargas-disponibles")
def listar_cargas_disponibles(usuario: str):
    """Return a paginated list of available purchase receipts."""
    ctx = user_context.get(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    cargas: List[Dict[str, object]] = []
    pagina = 1
    while True:
        url = f"{base_url}/api/v1/administration/buyedreceipt?page={pagina}"
        r = teco_request("GET", url, headers=headers)
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        data_json = r.json()
        items = data_json.get("items", [])
        for carga in items:
            cargas.append({
                "id": carga["id"],
                "name": carga["name"],
                "status": carga["status"],
                "createdAt": carga["createdAt"],
            })
        if pagina >= data_json.get("totalPages", 1):
            break
        pagina += 1
    return {"cargas_disponibles": cargas}


@router.post("/verificar-productos-existen", response_model=models.ProductosFaltantesResponse)
def verificar_productos_existen(data: models.VerificarProductosRequest):
    """Check whether the given product names exist in the system."""
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    nombres_faltantes: List[str] = []
    for nombre in data.nombres_productos:
        producto = buscar_producto_por_nombre(ctx, nombre)
        if not producto:
            nombres_faltantes.append(nombre)
    return {"productos_faltantes": nombres_faltantes}