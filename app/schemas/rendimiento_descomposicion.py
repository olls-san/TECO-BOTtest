from __future__ import annotations

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


Granularidad = Literal["DIA", "SEMANA", "MES"]


class RendimientoDescomposicionBody(BaseModel):
    usuario: str = Field(..., description="Usuario autenticado (clave de user_context)")
    area_id: Optional[int] = Field(None, description="ID del área STOCK")
    area_nombre: Optional[str] = Field(None, description="Nombre del área STOCK (coincidencia exacta)")
    fecha_inicio: Optional[str] = Field(None, description="YYYY-MM-DD (opcional, por defecto hoy)")
    fecha_fin: Optional[str] = Field(None, description="YYYY-MM-DD (opcional, por defecto = inicio)")
    granularidad: Granularidad = Field("DIA", description="DIA | SEMANA | MES")
    product_ids: Optional[List[int]] = Field(None, description="Filtra solo productos MANUFACTURED hijos con estos IDs")
    incluir_movimientos: bool = Field(False, description="Si true, incluye lista de KPIs por movimiento")


class PeriodoOut(BaseModel):
    desde: str
    hasta: str
    granularidad: Granularidad


class AreaOut(BaseModel):
    id: int
    nombre: str


class ResumenOut(BaseModel):
    padre_usado: float
    manufacturados: float
    merma: float
    rendimiento_ponderado_porcentaje: Optional[float] = None


class SerieItem(BaseModel):
    bucket: str
    padre_usado: float
    manufacturados: float
    merma: float
    rendimiento_porcentaje: Optional[float] = None


class PorProductoItem(BaseModel):
    productId: int
    productName: str
    measure: Optional[str] = None
    movimientos: int
    usado_padre: float
    manufacturados: float
    merma: float
    rendimiento_promedio: Optional[float] = None
    rendimiento_min: Optional[float] = None
    rendimiento_max: Optional[float] = None
    rendimiento_stddev: Optional[float] = None


class PadreItem(BaseModel):
    productId: int
    productName: str
    measure: Optional[str] = None
    usado: float


class MovimientoItem(BaseModel):
    movementId: int
    fecha: str
    padre: PadreItem
    manufacturados_total: float
    merma_total: float
    rendimiento_porcentaje: Optional[float] = None


class RendimientoDescomposicionResponse(BaseModel):
    periodo: PeriodoOut
    area: AreaOut
    filtros: dict
    resumen: ResumenOut
    series: List[SerieItem]
    por_producto: List[PorProductoItem]
    movimientos: List[MovimientoItem]
    warnings: List[str]
