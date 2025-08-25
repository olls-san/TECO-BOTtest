"""
services/dispatch_service.py
---------------------------

Service responsible for replicating products between stock areas of
different businesses by creating a dispatch. The flow follows several
steps: listing available businesses, listing stock areas for each
business, gathering product IDs from the origin area and finally
creating a movement dispatch. Filtering by category is optional.
"""

from __future__ import annotations

from typing import Dict, Any, List, Tuple
from fastapi import HTTPException

from app.core.context import get_user_context
from app.core.auth import get_base_url, build_auth_headers
from app.clients.http_client import HTTPClient
from app.schemas.dispatch import ReplicarProductosRequest


def replicar_productos(data: ReplicarProductosRequest, http_client: HTTPClient) -> Dict[str, Any]:
    ctx = get_user_context(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    token = ctx["token"]
    # Step 1: list businesses if missing IDs
    if not data.negocio_origen_id or not data.negocio_destino_id:
        headers = build_auth_headers(token, ctx["businessId"], ctx["region"])
        resp = http_client.request("GET", f"{base_url}/api/v1/administration/my-branches", headers=headers)
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail="No se pudieron obtener los negocios disponibles")
        return {"negocios_disponibles": resp.json()}
    headers_origen = build_auth_headers(token, data.negocio_origen_id, ctx["region"])
    headers_destino = build_auth_headers(token, data.negocio_destino_id, ctx["region"])
    # Step 2: list areas if missing names
    if not data.area_origen_nombre or not data.area_destino_nombre:
        resp_origen = http_client.request("GET", f"{base_url}/api/v1/administration/area?page=1&type=STOCK", headers=headers_origen)
        resp_dest = http_client.request("GET", f"{base_url}/api/v1/administration/area?page=1&type=STOCK", headers=headers_destino)
        if resp_origen.status_code != 200 or resp_dest.status_code != 200:
            raise HTTPException(status_code=500, detail="No se pudieron obtener las áreas de stock")
        areas_origen = resp_origen.json().get("items", [])
        areas_destino = resp_dest.json().get("items", [])
        def simplificar_area(a: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "id": a["id"],
                "nombre": a["name"],
                "business_id": a["business"]["id"],
            }
        return {
            "areas_origen": [simplificar_area(a) for a in areas_origen if a["business"]["id"] == data.negocio_origen_id],
            "areas_destino": [simplificar_area(a) for a in areas_destino if a["business"]["id"] == data.negocio_destino_id],
        }
    # Step 3: resolve area IDs
    resp_origen = http_client.request("GET", f"{base_url}/api/v1/administration/area?page=1&type=STOCK", headers=headers_origen)
    resp_dest = http_client.request("GET", f"{base_url}/api/v1/administration/area?page=1&type=STOCK", headers=headers_destino)
    areas_origen = resp_origen.json().get("items", [])
    areas_destino = resp_dest.json().get("items", [])
    area_origen = next((a for a in areas_origen if a["name"] == data.area_origen_nombre and a["business"]["id"] == data.negocio_origen_id), None)
    area_destino = next((a for a in areas_destino if a["name"] == data.area_destino_nombre and a["business"]["id"] == data.negocio_destino_id), None)
    if not area_origen or not area_destino:
        raise HTTPException(status_code=404, detail="No se encontraron las áreas indicadas o no pertenecen al negocio correcto")
    # Step 4: gather product IDs from origin area (pagination)
    productos_ids: List[int] = []
    pagina = 1
    while True:
        resp = http_client.request("GET", f"{base_url}/api/v1/administration/product/area/{area_origen['id']}?page={pagina}", headers=headers_origen)
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Error al obtener productos del área de stock en la página {pagina}")
        resultado = resp.json()
        productos = resultado.get("items", [])
        if not productos:
            break
        for p in productos:
            producto = p.get("product")
            if not producto or "id" not in producto:
                continue
            categoria = (producto.get("salesCategory") or {}).get("name")
            if data.filtro_categoria:
                if categoria != data.filtro_categoria:
                    continue
            productos_ids.append(producto["id"])
        pagina += 1
    if not productos_ids:
        raise HTTPException(status_code=404, detail="No se encontraron productos para replicar en el área origen")
    # Step 5: create dispatch
    despacho_payload = {
        "stockAreaFromId": area_origen["id"],
        "stockAreaToId": area_destino["id"],
        "mode": "MOVEMENT",
        "products": [{"productId": pid, "quantity": 0} for pid in productos_ids],
    }
    resp_despacho = http_client.request("POST", f"{base_url}/api/v1/administration/dispatch/v3", json=despacho_payload, headers=headers_origen)
    if resp_despacho.status_code != 201:
        raise HTTPException(status_code=500, detail=f"Error al crear el despacho: {resp_despacho.text}")
    return {
        "mensaje": "Despacho creado exitosamente para replicación",
        "despacho": resp_despacho.json(),
    }