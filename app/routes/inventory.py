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
from typing import Optional, Literal, Dict, Any, List
from datetime import datetime
import io, csv

from fastapi import HTTPException
# Core helpers existentes en tu proyecto:
# from app.core.http_sync import teco_request
# from ..utils import user_context, get_base_url, get_auth_headers
# from ..emailing import enviar_correo   # ajusta el import según tu estructura

# === Dependencias opcionales (fallbacks controlados) ===
try:
    import openpyxl
    from openpyxl.workbook import Workbook
    OPENPYXL_AVAILABLE = True
except Exception:
    OPENPYXL_AVAILABLE = False

try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False


# =============== Helpers robustos ======================

def _first_list_of_dicts(obj):
    """Encuentra la primera lista de dicts dentro de un json arbitrario."""
    if obj is None:
        return []
    if isinstance(obj, list) and all(isinstance(x, dict) for x in obj):
        return obj
    if isinstance(obj, dict):
        # priorizamos nombres típicos de paginación o envoltorios
        preferred = ["data", "items", "content", "records", "result", "rows"]
        for k in preferred:
            if k in obj:
                lst = _first_list_of_dicts(obj[k])
                if lst:
                    return lst
        # si no están las claves preferidas, probamos cualquier valor dict/list
        for v in obj.values():
            lst = _first_list_of_dicts(v)
            if lst:
                return lst
    return []


def _get_first(d: dict, *paths, default=None):
    """
    Devuelve el primer valor no vacío siguiendo rutas tipo 'a.b.c'.
    paths: strings con claves separadas por '.'
    """
    for p in paths:
        cur = d
        ok = True
        for part in p.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur not in (None, ""):
            return cur
    return default


def _safe_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def _parse_stock_rows(raw: dict | list) -> list[dict]:
    """
    Normaliza la respuesta del endpoint stock/disponibility a:
    { nombre, disponibilidad, medida, almacen }
    """
    rows = _first_list_of_dicts(raw)
    items: List[Dict[str, Any]] = []
    for row in rows:
        # candidatos de nombre
        nombre = _get_first(
            row,
            "productName",
            "product.name",
            "product.shortName",
            "displayName",
            "variantName",
            "name",
            "product.displayName",
            "product.variantName",
            default=None,
        )
        # fallback: usa códigos si no hay nombre legible
        if not nombre:
            nombre = _get_first(
                row,
                "product.code", "product.barCode",
                "code", "barCode",
                default="SIN_NOMBRE"
            )

        # candidatos de cantidad
        cantidad = _get_first(
            row,
            "available",
            "quantity",
            "stock",
            "totalAvailable",
            "availableQuantity",
            "product.available",
            default=0,
        )
        cantidad = _safe_float(cantidad)

        # candidatos de medida
        medida = _get_first(
            row,
            "measureShortName",
            "measure",
            "uom",
            "unit",
            "product.measureShortName",
            "product.measure",
            "product.uom",
            default="",
        )

        # candidatos de almacén / área
        almacen = _get_first(
            row,
            "stockName",
            "warehouseName",
            "areaName",
            "storeName",
            default="",
        )

        items.append({
            "nombre": str(nombre),
            "disponibilidad": cantidad,
            "medida": str(medida),
            "almacen": str(almacen),
        })
    return items


def _agrupar_por_almacen(items: List[Dict[str, Any]]):
    """
    Agrupa productos por 'almacen' y calcula totales.
    Devuelve:
    - total_global (float)
    - por_almacen: [{ almacen, total_cantidad, productos: [...] }]
    """
    grupos: Dict[str, Dict[str, Any]] = {}
    total_global = 0.0

    for it in items:
        al = it.get("almacen") or "SIN_ALMACEN"
        if al not in grupos:
            grupos[al] = {"almacen": al, "total_cantidad": 0.0, "productos": []}
        grupos[al]["productos"].append({
            "nombre": it["nombre"],
            "disponibilidad": it["disponibilidad"],
            "medida": it["medida"],
        })
        grupos[al]["total_cantidad"] += it["disponibilidad"]
        total_global += it["disponibilidad"]

    por_almacen = sorted(grupos.values(), key=lambda g: g["almacen"] or "")
    return total_global, por_almacen


def _debug_shape(raw: dict | list) -> dict:
    rows = _first_list_of_dicts(raw)
    freq = {}
    sample = []
    for i, r in enumerate(rows):
        if i < 3:
            # muestra solo claves de primer nivel con su tipo
            sample.append({k: type(v).__name__ for k, v in r.items()})
        for k in r.keys():
            freq[k] = freq.get(k, 0) + 1
    return {
        "total_detectados": len(rows),
        "frecuencia_claves_nivel1": dict(sorted(freq.items(), key=lambda x: (-x[1], x[0]))),
        "muestra_tipos_nivel1": sample,
    }


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

# ---------------- helpers ----------------

def _first_list_of_dicts(obj):
    if obj is None:
        return []
    if isinstance(obj, list) and all(isinstance(x, dict) for x in obj):
        return obj
    if isinstance(obj, dict):
        for k in ["data", "items", "content", "records", "result", "rows"]:
            if k in obj:
                lst = _first_list_of_dicts(obj[k])
                if lst:
                    return lst
        for v in obj.values():
            lst = _first_list_of_dicts(v)
            if lst:
                return lst
    return []

def _get_first(d: dict, *paths, default=None):
    for p in paths:
        cur = d; ok = True
        for part in p.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False; break
        if ok and cur not in (None, ""):
            return cur
    return default

def _safe_float(x) -> float:
    try: return float(x)
    except Exception: return 0.0

def _parse_stock_rows(raw: dict | list) -> list[dict]:
    """Normaliza a {nombre, disponibilidad, medida, almacen}."""
    rows = _first_list_of_dicts(raw)
    out: List[Dict[str, Any]] = []
    for row in rows:
        nombre = _get_first(
            row, "productName","product.name","product.shortName","displayName",
            "variantName","name","product.displayName","product.variantName",
            default=None
        ) or _get_first(row, "product.code","product.barCode","code","barCode", default="SIN_NOMBRE")
        cantidad = _safe_float(_get_first(
            row, "available","quantity","stock","totalAvailable","availableQuantity","product.available", default=0
        ))
        medida = _get_first(
            row, "measureShortName","measure","uom","unit",
            "product.measureShortName","product.measure","product.uom", default=""
        )
        almacen = _get_first(row, "stockName","warehouseName","areaName","storeName", default="")
        out.append({"nombre": str(nombre), "disponibilidad": cantidad, "medida": str(medida), "almacen": str(almacen)})
    return out

def _agrupar_por_almacen(items: List[Dict[str, Any]]):
    grupos: Dict[str, Dict[str, Any]] = {}
    total_global = 0.0
    for it in items:
        al = it.get("almacen") or "SIN_ALMACEN"
        if al not in grupos:
            grupos[al] = {"almacen": al, "total_cantidad": 0.0, "productos": []}
        grupos[al]["productos"].append({
            "nombre": it["nombre"], "disponibilidad": it["disponibilidad"], "medida": it["medida"]
        })
        grupos[al]["total_cantidad"] += it["disponibilidad"]
        total_global += it["disponibilidad"]
    por_almacen = sorted(grupos.values(), key=lambda g: g["almacen"] or "")
    return total_global, por_almacen


# ---------------- endpoint ----------------

@router.get("/totalizar-inventario")
def totalizar_inventario(
    usuario: str,
    enviar_por_correo: bool = False,
    destinatario: Optional[str] = None,
    formato: Literal["excel", "pdf"] = "excel",
    vista: Literal["total", "almacen"] = "total",  # selector de vista
):
    """
    vista=total   -> devuelve solo el total global (default)
    vista=almacen -> devuelve agrupado por almacén
    """

    # 1) Autenticación + headers (SIEMPRE usa región del login)
    ctx = user_context.get(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])

    # 2) Llamada Tecopos con paginación ?page=
    url = f"{base_url}/api/v1/report/stock/disponibility"
    page = 1
    items: List[Dict[str, Any]] = []

    while True:
        try:
            resp = teco_request("GET", url, headers=headers, params={"page": page})
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Error de red: {e}")
        if not (200 <= resp.status_code < 300):
            raise HTTPException(status_code=resp.status_code, detail=resp.text or "No se pudo obtener el inventario")

        parsed = _parse_stock_rows(resp.json())
        if not parsed:
            break
        items.extend(parsed)
        page += 1

    # 3) Totales y estructura según vista
    total_global, por_almacen = _agrupar_por_almacen(items)

    if vista == "total":
        resultado: Dict[str, Any] = {
            "status": "ok",
            "total_items": len(items),
            "total_global_cantidad": total_global,
            "envio_correo": {
                "solicitado": bool(enviar_por_correo),
                "realizado": False,
                "formato": formato,
                "destinatario": destinatario or None,
                "mensaje": None,
            },
        }
    else:  # vista == "almacen"
        resultado = {
            "status": "ok",
            "total_items": sum(len(x["productos"]) for x in por_almacen),
            "total_global_cantidad": total_global,
            "por_almacen": por_almacen,
            "envio_correo": {
                "solicitado": bool(enviar_por_correo),
                "realizado": False,
                "formato": formato,
                "destinatario": destinatario or None,
                "mensaje": None,
            },
        }

    # 4) Envío opcional por correo (respeta la vista)
    if enviar_por_correo:
        if not destinatario:
            raise HTTPException(status_code=400, detail="Debe enviar 'destinatario' para el envío por correo.")
        ahora = datetime.now().strftime("%Y-%m-%d_%H%M")
        mensaje_extra = None
        data_bytes = io.BytesIO()

        if formato == "excel":
            if OPENPYXL_AVAILABLE:
                wb: Workbook = openpyxl.Workbook()
                ws = wb.active
                if vista == "total":
                    ws.title = "Total"
                    ws.append(["Total global cantidad"])
                    ws.append([total_global])
                else:
                    ws.title = "Inventario por almacén"
                    ws.append(["Almacén", "Nombre", "Disponibilidad", "Medida"])
                    for bloque in por_almacen:
                        al = bloque["almacen"]
                        for p in bloque["productos"]:
                            ws.append([al, p["nombre"], p["disponibilidad"], p["medida"]])
                wb.save(data_bytes)
                data_bytes.seek(0)
                nombre_archivo = f"inventario_{vista}_{ahora}.xlsx"
                mime = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                buf = io.StringIO()
                w = csv.writer(buf)
                if vista == "total":
                    w.writerow(["Total global cantidad"])
                    w.writerow([total_global])
                else:
                    w.writerow(["Almacén", "Nombre", "Disponibilidad", "Medida"])
                    for bloque in por_almacen:
                        al = bloque["almacen"]
                        for p in bloque["productos"]:
                            w.writerow([al, p["nombre"], p["disponibilidad"], p["medida"]])
                data_bytes = io.BytesIO(buf.getvalue().encode("utf-8"))
                nombre_archivo = f"inventario_{vista}_{ahora}.csv"
                mime = ("text", "csv")
                mensaje_extra = "openpyxl no instalado; se envía CSV."

        elif formato == "pdf":
            if not REPORTLAB_AVAILABLE:
                # Fallback a Excel/CSV si falta reportlab (se mantiene la misma región del ctx)
                return totalizar_inventario(
                    usuario=usuario,
                    enviar_por_correo=True,
                    destinatario=destinatario,
                    formato="excel",
                    vista=vista,
                )
            c = canvas.Canvas(data_bytes, pagesize=A4)
            width, height = A4
            y = height - 40
            c.setFont("Helvetica-Bold", 12)
            c.drawString(40, y, "Totalizar Inventario"); y -= 20
            c.setFont("Helvetica", 10)
            c.drawString(40, y, f"Generado: {datetime.now().isoformat(timespec='seconds')}"); y -= 30

            if vista == "total":
                c.setFont("Helvetica-Bold", 11)
                c.drawString(40, y, "Total global cantidad:")
                c.setFont("Helvetica", 11)
                c.drawString(220, y, f"{total_global}")
                y -= 20
            else:
                c.setFont("Helvetica-Bold", 10)
                c.drawString(40, y, "Almacén"); c.drawString(220, y, "Nombre")
                c.drawString(420, y, "Disp."); c.drawString(470, y, "Med."); y -= 16
                c.setFont("Helvetica", 10)
                for bloque in por_almacen:
                    if y < 70: c.showPage(); y = height - 40
                    c.setFont("Helvetica-Bold", 10)
                    c.drawString(40, y, f"Almacén: {bloque['almacen'] or '—'}  (Total: {bloque['total_cantidad']})")
                    y -= 14; c.setFont("Helvetica", 10)
                    for p in bloque["productos"]:
                        if y < 60: c.showPage(); y = height - 60; c.setFont("Helvetica", 10)
                        c.drawString(40, y, (bloque["almacen"] or "—")[:22])
                        c.drawString(220, y, p["nombre"][:36])
                        c.drawRightString(460, y, f"{p['disponibilidad']}")
                        c.drawString(470, y, p["medida"][:12]); y -= 12
                    y -= 6
            c.showPage(); c.save(); data_bytes.seek(0)
            nombre_archivo = f"inventario_{vista}_{ahora}.pdf"
            mime = ("application", "pdf")

        else:
            raise HTTPException(status_code=400, detail="Formato no soportado")

        asunto = "Totalizar inventario"
        cuerpo = "Se adjunta el inventario solicitado."
        if mensaje_extra: cuerpo += f" Nota: {mensaje_extra}"

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
