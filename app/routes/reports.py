"""
routes/reports.py
------------------

API routes for sales reports, performance analysis, projections and
comparative statistics. Each route delegates to its respective
service function and ensures that input parameters and response
structures align with the original specification.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Body, Query, Request

# Logging utilities
from app.logging_config import logger, log_call
import json
from typing import Dict, Any

from app.clients.http_client import HTTPClient
from app.schemas.reports import (
    ReporteVentasRequest,
    QuiebreRequest,
    AnalisisDesempenoRequest,
    ReporteGlobalRequest,
    RangoFechasConHora,
)
from app.services.report_service import (
    reporte_ventas,
    reporte_quiebre_stock,
    analisis_desempeno,
    ventas_diarias,
    obtener_tipos_negocio,
    proyeccion_ventas,
    reporte_ventas_global,
    comparativa_semanal,
    ticket_promedio,
)

router = APIRouter()


def get_http_client(request: Request) -> HTTPClient:
    return request.app.state.http_client


@router.post("/reporte-ventas")
@log_call
def post_reporte_ventas(data: ReporteVentasRequest, http_client: HTTPClient = Depends(get_http_client)):
    """Devuelve el reporte de ventas para un rango de fechas. Registra eventos de inicio y finalización."""
    try:
        logger.info(json.dumps({
            "event": "reporte_ventas_request",
            "usuario": data.usuario,
            "fecha_inicio": str(data.fecha_inicio),
            "fecha_fin": str(data.fecha_fin),
        }))
    except Exception:
        pass
    try:
        resp = reporte_ventas(data, http_client)
        logger.info(json.dumps({
            "event": "reporte_ventas_response",
            "usuario": data.usuario,
            "num_productos": len(resp.get("productos", [])) if isinstance(resp.get("productos"), list) else None,
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "reporte_ventas_error",
            "usuario": getattr(data, 'usuario', None),
            "detalle": str(e),
        }), exc_info=True)
        raise


@router.post("/reporte-quiebre-stock")
@log_call
def post_reporte_quiebre_stock(request_body: QuiebreRequest, http_client: HTTPClient = Depends(get_http_client)):
    """Realiza un análisis de quiebre de stock. Registra eventos de inicio y finalización."""
    try:
        logger.info(json.dumps({
            "event": "reporte_quiebre_stock_request",
            "usuario": request_body.usuario,
            "fecha_inicio": request_body.fecha_inicio,
            "fecha_fin": request_body.fecha_fin,
            "pagina": request_body.pagina,
        }))
    except Exception:
        pass
    try:
        resp = reporte_quiebre_stock(request_body, http_client)
        logger.info(json.dumps({
            "event": "reporte_quiebre_stock_response",
            "usuario": request_body.usuario,
            "status": resp.get("status"),
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "reporte_quiebre_stock_error",
            "usuario": getattr(request_body, 'usuario', None),
            "detalle": str(e),
        }), exc_info=True)
        raise


@router.post("/analisis-desempeno")
@log_call
def post_analisis_desempeno(data: AnalisisDesempenoRequest, http_client: HTTPClient = Depends(get_http_client)):
    """Realiza un análisis de desempeño de ventas y registra eventos para observabilidad."""
    try:
        logger.info(json.dumps({
            "event": "analisis_desempeno_request",
            "usuario": data.usuario,
            "fecha_inicio": str(data.fecha_inicio),
            "fecha_fin": str(data.fecha_fin),
        }))
    except Exception:
        pass
    try:
        resp = analisis_desempeno(data, http_client)
        logger.info(json.dumps({
            "event": "analisis_desempeno_response",
            "usuario": data.usuario,
            "status": resp.get("status"),
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "analisis_desempeno_error",
            "usuario": getattr(data, 'usuario', None),
            "detalle": str(e),
        }), exc_info=True)
        raise


@router.post("/ventas-diarias")
@log_call
def post_ventas_diarias(data: Dict[str, Any] = Body(...), http_client: HTTPClient = Depends(get_http_client)):
    """Obtiene ventas diarias para un rango de fechas. Registra eventos de inicio y fin."""
    usuario = data.get("usuario")
    fecha_inicio = data.get("fecha_inicio")
    fecha_fin = data.get("fecha_fin")
    try:
        logger.info(json.dumps({
            "event": "ventas_diarias_request",
            "usuario": usuario,
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
        }))
    except Exception:
        pass
    try:
        resp = ventas_diarias(data, http_client)
        logger.info(json.dumps({
            "event": "ventas_diarias_response",
            "usuario": usuario,
            "total_dias": resp.get("total_dias"),
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "ventas_diarias_error",
            "usuario": usuario,
            "detalle": str(e),
        }), exc_info=True)
        raise


@router.get("/tipos-negocio")
@log_call
def get_tipos_negocio():
    """Devuelve la lista de tipos de negocio y registra evento."""
    try:
        logger.info(json.dumps({"event": "tipos_negocio_request"}))
    except Exception:
        pass
    resp = obtener_tipos_negocio()
    try:
        logger.info(json.dumps({"event": "tipos_negocio_response", "num_tipos": len(resp.get("tipos_negocio", []))}))
    except Exception:
        pass
    return resp


@router.post("/proyeccion-ventas")
@log_call
def post_proyeccion_ventas(
    usuario: str = Body(...),
    tipo_negocio: str = Body(...),
    fecha_base: str | None = Body(default=None),
    http_client: HTTPClient = Depends(get_http_client),
):
    """Calcula proyecciones de ventas y registra eventos."""
    try:
        logger.info(json.dumps({
            "event": "proyeccion_ventas_request",
            "usuario": usuario,
            "tipo_negocio": tipo_negocio,
            "fecha_base": fecha_base,
        }))
    except Exception:
        pass
    try:
        resp = proyeccion_ventas(usuario, tipo_negocio, fecha_base, http_client)
        logger.info(json.dumps({
            "event": "proyeccion_ventas_response",
            "usuario": usuario,
            "status": resp.get("status"),
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "proyeccion_ventas_error",
            "usuario": usuario,
            "detalle": str(e),
        }), exc_info=True)
        raise


@router.post("/reporte-ventas-global")
@log_call
def post_reporte_ventas_global(data: ReporteGlobalRequest, http_client: HTTPClient = Depends(get_http_client)):
    """Devuelve métricas de ventas globales consolidando todas las sucursales. Registra eventos."""
    try:
        logger.info(json.dumps({
            "event": "reporte_ventas_global_request",
            "usuario": data.usuario,
            "fecha_inicio": str(data.fecha_inicio),
            "fecha_fin": str(data.fecha_fin),
        }))
    except Exception:
        pass
    try:
        resp = reporte_ventas_global(data, http_client)
        logger.info(json.dumps({
            "event": "reporte_ventas_global_response",
            "usuario": data.usuario,
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "reporte_ventas_global_error",
            "usuario": getattr(data, 'usuario', None),
            "detalle": str(e),
        }), exc_info=True)
        raise


@router.get("/comparativa-semanal")
@log_call
def get_comparativa_semanal(
    usuario: str = Query(..., description="Usuario registrado (clave en user_context)"),
    fecha_inicio: str = Query(..., description="Fecha inicial en formato YYYY-MM-DD"),
    semanas: int = Query(2, ge=2, le=8, description="Número de semanas a comparar"),
    http_client: HTTPClient = Depends(get_http_client),
):
    """Compara ventas por día a través de varias semanas y registra eventos."""
    try:
        logger.info(json.dumps({
            "event": "comparativa_semanal_request",
            "usuario": usuario,
            "fecha_inicio": fecha_inicio,
            "semanas": semanas,
        }))
    except Exception:
        pass
    try:
        resp = comparativa_semanal(usuario, fecha_inicio, semanas, http_client)
        logger.info(json.dumps({
            "event": "comparativa_semanal_response",
            "usuario": usuario,
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "comparativa_semanal_error",
            "usuario": usuario,
            "detalle": str(e),
        }), exc_info=True)
        raise


@router.post("/ticket-promedio", tags=["AnÃ¡lisis"], operation_id="calcular_ticket_promedio")
@log_call
def post_ticket_promedio(data: RangoFechasConHora = Body(...), http_client: HTTPClient = Depends(get_http_client)):
    """Calcula el ticket promedio entre dos fechas y registra eventos."""
    try:
        logger.info(json.dumps({
            "event": "ticket_promedio_request",
            "usuario": data.usuario,
            "fecha_inicio": str(data.fecha_inicio),
            "fecha_fin": str(data.fecha_fin),
        }))
    except Exception:
        pass
    try:
        resp = ticket_promedio(data, http_client)
        logger.info(json.dumps({
            "event": "ticket_promedio_response",
            "usuario": data.usuario,
        }))
        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "ticket_promedio_error",
            "usuario": getattr(data, 'usuario', None),
            "detalle": str(e),
        }), exc_info=True)
        raise

