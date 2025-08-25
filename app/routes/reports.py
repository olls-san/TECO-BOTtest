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
def post_reporte_ventas(data: ReporteVentasRequest, http_client: HTTPClient = Depends(get_http_client)):
    return reporte_ventas(data, http_client)


@router.post("/reporte-quiebre-stock")
def post_reporte_quiebre_stock(request_body: QuiebreRequest, http_client: HTTPClient = Depends(get_http_client)):
    return reporte_quiebre_stock(request_body, http_client)


@router.post("/analisis-desempeno")
def post_analisis_desempeno(data: AnalisisDesempenoRequest, http_client: HTTPClient = Depends(get_http_client)):
    return analisis_desempeno(data, http_client)


@router.post("/ventas-diarias")
def post_ventas_diarias(data: Dict[str, Any] = Body(...), http_client: HTTPClient = Depends(get_http_client)):
    return ventas_diarias(data, http_client)


@router.get("/tipos-negocio")
def get_tipos_negocio():
    return obtener_tipos_negocio()


@router.post("/proyeccion-ventas")
def post_proyeccion_ventas(
    usuario: str = Body(...),
    tipo_negocio: str = Body(...),
    fecha_base: str | None = Body(default=None),
    http_client: HTTPClient = Depends(get_http_client),
):
    return proyeccion_ventas(usuario, tipo_negocio, fecha_base, http_client)


@router.post("/reporte-ventas-global")
def post_reporte_ventas_global(data: ReporteGlobalRequest, http_client: HTTPClient = Depends(get_http_client)):
    return reporte_ventas_global(data, http_client)


@router.get("/comparativa-semanal")
def get_comparativa_semanal(
    usuario: str = Query(..., description="Usuario registrado (clave en user_context)"),
    fecha_inicio: str = Query(..., description="Fecha inicial en formato YYYY-MM-DD"),
    semanas: int = Query(2, ge=2, le=8, description="Número de semanas a comparar"),
    http_client: HTTPClient = Depends(get_http_client),
):
    return comparativa_semanal(usuario, fecha_inicio, semanas, http_client)


@router.post("/ticket-promedio", tags=["Análisis"], operation_id="calcular_ticket_promedio")
def post_ticket_promedio(data: RangoFechasConHora = Body(...), http_client: HTTPClient = Depends(get_http_client)):
    return ticket_promedio(data, http_client)