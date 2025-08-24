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
# Trata como 0 cualquier cantidad |x| < ZERO_EPS (evita "casi ceros" tipo 7.1e-15)
ZERO_EPS = 1e-6

def _parse_stock_rows(raw_json: dict | list) -> List[Dict[str, Any]]:
    """
    Normaliza la respuesta de /report/stock/disponibility a REGISTROS POR PRODUCTO.
    - Lee 'result' si existe (estructura del backend mostrada).
    - Usa 'disponibility' como cantidad (si falta, cae a suma de stocks[].quantity).
    - Aplica ZERO_EPS para convertir "casi ceros" a 0.
    - Devuelve campos estándar usados por el endpoint: nombre, disponibilidad, medida, almacen="".
    """
    # 1) Detecta la lista real de filas
    if isinstance(raw_json, dict) and isinstance(raw_json.get("result"), list):
        rows = raw_json["result"]
    else:
        rows = _first_list_of_dicts(raw_json)

    items: List[Dict[str, Any]] = []

    # Mapeo opcional de medidas "técnicas" a legibles
    MEASURE_MAP = {
        "UNIT": "unid",
        "POUND": "lb",
        "LITER": "L",
        "KILOGRAM": "kg",
    }

    for row in rows:
        # nombre del producto
        nombre = _get_first(
            row,
            "productName", "product.name", "displayName", "variantName", "name",
            "product.displayName", "product.variantName",
            default=None,
        ) or _get_first(row, "universalCode", "productId", default="SIN_NOMBRE")

        # cantidad: preferimos 'disponibility'; si no está, sumamos stocks[].quantity
        cantidad = row.get("disponibility", None)
        if cantidad is None:
            cantidad = sum(_safe_float(s.get("quantity", 0)) for s in (row.get("stocks") or []) )
        cantidad = _safe_float(cantidad)
        if abs(cantidad) < ZERO_EPS:
            cantidad = 0.0

        # medida legible
        medida_raw = _get_first(row, "measure", "measureShortName", "uom", "unit", default="") or ""
        medida = MEASURE_MAP.get(str(medida_raw).upper(), str(medida_raw))

        # Registro por PRODUCTO (no por almacén)
        items.append({
            "nombre": str(nombre),
            "disponibilidad": cantidad,
            "medida": medida,
            "almacen": "",  # vacío porque estamos agregando por producto
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
    incluir_costo_pdf: bool = False,  # << NUEVO: solo afecta al PDF
):
    """
    ÚNICA VISTA: 'disponibles'
    - Lista productos con disponibilidad > 0 (Producto, Disponibilidad, Medida, CostoUnitario, Moneda)
    - Resumen: total_items y costo_total (por moneda; si solo hay una moneda, también plano)
    - Autodetección de paginación (sin loops).
    - Sin redondeos: se retornan floats tal cual.
    - NOTA: 'incluir_costo_pdf' controla SOLO el render del PDF; JSON/Excel/CSV incluyen costo siempre.
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

    first_json = first.json()
    first_items_raw, first_meta = _json_items_or_list(first_json)

    # Parseo base (nombre, disponibilidad, medida, almacén)
    items_norm: List[Dict[str, Any]] = _parse_stock_rows(first_items_raw)

    # ¿Backend indica que hay siguiente página?
    next_hint = _has_next_page(first_meta, page=1)
    if next_hint is True:
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

            page_json = resp.json()
            page_items_raw, page_meta = _json_items_or_list(page_json)
            if not page_items_raw:
                break

            cur_digest = _digest_page(page_items_raw)
            if prev_digest and cur_digest == prev_digest:
                break
            prev_digest = cur_digest

            items_norm.extend(_parse_stock_rows(page_items_raw))

            hint = _has_next_page(page_meta, page=page)
            if hint is False:
                break
            page += 1

    # 3) Enriquecer con costo unitario y moneda (para cálculos/Excel/CSV)
    def _index_key(it: Dict[str, Any]) -> tuple:
        return (it.get("nombre"), it.get("medida"), it.get("almacen"))

    index_map: Dict[tuple, Dict[str, Any]] = {}
    for it in items_norm:
        index_map[_index_key(it)] = {
            "Producto": it["nombre"],
            "Disponibilidad": it.get("disponibilidad", 0),
            "Medida": it.get("medida", ""),
            "CostoUnitario": 0.0,
            "Moneda": "UNK",
        }

    def _extraer_costo_y_moneda(row: dict) -> tuple[float, str]:
        costo_unit = _safe_float(_get_first(
            row,
            "cost.amount",
            "unitCost",
            "averageCost",
            "avgCost",
            "lastCost",
            "productCost.amount",
            "costAmount",
            default=0,
        ))
        moneda = _get_first(
            row,
            "cost.codeCurrency",
            "codeCurrency",
            "currency",
            "productCost.codeCurrency",
            default="UNK",
        ) or "UNK"
        return costo_unit, str(moneda)

    def _merge_costs_from_json(any_json):
        rows = _first_list_of_dicts(any_json)
        for r in rows:
            nombre = _get_first(
                r,
                "productName", "product.name", "product.shortName",
                "displayName", "variantName", "name",
                "product.displayName", "product.variantName",
                default=None,
            ) or _get_first(r, "product.code", "product.barCode", "code", "barCode", default="SIN_NOMBRE")
            medida = _get_first(
                r,
                "measureShortName", "measure", "uom", "unit",
                "product.measureShortName", "product.measure", "product.uom",
                default="",
            )
            almacen = _get_first(r, "stockName", "warehouseName", "areaName", "storeName", default="")
            key = (str(nombre), str(medida), str(almacen))
            if key in index_map:
                cu, mon = _extraer_costo_y_moneda(r)
                if cu or mon != "UNK":
                    index_map[key]["CostoUnitario"] = cu
                    index_map[key]["Moneda"] = mon

    _merge_costs_from_json(first_json)

    # 4) Filtrar productos con disponibilidad > 0 (sin redondeo)
    productos_filtrados = [
        it for it in items_norm
        if _safe_float(it.get("disponibilidad", 0) or 0) > ZERO_EPS
    ]

    # 5) Costo total por moneda
    costos_por_moneda: Dict[str, float] = {}
    for p in productos_filtrados:
        disp = _safe_float(p["Disponibilidad"])
        cu = _safe_float(p.get("CostoUnitario", 0))
        mon = str(p.get("Moneda") or "UNK")
        costos_por_moneda[mon] = costos_por_moneda.get(mon, 0.0) + (disp * cu)

    costo_total = None
    moneda_unica = None
    if len(costos_por_moneda) == 1:
        moneda_unica, costo_total = next(iter(costos_por_moneda.items()))

    resultado: Dict[str, Any] = {
        "status": "ok",
        "total_items": len(productos_filtrados),
        "costos_por_moneda": costos_por_moneda,
        "productos": productos_filtrados,
    }
    if costo_total is not None:
        resultado["costo_total"] = costo_total
        resultado["moneda"] = moneda_unica

    # 6) Exportación y envío por correo
    if enviar_por_correo:
        if not destinatario:
            raise HTTPException(status_code=400, detail="Debe enviar 'destinatario' para el envío por correo.")

        ahora = datetime.now().strftime("%Y-%m-%d_%H%M")
        data_bytes = io.BytesIO()
        mensaje_extra = None

        if formato == "excel":
            if OPENPYXL_AVAILABLE:
                wb: Workbook = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Disponibles"
                ws.append(["Producto", "Disponibilidad", "Medida", "CostoUnitario", "Moneda"])
                for p in productos_filtrados:
                    ws.append([p["Producto"], p["Disponibilidad"], p["Medida"], p["CostoUnitario"], p["Moneda"]])
                # Resumen
                ws.append([])
                ws.append(["total_items", len(productos_filtrados)])
                if costo_total is not None:
                    ws.append(["costo_total", costo_total, moneda_unica])
                ws.append(["costos_por_moneda"])
                for m, v in costos_por_moneda.items():
                    ws.append([m, v])
                wb.save(data_bytes)
                data_bytes.seek(0)
                nombre_archivo = f"inventario_disponibles_{ahora}.xlsx"
                mime = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(["Producto", "Disponibilidad", "Medida", "CostoUnitario", "Moneda"])
                for p in productos_filtrados:
                    w.writerow([p["Producto"], p["Disponibilidad"], p["Medida"], p["CostoUnitario"], p["Moneda"]])
                w.writerow([])
                w.writerow(["total_items", len(productos_filtrados)])
                if costo_total is not None:
                    w.writerow(["costo_total", costo_total, moneda_unica])
                w.writerow(["costos_por_moneda"])
                for m, v in costos_por_moneda.items():
                    w.writerow([m, v])
                data_bytes = io.BytesIO(buf.getvalue().encode("utf-8"))
                nombre_archivo = f"inventario_disponibles_{ahora}.csv"
                mime = ("text", "csv")
                mensaje_extra = "openpyxl no instalado; se envía CSV."

        elif formato == "pdf":
            if not REPORTLAB_AVAILABLE:
                return totalizar_inventario(
                    usuario=usuario,
                    enviar_por_correo=True,
                    destinatario=destinatario,
                    formato="excel",
                )

            c = canvas.Canvas(data_bytes, pagesize=A4)
            width, height = A4
            y = height - 40
            c.setFont("Helvetica-Bold", 12)
            c.drawString(40, y, "Inventario – Disponibles"); y -= 20
            c.setFont("Helvetica", 10)
            c.drawString(40, y, f"Generado: {datetime.now().isoformat(timespec='seconds')}"); y -= 30

            # encabezados según flag
            c.setFont("Helvetica-Bold", 10)
            c.drawString(40, y, "Producto")
            c.drawString(300, y, "Disp.")
            c.drawString(360, y, "Med.")
            if incluir_costo_pdf:
                c.drawString(420, y, "Costo")
                c.drawString(480, y, "Mon.")
            y -= 16
            c.setFont("Helvetica", 10)

            for p in productos_filtrados:
                if y < 60:
                    c.showPage(); y = height - 60; c.setFont("Helvetica", 10)
                    c.setFont("Helvetica-Bold", 10)
                    c.drawString(40, y, "Producto"); c.drawString(300, y, "Disp.")
                    c.drawString(360, y, "Med.")
                    if incluir_costo_pdf:
                        c.drawString(420, y, "Costo"); c.drawString(480, y, "Mon.")
                    y -= 16; c.setFont("Helvetica", 10)

                c.drawString(40, y, str(p["Producto"])[:46])
                c.drawRightString(340, y, f"{p['Disponibilidad']}")
                c.drawString(360, y, str(p["Medida"])[:10])

                if incluir_costo_pdf:
                    c.drawRightString(470, y, f"{p['CostoUnitario']}")
                    c.drawString(480, y, str(p["Moneda"])[:6])

                y -= 12

            # resumen al final
            y -= 10; c.setFont("Helvetica-Bold", 10)
            c.drawString(40, y, f"total_items: {len(productos_filtrados)}"); y -= 14
            if incluir_costo_pdf:
                if costo_total is not None:
                    c.drawString(40, y, f"costo_total: {costo_total} {moneda_unica}"); y -= 14
                c.drawString(40, y, "costos_por_moneda:")
                y -= 14; c.setFont("Helvetica", 10)
                for m, v in costos_por_moneda.items():
                    if y < 50:
                        c.showPage(); y = height - 50; c.setFont("Helvetica", 10)
                    c.drawString(60, y, f"{m}: {v}")
                    y -= 12

            c.showPage(); c.save(); data_bytes.seek(0)
            nombre_archivo = f"inventario_disponibles_{ahora}.pdf"
            mime = ("application", "pdf")

        else:
            raise HTTPException(status_code=400, detail="Formato no soportado")

        asunto = "Inventario – Disponibles"
        cuerpo = "Se adjunta el inventario solicitado (productos con disponibilidad > 0)."
        if formato == "pdf":
            cuerpo += f" (Costo {'incluido' if incluir_costo_pdf else 'no incluido'} en PDF)"

        ok = enviar_correo(
            destinatario=destinatario,
            asunto=asunto,
            cuerpo=cuerpo,
            archivo_adjunto=data_bytes,
            nombre_archivo=nombre_archivo,
            tipo_mime=mime,
        )
        resultado["envio_correo"] = {
            "solicitado": True,
            "realizado": bool(ok),
            "formato": formato,
            "destinatario": destinatario,
            "mensaje": "Correo enviado" if ok else "No se pudo enviar el correo",
            "incluir_costo_pdf": incluir_costo_pdf,
        }

    return resultado


