"""
Inventory and production efficiency endpoints.

This module provides endpoints to list stock areas and compute
efficiency metrics for ice cream and yogurt production.  Grouping
inventory-related operations together facilitates focused updates
without interfering with reporting or dispatch logic.
"""

from __future__ import annotations

from typing import Dict, List

import requests
from fastapi import APIRouter, HTTPException

from .. import models
from ..utils import (
    user_context,
    get_base_url,
    get_auth_headers,
    extraer_sabor,
)

router = APIRouter()


@router.get("/listar-areas")
def listar_areas(usuario: str):
    """Return a list of stock areas for the current business."""
    ctx = user_context.get(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    url = f"{base_url}/api/v1/administration/area"
    params = {"page": 1, "type": "STOCK"}
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Error al obtener las áreas")
    items = response.json().get("items", [])
    return [{"id": a["id"], "nombre": a["name"]} for a in items]


@router.post("/rendimiento-helado")
def rendimiento_helado(data: models.RendimientoHeladoRequest):
    """Calculate efficiency metrics for ice cream production."""
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    # Get area by name
    url_areas = f"{base_url}/api/v1/administration/area?page=1&type=STOCK"
    response_areas = requests.get(url_areas, headers=headers)
    if response_areas.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudieron obtener las áreas")
    areas = response_areas.json().get("items", [])
    area = next((a for a in areas if a["name"] == data.area_nombre), None)
    if not area:
        raise HTTPException(status_code=404, detail="Área no encontrada")
    area_id = area["id"]
    movimientos_url = (
        f"{base_url}/api/v1/administration/movement?areaId={area_id}&all_data=true"
        f"&dateFrom={data.fecha_inicio}&dateTo={data.fecha_fin}&category=TRANSFORMATION"
    )
    response_mov = requests.get(movimientos_url, headers=headers)
    if response_mov.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudieron obtener los movimientos")
    movimientos = response_mov.json().get("items", [])
    entradas = [m for m in movimientos if m["operation"] == "ENTRY"]
    salidas = [m for m in movimientos if m["operation"] == "OUT"]
    resultados: List[Dict[str, object]] = []
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
    return {
        "area_nombre": area["name"],
        "area_id": area["id"],
        "resumen": resultados,
    }


@router.post("/rendimiento-yogurt", response_model=models.RendimientoYogurtResponse)
def rendimiento_yogurt(data: models.RendimientoYogurtRequest):
    """Calculate efficiency metrics for yogurt production."""
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    areas_url = f"{base_url}/api/v1/administration/area?page=1&type=STOCK"
    res_areas = requests.get(areas_url, headers=headers)
    if res_areas.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudieron obtener las áreas")
    areas = res_areas.json().get("items", [])
    area = next((a for a in areas if a["name"] == data.area_nombre), None)
    if not area:
        raise HTTPException(status_code=404, detail="Área no encontrada")
    area_id = area["id"]
    movimientos_url = (
        f"{base_url}/api/v1/administration/movement?areaId={area_id}&all_data=true"
        f"&dateFrom={data.fecha_inicio}&dateTo={data.fecha_fin}&category=TRANSFORMATION"
    )
    response_mov = requests.get(movimientos_url, headers=headers)
    if response_mov.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudieron obtener los movimientos")
    movimientos = response_mov.json().get("items", [])
    entradas = [m for m in movimientos if m["operation"] == "ENTRY"]
    salidas = [m for m in movimientos if m["operation"] == "OUT"]
    resultados: List[models.RendimientoYogurtResumen] = []
    for salida in salidas:
        nombre_mezcla = salida["product"]["name"]
        if "Mezcla" not in nombre_mezcla:
            continue
        entrada = next((e for e in entradas if e.get("parentId") == salida["id"]), None)
        if not entrada:
            continue
        sabor = extraer_sabor(nombre_mezcla)
        mezcla_usada = abs(salida["quantity"])
        produccion = entrada["quantity"]
        rendimiento_real = round(produccion / mezcla_usada, 4) if mezcla_usada else 0
        rendimiento_ideal = 2
        eficiencia = round((rendimiento_real / rendimiento_ideal) * 100, 2)
        resultados.append(models.RendimientoYogurtResumen(
            tipo="Yogurt",
            sabor=sabor,
            mezcla_usada_litros=mezcla_usada,
            producto_producido_litros=produccion,
            rendimiento_real=rendimiento_real,
            rendimiento_ideal=rendimiento_ideal,
            eficiencia_porcentual=eficiencia,
        ))
    return models.RendimientoYogurtResponse(
        area_nombre=area["name"],
        area_id=area["id"],
        resumen=resultados,
    )