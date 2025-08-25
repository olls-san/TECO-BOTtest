"""
services/inventario_service.py
------------------------------

Service for totalling inventory and optionally sending the report via
email. Produces either an Excel or PDF representation of the inventory
list. The email functionality leverages a utility imported from
``email_utils``; ensure this module is available in your environment.
"""

from __future__ import annotations

from typing import Dict, Any, List, Tuple
from io import BytesIO
import pandas as pd
from datetime import datetime
from fastapi import HTTPException, Query

from app.core.context import get_user_context
from app.core.auth import get_base_url, build_auth_headers
from app.clients.http_client import HTTPClient
from app.utils.cache import cache

try:
    # Optional dependency; imported only if email sending is requested
    from email_utils import enviar_correo  # type: ignore
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
except Exception:
    enviar_correo = None  # type: ignore


def generar_pdf_inventario(productos: List[Dict[str, Any]]) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()
    elements = []
    data = [["Producto", "Disponibilidad", "Medida"]] + [
        [p["Producto"], str(p["Disponibilidad"]), p["Medida"]] for p in productos
    ]
    table = Table(data)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ]))
    elements.append(Paragraph("Reporte de Inventario", styles["Heading1"]))
    elements.append(Spacer(1, 12))
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return buffer


def totalizar_inventario(
    usuario: str,
    enviar_por_correo: bool,
    destinatario: str | None,
    formato: str,
    http_client: HTTPClient,
) -> Dict[str, Any]:
    ctx = get_user_context(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = build_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    # cache key: inventory
    cache_key = f"inventory_{ctx['businessId']}"
    productos_filtrados = cache.get(cache_key)
    if productos_filtrados is None:
        url = f"{base_url}/api/v1/report/stock/disponibility"
        response = http_client.request("GET", url, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Error al consultar inventario")
        data = response.json()
        productos = data.get("result", [])
        productos_filtrados = [
            {
                "Producto": p["productName"],
                "Disponibilidad": round(p.get("disponibility", 0), 2),
                "Medida": p.get("measure", ""),
            }
            for p in productos
            if p.get("disponibility", 0) > 0
        ]
        cache.set(cache_key, productos_filtrados, ttl=300)  # cache for 5 minutes
    if not productos_filtrados:
        raise HTTPException(status_code=404, detail="No hay productos con disponibilidad")
    # Optional email
    if enviar_por_correo and destinatario and enviar_correo:
        if formato == "excel":
            df = pd.DataFrame(productos_filtrados)
            output = BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False, sheet_name="Inventario")
            nombre_archivo = "inventario.xlsx"
            mime = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            output = generar_pdf_inventario(productos_filtrados)
            nombre_archivo = "inventario.pdf"
            mime = ("application", "pdf")
        enviar_correo(
            destinatario=destinatario,
            asunto="Reporte de Inventario",
            cuerpo="Adjunto el inventario solicitado.",
            archivo_adjunto=output,
            nombre_archivo=nombre_archivo,
            tipo_mime=mime,
        )
    return {
        "total": len(productos_filtrados),
        "productos": productos_filtrados,
    }