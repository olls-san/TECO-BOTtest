"""
schemas/dispatch.py
--------------------

Definitions for dispatching and replicating products between business
branches. These models encapsulate user choices when replicating
products and capture optional filtering parameters.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class ReplicarProductosRequest(BaseModel):
    usuario: str
    negocio_origen_id: Optional[int] = None
    negocio_destino_id: Optional[int] = None
    area_origen_nombre: Optional[str] = None
    area_destino_nombre: Optional[str] = None
    filtro_categoria: Optional[str] = None