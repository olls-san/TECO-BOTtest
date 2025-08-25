"""
routes/dispatch.py
-------------------

API routes for dispatch operations, including replicating products
between stock areas. This route follows the multi‑step flow of
soliciting business IDs, stock areas and then performing the
replication.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from app.clients.http_client import HTTPClient
from app.schemas.dispatch import ReplicarProductosRequest
from app.services.dispatch_service import replicar_productos


router = APIRouter()


def get_http_client(request: Request) -> HTTPClient:
    return request.app.state.http_client


@router.post("/replicar-productos", summary="Replicar productos entre negocios mediante despacho Tecopos", tags=["Despachos"])
def post_replicar_productos(data: ReplicarProductosRequest, http_client: HTTPClient = Depends(get_http_client)):
    return replicar_productos(data, http_client)