"""
schemas/rendimiento.py
----------------------

Models for performance measurement of ice cream and yogurt production.
These schemas are used by the corresponding endpoints to validate
incoming requests and structure outgoing responses.
"""

from __future__ import annotations

from typing import List, Literal
from datetime import date
from pydantic import BaseModel


class RendimientoHeladoRequest(BaseModel):
    usuario: str
    area_nombre: str
    fecha_inicio: date
    fecha_fin: date


class RendimientoYogurtRequest(BaseModel):
    usuario: str
    area_nombre: str
    fecha_inicio: date
    fecha_fin: date


class RendimientoYogurtResumen(BaseModel):
    tipo: Literal["Yogurt"]
    sabor: str
    mezcla_usada_litros: float
    producto_producido_litros: float
    rendimiento_real: float
    rendimiento_ideal: float
    eficiencia_porcentual: float


class RendimientoYogurtResponse(BaseModel):
    area_nombre: str
    area_id: int
    resumen: List[RendimientoYogurtResumen]