"""
services/currency_service.py
----------------------------

Service for batch currency updates across products. Handles listing
available price systems, simulating currency conversion and applying
updates when confirmed. Implements pagination using the shared HTTP
client and respects user context.
"""

from __future__ import annotations

from typing import Dict, Any, List
from fastapi import HTTPException

from app.core.context import get_user_context
from app.core.auth import get_base_url, build_auth_headers
from app.clients.http_client import HTTPClient
from app.schemas.currency import CambioMonedaRequest


def actualizar_monedas(data: CambioMonedaRequest, http_client: HTTPClient) -> Dict[str, Any]:
    ctx = get_user_context(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    # Obtener sistemas de precio
    info_url = f"{base_url}/api/v1/administration/my-business"
    info_res = http_client.request("GET", info_url, headers=headers)
    if info_res.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudo obtener información del negocio")
    price_systems = info_res.json().get("priceSystems", [])
    if data.system_price_id is not None:
        selected_system = next((s for s in price_systems if s["id"] == data.system_price_id), None)
    else:
        disponibles = [f"{s['name']} (ID: {s['id']})" for s in price_systems]
        return {
            "status": "selección_requerida",
            "mensaje": "Debe seleccionar un sistema de precio especificando el ID",
            "sistemas_disponibles": disponibles,
        }
    if not selected_system:
        raise HTTPException(status_code=400, detail="Sistema de precio no encontrado")
    system_price_id = selected_system["id"]
    actualizados: List[Any] = []
    page = 1
    while True:
        url = f"{base_url}/api/v1/administration/product?page={page}"
        res = http_client.request("GET", url, headers=headers)
        if res.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Error al obtener productos (página {page})")
        items = res.json().get("items", [])
        if not items:
            break
        for p in items:
            prices = p.get("prices", [])
            target_price = next((pr for pr in prices if pr.get("priceSystemId") == system_price_id), None)
            if not target_price:
                continue
            current_currency = target_price.get("codeCurrency")
            if current_currency == data.moneda_deseada:
                continue
            if current_currency != data.moneda_actual:
                continue
            if not data.confirmar:
                actualizados.append({
                    "id": p["id"],
                    "nombre": p["name"],
                    "systemPriceId": system_price_id,
                    "price": target_price["price"],
                    "codeCurrency": data.moneda_deseada,
                })
                continue
            # apply patch
            patch_url = f"{base_url}/api/v1/administration/product/{p['id']}"
            patch_payload = {
                "prices": [
                    {
                        "systemPriceId": system_price_id,
                        "price": target_price["price"],
                        "codeCurrency": data.moneda_deseada,
                    }
                ],
            }
            patch_res = http_client.request("PATCH", patch_url, headers=headers, json=patch_payload)
            if patch_res.status_code in [200, 204]:
                actualizados.append(p["name"])
            else:
                raise HTTPException(status_code=500, detail=f"Error al actualizar '{p['name']}'")
        page += 1
    if not data.confirmar:
        return {
            "status": "ok",
            "mensaje": "Simulación de cambio de moneda",
            "productos_para_cambiar": actualizados,
        }
    return {
        "status": "ok",
        "mensaje": "Monedas actualizadas correctamente",
        "productos_actualizados": actualizados,
    }