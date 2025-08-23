"""
Inventory and production efficiency endpoints.

This module provides endpoints to list stock areas and compute
efficiency metrics for ice cream and yogurt production.  Grouping
inventory-related operations together facilitates focused updates
without interfering with reporting or dispatch logic.
"""

from __future__ import annotations

from typing import Dict, List

# Use the shared HTTP client with retries and timeouts
from app.core.http_sync import teco_request
from fastapi import APIRouter, HTTPException
from typing import Optional, Literal
from datetime import datetime
import io, csv
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

from email_utils import enviar_correo


from .. import models
from ..utils import (
    user_context,
    get_base_url,
    get_auth_headers,
    extraer_sabor,
)

router = APIRouter()


@router.get("/listar-areas")
def listar_areas(usuario: str):
    """Return a list of stock areas for the current business."""
    ctx = user_context.get(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    url = f"{base_url}/api/v1/administration/area"
    params = {"page": 1, "type": "STOCK"}
    response = teco_request("GET", url, headers=headers, params=params)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail="Error al obtener las áreas")
    items = response.json().get("items", [])
    return [{"id": a["id"], "nombre": a["name"]} for a in items]


@router.post("/rendimiento-helado")
def rendimiento_helado(data: models.RendimientoHeladoRequest):
    """Calculate efficiency metrics for ice cream production."""
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    # Get area by name
    url_areas = f"{base_url}/api/v1/administration/area?page=1&type=STOCK"
    response_areas = teco_request("GET", url_areas, headers=headers)
    if response_areas.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudieron obtener las áreas")
    areas = response_areas.json().get("items", [])
    area = next((a for a in areas if a["name"] == data.area_nombre), None)
    if not area:
        raise HTTPException(status_code=404, detail="Área no encontrada")
    area_id = area["id"]
    movimientos_url = (
        f"{base_url}/api/v1/administration/movement?areaId={area_id}&all_data=true"
        f"&dateFrom={data.fecha_inicio}&dateTo={data.fecha_fin}&category=TRANSFORMATION"
    )
    response_mov = teco_request("GET", movimientos_url, headers=headers)
    if response_mov.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudieron obtener los movimientos")
    movimientos = response_mov.json().get("items", [])
    entradas = [m for m in movimientos if m["operation"] == "ENTRY"]
    salidas = [m for m in movimientos if m["operation"] == "OUT"]
    resultados: List[Dict[str, object]] = []
    for salida in salidas:
        nombre_mezcla = salida["product"]["name"]
        if "Mezcla" not in nombre_mezcla:
            continue
        entrada = next((e for e in entradas if e.get("parentId") == salida["id"]), None)
        if not entrada:
            continue
        sabor = extraer_sabor(nombre_mezcla)
        cantidad_mezcla = abs(salida["quantity"])
        cantidad_producida = entrada["quantity"]
        rendimiento_real = round(cantidad_producida / cantidad_mezcla, 4) if cantidad_mezcla else 0
        rendimiento_ideal = 2
        eficiencia = round((rendimiento_real / rendimiento_ideal) * 100, 2)
        resultados.append({
            "tipo": "Helado",
            "sabor": sabor,
            "mezcla_usada_litros": cantidad_mezcla,
            "producto_producido_litros": cantidad_producida,
            "rendimiento_real": rendimiento_real,
            "rendimiento_ideal": rendimiento_ideal,
            "eficiencia_porcentual": eficiencia,
        })
    return {
        "area_nombre": area["name"],
        "area_id": area["id"],
        "resumen": resultados,
    }


@router.post("/rendimiento-yogurt", response_model=models.RendimientoYogurtResponse)
def rendimiento_yogurt(data: models.RendimientoYogurtRequest):
    """Calculate efficiency metrics for yogurt production."""
    ctx = user_context.get(data.usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])
    areas_url = f"{base_url}/api/v1/administration/area?page=1&type=STOCK"
    res_areas = teco_request("GET", areas_url, headers=headers)
    if res_areas.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudieron obtener las áreas")
    areas = res_areas.json().get("items", [])
    area = next((a for a in areas if a["name"] == data.area_nombre), None)
    if not area:
        raise HTTPException(status_code=404, detail="Área no encontrada")
    area_id = area["id"]
    movimientos_url = (
        f"{base_url}/api/v1/administration/movement?areaId={area_id}&all_data=true"
        f"&dateFrom={data.fecha_inicio}&dateTo={data.fecha_fin}&category=TRANSFORMATION"
    )
    response_mov = teco_request("GET", movimientos_url, headers=headers)
    if response_mov.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudieron obtener los movimientos")
    movimientos = response_mov.json().get("items", [])
    entradas = [m for m in movimientos if m["operation"] == "ENTRY"]
    salidas = [m for m in movimientos if m["operation"] == "OUT"]
    resultados: List[models.RendimientoYogurtResumen] = []
    for salida in salidas:
        nombre_mezcla = salida["product"]["name"]
        if "Mezcla" not in nombre_mezcla:
            continue
        entrada = next((e for e in entradas if e.get("parentId") == salida["id"]), None)
        if not entrada:
            continue
        sabor = extraer_sabor(nombre_mezcla)
        mezcla_usada = abs(salida["quantity"])
        produccion = entrada["quantity"]
        rendimiento_real = round(produccion / mezcla_usada, 4) if mezcla_usada else 0
        rendimiento_ideal = 2
        eficiencia = round((rendimiento_real / rendimiento_ideal) * 100, 2)
        resultados.append(models.RendimientoYogurtResumen(
            tipo="Yogurt",
            sabor=sabor,
            mezcla_usada_litros=mezcla_usada,
            producto_producido_litros=produccion,
            rendimiento_real=rendimiento_real,
            rendimiento_ideal=rendimiento_ideal,
            eficiencia_porcentual=eficiencia,
        ))
    return models.RendimientoYogurtResponse(
        area_nombre=area["name"],
        area_id=area["id"],
        resumen=resultados,
    )

@router.get("/totalizar-inventario")
def totalizar_inventario(
    usuario: str,
    enviar_por_correo: bool = False,
    destinatario: Optional[str] = None,
    formato: Literal["excel", "pdf"] = "excel",
):
    """
    Devuelve inventario con claves fijas y, opcionalmente, lo envía por correo.
    - productos[i]: { nombre, disponibilidad, medida }
    - envio_correo: { solicitado, realizado, formato, destinatario, mensaje }
    """
    # 1) Autenticación + headers
    ctx = user_context.get(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])

    # 2) Llamada a Tecopos
    url = f"{base_url}/api/v1/report/stock/disponibility"
    resp = teco_request("GET", url, headers=headers)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="No se pudo obtener el inventario")

    filas = resp.json().get("data") or resp.json().get("items") or resp.json()
    if not isinstance(filas, list):
        filas = [filas] if filas else []

    # 3) Normalización → claves fijas
    productos = []
    for row in filas:
        nombre = (
            row.get("productName")
            or (row.get("product") or {}).get("name")
            or row.get("name")
            or "SIN_NOMBRE"
        )
        cantidad = float(row.get("quantity") or row.get("available") or row.get("stock") or 0)
        medida = (
            row.get("measure")
            or row.get("measureShortName")
            or (row.get("product") or {}).get("measure")
            or ""
        )
        productos.append({
            "nombre": str(nombre),
            "disponibilidad": cantidad,
            "medida": str(medida),
        })

    resultado = {
        "status": "ok",
        "total": len(productos),
        "productos": productos,
        "envio_correo": {
            "solicitado": bool(enviar_por_correo),
            "realizado": False,
            "formato": formato,
            "destinatario": destinatario or None,
            "mensaje": None,
        },
    }

    # 4) Envío opcional por correo
    if enviar_por_correo:
        if not destinatario:
            raise HTTPException(status_code=400, detail="Debe enviar 'destinatario' para el envío por correo.")

        ahora = datetime.now().strftime("%Y-%m-%d_%H%M")
        mensaje_extra = None

        if formato == "pdf" and not REPORTLAB_AVAILABLE:
            formato = "excel"
            mensaje_extra = "reportlab no instalado; se envía CSV (excel)."

        if formato == "excel":
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=["nombre", "disponibilidad", "medida"])
            writer.writeheader()
            writer.writerows(productos)
            data_bytes = io.BytesIO(buf.getvalue().encode("utf-8"))
            nombre_archivo = f"inventario_{ahora}.csv"
            mime = ("text", "csv")

        elif formato == "pdf":
            data_bytes = io.BytesIO()
            c = canvas.Canvas(data_bytes, pagesize=A4)
            width, height = A4
            y = height - 40
            c.setFont("Helvetica-Bold", 12)
            c.drawString(40, y, "Totalizar Inventario")
            y -= 20
            c.setFont("Helvetica", 10)
            c.drawString(40, y, f"Generado: {datetime.now().isoformat(timespec='seconds')}")
            y -= 30
            c.setFont("Helvetica-Bold", 10)
            c.drawString(40, y, "Nombre")
            c.drawString(300, y, "Disponibilidad")
            c.drawString(420, y, "Medida")
            y -= 16
            c.setFont("Helvetica", 10)
            for p in productos:
                if y < 60:
                    c.showPage(); y = height - 60
                c.drawString(40, y, p["nombre"][:55])
                c.drawRightString(400, y, f'{p["disponibilidad"]}')
                c.drawString(420, y, p["medida"][:15])
                y -= 14
            c.showPage(); c.save()
            data_bytes.seek(0)
            nombre_archivo = f"inventario_{ahora}.pdf"
            mime = ("application", "pdf")

        else:
            raise HTTPException(status_code=400, detail="Formato no soportado")

        asunto = "Totalizar inventario"
        cuerpo = "Se adjunta el inventario solicitado."
        if mensaje_extra:
            cuerpo += f" Nota: {mensaje_extra}"

        ok = enviar_correo(
            destinatario=destinatario,
            asunto=asunto,
            cuerpo=cuerpo,
            archivo_adjunto=data_bytes,
            nombre_archivo=nombre_archivo,
            tipo_mime=mime,
        )
        resultado["envio_correo"]["realizado"] = bool(ok)
        resultado["envio_correo"]["mensaje"] = "Correo enviado" if ok else "No se pudo enviar el correo"

    return resultado
