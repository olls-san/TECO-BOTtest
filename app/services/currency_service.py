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
from app.logging_config import logger, log_call
import json
from app.schemas.currency import CambioMonedaRequest


@log_call
def actualizar_monedas(data: CambioMonedaRequest, http_client: HTTPClient) -> Dict[str, Any]:
    ctx = get_user_context(data.usuario)
    if not ctx:
        logger.warning(json.dumps({
            "event": "actualizar_monedas_sin_sesion",
            "usuario": data.usuario,
            "detalle": "Usuario no autenticado",
        }))
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    # Log inicio de actualización de monedas
    try:
        logger.info(json.dumps({
            "event": "actualizar_monedas_inicio",
            "usuario": data.usuario,
            "region": ctx.get("region"),
            "businessId": ctx.get("businessId"),
            "moneda_actual": data.moneda_actual,
            "moneda_deseada": data.moneda_deseada,
            "system_price_id": data.system_price_id,
            "confirmar": data.confirmar,
        }))
    except Exception:
        pass
    # Obtener sistemas de precio
    info_url = f"{base_url}/api/v1/administration/my-business"
    info_res = http_client.request("GET", info_url, headers=headers)
    if info_res.status_code != 200:
        logger.error(json.dumps({
            "event": "actualizar_monedas_error",
            "usuario": data.usuario,
            "detalle": "No se pudo obtener información del negocio",
            "status_code": info_res.status_code,
        }))
        raise HTTPException(status_code=500, detail="No se pudo obtener información del negocio")
    price_systems = info_res.json().get("priceSystems", [])
    if data.system_price_id is not None:
        selected_system = next((s for s in price_systems if s["id"] == data.system_price_id), None)
    else:
        disponibles = [f"{s['name']} (ID: {s['id']})" for s in price_systems]
        logger.info(json.dumps({
            "event": "actualizar_monedas_seleccion_requerida",
            "usuario": data.usuario,
            "sistemas_disponibles": disponibles,
        }))
        return {
            "status": "selección_requerida",
            "mensaje": "Debe seleccionar un sistema de precio especificando el ID",
            "sistemas_disponibles": disponibles,
        }
    if not selected_system:
        logger.warning(json.dumps({
            "event": "actualizar_monedas_system_not_found",
            "usuario": data.usuario,
            "system_price_id": data.system_price_id,
        }))
        raise HTTPException(status_code=400, detail="Sistema de precio no encontrado")
    system_price_id = selected_system["id"]
    actualizados: List[Any] = []
    page = 1
    while True:
        url = f"{base_url}/api/v1/administration/product?page={page}"
        # Llamada GET para obtener productos paginados
        res = http_client.request("GET", url, headers=headers)
        if res.status_code != 200:
            logger.error(json.dumps({
                "event": "actualizar_monedas_error",
                "usuario": data.usuario,
                "detalle": f"Error al obtener productos (página {page})",
                "status_code": res.status_code,
            }))
            raise HTTPException(status_code=500, detail=f"Error al obtener productos (página {page})")
        items = res.json().get("items", [])
        if not items:
            break
        for p in items:
            prices = p.get("prices", [])
            # localizar precio objetivo dentro de la lista de precios
            target_price = next((pr for pr in prices if pr.get("priceSystemId") == system_price_id), None)
            if not target_price:
                continue
            current_currency = target_price.get("codeCurrency")
            # saltar si ya está en la moneda deseada
            if current_currency == data.moneda_deseada:
                continue
            # solo procesar productos con moneda actual especificada
            if current_currency != data.moneda_actual:
                continue
            if not data.confirmar:
                # modo simulación: acumular candidatos para mostrar al usuario
                actualizados.append({
                    "id": p["id"],
                    "nombre": p["name"],
                    "systemPriceId": system_price_id,
                    "price": target_price["price"],
                    "codeCurrency": data.moneda_deseada,
                })
                continue
            # aplicar el cambio de moneda a través de PATCH
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
                logger.error(json.dumps({
                    "event": "actualizar_monedas_error",
                    "usuario": data.usuario,
                    "producto": p.get("name"),
                    "status_code": patch_res.status_code,
                    "detalle": patch_res.text,
                }))
                raise HTTPException(status_code=500, detail=f"Error al actualizar '{p['name']}'")
        page += 1
    if not data.confirmar:
        logger.info(json.dumps({
            "event": "actualizar_monedas_simulacion",
            "usuario": data.usuario,
            "productos_para_cambiar": len(actualizados),
        }))
        return {
            "status": "ok",
            "mensaje": "Simulación de cambio de moneda",
            "productos_para_cambiar": actualizados,
        }
    logger.info(json.dumps({
        "event": "actualizar_monedas_exito",
        "usuario": data.usuario,
        "productos_actualizados": len(actualizados),
    }))
    return {
        "status": "ok",
        "mensaje": "Monedas actualizadas correctamente",
        "productos_actualizados": actualizados,
    }