from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
from math import sqrt

from fastapi import Depends, HTTPException
from httpx import Client

from app.core.context import get_user_context
from app.utils import normalizar_rango
from app.core.http_sync import get_http_client  # inyección requerida (sin paréntesis)
from app.clients.rendimiento_descomposicion_client import RendimientoDescomposicionClient

# Helpers locales (no exponen datos sensibles)
from datetime import datetime, date
from zoneinfo import ZoneInfo


# --------------------------
# FECHAS
# --------------------------
def _parse_yyyy_mm_dd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _today_ny() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def _bucket_key(dt_iso: str, granularidad: str) -> str:
    """
    Retorna la clave de bucket en string según granularidad.
    - DIA: YYYY-MM-DD
    - SEMANA: YYYY-Www (ISO week)
    - MES: YYYY-MM
    """
    # Formatos posibles: "2025-08-26T15:18:34.724Z" o sin Z
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
    if granularidad == "DIA":
        return ts.strftime("%Y-%m-%d")
    if granularidad == "SEMANA":
        iso = ts.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    # MES
    return ts.strftime("%Y-%m")


# --------------------------
# SELECCIÓN DE ÁREA
# --------------------------
def _resolve_area_or_ask(
    *,
    client: RendimientoDescomposicionClient,
    area_id: Optional[int],
    area_nombre: Optional[str],
    modo_asistente: bool,
) -> Tuple[Optional[int], Optional[str], Optional[Dict[str, Any]]]:
    """
    Devuelve (area_id_resuelto, area_name_resuelto, ask_payload_o_None).
    Si falta área y 'modo_asistente' es True → ask con opciones (si hay sesión).
    Si el nombre es ambiguo → ask con candidatas.
    """
    resolved_area_name: Optional[str] = None

    # Si viene ID, intentar resolver nombre (opcional)
    if area_id:
        try:
            # intento de obtener nombre de la lista (opcional; si falla, seguimos con None)
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
        # Preferimos usar find_area_candidates si existe en el client
        try:
            match, candidates = client.find_area_candidates(area_nombre)
        except AttributeError:
            # Si no existe, degradar a búsqueda exacta simple
            areas = client.list_stock_areas()
            match = next(({"id": a["id"], "name": a["name"]} for a in areas if (a.get("name") or "").strip().lower() == area_nombre.strip().lower()), None)
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
        # En asistente, pedimos selección (si hay sesión podremos poblar opciones desde la ruta que uses para listar áreas)
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


# --------------------------
# KPIs por movimiento
# --------------------------
def _compute_kpis_from_detail(
    detail: Dict[str, Any],
    product_filter: Optional[List[int]],
    warnings: List[str],
) -> Dict[str, Any]:
    """
    Calcula:
      - usado_padre
      - manufacturados_total (solo hijos ENTRY/DESCOMPOSITION/MANUFACTURED)
      - merma_total (ENTRY/WASTE o type=WASTE)
      - rendimiento_porcentaje (si misma unidad)
      - devuelve además metadatos: padre, fecha, movementId
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
            # filtro de productos no aplica a merma
            waste_total += qty
            continue

    # rendimiento solo si unidad coincide
    rendimiento = None
    if parent_measure and all((v["measure"] == parent_measure for v in manuf_by_product.values() if v["qty"] > 0)):
        if parent_qty > 0:
            rendimiento = (manuf_total / parent_qty) * 100.0
    else:
        # detectar si hubo al menos un hijo manufacturado con unidad distinta
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


# --------------------------
# SERVICE
# --------------------------
def rendimiento_descomposicion_service(
    *,
    body: Dict[str, Any],
    http: Client = Depends(get_http_client),  # requerido por el proyecto
) -> Dict[str, Any]:
    """
    Resuelve POST /rendimientoDescomposicion
    - Valida contexto
    - Resuelve área (id/nombre) con 'ask' si aplica
    - Lista padres OUT/DESCOMPOSITION (paginado)
    - Detalle por movimiento y KPIs
    - Agregados por bucket (DIA/SEMANA/MES) y por producto
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
        # Defensa adicional (no debería ocurrir aquí)
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

    # Guardamos rango normalizado (coherencia de proyecto), aunque Tecopos usará sólo la parte fecha
    fi_dt = _parse_yyyy_mm_dd(fecha_inicio)
    ff_dt = _parse_yyyy_mm_dd(fecha_fin)
    _df, _dt = normalizar_rango(
        datetime.combine(fi_dt, datetime.min.time()),
        datetime.combine(ff_dt, datetime.min.time()),
    )  # devuelve "YYYY-MM-DD HH:MM" (informativo)

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

    # 6) Listar padres (paginación) y computar KPIs por movimiento
    warnings: List[str] = []
    movimientos_kpi: List[Dict[str, Any]] = []
    # IMPORTANTe: Tecopos espera YYYY-MM-DD; pasamos fecha_inicio/fin (no las horas)
    for page_items in client.iter_parent_movements(area_id=area_id, date_from=fecha_inicio, date_to=fecha_fin):
        for it in page_items:
            mid = it.get("id")
            if mid is None:
                continue
            detail = client.get_movement_detail(int(mid))
            kpi = _compute_kpis_from_detail(detail, product_filter, warnings)
            movimientos_kpi.append(kpi)

    # 7) Agregados
    # 7.1 Resumen global
    total_usado = sum(m["padre"]["usado"] for m in movimientos_kpi)
    total_manuf = sum(m["manufacturados_total"] for m in movimientos_kpi)
    total_merma = sum(m["merma_total"] for m in movimientos_kpi)
    rend_ponderado = None
    if total_usado > 0:
        rend_ponderado = round((total_manuf / total_usado) * 100.0, 2)

    # 7.2 Series por bucket
    series_aggr: Dict[str, Dict[str, float]] = defaultdict(lambda: {"usado": 0.0, "manuf": 0.0, "merma": 0.0})
    series_ratio: Dict[str, Optional[float]] = {}
    for m in movimientos_kpi:
        b = _bucket_key(m.get("createdAt") or (m.get("fecha") + "T00:00:00"), granularidad)
        series_aggr[b]["usado"] += m["padre"]["usado"]
        series_aggr[b]["manuf"] += m["manufacturados_total"]
        series_aggr[b]["merma"] += m["merma_total"]

    for b, vals in series_aggr.items():
        rp = None
        if vals["usado"] > 0:
            rp = round((vals["manuf"] / vals["usado"]) * 100.0, 2)
        series_ratio[b] = rp

    series = [
        {
            "bucket": b,
            "padre_usado": round(vals["usado"], 4),
            "manufacturados": round(vals["manuf"], 4),
            "merma": round(vals["merma"], 4),
            "rendimiento_porcentaje": series_ratio[b],
        }
        for b, vals in sorted(series_aggr.items(), key=lambda kv: kv[0])
    ]

    # 7.3 Por producto (solo hijos MANUFACTURED)
    prod_aggr: Dict[int, Dict[str, Any]] = defaultdict(lambda: {
        "name": "",
        "measure": None,
        "mov": 0,
        "usado": 0.0,
        "manuf": 0.0,
        "merma": 0.0,
        "rend_list": [],  # rendimientos por movimiento donde participa
    })
    for m in movimientos_kpi:
        for pid, info in (m.get("manuf_by_product") or {}).items():
            pa = prod_aggr[int(pid)]
            pa["name"] = info.get("name") or pa["name"]
            pa["measure"] = info.get("measure") if info.get("measure") else pa["measure"]
            pa["mov"] += 1
            pa["usado"] += m["padre"]["usado"]
            pa["manuf"] += float(info.get("qty") or 0.0)
            pa["merma"] += m["merma_total"]  # aproximación: asociar merma total del movimiento
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

    # 8) Preparar salida EXACTA al contrato
    out = {
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
