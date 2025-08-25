"""
schemas/currency.py
--------------------

Models related to currency operations such as bulk currency
conversion. These schemas mirror the structure of the original
application to ensure request and response compatibility.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class CambioMonedaRequest(BaseModel):
    usuario: str
    moneda_actual: str
    moneda_deseada: str
    system_price_id: Optional[int] = None  # requerido para confirmar
    confirmar: bool = False
    forzar_todos: bool = False