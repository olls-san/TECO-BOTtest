"""
Inventory and production efficiency endpoints.

Endpoints:
- GET  /listar-areas
- POST /rendimiento-helado
- POST /rendimiento-yogurt
- GET  /totalizar-inventario  (arreglado: autodetección de paginación, sin loops)
"""

from __future__ import annotations

from typing import Optional, Literal, Dict, Any, List
from datetime import datetime
import io
import csv
from hashlib import sha1

from fastapi import APIRouter, HTTPException
from app.core.http_sync import teco_request

# Helpers y modelos del proyecto
from .. import models
from ..utils import (
    user_context,
    get_base_url,
    get_auth_headers,
    extraer_sabor,
)

# Email
from email_utils import enviar_correo

# Dependencias opcionales (exportaciones)
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


router = APIRouter()


# =========================
# Helpers genéricos JSON
# =========================

def _first_list_of_dicts(obj) -> List[dict]:
    """Encuentra la primera lista de dicts dentro de un json arbitrario."""
    if obj is None:
        return []
    if isinstance(obj, list) and all(isinstance(x, dict) for x in obj):
        return obj
    if isinstance(obj, dict):
        # prioriza envoltorios comunes
        for k in ["data", "items", "content", "records", "result", "rows"]:
            if k in obj:
                lst = _first_list_of_dicts(obj[k])
                if lst:
                    return lst
        # si no están, prueba cualquier valor
        for v in obj.values():
            lst = _first_list_of_dicts(v)
            if lst:
                return lst
    return []


def _get_first(d: dict, *paths, default=None):
    """Devuelve el primer valor no vacío siguiendo rutas 'a.b.c'."""
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


# =========================
# Helpers de inventario
# =========================

def _parse_stock_rows(raw_json: dict | list) -> List[Dict[str, Any]]:
    """
    Normaliza la respuesta del endpoint stock/disponibility a:
    { nombre, disponibilidad, medida, almacen }
    """
    rows = _first_list_of_dicts(raw_json)
    items: List[Dict[str, Any]] = []
    for row in rows:
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
        if not nombre:
            nombre = _get_first(
                row,
                "product.code",
                "product.barCode",
                "code",
                "barCode",
                default="SIN_NOMBRE",
            )

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

        almacen = _get_first(
            row,
            "stockName",
            "warehouseName",
            "areaName",
            "storeName",
            default="",
        )

        items.append(
            {
                "nombre": str(nombre),
                "disponibilidad": cantidad,
                "medida": str(medida),
                "almacen": str(almacen),
            }
        )
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
        grupos[al]["productos"].append(
            {
                "nombre": it["nombre"],
                "disponibilidad": it["disponibilidad"],
                "medida": it["medida"],
            }
        )
        grupos[al]["total_cantidad"] += it["disponibilidad"]
        total_global += it["disponibilidad"]

    por_almacen = sorted(grupos.values(), key=lambda g: g["almacen"] or "")
    return total_global, por_almacen


# =========================
# Helpers paginación segura
# =========================

def _json_items_or_list(obj):
    """Devuelve (lista_items, meta_json)."""
    return _first_list_of_dicts(obj), obj


def _has_next_page(meta: Any, page: int) -> Optional[bool]:
    """
    Intenta inferir si existe siguiente página a partir de campos comunes.
    True/False si se puede inferir, None si no hay señal.
    """
    if isinstance(meta, dict):
        p = meta.get("page") or meta.get("number")
        total_pages = meta.get("totalPages") or meta.get("total_pages")
        if isinstance(p, int) and isinstance(total_pages, int):
            return p + 1 < total_pages
        if "hasNext" in meta:
            return bool(meta["hasNext"])
        if "last" in meta:
            return not bool(meta["last"])
    return None


def _digest_page(items: List[dict]) -> Optional[str]:
    """
    Hash simple de una página para detectar contenido repetido
    cuando el backend ignora ?page=.
    """
    try:
        subset = items[:50]
        b = repr(subset).encode("utf-8", "ignore")
        return sha1(b).hexdigest()
    except Exception:
        return None


# =========================
# Endpoints
# =========================

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
        rendimiento_ideal = 2  # helado
        eficiencia = round((rendimiento_real / rendimiento_ideal) * 100, 2)

        resultados.append(
            {
                "tipo": "Helado",
                "sabor": sabor,
                "mezcla_usada_litros": cantidad_mezcla,
                "producto_producido_litros": cantidad_producida,
                "rendimiento_real": rendimiento_real,
                "rendimiento_ideal": rendimiento_ideal,
                "eficiencia_porcentual": eficiencia,
            }
        )

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
        rendimiento_ideal = 2  # yogurt base 1.0 en pautas antiguas; se mantiene 2 si así quedó tu estándar
        eficiencia = round((rendimiento_real / rendimiento_ideal) * 100, 2)

        resultados.append(
            models.RendimientoYogurtResumen(
                tipo="Yogurt",
                sabor=sabor,
                mezcla_usada_litros=mezcla_usada,
                producto_producido_litros=produccion,
                rendimiento_real=rendimiento_real,
                rendimiento_ideal=rendimiento_ideal,
                eficiencia_porcentual=eficiencia,
            )
        )

    return models.RendimientoYogurtResponse(
        area_nombre=area["name"],
        area_id=area["id"],
        resumen=resultados,
    )


# =========================
# TOTALIZAR INVENTARIO (FIX)
# =========================

@router.get("/totalizar-inventario")
def totalizar_inventario(
    usuario: str,
    enviar_por_correo: bool = False,
    destinatario: Optional[str] = None,
    formato: Literal["excel", "pdf"] = "excel",
    vista: Literal["total", "almacen"] = "total",
):
    """
    - Si el endpoint NO pagina: hace una sola llamada.
    - Si pagina: itera de forma segura hasta agotar páginas o detectar repetición.
    - 'vista=total' -> solo total global; 'vista=almacen' -> agrupado por almacén.
    """

    # 1) Autenticación + headers
    ctx = user_context.get(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])

    url = f"{base_url}/api/v1/report/stock/disponibility"

    # 2) Primer fetch (autodetección de paginación)
    try:
        first = teco_request("GET", url, headers=headers, params={"page": 1})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error de red: {e}")

    if not (200 <= first.status_code < 300):
        raise HTTPException(status_code=first.status_code, detail=first.text or "No se pudo obtener inventario")

    first_items_raw, first_meta = _json_items_or_list(first.json())
    items_norm: List[Dict[str, Any]] = []
    items_norm.extend(_parse_stock_rows(first_items_raw))

    # ¿Backend indica que hay siguiente página?
    next_hint = _has_next_page(first_meta, page=1)

    if next_hint is True:
        # Itera con guardas anti-loop
        max_pages = 1000
        prev_digest = _digest_page(first_items_raw)
        page = 2
        while page <= max_pages:
            try:
                resp = teco_request("GET", url, headers=headers, params={"page": page})
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Error de red en página {page}: {e}")

            if not (200 <= resp.status_code < 300):
                raise HTTPException(status_code=resp.status_code, detail=resp.text or f"Error en página {page}")

            page_items_raw, page_meta = _json_items_or_list(resp.json())
            if not page_items_raw:
                break

            cur_digest = _digest_page(page_items_raw)
            if prev_digest and cur_digest == prev_digest:
                # contenido repetido -> rompemos
                break
            prev_digest = cur_digest

            items_norm.extend(_parse_stock_rows(page_items_raw))

            hint = _has_next_page(page_meta, page=page)
            if hint is False:
                break
            page += 1

    # Si next_hint es False o None => asumimos sin paginación adicional
    # y continuamos con lo ya obtenido.

    # 3) Totales / vistas
    total_global, por_almacen = _agrupar_por_almacen(items_norm)
    resultado: Dict[str, Any] = {
        "status": "ok",
        "total_items": len(items_norm) if vista == "total" else sum(len(x["productos"]) for x in por_almacen),
        "total_global_cantidad": total_global,
        "envio_correo": {
            "solicitado": bool(enviar_por_correo),
            "realizado": False,
            "formato": formato,
            "destinatario": destinatario or None,
            "mensaje": None,
        },
    }
    if vista == "almacen":
        resultado["por_almacen"] = por_almacen

    # 4) Exportación y envío opcional por correo
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
                # Fallback a Excel/CSV si falta reportlab
                if OPENPYXL_AVAILABLE:
                    formato_alt = "excel"
                else:
                    formato_alt = "excel"  # se generará CSV de fallback
                return totalizar_inventario(
                    usuario=usuario,
                    enviar_por_correo=True,
                    destinatario=destinatario,
                    formato=formato_alt,
                    vista=vista,
                )

            c = canvas.Canvas(data_bytes, pagesize=A4)
            width, height = A4
            y = height - 40
            c.setFont("Helvetica-Bold", 12)
            c.drawString(40, y, "Totalizar Inventario")
            y -= 20
            c.setFont("Helvetica", 10)
            c.drawString(40, y, f"Generado: {datetime.now().isoformat(timespec='seconds')}")
            y -= 30

            if vista == "total":
                c.setFont("Helvetica-Bold", 11)
                c.drawString(40, y, "Total global cantidad:")
                c.setFont("Helvetica", 11)
                c.drawString(220, y, f"{total_global}")
                y -= 20
            else:
                c.setFont("Helvetica-Bold", 10)
                c.drawString(40, y, "Almacén")
                c.drawString(220, y, "Nombre")
                c.drawString(420, y, "Disp.")
                c.drawString(470, y, "Med.")
                y -= 16
                c.setFont("Helvetica", 10)
                for bloque in por_almacen:
                    if y < 70:
                        c.showPage()
                        y = height - 40
                    c.setFont("Helvetica-Bold", 10)
                    c.drawString(
                        40,
                        y,
                        f"Almacén: {bloque['almacen'] or '—'}  (Total: {bloque['total_cantidad']})",
                    )
                    y -= 14
                    c.setFont("Helvetica", 10)
                    for p in bloque["productos"]:
                        if y < 60:
                            c.showPage()
                            y = height - 60
                            c.setFont("Helvetica", 10)
                        c.drawString(40, y, (bloque["almacen"] or "—")[:22])
                        c.drawString(220, y, p["nombre"][:36])
                        c.drawRightString(460, y, f"{p['disponibilidad']}")
                        c.drawString(470, y, p["medida"][:12])
                        y -= 12
                    y -= 6

            c.showPage()
            c.save()
            data_bytes.seek(0)
            nombre_archivo = f"inventario_{vista}_{ahora}.pdf"
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

