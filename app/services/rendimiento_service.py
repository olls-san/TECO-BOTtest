"""
services/rendimiento_service.py
-------------------------------

Service for computing production yields of ice cream and yogurt.
Extracts transformation movements from Tecopos, associates input and
output batches and calculates efficiencies. The business logic
conforms to the original implementation.
"""

from __future__ import annotations

from typing import Dict, Any, List
from datetime import date, datetime
from fastapi import HTTPException

from app.core.context import get_user_context
from app.core.auth import get_base_url, build_auth_headers
from app.clients.http_client import HTTPClient
from app.logging_config import logger, log_call
import json
from app.schemas.rendimiento import (
    RendimientoHeladoRequest,
    RendimientoYogurtRequest,
    RendimientoYogurtResponse,
    RendimientoYogurtResumen,
)


def extraer_sabor(nombre_producto: str) -> str:
    partes = nombre_producto.split("Mezcla")
    if len(partes) > 1:
        return partes[1].strip(" 🍓🍦").strip()
    return nombre_producto


@log_call
def rendimiento_helado(data: RendimientoHeladoRequest, http_client: HTTPClient) -> Dict[str, Any]:
    ctx = get_user_context(data.usuario)
    if not ctx:
        logger.warning(json.dumps({
            "event": "rendimiento_helado_sin_sesion",
            "usuario": data.usuario,
            "detalle": "Usuario no autenticado",
        }))
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    # Log inicio del cálculo de rendimiento de helado
    try:
        logger.info(json.dumps({
            "event": "rendimiento_helado_inicio",
            "usuario": data.usuario,
            "region": ctx.get("region"),
            "businessId": ctx.get("businessId"),
            "area_nombre": data.area_nombre,
            "fecha_inicio": str(data.fecha_inicio),
            "fecha_fin": str(data.fecha_fin),
        }))
    except Exception:
        pass
    # paso 1: obtener área por nombre
    url_areas = f"{base_url}/api/v1/administration/area?page=1&type=STOCK"
    response_areas = http_client.request("GET", url_areas, headers=headers)
    if response_areas.status_code != 200:
        logger.error(json.dumps({
            "event": "rendimiento_helado_error",
            "usuario": data.usuario,
            "detalle": "No se pudieron obtener las áreas",
            "status_code": response_areas.status_code,
        }))
        raise HTTPException(status_code=500, detail="No se pudieron obtener las áreas")
    areas = response_areas.json().get("items", [])
    area = next((a for a in areas if a["name"] == data.area_nombre), None)
    if not area:
        logger.warning(json.dumps({
            "event": "rendimiento_helado_area_no_encontrada",
            "usuario": data.usuario,
            "area_nombre": data.area_nombre,
        }))
        raise HTTPException(status_code=404, detail="Área no encontrada")
    area_id = area["id"]
    # paso 2: obtener movimientos de transformación
    movimientos_url = (
        f"{base_url}/api/v1/administration/movement?areaId={area_id}&all_data=true"
        f"&dateFrom={data.fecha_inicio}&dateTo={data.fecha_fin}&category=TRANSFORMATION"
    )
    response_mov = http_client.request("GET", movimientos_url, headers=headers)
    if response_mov.status_code != 200:
        logger.error(json.dumps({
            "event": "rendimiento_helado_error_movimientos",
            "usuario": data.usuario,
            "status_code": response_mov.status_code,
            "detalle": "No se pudieron obtener los movimientos",
        }))
        raise HTTPException(status_code=500, detail="No se pudieron obtener los movimientos")
    movimientos = response_mov.json().get("items", [])
    entradas = [m for m in movimientos if m["operation"] == "ENTRY"]
    salidas = [m for m in movimientos if m["operation"] == "OUT"]
    resultados: List[Dict[str, Any]] = []
    for salida in salidas:
        nombre_mezcla = salida["product"]["name"]
        if "Mezcla" not in nombre_mezcla:
            continue
        entrada = next((e for e in entradas if e.get("parentId") == salida["id"]), None)
        if not entrada:
            continue
        sabor = extraer_sabor(nombre_mezcla)
        cantidad_mezcla = abs(salida["quantity"])
        cantidad_producida = entrada["quantity"]
        rendimiento_real = round(cantidad_producida / cantidad_mezcla, 4) if cantidad_mezcla else 0
        rendimiento_ideal = 2
        eficiencia = round((rendimiento_real / rendimiento_ideal) * 100, 2)
        resultados.append({
            "tipo": "Helado",
            "sabor": sabor,
            "mezcla_usada_litros": cantidad_mezcla,
            "producto_producido_litros": cantidad_producida,
            "rendimiento_real": rendimiento_real,
            "rendimiento_ideal": rendimiento_ideal,
            "eficiencia_porcentual": eficiencia,
        })
    # Log fin de cálculo
    logger.info(json.dumps({
        "event": "rendimiento_helado_fin",
        "usuario": data.usuario,
        "area_id": area["id"],
        "num_registros": len(resultados),
    }))
    return {
        "area_nombre": area["name"],
        "area_id": area["id"],
        "resumen": resultados,
    }


@log_call
def rendimiento_yogurt(data: RendimientoYogurtRequest, http_client: HTTPClient) -> RendimientoYogurtResponse:
    ctx = get_user_context(data.usuario)
    if not ctx:
        logger.warning(json.dumps({
            "event": "rendimiento_yogurt_sin_sesion",
            "usuario": data.usuario,
            "detalle": "Usuario no autenticado",
        }))
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    # Log inicio del cálculo de rendimiento de yogurt
    try:
        logger.info(json.dumps({
            "event": "rendimiento_yogurt_inicio",
            "usuario": data.usuario,
            "region": ctx.get("region"),
            "businessId": ctx.get("businessId"),
            "area_nombre": data.area_nombre,
            "fecha_inicio": str(data.fecha_inicio),
            "fecha_fin": str(data.fecha_fin),
        }))
    except Exception:
        pass
    # obtener ID de área
    areas_url = f"{base_url}/api/v1/administration/area?page=1&type=STOCK"
    res_areas = http_client.request("GET", areas_url, headers=headers)
    if res_areas.status_code != 200:
        logger.error(json.dumps({
            "event": "rendimiento_yogurt_error_areas",
            "usuario": data.usuario,
            "status_code": res_areas.status_code,
            "detalle": "Error consultando áreas",
        }))
        raise HTTPException(status_code=500, detail="Error consultando áreas")
    area_id = None
    for area in res_areas.json().get("items", []):
        if area["name"].strip().lower() == data.area_nombre.strip().lower():
            area_id = area["id"]
            break
    if not area_id:
        logger.warning(json.dumps({
            "event": "rendimiento_yogurt_area_no_encontrada",
            "usuario": data.usuario,
            "area_nombre": data.area_nombre,
        }))
        raise HTTPException(status_code=404, detail="Área no encontrada")
    # consultar movimientos
    movimientos_url = (
        f"{base_url}/api/v1/administration/movement?areaId={area_id}&all_data=true"
        f"&dateFrom={data.fecha_inicio}&dateTo={data.fecha_fin}&category=TRANSFORMATION"
    )
    res_movs = http_client.request("GET", movimientos_url, headers=headers)
    if res_movs.status_code != 200:
        logger.error(json.dumps({
            "event": "rendimiento_yogurt_error_movimientos",
            "usuario": data.usuario,
            "status_code": res_movs.status_code,
            "detalle": "Error consultando movimientos",
        }))
        raise HTTPException(status_code=500, detail="Error consultando movimientos")
    movimientos = res_movs.json().get("items", [])
    producciones: List[RendimientoYogurtResumen] = []
    for mov in movimientos:
        if mov["operation"] == "OUT":
            mezcla_id = mov["id"]
            mezcla_qty = abs(mov["quantity"])
            for entrada in movimientos:
                if entrada["operation"] == "ENTRY" and entrada.get("parentId") == mezcla_id:
                    producto_final = entrada["product"]["name"]
                    qty_final = entrada["quantity"]
                    rendimiento_real = qty_final / mezcla_qty if mezcla_qty else 0
                    rendimiento_ideal = 1.0
                    eficiencia = round((rendimiento_real / rendimiento_ideal) * 100, 2) if rendimiento_ideal else 0
                    producciones.append(
                        RendimientoYogurtResumen(
                            tipo="Yogurt",
                            sabor=producto_final.replace("Yogurt", "").strip(),
                            mezcla_usada_litros=mezcla_qty,
                            producto_producido_litros=qty_final,
                            rendimiento_real=round(rendimiento_real, 4),
                            rendimiento_ideal=rendimiento_ideal,
                            eficiencia_porcentual=eficiencia,
                        )
                    )
    # Log fin del cálculo
    logger.info(json.dumps({
        "event": "rendimiento_yogurt_fin",
        "usuario": data.usuario,
        "area_id": area_id,
        "num_registros": len(producciones),
    }))
    return RendimientoYogurtResponse(area_nombre=data.area_nombre, area_id=area_id, resumen=producciones)
