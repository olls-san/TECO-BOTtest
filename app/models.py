"""
Pydantic models for the Tecopos API wrapper.

This module centralises all of the request and response schemas used
throughout the application. Keeping the models in a dedicated file
makes it easier to update or extend them without touching the main
application logic.

Each model corresponds to a particular endpoint or helper function.
For clarity, optional parameters are typed with ``Optional`` and
reasonable default values are provided where appropriate.
"""

from datetime import datetime, date
from typing import List, Optional, Literal, Dict

from pydantic import BaseModel, Field, validator


class LoginData(BaseModel):
    """Schema for login requests."""
    usuario: str
    password: str
    region: str = "apidev"


class QuiebreRequest(BaseModel):
    """Request schema for the stock break report."""
    usuario: str
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None
    pagina: Optional[int] = 1


class SeleccionNegocio(BaseModel):
    """Request model used when selecting a business from multiple options."""
    usuario: str
    nombre_negocio: str = Field(alias="negocio")

    class Config:
        allow_population_by_field_name = True


class AnalisisDesempenoRequest(BaseModel):
    """Request model for sales performance analysis."""
    usuario: str
    fecha_inicio: datetime
    fecha_fin: datetime


class Producto(BaseModel):
    """Model used when creating a new product.

    Attributes
    ----------
    nombre: The name of the product.
    precio: The sales price.
    costo: Optional cost of the product.
    moneda: Currency code, default USD.
    tipo: Product type, default STOCK.
    categorias: List of category names. If omitted the category will be
        inferred automatically.
    usuario: The user performing the operation.
    """

    nombre: str
    precio: float
    costo: float | None = None
    moneda: str = Field(default="USD")
    tipo: str = Field(default="STOCK")
    categorias: List[str] = Field(default_factory=list)
    usuario: str


class ReporteVentasRequest(BaseModel):
    """Request model for the detailed sales report."""
    usuario: str
    fecha_inicio: datetime
    fecha_fin: datetime


class CambioMonedaRequest(BaseModel):
    """Request schema for bulk currency updates on product prices."""
    usuario: str
    moneda_actual: str
    moneda_deseada: str
    system_price_id: Optional[int] = None
    confirmar: bool = False
    forzar_todos: bool = False


class ProductoEntradaInteligente(BaseModel):
    """Schema for a product entry in the intelligent entry system."""
    nombre: str
    cantidad: int
    precio: float
    moneda: str = "CUP"

    @validator("cantidad")
    def validar_cantidad_positiva(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("La cantidad debe ser mayor que cero")
        return v

    @validator("nombre")
    def validar_nombre_no_vacio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("El nombre del producto no puede estar vacío")
        return v


class EntradaInteligenteRequest(BaseModel):
    """Request schema for the intelligent entry endpoint."""
    usuario: str
    stockAreaId: Optional[int] = 0
    productos: List[ProductoEntradaInteligente]


class ReporteGlobalRequest(BaseModel):
    """Request model for the global sales report.

    Dates are optional; if omitted the report will cover the last 30 days.
    """
    usuario: str
    fecha_inicio: Optional[datetime] = None
    fecha_fin: Optional[datetime] = None


class RangoFechasConHora(BaseModel):
    """Input model for calculating average ticket size."""
    usuario: str
    fecha_inicio: datetime
    fecha_fin: datetime


class ReplicarProductosRequest(BaseModel):
    """Request schema for replicating products between branches."""
    usuario: str
    negocio_origen_id: Optional[int] = None
    negocio_destino_id: Optional[int] = None
    area_origen_nombre: Optional[str] = None
    area_destino_nombre: Optional[str] = None
    filtro_categoria: Optional[str] = None


class RendimientoHeladoRequest(BaseModel):
    """Request model for ice cream efficiency calculations."""
    usuario: str
    area_nombre: str
    fecha_inicio: date
    fecha_fin: date


class RendimientoYogurtRequest(BaseModel):
    """Request model for yogurt efficiency calculations."""
    usuario: str
    area_nombre: str
    fecha_inicio: date
    fecha_fin: date


class RendimientoYogurtResumen(BaseModel):
    """Response item for yogurt efficiency calculations."""
    tipo: Literal["Yogurt"]
    sabor: str
    mezcla_usada_litros: float
    producto_producido_litros: float
    rendimiento_real: float
    rendimiento_ideal: float
    eficiencia_porcentual: float


class RendimientoYogurtResponse(BaseModel):
    """Response schema for yogurt efficiency endpoint."""
    area_nombre: str
    area_id: int
    resumen: List[RendimientoYogurtResumen]


class Cost(BaseModel):
    """Cost information used when creating batches."""
    amount: float
    codeCurrency: str


class ProductoCarga(BaseModel):
    """Model representing a single product to be loaded into a purchase receipt."""
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
    """Request schema for creating a purchase receipt with products."""
    usuario: str
    name: str
    observations: Optional[str] = ""
    productos: List[ProductoCarga]


class ProductoEntradaCarga(BaseModel):
    """Schema for a product entry into an existing purchase receipt."""
    name: str
    price: float
    codeCurrency: str
    quantity: int
    expirationAt: datetime
    noPackages: int
    uniqueCode: str


class EntradaProductosEnCargaRequest(BaseModel):
    """Request model for adding products into a purchase receipt batch."""
    usuario: str
    carga_id: int = Field(..., alias="cargaId")
    productos: List[ProductoEntradaCarga]


class VerificarProductosRequest(BaseModel):
    """Request for verifying existence of products by name."""
    usuario: str
    nombres_productos: List[str]


class ProductosFaltantesResponse(BaseModel):
    """Response listing products that are missing from the system."""
    productos_faltantes: List[str]
