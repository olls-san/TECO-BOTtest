"""
Inventory and production efficiency endpoints.

Endpoints:
- GET  /listar-areas
- POST /rendimiento-helado
- POST /rendimiento-yogurt
- GET  /totalizar-inventario  (MIN: solo productName, disponibility, total_cost + resumen)
"""

from __future__ import annotations

from typing import Optional, Literal, Dict, Any, List
from datetime import datetime
import io
import csv
from hashlib import sha1
from fastapi import Query
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

# Email (no se usa en el endpoint mínimo, pero se deja disponible)
from email_utils import enviar_correo

# Dependencias opcionales (no usadas por el endpoint mínimo)
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
    - Devuelve campos estándar usados por otras vistas (no se usa en el endpoint mínimo).
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
    (No se usa en el endpoint mínimo; se conserva por compatibilidad.)
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
    if isinstance(obj, dict) and isinstance(obj.get("result"), list):
        return obj["result"], obj
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
# TOTALIZAR INVENTARIO (MÍNIMO)
# =========================

@router.get("/totalizar-inventario")
def totalizar_inventario(
    usuario: str,
    enviar_por_correo: bool = Query(False, description="Si es true, genera y envía un archivo al correo indicado."),
    destinatario: Optional[str] = Query(None, description="Correo destino; obligatorio si enviar_por_correo=true."),
    formato: Literal["pdf", "excel"] = Query("pdf", description="Formato del archivo si se envía por correo."),
):
    """
    Respuesta mínima por PRODUCTO:
      - productos[]: [{ productName, disponibility, total_cost }]
      - resumen: { items, disponibilidad_total, costo_total }

    Envío opcional por correo (PDF/Excel) SOLO si enviar_por_correo=true y se indica 'destinatario'.
    Regla: El archivo (PDF o Excel) se genera SIN costos; contiene solo cantidades generales.
    """
    # 1) Autenticación + headers
    ctx = user_context.get(usuario)
    if not ctx:
        raise HTTPException(status_code=403, detail="Usuario no autenticado")
    base_url = get_base_url(ctx["region"])
    headers = get_auth_headers(ctx["token"], ctx["businessId"], ctx["region"])

    url = f"{base_url}/api/v1/report/stock/disponibility"
    productos: List[Dict[str, Any]] = []

    # 2) Paginación segura
    page = 1
    last_digest: Optional[str] = None
    MAX_PAGES = 1000

    while page <= MAX_PAGES:
        try:
            resp = teco_request("GET", url, headers=headers, params={"page": page})
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Error de red: {e}")

        if not (200 <= resp.status_code < 300):
            raise HTTPException(status_code=resp.status_code, detail=resp.text or f"Error en página {page}")

        js = resp.json()

        # Soporta estructura con { result: [...] }
        rows = js["result"] if isinstance(js, dict) and isinstance(js.get("result"), list) else _first_list_of_dicts(js)
        if not rows:
            break

        # Anti-loop: cortar si el backend ignora ?page=
        dig = sha1(repr(rows[:50]).encode("utf-8", "ignore")).hexdigest()
        if last_digest is not None and dig == last_digest:
            break
        last_digest = dig

        # 3) Normalizar SOLO los 3 campos pedidos (por PRODUCTO)
        for r in rows:
            name = r.get("productName") or r.get("name") or r.get("universalCode") or r.get("productId") or "SIN_NOMBRE"

            # cantidad: preferimos 'disponibility'; si falta, sumamos stocks[].quantity
            disp = r.get("disponibility", None)
            if disp is None:
                stocks = r.get("stocks") or []
                if isinstance(stocks, list):
                    disp = sum(_safe_float(s.get("quantity", 0)) for s in stocks)
                else:
                    disp = 0.0
            disp = _safe_float(disp)
            if abs(disp) < ZERO_EPS:
                disp = 0.0

            # total_cost puede venir (para el JSON), pero NO se usa en archivos
            tcost = _safe_float(r.get("total_cost", 0))

            # Guardar solo productos con disponibilidad > 0 real
            if disp > ZERO_EPS:
                productos.append({
                    "productName": str(name),
                    "disponibility": disp,
                    "total_cost": tcost,
                })

        page += 1

    # 4) Resumen mínimo (el JSON mantiene costo_total; los archivos NO lo muestran)
    disponibilidad_total = sum(_safe_float(p["disponibility"]) for p in productos)
    costo_total = sum(_safe_float(p["total_cost"]) for p in productos)

    payload = {
        "status": "ok",
        "resumen": {
            "items": len(productos),
            "disponibilidad_total": disponibilidad_total,
            "costo_total": costo_total,
        },
        "productos": productos,
    }

    # 5) Envío opcional por correo (nunca usar el correo del usuario logueado por defecto)
    if enviar_por_correo:
        if not destinatario:
            raise HTTPException(status_code=400, detail="destinatario es obligatorio cuando enviar_por_correo=true")

        try:
            if formato == "pdf":
                data_bytes, filename, mime = _generar_pdf_sin_costos(productos, payload)
            else:
                data_bytes, filename, mime = _generar_excel_sin_costos(productos, payload)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"No se pudo generar el archivo: {e}")

        try:
            enviar_correo(
                to_email=destinatario,
                subject="Totalizar inventario",
                body_text="Adjunto el reporte solicitado (sin costos, solo cantidades generales).",
                attachment=(data_bytes, filename, mime),
            )
            payload["archivo_enviado"] = {
                "nombre": filename,
                "formato": formato,
                "destinatario": destinatario,
                "fecha_envio": datetime.utcnow().isoformat() + "Z",
            }
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"No se pudo enviar el correo: {e}")

    return payload

def _generar_pdf_sin_costos(productos, payload):
    """
    Genera un PDF SIN costos (solo producto y disponibilidad + resumen de cantidades).
    Requiere REPORTLAB_AVAILABLE=True.
    """
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("ReportLab no está disponible para generar PDF.")
    import io
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h - 50

    c.drawString(40, y, "Totalizar Inventario (sin costos)"); y -= 20
    c.drawString(40, y, f"Items: {payload['resumen']['items']}"); y -= 20
    c.drawString(40, y, f"Disponibilidad Total: {payload['resumen']['disponibilidad_total']}"); y -= 30

    # Encabezado sin costos
    c.drawString(40, y, "Producto | Disponibilidad"); y -= 18

    # Limitar filas para evitar PDFs gigantes
    for p in productos[:1000]:
        line = f"{p['productName']} | {p['disponibility']}"
        c.drawString(40, y, line); y -= 14
        if y < 60:
            c.showPage(); y = h - 50

    c.save()
    buf.seek(0)
    return buf.read(), "totalizar-inventario.pdf", "application/pdf"


def _generar_excel_sin_costos(productos, payload):
    """
    Genera un Excel SIN costos:
      - Hoja 'Inventario' con columnas: Producto, Disponibilidad
      - Hoja 'Resumen' con Items y Disponibilidad Total (sin costo total)
    Requiere OPENPYXL_AVAILABLE=True.
    """
    if not OPENPYXL_AVAILABLE:
        raise RuntimeError("openpyxl no está disponible para generar Excel.")
    import io
    from openpyxl import Workbook

    wb = Workbook()

    # Hoja detalle
    ws = wb.active
    ws.title = "Inventario"
    ws.append(["Producto", "Disponibilidad"])
    for p in productos:
        ws.append([p["productName"], p["disponibility"]])

    # Hoja resumen (sin costos)
    ws2 = wb.create_sheet("Resumen")
    ws2.append(["Items", "Disponibilidad Total"])
    ws2.append([
        payload["resumen"]["items"],
        payload["resumen"]["disponibilidad_total"],
    ])

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio.read(), "totalizar-inventario.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


