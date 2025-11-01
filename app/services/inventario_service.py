"""
services/inventario_service.py
------------------------------

Service for totalling inventory and optionally sending the report via
email. Produces either an Excel or PDF representation of the inventory
list. The email functionality leverages a utility imported from
`email_utils`; ensure this module is available in your environment.

Notas:
- Implementa paginación explícita (?page=1..N) contra Tecopos.
- Envía los adjuntos como bytes y valida tamaño > 0 antes de enviar.
- Separa los imports de reportlab y email_utils para que Excel pueda
  enviarse aunque falte reportlab en el entorno.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
from io import BytesIO
import pandas as pd
from fastapi import HTTPException

from app.core.context import get_user_context
from app.core.auth import get_base_url, build_auth_headers
from app.clients.http_client import HTTPClient
from app.logging_config import logger, log_call
import json
from app.utils.cache import cache

# -------------------------------
# Imports opcionales (separados)
# -------------------------------
try:
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False

try:
    # Debe exponer una función: enviar_correo(destinatario, asunto, cuerpo, archivo_adjunto, nombre_archivo, tipo_mime)
    from email_utils import enviar_correo  # type: ignore
except Exception:
    enviar_correo = None  # type: ignore


# -------------------------------
# Helpers internos
# -------------------------------
def _teco_get_all_stock(http_client: HTTPClient, base_url: str, headers: dict) -> List[Dict[str, Any]]:
    """
    Obtiene todo el inventario con paginación explícita (?page=1..N).
    Admite respuesta como lista directa o como objeto con claves comunes.
    """
    items: List[Dict[str, Any]] = []
    page = 1
    while True:
        url = f"{base_url}/api/v1/report/stock/disponibility"
        resp = http_client.request("GET", url, headers=headers, params={"page": page})
        if resp.status_code < 200 or resp.status_code >= 300:
            raise HTTPException(status_code=resp.status_code, detail=f"Error al consultar inventario (page={page})")

        data = resp.json()
        # Adapta según formato real: lista directa o envuelta en "items"/"content"/"result"
        if isinstance(data, list):
            chunk = data
        else:
            chunk = (
                data.get("items")
                or data.get("content")
                or data.get("result")
                or []
            )

        if not chunk:
            break

        items.extend(chunk)
        page += 1

    return items


def _filtrar_mapeo_productos(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Mapea las posibles claves devueltas por Tecopos a la salida estándar:
    Producto, Disponibilidad, Medida.
    Filtra los que tengan disponibilidad > 0.
    """
    out: List[Dict[str, Any]] = []
    for p in raw:
        nombre = p.get("productName") or p.get("name") or ""
        disp = p.get("disponibility", p.get("quantity", 0)) or 0
        medida = p.get("measure", "") or p.get("unit", "")
        try:
            disp_num = float(disp)
        except Exception:
            disp_num = 0.0

        if disp_num > 0:
            out.append(
                {
                    "Producto": nombre,
                    "Disponibilidad": round(disp_num, 2),
                    "Medida": medida,
                }
            )
    return out


def generar_pdf_inventario(productos: List[Dict[str, Any]]) -> BytesIO:
    """
    Genera un PDF en memoria (BytesIO) con la tabla de inventario.
    Requiere reportlab instalado. Lanza 500 si reportlab no está disponible.
    """
    if not REPORTLAB_OK:
        raise HTTPException(status_code=500, detail="Dependencia faltante: reportlab no está disponible")

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()
    elements = []

    data = [["Producto", "Disponibilidad", "Medida"]] + [
        [p["Producto"], str(p["Disponibilidad"]), p["Medida"]] for p in productos
    ]

    table = Table(data)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    )

    elements.append(Paragraph("Reporte de Inventario", styles["Heading1"]))
    elements.append(Spacer(1, 12))
    elements.append(table)
    doc.build(elements)

    buffer.seek(0)
    return buffer


# -------------------------------
# Servicio principal
# -------------------------------
@log_call
def totalizar_inventario(
    usuario: str,
    enviar_por_correo: bool,
    destinatario: Optional[str],
    formato: str,  # "excel" o "pdf"
    http_client: HTTPClient,
) -> Dict[str, Any]:
    """
    Retorna:
    {
        "total": int,
        "productos": [ { "Producto": str, "Disponibilidad": float, "Medida": str }, ... ]
    }

    Si enviar_por_correo=True y se provee destinatario, adjunta el reporte (excel/pdf) al correo.
    """
    # 1) Contexto Tecopos
    ctx = get_user_context(usuario)
    if not ctx:
        logger.warning(json.dumps({
            "event": "totalizar_inventario_sin_sesion",
            "usuario": usuario,
            "detalle": "Usuario no autenticado",
        }))
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    # Log inicio del proceso
    try:
        logger.info(json.dumps({
            "event": "totalizar_inventario_inicio",
            "usuario": usuario,
            "region": ctx.get("region"),
            "businessId": ctx.get("businessId"),
            "enviar_por_correo": enviar_por_correo,
            "formato": formato,
        }))
    except Exception:
        pass

    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])

    # 2) Cache (por businessId)
    cache_key = f"inventory_{ctx['businessId']}"
    productos_filtrados: Optional[List[Dict[str, Any]]] = cache.get(cache_key)

    # 3) Fetch + paginación cuando no hay cache
    if productos_filtrados is None:
        raw_items = _teco_get_all_stock(http_client=http_client, base_url=base_url, headers=headers)
        productos_filtrados = _filtrar_mapeo_productos(raw_items)
        cache.set(cache_key, productos_filtrados, ttl=300)  # 5 minutos

    # 4) Validaciones
    if not productos_filtrados:
        logger.warning(json.dumps({
            "event": "totalizar_inventario_sin_productos",
            "usuario": usuario,
            "detalle": "No hay productos con disponibilidad",
        }))
        raise HTTPException(status_code=404, detail="No hay productos con disponibilidad")

    # 5) Envío de correo (opcional)
    if enviar_por_correo and destinatario:
        if not enviar_correo:
            logger.error(json.dumps({
                "event": "totalizar_inventario_error_correo",
                "usuario": usuario,
                "detalle": "Módulo de correo no disponible (email_utils)",
            }))
            raise HTTPException(status_code=500, detail="Módulo de correo no disponible (email_utils)")

        if formato.lower() == "excel":
            # Construir Excel en memoria
            df = pd.DataFrame(productos_filtrados)
            output = BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False, sheet_name="Inventario")
            output.seek(0)  # rebobinar antes de leer
            archivo_bytes = output.getvalue()
            nombre_archivo = "inventario.xlsx"
            tipo_mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            # Construir PDF en memoria (requiere reportlab)
            pdf_buffer = generar_pdf_inventario(productos_filtrados)
            archivo_bytes = pdf_buffer.getvalue()
            nombre_archivo = "inventario.pdf"
            tipo_mime = "application/pdf"

        # Verificación defensiva: tamaño > 0
        if not archivo_bytes or len(archivo_bytes) == 0:
            logger.error(json.dumps({
                "event": "totalizar_inventario_error_adjunto",
                "usuario": usuario,
                "detalle": "Adjunto vacío; verificar generación del archivo",
            }))
            raise HTTPException(status_code=500, detail="Adjunto vacío; verificar generación del archivo")

        # Enviar correo (adjunto como bytes)
        enviar_correo(
            destinatario=destinatario,
            asunto="Reporte de Inventario",
            cuerpo="Adjunto el inventario solicitado.",
            archivo_adjunto=archivo_bytes,
            nombre_archivo=nombre_archivo,
            tipo_mime=tipo_mime,
        )
        # Log envío de correo exitoso
        logger.info(json.dumps({
            "event": "totalizar_inventario_correo_enviado",
            "usuario": usuario,
            "destinatario": destinatario,
            "formato": formato,
        }))

    # 6) Respuesta
    # Log finalización del totalizado
    logger.info(json.dumps({
        "event": "totalizar_inventario_fin",
        "usuario": usuario,
        "total_productos": len(productos_filtrados),
    }))
    return {
        "total": len(productos_filtrados),
        "productos": productos_filtrados,
    }
