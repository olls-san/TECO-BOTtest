"""
schemas/carga.py
-----------------

Models to represent buying receipts (cargas) and related operations
such as creating a receipt with products and adding products to an
existing receipt. These correspond to the endpoints for inventory
carga management.
"""

from __future__ import annotations

from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class Cost(BaseModel):
    amount: float
    codeCurrency: str


class ProductoCarga(BaseModel):
    name: str
    code: str
    price: float
    codeCurrency: str
    cost: float
    unit: str
    iva: Optional[float] = 0
    barcode: Optional[str] = None
    category: Optional[str] = "Sin categoría"
    quantity: int
    expirationAt: str
    noPackages: int
    lote: str = Field(..., alias="uniqueCode")


class CrearCargaConProductosRequest(BaseModel):
    usuario: str
    name: str
    observations: Optional[str] = ""
    productos: List[ProductoCarga]


class ProductoEntradaCarga(BaseModel):
    name: str
    price: float
    codeCurrency: str
    quantity: int
    expirationAt: datetime
    noPackages: int
    uniqueCode: str


class EntradaProductosEnCargaRequest(BaseModel):
    usuario: str
    carga_id: int = Field(..., alias="cargaId")
    productos: List[ProductoEntradaCarga]


class VerificarProductosRequest(BaseModel):
    usuario: str
    nombres_productos: List[str]


class ProductosFaltantesResponse(BaseModel):
    productos_faltantes: List[str]