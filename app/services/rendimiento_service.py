"""
services/rendimiento_service.py
-------------------------------

Service for computing production yields of ice cream and yogurt.
Extracts transformation movements from Tecopos, associates input and
output batches and calculates efficiencies. The business logic
conforms to the original implementation.
"""
# app/services/rendimiento_descomposicion_service.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
from math import sqrt
from datetime import datetime, date
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException
from httpx import Client

from app.utils import user_context, normalizar_rango
from app.core.http_sync import get_http_client  # inyección requerida (sin paréntesis)
from app.clients.rendimiento_descomposicion_client import RendimientoDescomposicionClient

# --------------------------
# FECHAS
# --------------------------
def _parse_yyyy_mm_dd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()

def _today_ny() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()

def _bucket_key(dt_iso: str, granularidad: str) -> str:
    """
    - DIA: YYYY-MM-DD
    - SEMANA: YYYY-Www
    - MES: YYYY-MM
    """
    try:
        ts = datetime.strptime(dt_iso, "%Y-%m-%dT%H:%M:%S.%fZ")
    except Exception:
        try:
            ts = datetime.strptime(dt_iso, "%Y-%m-%dT%H:%M:%S%z")
        except Exception:
            try:
                ts = datetime.strptime(dt_iso, "%Y-%m-%dT%H:%M:%S")
            except Exception:
                ts = datetime.strptime(dt_iso[:10], "%Y-%m-%d")
    if granularidad == "DIA":
        return ts.strftime("%Y-%m-%d")
    if granularidad == "SEMANA":
        iso = ts.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    return ts.strftime("%Y-%m")

# --------------------------
# KPIs por movimiento
# --------------------------
def _compute_kpis_from_detail(
    detail: Dict[str, Any],
    product_filter: Optional[List[int]],
    warnings: List[str],
) -> Dict[str, Any]:
    parent_qty = float(abs(detail.get("quantity") or 0))
    parent_product = detail.get("product") or {}
    parent_measure = parent_product.get("measure")
    parent_name = parent_product.get("name") or ""
    parent_id = parent_product.get("id")
    movement_id = int(detail.get("id"))
    created_at = detail.get("createdAt") or ""
    area_name = (detail.get("area") or {}).get("name") or ""

    childs = detail.get("childs") or []

    manuf_total = 0.0
    waste_total = 0.0
    manuf_by_product: Dict[int, Dict[str, Any]] = defaultdict(lambda: {"name": "", "measure": None, "qty": 0.0})

    for ch in childs:
        op = ch.get("operation")
        cat = ch.get("category")
        prod = ch.get("product") or {}
        ptype = prod.get("type")
        pid = prod.get("id")
        pname = prod.get("name") or ""
        pmeasure = prod.get("measure")
        qty = float(ch.get("quantity") or 0.0)

        # MANUFACTURED (ENTRY/DESCOMPOSITION/MANUFACTURED)
        if op == "ENTRY" and cat == "DESCOMPOSITION" and ptype == "MANUFACTURED":
            if product_filter and pid not in product_filter:
                continue
            manuf_total += qty
            d = manuf_by_product[pid]
            d["name"] = pname
            d["measure"] = pmeasure
            d["qty"] += qty
            continue

        # WASTE (ENTRY/WASTE o type=WASTE)
        if op == "ENTRY" and (ptype == "WASTE" or cat == "WASTE"):
            waste_total += qty
            continue

    rendimiento = None
    # rendimiento solo si todas las unidades manufacturadas coinciden con la del padre
    if parent_measure and all((v["measure"] == parent_measure for v in manuf_by_product.values() if v["qty"] > 0)):
        if parent_qty > 0:
            rendimiento = (manuf_total / parent_qty) * 100.0
    else:
        if any((v["measure"] and parent_measure and v["measure"] != parent_measure) for v in manuf_by_product.values()):
            warnings.append(
                f"Unidades distintas en movementId={movement_id}: padre={parent_measure}, hijos={[v['measure'] for v in manuf_by_product.values()]}"
            )

    return {
        "movementId": movement_id,
        "fecha": created_at[:10] if created_at else "",
        "padre": {
            "productId": parent_id,
            "productName": parent_name,
            "measure": parent_measure,
            "usado": parent_qty,
        },
        "manufacturados_total": manuf_total,
        "merma_total": waste_total,
        "rendimiento_porcentaje": None if rendimiento is None else round(rendimiento, 2),
        "createdAt": created_at,
        "manuf_by_product": {pid: v for pid, v in manuf_by_product.items()},
        "areaName": area_name,
    }

def _stats(values: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    if not values:
        return None, None, None, None
    n = len(values)
    prom = sum(values) / n
    minv = min(values)
    maxv = max(values)
    std = (sum((x - prom) ** 2 for x in values) / (n - 1)) ** 0.5 if n > 1 else 0.0
    return round(prom, 2), round(minv, 2), round(maxv, 2), round(std, 2)

# --------------------------
# SERVICE
# --------------------------
def rendimiento_descomposicion_service(
    *,
    body: Dict[str, Any],
    http: Client = Depends(get_http_client),  # requerido
) -> Dict[str, Any]:
    usuario = body.get("usuario")
    if not usuario:
        raise HTTPException(status_code=400, detail="Falta 'usuario'")

    # 1) Contexto
    ctx = user_context.get(usuario)  # type: ignore[union-attr]
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")

    area_id = body.get("area_id")
    area_nombre = body.get("area_nombre")
    if not area_id and not area_nombre:
        raise HTTPException(status_code=400, detail="Debes enviar 'area_id' o 'area_nombre'")

    # 2) Fechas
    fecha_inicio = body.get("fecha_inicio")
    fecha_fin = body.get("fecha_fin")
    if not fecha_inicio and not fecha_fin:
        today = _today_ny()
        fecha_inicio = today.strftime("%Y-%m-%d")
        fecha_fin = fecha_inicio
    elif fecha_inicio and not fecha_fin:
        fecha_fin = fecha_inicio
    elif fecha_fin and not fecha_inicio:
        fecha_inicio = fecha_fin

    fi_dt = _parse_yyyy_mm_dd(fecha_inicio)
    ff_dt = _parse_yyyy_mm_dd(fecha_fin)

    date_from, date_to = normalizar_rango(
        datetime.combine(fi_dt, datetime.min.time()),
        datetime.combine(ff_dt, datetime.min.time()),
    )

    granularidad = body.get("granularidad") or "DIA"
    product_filter = body.get("product_ids") or None
    incluir_movs = bool(body.get("incluir_movimientos", False))

    # 3) Cliente Tecopos
    client = RendimientoDescomposicionClient(
        region=ctx["region"],
        token=ctx["token"],
        business_id=ctx["businessId"],
    )

    # 4) Resolver área si vino por nombre
    resolved_area_name = None
    if not area_id:
        area_obj = client.resolve_area_by_name(area_nombre)
        if not area_obj:
            raise HTTPException(status_code=400, detail=f"Área '{area_nombre}' no encontrada")
        area_id = int(area_obj["id"])
        resolved_area_name = area_obj["name"]

    # 5) Listar padres (paginación) y computar KPIs por movimiento
    warnings: List[str] = []
    movimientos_kpi: List[Dict[str, Any]] = []
    for page_items in client.iter_parent_movements(area_id=area_id, date_from=date_from, date_to=date_to):
        for it in page_items:
            mid = it.get("id")
            if mid is None:
                continue
            detail = client.get_movement_detail(int(mid))
            kpi = _compute_kpis_from_detail(detail, product_filter, warnings)
            movimientos_kpi.append(kpi)

    # 6) Agregados
    total_usado = sum(m["padre"]["usado"] for m in movimientos_kpi)
    total_manuf = sum(m["manufacturados_total"] for m in movimientos_kpi)
    total_merma = sum(m["merma_total"] for m in movimientos_kpi)
    rend_ponderado = round((total_manuf / total_usado) * 100.0, 2) if total_usado > 0 else None

    # Series por bucket
    from collections import defaultdict as _dd
    series_aggr: Dict[str, Dict[str, float]] = _dd(lambda: {"usado": 0.0, "manuf": 0.0, "merma": 0.0})
    for m in movimientos_kpi:
        b = _bucket_key(m.get("createdAt") or (m.get("fecha") + "T00:00:00"), granularidad)
        series_aggr[b]["usado"] += m["padre"]["usado"]
        series_aggr[b]["manuf"] += m["manufacturados_total"]
        series_aggr[b]["merma"] += m["merma_total"]

    series = []
    for b, vals in sorted(series_aggr.items(), key=lambda kv: kv[0]):
        rp = round((vals["manuf"] / vals["usado"]) * 100.0, 2) if vals["usado"] > 0 else None
        series.append({
            "bucket": b,
            "padre_usado": round(vals["usado"], 4),
            "manufacturados": round(vals["manuf"], 4),
            "merma": round(vals["merma"], 4),
            "rendimiento_porcentaje": rp,
        })

    # Por producto (solo MANUFACTURED)
    prod_aggr: Dict[int, Dict[str, Any]] = _dd(lambda: {
        "name": "",
        "measure": None,
        "mov": 0,
        "usado": 0.0,
        "manuf": 0.0,
        "merma": 0.0,
        "rend_list": [],
    })
    for m in movimientos_kpi:
        for pid, info in (m.get("manuf_by_product") or {}).items():
            pa = prod_aggr[int(pid)]
            pa["name"] = info.get("name") or pa["name"]
            pa["measure"] = info.get("measure") if info.get("measure") else pa["measure"]
            pa["mov"] += 1
            pa["usado"] += m["padre"]["usado"]
            pa["manuf"] += float(info.get("qty") or 0.0)
            pa["merma"] += m["merma_total"]
            if m["rendimiento_porcentaje"] is not None:
                pa["rend_list"].append(m["rendimiento_porcentaje"])

    por_producto: List[Dict[str, Any]] = []
    for pid, info in prod_aggr.items():
        prom, minv, maxv, std = _stats(info["rend_list"])
        por_producto.append({
            "productId": pid,
            "productName": info["name"],
            "measure": info["measure"],
            "movimientos": info["mov"],
            "usado_padre": round(info["usado"], 4),
            "manufacturados": round(info["manuf"], 4),
            "merma": round(info["merma"], 4),
            "rendimiento_promedio": prom,
            "rendimiento_min": minv,
            "rendimiento_max": maxv,
            "rendimiento_stddev": std,
        })

    # nombre de área: preferir el resuelto por nombre; si no, tomar el del primer detalle
    first_area_name = movimientos_kpi[0]["areaName"] if movimientos_kpi else ""
    area_name_final = resolved_area_name or first_area_name or ""

    out = {
        "periodo": {
            "desde": fecha_inicio,
            "hasta": fecha_fin,
            "granularidad": granularidad,
        },
        "area": {
            "id": int(area_id),
            "nombre": area_name_final,
        },
        "filtros": {
            "product_ids": product_filter or [],
        },
        "resumen": {
            "padre_usado": round(total_usado, 4),
            "manufacturados": round(total_manuf, 4),
            "merma": round(total_merma, 4),
            "rendimiento_ponderado_porcentaje": rend_ponderado,
        },
        "series": series,
        "por_producto": por_producto,
        "movimientos": [
            {
                "movementId": m["movementId"],
                "fecha": m["fecha"],
                "padre": m["padre"],
                "manufacturados_total": round(m["manufacturados_total"], 4),
                "merma_total": round(m["merma_total"], 4),
                "rendimiento_porcentaje": m["rendimiento_porcentaje"],
            }
            for m in (movimientos_kpi if incluir_movs else [])
        ],
        "warnings": warnings,
    }
    return out
