"""
services/report_service.py
--------------------------

Business logic for various reporting endpoints including sales
analysis, daily sales, stock break reporting, projections and
comparisons. Functions in this module mirror the behaviour of the
original monolithic endpoints but operate with the shared HTTP client
and structured schemas. Error handling is consistent with FastAPI’s
HTTPException.
"""

from __future__ import annotations

from typing import Dict, Any, List, Tuple
from datetime import datetime, timedelta, time, timezone, date
from fastapi import HTTPException

from app.core.context import get_user_context
from app.core.auth import get_base_url, build_auth_headers
from app.clients.http_client import HTTPClient
from app.logging_config import logger, log_call
import json
from app.schemas.reports import (
    QuiebreRequest,
    ReporteVentasRequest,
    AnalisisDesempenoRequest,
    ReporteGlobalRequest,
    RangoFechasConHora,
)

from collections import defaultdict


@log_call
def reporte_ventas(data: ReporteVentasRequest, http_client: HTTPClient) -> Dict[str, Any]:
    """Retrieve a detailed sales report for a date range.

    Calls the Tecopos report endpoint and summarises the response
    according to the legacy output structure. Dates are normalised to
    include the full day.
    """
    ctx = get_user_context(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    # adjust times to full day
    fecha_inicio = datetime.combine(data.fecha_inicio.date(), time(0, 1))
    fecha_fin = datetime.combine(data.fecha_fin.date(), time(23, 59))
    url = f"{base_url}/api/v1/report/selled-products"
    params = {
        "dateFrom": fecha_inicio.strftime("%Y-%m-%d %H:%M"),
        "dateTo": fecha_fin.strftime("%Y-%m-%d %H:%M"),
        "status": "BILLED",
    }
    res = http_client.request("GET", url, headers=headers, params=params)
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudo obtener el reporte de ventas")
    productos = res.json().get("products", [])
    resumen: List[Dict[str, Any]] = []
    for p in productos:
        for venta in p.get("totalSales", []):
            resumen.append(
                {
                    "productId": p["productId"],
                    "nombre": p["name"],
                    "cantidad_vendida": p["quantitySales"],
                    "total_ventas": venta["amount"],
                    "moneda": venta["codeCurrency"],
                    "unidad": p["measure"],
                    "categoria": p["productCategory"],
                    "area_venta": p["areaSales"],
                    "stock_actual": float(p.get("totalQuantity", 0)),
                }
            )
    return {
        "status": "ok",
        "mensaje": f"Reporte del {fecha_inicio.date()} al {fecha_fin.date()}",
        "productos": resumen,
    }


@log_call
def reporte_quiebre_stock(request: QuiebreRequest, http_client: HTTPClient) -> Dict[str, Any]:
    """Perform stock break analysis based on sales performance.

    Invokes ``reporte_ventas`` internally to obtain the sales summary
    and classifies products into risk or star categories depending on
    their rotation and stock levels.
    """
    try:
        today = datetime.today()
        fecha_fin = (
            datetime.strptime(request.fecha_fin, "%Y-%m-%d") if request.fecha_fin else today
        )
        fecha_inicio = (
            datetime.strptime(request.fecha_inicio, "%Y-%m-%d")
            if request.fecha_inicio
            else today - timedelta(days=15)
        )
        # reuse the report
        reporte = reporte_ventas(
            ReporteVentasRequest(
                usuario=request.usuario, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin
            ),
            http_client,
        )
        productos = reporte.get("productos", [])
        productos_riesgo: List[Dict[str, Any]] = []
        productos_estrella: List[Dict[str, Any]] = []
        for p in productos:
            cantidad_vendida = p.get("cantidad_vendida", 0)
            if cantidad_vendida <= 0:
                continue
            rotacion_diaria = cantidad_vendida / 15
            stock = float(p.get("stock_actual", 0))
            if rotacion_diaria <= 2 or stock <= 0:
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
        inicio = (pagina - 1) * 10
        fin = inicio + 10
        pagina_actual = todos[inicio:fin]
        return {
            "status": "ok",
            "mensaje": f"Análisis de quiebre del {fecha_inicio.date()} al {fecha_fin.date()}",
            "pagina_actual": pagina,
            "total_paginas": total_paginas,
            "productos_estrella": productos_estrella if pagina == 1 else [],
            "productos_riesgo": pagina_actual if pagina > 1 else [],
        }
    except Exception as e:
        return {
            "status": "error",
            "mensaje": f"Ocurrió un error: {str(e)}",
        }


@log_call
def analizar_desempeno_ventas(productos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute summary statistics and top performers from sales data."""
    if not productos:
        return {"mensaje": "No hubo ventas en el rango seleccionado."}
    total_ventas = sum(p["total_ventas"] for p in productos)
    total_unidades = sum(p["cantidad_vendida"] for p in productos)
    ticket_promedio = total_ventas / len(productos) if productos else 0
    top_cantidad = sorted(productos, key=lambda p: p["cantidad_vendida"], reverse=True)[:5]
    top_ingreso = sorted(productos, key=lambda p: p["total_ventas"], reverse=True)[:5]
    productos_con_ganancia = []
    for p in productos:
        total_cost = p.get("total_cost", 0) or 0
        ganancia = p["total_ventas"] - total_cost
        productos_con_ganancia.append({
            "nombre": p["nombre"],
            "ganancia": ganancia,
            "moneda": p["moneda"],
        })
    top_ganancia = sorted(productos_con_ganancia, key=lambda x: x["ganancia"], reverse=True)[:5]
    return {
        "resumen": {
            "total_vendido": f"{total_ventas:.2f} {productos[0]['moneda']}",
            "total_unidades_vendidas": total_unidades,
            "ticket_promedio_por_producto": f"{ticket_promedio:.2f} {productos[0]['moneda']}",
            "top_5_mas_vendidos": [
                {"nombre": p["nombre"], "cantidad": p["cantidad_vendida"]} for p in top_cantidad
            ],
            "top_5_mayor_ingreso": [
                {"nombre": p["nombre"], "ingreso": f"{p['total_ventas']} {p['moneda']}"} for p in top_ingreso
            ],
            "top_5_mayor_ganancia": [
                {"nombre": p["nombre"], "ganancia": f"{p['ganancia']} {p['moneda']}"} for p in top_ganancia
            ],
        }
    }


@log_call
def analisis_desempeno(data: AnalisisDesempenoRequest, http_client: HTTPClient) -> Dict[str, Any]:
    """Perform a sales performance analysis over a date range."""
    ctx = get_user_context(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    url = f"{base_url}/api/v1/report/selled-products"
    fecha_inicio = datetime.combine(data.fecha_inicio.date(), time(0, 1))
    fecha_fin = datetime.combine(data.fecha_fin.date(), time(23, 59))
    params = {
        "dateFrom": fecha_inicio.strftime("%Y-%m-%d %H:%M"),
        "dateTo": fecha_fin.strftime("%Y-%m-%d %H:%M"),
        "status": "BILLED",
    }
    res = http_client.request("GET", url, headers=headers, params=params)
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudo obtener el reporte de ventas")
    productos_raw = res.json().get("products", [])
    productos: List[Dict[str, Any]] = []
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
    analisis = analizar_desempeno_ventas(productos)
    return {
        "status": "ok",
        "mensaje": f"Análisis del {data.fecha_inicio.date()} al {data.fecha_fin.date()}",
        "resultado": analisis,
    }


# Types of business and recommended projection models
TIPOS_NEGOCIO: Dict[str, Dict[str, Any]] = {
    "Punto de Venta (Minorista de barrio)": {
        "historial_recomendado_dias": 30,
        "proyeccion_recomendada": "media_movil",
        "descripcion_modelo": "Promedio de ventas recientes. Ideal para productos de consumo diario.",
    },
    "Restaurante o Bar": {
        "historial_recomendado_dias": 15,
        "proyeccion_recomendada": "suavizado_exponencial",
        "descripcion_modelo": "Pone más peso en ventas recientes. Útil para demanda variable.",
    },
    "Mayorista": {
        "historial_recomendado_dias": 60,
        "proyeccion_recomendada": "tendencia_lineal",
        "descripcion_modelo": "Detecta crecimiento o caída en ventas y lo proyecta hacia adelante.",
    },
    "Mercado": {
        "historial_recomendado_dias": 30,
        "proyeccion_recomendada": "media_movil",
        "descripcion_modelo": "Promedia ventas frecuentes. Útil para productos de rotación rápida.",
    },
    "Refrigerados (Cárnicos)": {
        "historial_recomendado_dias": 45,
        "proyeccion_recomendada": "lineal",
        "descripcion_modelo": "Proyección basada en tendencia lineal simple. Requiere historial estable.",
    },
}


@log_call
def obtener_tipos_negocio() -> Dict[str, Any]:
    """Return the configured business types and their recommendation metadata."""
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


def aplicar_modelo_proyeccion(ventas_diarias: List[Dict[str, Any]], modelo: str) -> List[Dict[str, Any]]:
    """Apply a projection model to the daily sales history.

    The history is a list of days, each containing a ``productos`` key.
    The models implemented mirror the original code’s behaviour. New
    projection models can be added in the future.
    """
    ventas_por_producto: Dict[Any, List[int]] = defaultdict(list)
    for dia in ventas_diarias:
        for p in dia.get("productos", []):
            ventas_por_producto[p["productId"]].append(p["quantitySales"])
    proyecciones: List[Dict[str, Any]] = []
    for productId, cantidades in ventas_por_producto.items():
        if modelo == "media_movil":
            proy = sum(cantidades[-7:]) / min(len(cantidades), 7)
        elif modelo == "lineal":
            proy = (cantidades[-1] - cantidades[0]) / max(len(cantidades) - 1, 1)
        elif modelo == "tendencia_lineal":
            proy = (cantidades[-1] - cantidades[0]) / max(len(cantidades) - 1, 1) + cantidades[-1]
        elif modelo == "suavizado_exponencial":
            alpha = 0.3
            s = cantidades[0]
            for y in cantidades[1:]:
                s = alpha * y + (1 - alpha) * s
            proy = s
        else:
            proy = cantidades[-1]
        proyecciones.append({"productId": productId, "cantidad_proyectada": round(proy, 2)})
    return proyecciones


@log_call
def enriquecer_proyeccion_con_nombres(usuario: str, proyeccion: List[Dict[str, Any]], http_client: HTTPClient) -> List[Dict[str, Any]]:
    """Enhance projections with product names by fetching product pages."""
    ctx = get_user_context(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    productos_map: Dict[Any, str] = {}
    pagina = 1
    while True:
        url = f"{base_url}/api/v1/administration/product?page={pagina}"
        resp = http_client.request("GET", url, headers=headers)
        productos = resp.json().get("items", [])
        if not productos:
            break
        for p in productos:
            productos_map[p["id"]] = p["name"]
        pagina += 1
    for item in proyeccion:
        pid = item["productId"]
        item["nombre"] = productos_map.get(pid, f"Producto {pid}")
    return proyeccion


@log_call
def ventas_diarias(data: Dict[str, Any], http_client: HTTPClient) -> Dict[str, Any]:
    """Retrieve daily sales for each day within a date range."""
    usuario = data.get("usuario")
    fecha_inicio_str = data.get("fecha_inicio")
    fecha_fin_str = data.get("fecha_fin")
    if not usuario or not fecha_inicio_str or not fecha_fin_str:
        raise HTTPException(status_code=400, detail="usuario, fecha_inicio y fecha_fin son requeridos")
    ctx = get_user_context(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    fecha_inicio = datetime.strptime(fecha_inicio_str, "%Y-%m-%d")
    fecha_fin = datetime.strptime(fecha_fin_str, "%Y-%m-%d")
    if fecha_inicio > fecha_fin:
        raise HTTPException(status_code=400, detail="fecha_inicio debe ser menor o igual que fecha_fin")
    resultados: List[Dict[str, Any]] = []
    dias = (fecha_fin - fecha_inicio).days + 1
    for i in range(dias):
        dia = fecha_inicio + timedelta(days=i)
        inicio_dia = datetime.combine(dia.date(), time(0, 1))
        fin_dia = datetime.combine(dia.date(), time(23, 59))
        date_from = inicio_dia.strftime("%Y-%m-%d %H:%M")
        date_to = fin_dia.strftime("%Y-%m-%d %H:%M")
        url = f"{base_url}/api/v1/report/selled-products?dateFrom={date_from}&dateTo={date_to}&status=BILLED"
        try:
            res = http_client.request("GET", url, headers=headers)
            if res.status_code != 200:
                raise Exception(f"Error HTTP {res.status_code}: {res.text}")
            resultados.append({
                "fecha": dia.strftime("%Y-%m-%d"),
                "productos": res.json().get("products", []),
            })
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error consultando el día {dia.strftime('%Y-%m-%d')}: {str(e)}")
    return {
        "status": "ok",
        "mensaje": f"Ventas diarias entre {fecha_inicio_str} y {fecha_fin_str}",
        "total_dias": dias,
        "ventas_diarias": resultados,
    }


@log_call
def proyeccion_ventas(usuario: str, tipo_negocio: str, fecha_base: str | None, http_client: HTTPClient) -> Dict[str, Any]:
    """Calculate sales projections based on historical data and business type."""
    if tipo_negocio not in TIPOS_NEGOCIO:
        raise HTTPException(status_code=400, detail={
            "error": "Tipo de negocio no soportado",
            "tipos_disponibles": list(TIPOS_NEGOCIO.keys()),
        })
    dias_historial = TIPOS_NEGOCIO[tipo_negocio]["historial_recomendado_dias"]
    modelo = TIPOS_NEGOCIO[tipo_negocio]["proyeccion_recomendada"]
    fecha_fin = datetime.strptime(fecha_base, "%Y-%m-%d") if fecha_base else datetime.now()
    fecha_inicio = fecha_fin - timedelta(days=dias_historial)
    ventas_diarias_resultado: List[Dict[str, Any]] = []
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
                data = ventas_diarias(payload, http_client)
                if data.get("status") != "ok":
                    raise Exception(data.get("mensaje", "Error inesperado en ventas-diarias"))
                ventas_diarias_resultado.append({
                    "fecha": fecha_actual.strftime("%Y-%m-%d"),
                    "productos": data.get("ventas_diarias", [{}])[0].get("productos", []),
                })
                exito = True
            except Exception:
                intentos += 1
                time.sleep(1)
        if not exito:
            dias_fallidos.append(fecha_actual.strftime("%Y-%m-%d"))
        fecha_actual += timedelta(days=1)
    if not ventas_diarias_resultado:
        raise HTTPException(status_code=500, detail="No se pudieron obtener datos de ventas")
    resultado = aplicar_modelo_proyeccion(ventas_diarias_resultado, modelo)
    resultado = enriquecer_proyeccion_con_nombres(usuario, resultado, http_client)
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


def reporte_ventas_global(data: ReporteGlobalRequest, http_client: HTTPClient) -> Dict[str, Any]:
    """Return consolidated sales metrics across the user’s businesses."""
    ctx = get_user_context(data.usuario)
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
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    params = {"dateFrom": fi.date().isoformat(), "dateTo": ff.date().isoformat()}
    url = f"{base_url}/api/v1/report/incomes/v2/total-sales"
    resp = http_client.request("GET", url, headers=headers, params=params, timeout=30)
    if resp.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Error al obtener ventas globales ({resp.status_code}): {resp.text}")
    raw = resp.json()
    detalles: List[Dict[str, Any]] = []
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


@log_call
def comparativa_semanal(usuario: str, fecha_inicio: str, semanas: int, http_client: HTTPClient) -> Dict[str, Any]:
    """Compare daily sales across multiple weeks."""
    ctx = get_user_context(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    fecha_ini = datetime.strptime(fecha_inicio, "%Y-%m-%d")
    dias_totales = semanas * 7
    fecha_fin = fecha_ini + timedelta(days=dias_totales - 1)
    ventas_data: List[Dict[str, Any]] = []
    for offset in range(dias_totales):
        dia = fecha_ini + timedelta(days=offset)
        rv_req = ReporteVentasRequest(usuario=usuario, fecha_inicio=datetime.combine(dia.date(), time(0, 1)), fecha_fin=datetime.combine(dia.date(), time(23, 59)))
        rv_res = reporte_ventas(rv_req, http_client)
        productos = rv_res.get("productos", [])
        total_dia = sum(p.get("total_ventas", 0) for p in productos)
        moneda = productos[0].get("moneda") if productos else ctx.get("currency", "")
        ventas_data.append({"amount": total_dia, "currency": moneda})
    if not any(v["amount"] > 0 for v in ventas_data):
        raise HTTPException(status_code=404, detail=(f"Sin datos de ventas desde {fecha_ini.date()} hasta {fecha_fin.date()}. Comprueba el rango consultado."))
    semanas_ventas = [ventas_data[i * 7 : (i + 1) * 7] for i in range(semanas)]
    dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    comparativa: List[Dict[str, Any]] = []
    for idx, dia_nombre in enumerate(dias_semana):
        fila: Dict[str, Any] = {"dia": dia_nombre}
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


@log_call
def ticket_promedio(data: RangoFechasConHora, http_client: HTTPClient) -> Dict[str, Dict[str, Any]]:
    """Calculate average ticket size per currency between two dates."""
    ctx = get_user_context(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Sesión no iniciada")
    url_base = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    params = {
        "dateFrom": data.fecha_inicio.strftime("%Y-%m-%d %H:%M"),
        "dateTo": data.fecha_fin.strftime("%Y-%m-%d %H:%M"),
        "status": "BILLED",
    }
    url = f"{url_base}/api/v1/report/byorders"
    response = http_client.request("GET", url, headers=headers, params=params)
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Error al obtener órdenes")
    response_data = response.json()
    ordenes = response_data.get("orders", [])
    if not isinstance(ordenes, list):
        raise HTTPException(status_code=500, detail="Respuesta inesperada de Tecopos")
    resumen: Dict[str, Dict[str, Any]] = {}
    for orden in ordenes:
        for item in orden.get("totalToPay", []):
            moneda = item["codeCurrency"]
            total = item["amount"]
            if moneda not in resumen:
                resumen[moneda] = {
                    "cantidad_ordenes": 0,
                    "total_ventas": 0.0,
                }
            resumen[moneda]["cantidad_ordenes"] += 1
            resumen[moneda]["total_ventas"] += total
    for moneda in resumen:
        resumen[moneda]["ticket_promedio"] = round(
            resumen[moneda]["total_ventas"] / resumen[moneda]["cantidad_ordenes"], 2
        )
    return resumen