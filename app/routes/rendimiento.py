"""
routes/rendimiento.py
----------------------

API routes for computing yields of ice cream and yogurt production.
These endpoints call the corresponding service functions and return
structured responses.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from app.clients.http_client import HTTPClient
from app.schemas.rendimiento import (
    RendimientoHeladoRequest,
    RendimientoYogurtRequest,
    RendimientoYogurtResponse,
)
from app.services.rendimiento_service import rendimiento_helado, rendimiento_yogurt


router = APIRouter()


def get_http_client(request: Request) -> HTTPClient:
    return request.app.state.http_client


@router.post("/rendimiento-helado")
def post_rendimiento_helado(data: RendimientoHeladoRequest, http_client: HTTPClient = Depends(get_http_client)):
    return rendimiento_helado(data, http_client)


@router.post("/rendimiento-yogurt", response_model=RendimientoYogurtResponse)
def post_rendimiento_yogurt(data: RendimientoYogurtRequest, http_client: HTTPClient = Depends(get_http_client)):
    return rendimiento_yogurt(data, http_client)

