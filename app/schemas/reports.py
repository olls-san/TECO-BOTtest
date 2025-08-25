"""
schemas/reports.py
-------------------

Defines schemas used for sales, inventory and analytical reports. These
models capture the date ranges and pagination parameters supplied by
clients and are consumed by the report services.
"""

from __future__ import annotations

from typing import Optional, Dict
from datetime import datetime
from pydantic import BaseModel, Field


class QuiebreRequest(BaseModel):
    usuario: str
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None
    pagina: Optional[int] = 1


class AnalisisDesempenoRequest(BaseModel):
    usuario: str
    fecha_inicio: datetime
    fecha_fin: datetime


class ReporteVentasRequest(BaseModel):
    usuario: str
    fecha_inicio: datetime
    fecha_fin: datetime


class ReporteGlobalRequest(BaseModel):
    usuario: str
    fecha_inicio: Optional[datetime] = None
    fecha_fin: Optional[datetime] = None


class RangoFechasConHora(BaseModel):
    usuario: str
    fecha_inicio: datetime
    fecha_fin: datetime