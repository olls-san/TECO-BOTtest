"""
schemas/products.py
--------------------

Models representing product information and operations. These
definitions correspond to the request bodies for creating products,
intelligent stock entries and batch operations. The validators ensure
basic sanity checks on incoming data.
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class Producto(BaseModel):
    nombre: str
    precio: float
    costo: Optional[float] = None
    moneda: str = Field(default="USD")
    tipo: str = Field(default="STOCK")
    categorias: List[str] = Field(default_factory=list)
    usuario: str


class ProductoEntradaInteligente(BaseModel):
    nombre: str
    cantidad: int
    precio: float
    moneda: str = "CUP"

    @field_validator("cantidad")
    @classmethod
    def validar_cantidad_positiva(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("La cantidad debe ser mayor que cero")
        return v

    @field_validator("nombre")
    @classmethod
    def validar_nombre_no_vacio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("El nombre del producto no puede estar vacío")
        return v


class EntradaInteligenteRequest(BaseModel):
    usuario: str
    stockAreaId: Optional[int] = 0
    productos: List[ProductoEntradaInteligente]