"""
routes/currency.py
------------------

API route for bulk currency updates. Delegates to the currency
service and maintains the original behaviour of simulating changes
before applying them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from app.clients.http_client import HTTPClient
from app.schemas.currency import CambioMonedaRequest
from app.services.currency_service import actualizar_monedas


router = APIRouter()


def get_http_client(request: Request) -> HTTPClient:
    return request.app.state.http_client


@router.post("/actualizar-monedas")
def post_actualizar_monedas(data: CambioMonedaRequest, http_client: HTTPClient = Depends(get_http_client)):
    return actualizar_monedas(data, http_client)
