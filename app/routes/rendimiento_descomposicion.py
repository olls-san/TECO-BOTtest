from __future__ import annotations

from fastapi import APIRouter

# Logging utilities
from app.logging_config import logger  # import only logger
import json
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
    Registra eventos de entrada y salida para trazabilidad.
    """
    try:
        logger.info(json.dumps({
            "event": "rendimiento_descomposicion_request",
            "usuario": payload.usuario,
            "area_id": payload.area_id,
            "fecha_inicio": payload.fecha_inicio,
            "fecha_fin": payload.fecha_fin,
            "grupo": payload.grupo,
            "solo_manufacturados": payload.solo_manufacturados,
        }))
    except Exception:
        pass
    try:
        result = rendimiento_descomposicion_service(body=payload.model_dump(by_alias=True))
        logger.info(json.dumps({
            "event": "rendimiento_descomposicion_response",
            "usuario": payload.usuario,
        }))
        return RendimientoDescomposicionResponse(**result)
    except Exception as e:
        logger.error(json.dumps({
            "event": "rendimiento_descomposicion_error",
            "usuario": getattr(payload, 'usuario', None),
            "detalle": str(e),
        }), exc_info=True)
        raise
