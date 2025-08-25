"""
routes/inventario.py
--------------------

Route for totalling inventory and optionally emailing the report.
Provides query parameters to control emailing and output format.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from typing import Optional
from app.clients.http_client import HTTPClient
from app.services.inventario_service import totalizar_inventario


router = APIRouter()


def get_http_client(request: Request) -> HTTPClient:
    return request.app.state.http_client


@router.get("/totalizar-inventario")
def get_totalizar_inventario(
    usuario: str,
    enviar_por_correo: bool = Query(False),
    destinatario: Optional[str] = Query(None),
    formato: str = Query("excel", regex="^(excel|pdf)$"),
    http_client: HTTPClient = Depends(get_http_client),
):
    return totalizar_inventario(usuario, enviar_por_correo, destinatario, formato, http_client)

