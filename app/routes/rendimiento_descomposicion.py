from __future__ import annotations

from fastapi import APIRouter
from app.schemas.rendimiento_descomposicion import (
    RendimientoDescomposicionBody,
    RendimientoDescomposicionResponse,
)
from app.services.rendimiento_descomposicion_service import rendimiento_descomposicion_service

router = APIRouter()


@router.post("/rendimientoDescomposicion")
def rendimiento_descomposicion_post(
    payload: RendimientoDescomposicionBody,
) -> RendimientoDescomposicionResponse:
    """
    Calcula rendimiento de descomposición para un área y periodo (día por defecto),
    con opción de agrupar por DIA/SEMANA/MES y filtrar por productos MANUFACTURED hijos.
    """
    result = rendimiento_descomposicion_service(body=payload.model_dump(by_alias=True))
    return RendimientoDescomposicionResponse(**result)
