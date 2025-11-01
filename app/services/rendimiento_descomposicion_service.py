# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
from math import sqrt
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, Body, Depends, HTTPException
from httpx import Client

# 🧩 Dependencias del proyecto (ya existentes en tu base)
from app.core.context import get_user_context
from app.utils import normalizar_rango
from app.logging_config import logger, log_call
import json
from app.core.http_sync import get_http_client  # inyección requerida (sin paréntesis)
from app.clients.rendimiento_descomposicion_client import RendimientoDescomposicionClient

# ==============================================================================
# FECHAS
# ==============================================================================

def _parse_yyyy_mm_dd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _today_ny() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def _bucket_key(dt_iso: str, granularidad: str) -> str:
    """
    Retorna la clave de bucket según granularidad.
      - DIA    -> YYYY-MM-DD
      - SEMANA -> YYYY-Www (ISO week)
      - MES    -> YYYY-MM
    Acepta formatos ISO con o sin 'Z' y con/sin microsegundos.
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
                # fallback: solo fecha
                ts = datetime.strptime(dt_iso[:10], "%Y-%m-%d")

    g = (granularidad or "DIA").upper()
    if g == "DIA":
        return ts.strftime("%Y-%m-%d")
    if g == "SEMANA":
        iso = ts.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    # MES
    return ts.strftime("%Y-%m")


# ==============================================================================
# SELECCIÓN DE ÁREA
# ==============================================================================

def _resolve_area_or_ask(
    *,
    client: RendimientoDescomposicionClient,
    area_id: Optional[int],
    area_nombre: Optional[str],
    modo_asistente: bool,
) -> Tuple[Optional[int], Optional[str], Optional[Dict[str, Any]]]:
    """
    Devuelve (area_id_resuelto, area_name_resuelto, ask_payload_o_None).
    Si falta área y 'modo_asistente' es True → devuelve un 'ask' con opciones (si hay sesión).
    Si el nombre es ambiguo → 'ask' con candidatas.
    """
    resolved_area_name: Optional[str] = None

    # Si viene ID, intentar resolver nombre (opcional)
    if area_id:
        try:
            areas = client.list_stock_areas()
            for a in areas:
                if int(a.get("id")) == int(area_id):
                    resolved_area_name = a.get("name") or None
                    break
        except Exception:
            pass
        return int(area_id), resolved_area_name, None

    # Si viene nombre, buscar coincidencias
    if area_nombre:
        try:
            match, candidates = client.find_area_candidates(area_nombre)
        except AttributeError:
            areas = client.list_stock_areas()
            match = next(
                ({"id": a["id"], "name": a["name"]}
                 for a in areas
                 if (a.get("name") or "").strip().lower() == area_nombre.strip().lower()),
                None
            )
            candidates = []

        if match:
            return int(match["id"]), match["name"], None
        if candidates:
            return None, None, {
                "status": "ask",
                "intent": "rendimiento_descomposicion",
                "prompt": f"Tu búsqueda coincide con varias áreas parecidas a '{area_nombre}'. Elige una:",
                "missing": ["area_id o area_nombre"],
                "options": candidates[:10],
            }
        raise HTTPException(status_code=400, detail=f"Área '{area_nombre}' no encontrada")

    # No llegó ni id ni nombre
    if modo_asistente:
        try:
            options = [{"id": a["id"], "label": a["name"]} for a in client.list_stock_areas()][:15]
        except Exception:
            options = []
        return None, None, {
            "status": "ask",
            "intent": "rendimiento_descomposicion",
            "prompt": "¿Sobre qué área quieres calcular el rendimiento de descomposición?",
            "missing": ["area_id o area_nombre"],
            "options": options,
        }

    # Sin asistente → 400 duro
    raise HTTPException(status_code=400, detail="Debes enviar 'area_id' o 'area_nombre'")


# ==============================================================================
# KPIs por movimiento (DESCOMPOSITION)
# ==============================================================================

def _compute_kpis_from_detail(
    detail: Dict[str, Any],
    product_filter: Optional[List[int]],
    warnings: List[str],
) -> Dict[str, Any]:
    """
    Calcula para un movimiento padre (OUT/DESCOMPOSITION) con childs:
      - usado_padre
      - manufacturados_total (ENTRY/DESCOMPOSITION/MANUFACTURED)
      - merma_total       (ENTRY/WASTE o type=WASTE)
      - rendimiento_porcentaje (si unidades coinciden)  ->  (manufacturados_total / usado_padre) * 100
      - devuelve metadatos: padre, fecha, movementId, createdAt y desglose por producto manufacturado
    """
    parent_qty = float(abs(detail.get("quantity") or 0))
    parent_product = detail.get("product") or {}
    parent_measure = parent_product.get("measure")
    parent_name = parent_product.get("name") or ""
    parent_id = parent_product.get("id")
    movement_id = int(detail.get("id"))
    created_at = detail.get("createdAt") or ""

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
            d = manuf_by_product[int(pid)]
            d["name"] = pname
            d["measure"] = pmeasure
            d["qty"] += qty
            continue

        # WASTE (ENTRY/WASTE o type=WASTE)
        if op == "ENTRY" and (ptype == "WASTE" or cat == "WASTE"):
            waste_total += qty
            continue

    # rendimiento solo si unidad coincide
    rendimiento = None
    if parent_measure and all((v["measure"] == parent_measure for v in manuf_by_product.values() if v["qty"] > 0)):
        if parent_qty > 0:
            rendimiento = (manuf_total / parent_qty) * 100.0
    else:
        # al menos una unidad distinta
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
        "manuf_by_product": {int(pid): v for pid, v in manuf_by_product.items()},
    }


def _stats(values: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    if not values:
        return None, None, None, None
    n = len(values)
    prom = sum(values) / n
    minv = min(values)
    maxv = max(values)
    if n > 1:
        var = sum((x - prom) ** 2 for x in values) / (n - 1)
        std = sqrt(var)
    else:
        std = 0.0
    return round(prom, 2), round(minv, 2), round(maxv, 2), round(std, 2)


# ==============================================================================
# SERVICE
# ==============================================================================

@log_call
def rendimiento_descomposicion_service(
    *,
    body: Dict[str, Any],
    http: Client = Depends(get_http_client),  # requerido por el proyecto
) -> Dict[str, Any]:
    """
    Resuelve POST /rendimientoDescomposicion
    - Valida contexto
    - Resuelve área (id/nombre) con 'ask' si aplica
    - Lista padres OUT/DESCOMPOSITION (paginado por fechas - chunking)
    - Obtiene detalle por movimiento en paralelo y calcula KPIs
    - Agrega por bucket (DIA/SEMANA/MES) y por producto
    - Soporta rangos largos (ej. 1 año) con bajo uso de memoria (streaming)
    """
    usuario = body.get("usuario")
    if not usuario:
        raise HTTPException(status_code=400, detail="Falta 'usuario'")

    # 1) Contexto
    ctx = get_user_context(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")

    # 2) Cliente Tecopos
    client = RendimientoDescomposicionClient(
        region=ctx["region"],
        token=ctx["token"],
        business_id=ctx["businessId"],
    )

    # 3) Área (id/nombre) con soporte 'ask' en asistente
    area_id_in = body.get("area_id")
    area_nombre = body.get("area_nombre")
    modo_asistente = bool(body.get("modo_asistente")) or bool(body.get("texto"))

    area_id, resolved_area_name, ask_payload = _resolve_area_or_ask(
        client=client,
        area_id=area_id_in,
        area_nombre=area_nombre,
        modo_asistente=modo_asistente,
    )
    if ask_payload:
        return ask_payload
    if not area_id:
        raise HTTPException(status_code=400, detail="Debes enviar 'area_id' o 'area_nombre'")

    # 4) Fechas de trabajo
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
    # Normalización informativa 00:01–23:59 (coherencia de proyecto)
    _df, _dt = normalizar_rango(
        datetime.combine(fi_dt, datetime.min.time()),
        datetime.combine(ff_dt, datetime.min.time()),
    )

    # 5) Filtros/flags
    granularidad = (body.get("granularidad") or "DIA").upper()
    if granularidad not in {"DIA", "SEMANA", "MES"}:
        granularidad = "DIA"

    product_filter = body.get("product_ids") or None
    if product_filter:
        try:
            product_filter = [int(x) for x in product_filter]
        except Exception:
            raise HTTPException(status_code=400, detail="'product_ids' debe ser una lista de enteros")

    incluir_movs = bool(body.get("incluir_movimientos", False))

    # 6) Parámetros de escalabilidad
    chunk_days = int(body.get("chunk_days") or 30)          # días por ventana
    max_concurrency = int(body.get("max_concurrency") or 8) # hilos para detalles
    modo_agregado = bool(body.get("modo_agregado", False))  # fuerza no guardar movimientos
    if modo_agregado:
        incluir_movs = False

    # 7) Acumuladores en streaming
    total_usado = 0.0
    total_manuf = 0.0
    total_merma = 0.0

    series_aggr: Dict[str, Dict[str, float]] = defaultdict(lambda: {"usado": 0.0, "manuf": 0.0, "merma": 0.0})
    prod_aggr: Dict[int, Dict[str, Any]] = defaultdict(lambda: {
        "name": "",
        "measure": None,
        "mov": 0,
        "usado": 0.0,
        "manuf": 0.0,
        "merma": 0.0,
        "rend_list": [],
    })
    movimientos_kpi: List[Dict[str, Any]] = [] if incluir_movs else None
    warnings: List[str] = []

    def _fetch_detail(mid: int) -> Optional[Dict[str, Any]]:
        try:
            detail = client.get_movement_detail(int(mid))  # padre OUT/DESCOMPOSITION con childs
            return _compute_kpis_from_detail(detail, product_filter, warnings)
        except Exception as e:
            warnings.append(f"Error al obtener detalle movementId={mid}: {e}")
            return None

    # 8) Chunking de fechas + paginación + paralelismo (pool único)
    executor = ThreadPoolExecutor(max_workers=max_concurrency)
    try:
        cur = fi_dt
        one_day = timedelta(days=1)

        while cur <= ff_dt:
            chunk_end = min(cur + timedelta(days=chunk_days - 1), ff_dt)

            ids_en_chunk: List[int] = []
            for page_items in client.iter_parent_movements(
                area_id=area_id,
                date_from=cur.strftime("%Y-%m-%d"),
                date_to=chunk_end.strftime("%Y-%m-%d"),
            ):
                for it in page_items:
                    mid = it.get("id")
                    if mid is not None:
                        ids_en_chunk.append(int(mid))

            if ids_en_chunk:
                futures = [executor.submit(_fetch_detail, mid) for mid in ids_en_chunk]
                for fut in as_completed(futures):
                    kpi = fut.result()
                    if not kpi:
                        continue

                    # --- agregados globales ---
                    total_usado += kpi["padre"]["usado"]
                    total_manuf += kpi["manufacturados_total"]
                    total_merma += kpi["merma_total"]

                    # --- serie temporal ---
                    b = _bucket_key(kpi.get("createdAt") or (kpi.get("fecha") + "T00:00:00"), granularidad)
                    series_aggr[b]["usado"] += kpi["padre"]["usado"]
                    series_aggr[b]["manuf"] += kpi["manufacturados_total"]
                    series_aggr[b]["merma"] += kpi["merma_total"]

                    # --- por producto (hijos MANUFACTURED) ---
                    for pid, info in (kpi.get("manuf_by_product") or {}).items():
                        pa = prod_aggr[int(pid)]
                        pa["name"] = info.get("name") or pa["name"]
                        if info.get("measure"):
                            pa["measure"] = info.get("measure")
                        pa["mov"] += 1
                        pa["usado"] += kpi["padre"]["usado"]
                        pa["manuf"] += float(info.get("qty") or 0.0)
                        pa["merma"] += kpi["merma_total"]
                        if kpi["rendimiento_porcentaje"] is not None:
                            pa["rend_list"].append(kpi["rendimiento_porcentaje"])

                    if incluir_movs:
                        movimientos_kpi.append({
                            "movementId": kpi["movementId"],
                            "fecha": kpi["fecha"],
                            "padre": kpi["padre"],
                            "manufacturados_total": round(kpi["manufacturados_total"], 4),
                            "merma_total": round(kpi["merma_total"], 4),
                            "rendimiento_porcentaje": kpi["rendimiento_porcentaje"],
                        })

            cur = chunk_end + one_day
    finally:
        executor.shutdown(wait=True)

    # 9) Cierre de agregados
    rend_ponderado = round((total_manuf / total_usado) * 100.0, 2) if total_usado > 0 else None

    series_ratio: Dict[str, Optional[float]] = {}
    for b, vals in series_aggr.items():
        rp = round((vals["manuf"] / vals["usado"]) * 100.0, 2) if vals["usado"] > 0 else None
        series_ratio[b] = rp

    series = [
        {
            "bucket": b,
            "padre_usado": round(vals["usado"], 4),
            "manufacturados": round(vals["manuf"] or 0.0, 4),
            "merma": round(vals["merma"] or 0.0, 4),
            "rendimiento_porcentaje": series_ratio[b],
        }
        for b, vals in sorted(series_aggr.items(), key=lambda kv: kv[0])
    ]

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

    return {
        "periodo": {
            "desde": fecha_inicio,
            "hasta": fecha_fin,
            "granularidad": granularidad,
        },
        "area": {
            "id": int(area_id),
            "nombre": resolved_area_name or "",
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
        "movimientos": (movimientos_kpi or []) if incluir_movs else [],
        "warnings": warnings,
    }


