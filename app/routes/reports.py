"""
Sales and analytics reporting endpoints.

This module groups endpoints that produce various reports and analyses,
such as sales summaries, stock break alerts, performance analysis,
daily sales, projections, and comparative metrics.  Keeping these
operations together helps maintain a coherent view of reporting
functionality and simplifies future enhancements or bug fixes.
"""

from __future__ import annotations

import logging
import time as time_module
from datetime import datetime, timedelta, time, timezone
from typing import Dict, List, Tuple

from app.core.http_sync import teco_request
from fastapi import APIRouter, HTTPException, Body, Query
from datetime import datetime, time as time_mod
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

class VentasVariasMonedasRequest(BaseModel):
    usuario: str
    fecha_inicio: datetime | str = Field(..., description="ISO datetime o 'YYYY-MM-DD'")
    fecha_fin: datetime | str = Field(..., description="ISO datetime o 'YYYY-MM-DD'")
    tasas_cambio: Optional[Dict[str, float]] = Field(
        default=None,
        description='Diccionario de tasas. Ej: {"USD_to_CUP": 250, "CUP_to_USD": 0.004}'
    )

from .. import models
from ..utils import (
    user_context,
    TIPOS_NEGOCIO,
    get_base_url,
    get_auth_headers,
    aplicar_modelo_proyeccion,
    enriquecer_proyeccion_con_nombres,
    analizar_desempeño_ventas,
)

def _parse_date_range(fi: datetime | str, ff: datetime | str) -> tuple[str, str]:
    def _parse(d):
        if isinstance(d, datetime):
            return d
        try:
            # 'YYYY-MM-DD'
            return datetime.strptime(d, "%Y-%m-%d")
        except Exception:
            # ISO 8601
            return datetime.fromisoformat(d)
    d1 = _parse(fi); d2 = _parse(ff)
    d1 = datetime.combine(d1.date(), time_mod(0, 1))
    d2 = datetime.combine(d2.date(), time_mod(23, 59))
    return d1.strftime("%Y-%m-%d %H:%M"), d2.strftime("%Y-%m-%d %H:%M")

def _convert(amount: float, from_code: str, to_code: str, tasas: Optional[Dict[str, float]]) -> Optional[float]:
    if from_code == to_code:
        return float(amount)
    if not tasas:
        return None
    key = f"{from_code}_to_{to_code}"
    rate = tasas.get(key)
    if rate is None:
        return None
    try:
        return float(amount) * float(rate)
    except Exception:
        return None

# Import pydantic for custom request model in reporte_ventas
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import time as time_cls

router = APIRouter()

# Set up a dedicated logger for ventas_diarias similar to the original code
logger = logging.getLogger("ventas_diarias")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler("ventas.log", encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


# Disabled original reporte_ventas; see optimised version below
#@router.post("/reporte-ventas")
def reporte_ventas_old(
    data: models.ReporteVentasRequest,
    formato: str | None = Query(
        None,
        description="Formato opcional del reporte (csv o excel) para descargar el detalle completo",
    ),
):
    """Genera un reporte de ventas entre dos fechas con resumen y exportación opcional."""
    # Validación y contexto de autenticación
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])

    # Construir rango de fechas con horas para extremos del día
    fecha_inicio = datetime.combine(data.fecha_inicio.date(), time(0, 1))
    fecha_fin = datetime.combine(data.fecha_fin.date(), time(23, 59))

    # Llamada a la API de Tecopos
    url = f"{base_url}/api/v1/report/selled-products"
    params = {
        "dateFrom": fecha_inicio.strftime("%Y-%m-%d %H:%M"),
        "dateTo": fecha_fin.strftime("%Y-%m-%d %H:%M"),
        "status": "BILLED",
    }
    res = teco_request("GET", url, headers=headers, params=params)
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudo obtener el reporte de ventas")
    productos_raw = res.json().get("products", [])

    # Transformar la respuesta en una lista de productos con ventas detalladas
    resumen: List[Dict[str, object]] = []
    for p in productos_raw:
        for venta in p.get("totalSales", []):
            resumen.append({
                "productId": p["productId"],
                "nombre": p["name"],
                "cantidad_vendida": p.get("quantitySales", 0),
                "total_ventas": venta.get("amount", 0),
                "moneda": venta.get("codeCurrency"),
                "unidad": p.get("measure"),
                "categoria": p.get("productCategory"),
                "area_venta": p.get("areaSales"),
                "stock_actual": float(p.get("totalQuantity", 0)),
            })

    # Si no hay productos, devolver mensaje vacío
    if not resumen:
        return {
            "status": "ok",
            "mensaje": f"No se encontraron ventas entre {fecha_inicio.date()} y {fecha_fin.date()}",
            "resumen": {},
            "productos": [],
        }

    # Calcular métricas agregadas para el resumen
    total_ventas = sum(item.get("total_ventas", 0) for item in resumen)
    total_cantidad = sum(item.get("cantidad_vendida", 0) for item in resumen)
    try:
        import pandas as pd  # se usa para ordenar y exportar
        df = pd.DataFrame(resumen)
        top_5 = (
            df.sort_values(by="total_ventas", ascending=False)
            .head(5)[["productId", "nombre", "cantidad_vendida", "total_ventas"]]
            .to_dict("records")
        )
    except Exception:
        # Fallback sin pandas
        top_5 = sorted(
            [
                {
                    "productId": item["productId"],
                    "nombre": item["nombre"],
                    "cantidad_vendida": item["cantidad_vendida"],
                    "total_ventas": item["total_ventas"],
                }
                for item in resumen
            ],
            key=lambda x: x["total_ventas"],
            reverse=True,
        )[:5]

    # Calcular agregados
    total_ventas = sum(item.get("total_ventas", 0) for item in resumen)
    total_cantidad = sum(item.get("cantidad_vendida", 0) for item in resumen)    
    total_stock = sum(item.get("stock_actual", 0) for item in resumen)

    # Actualiza el diccionario resumen_agregado
    resumen_agregado = {
        "total_ventas": round(total_ventas, 2),           # Monto total de ventas
        "cantidad_items_vendidos": round(total_cantidad, 2),   # Suma de unidades vendidas
        "cantidad_productos_vendidos": len(resumen),      # Número de productos distintos con ventas
        "stock_actual_total": round(total_stock, 2),       # Stock acumulado de todos los productos
        "top_5_productos": top_5,                          # Sigue mostrando el top 5, si lo deseas
    }

    # Si se solicita formato de archivo, generar CSV o Excel
    if formato:
        if formato.lower() not in {"csv", "excel"}:
            raise HTTPException(status_code=400, detail="Formato no soportado, use 'csv' o 'excel'")
        if 'pd' not in locals():
            raise HTTPException(status_code=500, detail="Pandas es requerido para exportar archivos")
        import pandas as pd  # asegurar disponibilidad
        df = pd.DataFrame(resumen)
        if formato.lower() == "csv":
            buffer = io.StringIO()
            df.to_csv(buffer, index=False)
            buffer.seek(0)
            return StreamingResponse(
                io.BytesIO(buffer.getvalue().encode("utf-8")),
                media_type="text/csv",
                headers={
                    "Content-Disposition": f"attachment; filename=reporte_ventas_{fecha_inicio.date()}_{fecha_fin.date()}.csv",
                },
            )
        else:  # excel
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False, sheet_name="Ventas")
            buffer.seek(0)
            return StreamingResponse(
                buffer,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={
                    "Content-Disposition": f"attachment; filename=reporte_ventas_{fecha_inicio.date()}_{fecha_fin.date()}.xlsx",
                },
            )

    # Respuesta JSON con resumen y detalle
    return {
        "status": "ok",
        "mensaje": f"Reporte del {fecha_inicio.date()} al {fecha_fin.date()}",
        "resumen": resumen_agregado,
        "productos": resumen,
    }

class ReporteVentasRequestNuevo(BaseModel):
    """
    Request body for the reporte-ventas endpoint.

    Extends the original ReporteVentasRequest by adding an optional
    ``incluir_stock`` flag to include inventory levels in the summary.
    """
    usuario: str
    fecha_inicio: datetime
    fecha_fin: datetime
    incluir_stock: Optional[bool] = False

@router.post("/reporte-ventas", summary="Genera reporte de ventas con totales (y stock opcional)")
def reporte_ventas(data: ReporteVentasRequestNuevo):
    """
    Genera un reporte de ventas entre dos fechas y devuelve totales de ventas,
    ítems vendidos y productos distintos.  Si ``incluir_stock`` es True se
    incluye un desglose del stock disponible por almacén.
    """
    # Validación y contexto de autenticación
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])

    # Normaliza las fechas al rango completo del día
    fi = datetime.combine(data.fecha_inicio.date(), time_cls(0, 1))
    ff = datetime.combine(data.fecha_fin.date(), time_cls(23, 59))

    # Llamada a la API de Tecopos (POST) para obtener el resumen de ventas
    url = f"{base_url}/api/v1/report/selled-products"
    payload = {
        "dateFrom": fi.strftime("%Y-%m-%d %H:%M"),
        "dateTo": ff.strftime("%Y-%m-%d %H:%M"),
    }
    resp = teco_request("POST", url, headers=headers, json=payload)
    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    data_json = resp.json()

    ventas = data_json.get("data") or data_json
    if not isinstance(ventas, list):
        ventas = [ventas] if ventas else []

    total_ventas = 0.0
    cant_items_vendidos = 0
    cant_productos_vendidos = 0

    for v in ventas:
        # Algunos endpoints devuelven nombres distintos para los campos; se cubren ambos
        total_ventas += float(v.get("totalAmount") or v.get("total") or 0)
        cant_items_vendidos += int(v.get("itemsCount") or v.get("items") or 0)
        cant_productos_vendidos += int(v.get("productsCount") or v.get("products") or 0)

    resultado: Dict[str, Any] = {
        "rango": {"desde": fi.isoformat(), "hasta": ff.isoformat()},
        "resumen": {
            "total_ventas": round(total_ventas, 2),
            "cantidad_items_vendidos": cant_items_vendidos,
            "cantidad_productos_vendidos": cant_productos_vendidos,
        },
        "raw": ventas,
    }

    if data.incluir_stock:
        stock_url = f"{base_url}/api/v1/report/stock/disponibility"
        stock_resp = teco_request("GET", stock_url, headers=headers)
        if stock_resp.status_code >= 400:
            raise HTTPException(status_code=stock_resp.status_code, detail=stock_resp.text)
        filas = stock_resp.json().get("data") or stock_resp.json()
        if not isinstance(filas, list):
            filas = [filas] if filas else []
        por_almacen: Dict[str, float] = {}
        total_general = 0.0
        for row in filas:
            stock_name = str(row.get("stockName") or "SIN_NOMBRE")
            qty = float(row.get("quantity") or 0)
            por_almacen[stock_name] = por_almacen.get(stock_name, 0.0) + qty
            total_general += qty
        resultado["stock"] = {"por_almacen": por_almacen, "total_general": total_general}

    return resultado


@router.post("/reporte-quiebre-stock")
def reporte_quiebre_stock(request: models.QuiebreRequest):
    """Identify products at risk of stock break based on recent sales."""
    try:
        hoy = datetime.today()
        fecha_fin = datetime.strptime(request.fecha_fin, "%Y-%m-%d") if request.fecha_fin else hoy
        fecha_inicio = datetime.strptime(request.fecha_inicio, "%Y-%m-%d") if request.fecha_inicio else hoy - timedelta(days=15)
        reporte = reporte_ventas(models.ReporteVentasRequest(
            usuario=request.usuario,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
        ))
        productos = reporte.get("productos", [])
        productos_riesgo: List[Dict[str, object]] = []
        productos_estrella: List[Dict[str, object]] = []
        for p in productos:
            cantidad_vendida = p.get("cantidad_vendida", 0)
            if cantidad_vendida <= 0:
                continue
            rotacion_diaria = cantidad_vendida / 15
            stock = float(p.get("stock_actual", 0))
            if rotacion_diaria <= 2:
                continue
            if stock <= 0:
                continue
            dias_quiebre = round(stock / rotacion_diaria, 1)
            if dias_quiebre > 15:
                continue
            urgencia = "crítico" if dias_quiebre <= 5 else "advertencia"
            item = {
                "nombre": p["nombre"],
                "rotacion_diaria": round(rotacion_diaria, 2),
                "stock_actual": stock,
                "dias_quiebre": dias_quiebre,
                "nivel_urgencia": urgencia,
            }
            utilidad = p.get("total_ventas", 0)
            if rotacion_diaria > 5 and utilidad > 100:
                productos_estrella.append(item)
            else:
                productos_riesgo.append(item)
        productos_estrella.sort(key=lambda x: x["dias_quiebre"])
        productos_riesgo.sort(key=lambda x: x["dias_quiebre"])
        todos = productos_estrella + productos_riesgo
        total_paginas = (len(todos) + 9) // 10
        pagina = request.pagina or 1
        inicio_idx = (pagina - 1) * 10
        fin_idx = inicio_idx + 10
        pagina_actual = todos[inicio_idx:fin_idx]
        return {
            "status": "ok",
            "mensaje": f"Análisis de quiebre del {fecha_inicio.date()} al {fecha_fin.date()}",
            "pagina_actual": pagina,
            "total_paginas": total_paginas,
            "productos_estrella": productos_estrella if pagina == 1 else [],
            "productos_riesgo": pagina_actual if pagina > 1 else [],
        }
    except Exception as e:
        return {"status": "error", "mensaje": f"Ocurrió un error: {str(e)}"}


@router.post("/analisis-desempeno")
def analisis_desempeno(data: models.AnalisisDesempenoRequest):
    """Return performance analysis metrics for the specified date range."""
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    url = f"{base_url}/api/v1/report/selled-products"
    fecha_inicio = datetime.combine(data.fecha_inicio.date(), time(0, 1))
    fecha_fin = datetime.combine(data.fecha_fin.date(), time(23, 59))
    params = {
        "dateFrom": fecha_inicio.strftime("%Y-%m-%d %H:%M"),
        "dateTo": fecha_fin.strftime("%Y-%m-%d %H:%M"),
        "status": "BILLED",
    }
    res = teco_request("GET", url, headers=headers, params=params)
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudo obtener el reporte de ventas")
    productos_raw = res.json().get("products", [])
    productos: List[Dict[str, object]] = []
    for p in productos_raw:
        for venta in p.get("totalSales", []):
            productos.append({
                "productId": p["productId"],
                "nombre": p["name"],
                "cantidad_vendida": p["quantitySales"],
                "total_ventas": venta["amount"],
                "moneda": venta["codeCurrency"],
                "unidad": p["measure"],
                "categoria": p["productCategory"],
                "area_venta": p["areaSales"],
                "total_cost": p.get("totalCost", {}).get("amount", 0),
            })
    analisis = analizar_desempeño_ventas(productos)
    return {
        "status": "ok",
        "mensaje": f"Análisis del {data.fecha_inicio.date()} al {data.fecha_fin.date()}",
        "resultado": analisis,
    }


@router.post("/ventas-diarias")
def ventas_diarias(data: Dict[str, str]):
    """Return a list of daily sales between two dates (inclusive)."""
    usuario = data.get("usuario")
    fecha_inicio_str = data.get("fecha_inicio")
    fecha_fin_str = data.get("fecha_fin")
    if not usuario or not fecha_inicio_str or not fecha_fin_str:
        raise HTTPException(status_code=400, detail="usuario, fecha_inicio y fecha_fin son requeridos")
    ctx = user_context.get(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    fecha_inicio = datetime.strptime(fecha_inicio_str, "%Y-%m-%d")
    fecha_fin = datetime.strptime(fecha_fin_str, "%Y-%m-%d")
    if fecha_inicio > fecha_fin:
        raise HTTPException(status_code=400, detail="fecha_inicio debe ser menor o igual que fecha_fin")
    resultados: List[Dict[str, object]] = []
    dias = (fecha_fin - fecha_inicio).days + 1
    for i in range(dias):
        dia = fecha_inicio + timedelta(days=i)
        inicio_dia = datetime.combine(dia.date(), time(0, 1))
        fin_dia = datetime.combine(dia.date(), time(23, 59))
        date_from = inicio_dia.strftime("%Y-%m-%d %H:%M")
        date_to = fin_dia.strftime("%Y-%m-%d %H:%M")
        url = f"{base_url}/api/v1/report/selled-products?dateFrom={date_from}&dateTo={date_to}&status=BILLED"
        logger.info(f"📅 Consultando ventas del {dia.strftime('%Y-%m-%d')}")
        logger.info(f"➡️ URL: {url}")
        logger.info(f"➡️ HEADERS: {headers}")
        try:
            res = teco_request("GET", url, headers=headers)
            logger.info(f"⬅️ Status Code: {res.status_code}")
            logger.info(f"⬅️ Respuesta: {res.text[:500]}")
            if res.status_code != 200:
                raise Exception(f"Error HTTP {res.status_code}: {res.text}")
            resultados.append({
                "fecha": dia.strftime("%Y-%m-%d"),
                "productos": res.json().get("products", []),
            })
        except Exception as e:
            logger.error(f"❌ Error en {dia.strftime('%Y-%m-%d')}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error consultando el día {dia.strftime('%Y-%m-%d')}: {str(e)}")
    return {
        "status": "ok",
        "mensaje": f"Ventas diarias entre {fecha_inicio_str} y {fecha_fin_str}",
        "total_dias": dias,
        "ventas_diarias": resultados,
    }


@router.get("/tipos-negocio")
def obtener_tipos_negocio():
    """List the supported business types along with their recommended models."""
    return {
        "status": "ok",
        "tipos_negocio": [
            {
                "nombre": nombre,
                "historial_recomendado_dias": datos["historial_recomendado_dias"],
                "proyeccion_recomendada": datos["proyeccion_recomendada"],
                "descripcion_modelo": datos.get("descripcion_modelo", ""),
            }
            for nombre, datos in TIPOS_NEGOCIO.items()
        ],
    }


@router.post("/proyeccion-ventas")
def proyeccion_ventas(
    usuario: str = Body(...),
    tipo_negocio: str = Body(...),
    fecha_base: str = Body(default=None),
):
    """Calculate a sales projection for a business type using recent history."""
    if tipo_negocio not in TIPOS_NEGOCIO:
        raise HTTPException(status_code=400, detail={
            "error": "Tipo de negocio no soportado",
            "tipos_disponibles": list(TIPOS_NEGOCIO.keys()),
        })
    dias_historial = TIPOS_NEGOCIO[tipo_negocio]["historial_recomendado_dias"]
    modelo = TIPOS_NEGOCIO[tipo_negocio]["proyeccion_recomendada"]
    fecha_fin = datetime.strptime(fecha_base, "%Y-%m-%d") if fecha_base else datetime.now()
    fecha_inicio = fecha_fin - timedelta(days=dias_historial)
    ventas_diarias_resultado: List[Dict[str, object]] = []
    dias_fallidos: List[str] = []
    fecha_actual = fecha_inicio
    while fecha_actual <= fecha_fin:
        payload = {
            "usuario": usuario,
            "fecha_inicio": fecha_actual.strftime("%Y-%m-%d"),
            "fecha_fin": fecha_actual.strftime("%Y-%m-%d"),
        }
        intentos = 0
        exito = False
        while intentos < 3 and not exito:
            try:
                data_resp = ventas_diarias(payload)
                if data_resp.get("status") != "ok":
                    raise Exception(data_resp.get("mensaje", "Error inesperado en ventas-diarias"))
                ventas_diarias_resultado.append({
                    "fecha": fecha_actual.strftime("%Y-%m-%d"),
                    "productos": data_resp.get("ventas_diarias", [{}])[0].get("productos", []),
                })
                exito = True
            except Exception:
                intentos += 1
                time_module.sleep(1)
        if not exito:
            dias_fallidos.append(fecha_actual.strftime("%Y-%m-%d"))
        fecha_actual += timedelta(days=1)
    if not ventas_diarias_resultado:
        raise HTTPException(status_code=500, detail="No se pudieron obtener datos de ventas")
    resultado = aplicar_modelo_proyeccion(ventas_diarias_resultado, modelo)
    ctx = user_context.get(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    resultado = enriquecer_proyeccion_con_nombres(usuario, resultado, base_url, headers)
    resultado_ordenado = sorted(resultado, key=lambda x: x["cantidad_proyectada"], reverse=True)
    resumen = {
        "total_productos_proyectados": len(resultado),
        "top_5_productos": [
            {"nombre": p["nombre"], "cantidad_proyectada": p["cantidad_proyectada"]}
            for p in resultado_ordenado[:5]
        ],
    }
    return {
        "status": "ok",
        "mensaje": f"Proyección calculada usando modelo '{modelo}' para negocio '{tipo_negocio}'",
        "tipo_negocio": tipo_negocio,
        "modelo_usado": modelo,
        "dias_analizados": dias_historial,
        "fecha_inicio": fecha_inicio.strftime("%Y-%m-%d"),
        "fecha_fin": fecha_fin.strftime("%Y-%m-%d"),
        "resumen": resumen,
        "proyeccion_completa": resultado_ordenado,
        "dias_sin_datos": dias_fallidos,
    }


@router.post("/reporte-ventas-global")
def reporte_ventas_global(data: models.ReporteGlobalRequest):
    """Aggregate sales across all branches for the user within a date range."""
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    ahora_utc = datetime.now(timezone.utc)
    fi = data.fecha_inicio or ahora_utc - timedelta(days=30)
    ff = data.fecha_fin or ahora_utc
    if fi.tzinfo is None:
        fi = fi.replace(tzinfo=timezone.utc)
    if ff.tzinfo is None:
        ff = ff.replace(tzinfo=timezone.utc)
    if fi > ff:
        fi, ff = ff, fi
    if ff > ahora_utc:
        ff = ahora_utc
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    params = {"dateFrom": fi.date().isoformat(), "dateTo": ff.date().isoformat()}
    url = f"{base_url}/api/v1/report/incomes/v2/total-sales"
    resp = teco_request("GET", url, headers=headers, params=params)
    if resp.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail=f"Error al obtener ventas globales ({resp.status_code}): {resp.text}",
        )
    raw = resp.json()
    detalles: List[Dict[str, object]] = []
    total_sales = 0.0
    total_cost = 0.0
    total_profit = 0.0
    for b in raw:
        ventas = b.get("totalSalesMainCurerncy") or b.get("totalIncomesMainCurrency", 0)
        costo = b.get("totalCost", 0)
        ganancia = b.get("grossProfit", ventas - costo)
        detalles.append({
            "businessId": b["id"],
            "businessName": b["name"],
            "sales": round(ventas, 2),
            "cost": round(costo, 2),
            "profit": round(ganancia, 2),
        })
        total_sales += ventas
        total_cost += costo
        total_profit += ganancia
    return {
        "period": {"start": fi.date().isoformat(), "end": ff.date().isoformat()},
        "total_sales": round(total_sales, 2),
        "total_cost": round(total_cost, 2),
        "total_profit": round(total_profit, 2),
        "currency": raw[0].get("costCurrency", "") if raw else "",
        "by_business": detalles,
    }


@router.get("/comparativa-semanal")
def comparativa_semanal(
    usuario: str = Query(..., description="Usuario registrado (clave en user_context)"),
    fecha_inicio: str = Query(..., description="Fecha inicial en formato YYYY-MM-DD"),
    semanas: int = Query(2, ge=2, le=8, description="Número de semanas a comparar"),
):
    """Compare daily sales across multiple weeks starting from a given date."""
    ctx = user_context.get(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    fecha_ini = datetime.strptime(fecha_inicio, "%Y-%m-%d")
    dias_totales = semanas * 7
    fecha_fin = fecha_ini + timedelta(days=dias_totales - 1)
    ventas_data: List[Dict[str, object]] = []
    for offset in range(dias_totales):
        dia = fecha_ini + timedelta(days=offset)
        rv_req = models.ReporteVentasRequest(
            usuario=usuario,
            fecha_inicio=datetime.combine(dia.date(), time(0, 1)),
            fecha_fin=datetime.combine(dia.date(), time(23, 59)),
        )
        rv_res = reporte_ventas(rv_req)
        productos = rv_res.get("productos", [])
        total_dia = sum(p.get("total_ventas", 0) for p in productos)
        moneda = productos[0].get("moneda") if productos else ctx.get("currency", "")
        ventas_data.append({"amount": total_dia, "currency": moneda})
    if not any(v["amount"] > 0 for v in ventas_data):
        raise HTTPException(status_code=404, detail=(
            f"Sin datos de ventas desde {fecha_ini.date()} hasta {fecha_fin.date()}. "
            "Comprueba el rango consultado."
        ))
    semanas_ventas = [ventas_data[i * 7:(i + 1) * 7] for i in range(semanas)]
    dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    comparativa: List[Dict[str, object]] = []
    for idx, dia_nombre in enumerate(dias_semana):
        fila: Dict[str, object] = {"dia": dia_nombre}
        for s in range(semanas):
            vd = semanas_ventas[s][idx]
            fila[f"semana{s+1}"] = f"{vd['amount']:.2f} {vd['currency']}"
        for s in range(1, semanas):
            base = semanas_ventas[s - 1][idx]["amount"]
            actual = semanas_ventas[s][idx]["amount"]
            diff = actual - base
            pct = round((diff / base * 100) if base else 0, 2)
            fila[f"diferencia_s{s}_s{s+1}"] = f"{diff:.2f} {vd['currency']}"
            fila[f"porcentaje_s{s}_s{s+1}"] = f"{pct}%"
        comparativa.append(fila)
    return {
        "negocio": ctx.get("businessName", "(desconocido)"),
        "fecha_inicio": fecha_ini.date().isoformat(),
        "fecha_fin": fecha_fin.date().isoformat(),
        "comparativa": comparativa,
    }


@router.post("/ticket-promedio")
def ticket_promedio(data: models.RangoFechasConHora) -> Dict[str, dict]:
    """Calculate average order ticket for each currency within a date range."""
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Sesión no iniciada")
    url_base = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    params = {
        "dateFrom": data.fecha_inicio.strftime("%Y-%m-%d %H:%M"),
        "dateTo": data.fecha_fin.strftime("%Y-%m-%d %H:%M"),
        "status": "BILLED",
    }
    url = f"{url_base}/api/v1/report/byorders"
    response = teco_request("GET", url, headers=headers, params=params)
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Error al obtener órdenes")
    response_data = response.json()
    ordenes = response_data.get("orders", [])
    if not isinstance(ordenes, list):
        raise HTTPException(status_code=500, detail="Respuesta inesperada de Tecopos")
    resumen: Dict[str, Dict[str, object]] = {}
    for orden in ordenes:
        for item in orden.get("totalToPay", []):
            moneda = item["codeCurrency"]
            total = item["amount"]
            if moneda not in resumen:
                resumen[moneda] = {"cantidad_ordenes": 0, "total_ventas": 0.0}
            resumen[moneda]["cantidad_ordenes"] += 1
            resumen[moneda]["total_ventas"] += total
    for moneda in resumen:
        resumen[moneda]["ticket_promedio"] = round(
            resumen[moneda]["total_ventas"] / resumen[moneda]["cantidad_ordenes"], 2
        )
    return resumen

@router.post("/reporte-ventas-varias-monedas")
def reporte_ventas_varias_monedas(data: VentasVariasMonedasRequest):
    # Bloque obligatorio
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])

    dateFrom, dateTo = _parse_date_range(data.fecha_inicio, data.fecha_fin)

    # 1) Ventas vendidas
    url = f"{base_url}/api/v1/report/selled-products"
    payload = {"dateFrom": dateFrom, "dateTo": dateTo}
    resp = teco_request("POST", url, headers=headers, json=payload)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Error al obtener reporte de ventas")
    ventas = resp.json().get("data") or resp.json()
    if not isinstance(ventas, list):
        ventas = [ventas] if ventas else []

    # 2) Stock actual (opcional)
    stock_map: Dict[int, float] = {}
    stock_url = f"{base_url}/api/v1/report/stock/disponibility"
    sresp = teco_request("GET", stock_url, headers=headers)
    if sresp.status_code == 200:
        filas = sresp.json().get("data") or sresp.json().get("items") or sresp.json()
        if not isinstance(filas, list):
            filas = [filas] if filas else []
        for r in filas:
            pid = (r.get("product") or {}).get("id") or r.get("productId")
            qty = r.get("quantity") or r.get("available") or r.get("stock")
            if pid is not None and qty is not None:
                try:
                    stock_map[int(pid)] = float(qty)
                except Exception:
                    pass

    productos_out: List[Dict[str, Any]] = []
    for v in ventas:
        pid = v.get("productId") or (v.get("product") or {}).get("id")
        nombre = v.get("name") or (v.get("product") or {}).get("name") or "SIN_NOMBRE"
        cantidad = float(v.get("quantitySales") or v.get("quantity") or 0)
        medida = v.get("measure") or (v.get("product") or {}).get("measure") or ""
        categoria = v.get("category") or (v.get("product") or {}).get("category") or ""
        area_venta = v.get("areaSales") or v.get("area") or ""

        # Total ventas por moneda (array u objeto)
        ventas_arr = v.get("totalSales") or []
        if isinstance(ventas_arr, dict):  # si viene como objeto único
            ventas_arr = [ventas_arr]

        totales_por_moneda: Dict[str, float] = {}
        for t in ventas_arr:
            code = t.get("codeCurrency") or t.get("currency") or "CUP"
            amt = float(t.get("amount") or 0)
            totales_por_moneda[code] = totales_por_moneda.get(code, 0.0) + amt

        # Costos (si están)
        total_cost = v.get("totalCost") or {}
        total_fixed = v.get("totalFixedCost") or {}
        cost_amount = float(total_cost.get("amount") or 0) + float(total_fixed.get("amount") or 0)
        cost_code = total_cost.get("codeCurrency") or total_fixed.get("codeCurrency") or "CUP"

        # Determinar moneda principal (preferimos CUP si hay tasa)
        principal = "CUP" if data.tasas_cambio and any(k.endswith("_to_CUP") for k in data.tasas_cambio) else (list(totales_por_moneda.keys())[:1] or ["CUP"])[0]

        # Conversión a la moneda principal
        venta_principal = 0.0
        for code, amt in totales_por_moneda.items():
            conv = _convert(amt, code, principal, data.tasas_cambio)
            venta_principal += conv if conv is not None else (amt if code == principal else 0.0)

        # Coste convertido a principal
        coste_principal = _convert(cost_amount, cost_code, principal, data.tasas_cambio)
        if coste_principal is None and cost_code == principal:
            coste_principal = cost_amount
        utilidad_estimada = None
        if coste_principal is not None:
            utilidad_estimada = venta_principal - coste_principal

        productos_out.append({
            "productId": pid,
            "nombre": nombre,
            "cantidad_vendida": cantidad,
            "unidad": medida,
            "categoria": categoria,
            "area_venta": area_venta,
            "stock_actual": stock_map.get(int(pid)) if pid is not None else None,
            "venta_total_moneda_principal": round(venta_principal, 4),
            "moneda_principal": principal,
            "total_coste": float(cost_amount),
            "moneda_coste": cost_code,
            "venta_usd": round(totales_por_moneda.get("USD", 0.0), 4),
            "venta_cup": round(totales_por_moneda.get("CUP", 0.0), 4),
            "venta_eur": round(totales_por_moneda.get("EUR", 0.0), 4),
            "coste_convertido_a_moneda_principal": round(coste_principal, 4) if coste_principal is not None else None,
            "tasa_utilizada": (data.tasas_cambio.get(f"{cost_code}_to_{principal}") if data.tasas_cambio else None),
            "utilidad_estimada": round(utilidad_estimada, 4) if utilidad_estimada is not None else None,
        })

    return {
        "status": "ok",
        "mensaje": f"Ventas entre {dateFrom} y {dateTo}",
        "productos": productos_out,
    }

class AnalisisVariasMonedasRequest(BaseModel):
    usuario: str
    fecha_inicio: datetime | str
    fecha_fin: datetime | str
    tasas_cambio: Optional[Dict[str, float]] = None

@router.post("/analisis-desempeno-varias-monedas")
def analisis_desempeno_varias_monedas(data: AnalisisVariasMonedasRequest):
    # Auth + headers
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])

    dateFrom, dateTo = _parse_date_range(data.fecha_inicio, data.fecha_fin)

    # Ventas
    url = f"{base_url}/api/v1/report/selled-products"
    payload = {"dateFrom": dateFrom, "dateTo": dateTo}
    resp = teco_request("POST", url, headers=headers, json=payload)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Error al obtener reporte de ventas")
    ventas = resp.json().get("data") or resp.json()
    if not isinstance(ventas, list):
        ventas = [ventas] if ventas else []

    # Agrega por producto (conversión a principal)
    principal = "CUP" if data.tasas_cambio and any(k.endswith("_to_CUP") for k in (data.tasas_cambio or {})) else "USD"
    resumen: Dict[int, Dict[str, Any]] = {}

    for v in ventas:
        pid = v.get("productId") or (v.get("product") or {}).get("id")
        if pid is None:
            # si no hay ID, lo agregamos como -1 nameless
            pid = -1
        nombre = v.get("name") or (v.get("product") or {}).get("name") or "SIN_NOMBRE"
        medida = v.get("measure") or (v.get("product") or {}).get("measure") or ""
        categoria = v.get("category") or (v.get("product") or {}).get("category") or ""
        area_venta = v.get("areaSales") or v.get("area") or ""
        cantidad = float(v.get("quantitySales") or v.get("quantity") or 0)

        ventas_arr = v.get("totalSales") or []
        if isinstance(ventas_arr, dict):
            ventas_arr = [ventas_arr]

        totales_por_moneda: Dict[str, float] = {}
        for t in ventas_arr:
            code = t.get("codeCurrency") or t.get("currency") or "CUP"
            amt = float(t.get("amount") or 0)
            totales_por_moneda[code] = totales_por_moneda.get(code, 0.0) + amt

        total_cost = v.get("totalCost") or {}
        total_fixed = v.get("totalFixedCost") or {}
        cost_amount = float(total_cost.get("amount") or 0) + float(total_fixed.get("amount") or 0)
        cost_code = total_cost.get("codeCurrency") or total_fixed.get("codeCurrency") or "CUP"

        # monto en principal
        venta_principal = 0.0
        for code, amt in totales_por_moneda.items():
            conv = _convert(amt, code, principal, data.tasas_cambio)
            venta_principal += conv if conv is not None else (amt if code == principal else 0.0)

        coste_principal = _convert(cost_amount, cost_code, principal, data.tasas_cambio)
        if coste_principal is None and cost_code == principal:
            coste_principal = cost_amount

        bucket = resumen.setdefault(int(pid), {
            "productId": pid if pid != -1 else None,
            "nombre": nombre,
            "unidad": medida,
            "categoria": categoria,
            "area_venta": area_venta,
            "cantidad_vendida": 0.0,
            "venta_total_moneda_principal": 0.0,
            "total_coste_principal": 0.0,
            "moneda_principal": principal,
        })
        bucket["cantidad_vendida"] += cantidad
        bucket["venta_total_moneda_principal"] += venta_principal
        bucket["total_coste_principal"] += (coste_principal or 0.0)

    # A la salida en lista + utilidad
    salida: List[Dict[str, Any]] = []
    for pid, b in resumen.items():
        utilidad = b["venta_total_moneda_principal"] - b["total_coste_principal"]
        salida.append({
            "productId": b["productId"],
            "nombre": b["nombre"],
            "cantidad_vendida": round(b["cantidad_vendida"], 4),
            "unidad": b["unidad"],
            "categoria": b["categoria"],
            "area_venta": b["area_venta"],
            "venta_total_moneda_principal": round(b["venta_total_moneda_principal"], 4),
            "moneda_principal": b["moneda_principal"],
            "total_coste": round(b["total_coste_principal"], 4),
            "moneda_coste": b["moneda_principal"],  # ya convertido a principal
            "utilidad_estimada": round(utilidad, 4),
        })

    return {
        "status": "ok",
        "mensaje": f"Análisis generado entre {dateFrom} y {dateTo}",
        "resultado": salida,
    }
