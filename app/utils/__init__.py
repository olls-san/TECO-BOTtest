# app/utils/__init__.py
"""
Exporta utilidades clave para que 'from app.utils import ...' funcione de forma estable,
aun si la estructura interna varía entre entornos.

Incluye fallbacks seguros (sin romper deploy) para:
- user_context
- normalizar_rango
- get_base_url
- get_auth_headers
- extraer_sabor
"""

from __future__ import annotations
from typing import Any, Dict
from datetime import datetime, time

# -----------------------------
# user_context
# -----------------------------
try:
    from .context import user_context  # p.ej. app/utils/context.py
except Exception:
    try:
        from .user_context import user_context  # p.ej. app/utils/user_context.py
    except Exception:
        # Fallback mínimo: dict en memoria. Si está vacío, los endpoints devolverán 403.
        user_context: Dict[str, Dict[str, Any]] = {}  # type: ignore

# -----------------------------
# normalizar_rango
# -----------------------------
def _default_normalizar_rango(fi: datetime, ff: datetime):
    inicio = datetime.combine(fi.date(), time(0, 1))
    fin = datetime.combine(ff.date(), time(23, 59))
    return (
        inicio.strftime("%Y-%m-%d %H:%M"),
        fin.strftime("%Y-%m-%d %H:%M"),
    )

try:
    # p.ej. app/utils/dates.py
    from .dates import normalizar_rango  # type: ignore
except Exception:
    try:
        # variantes comunes
        from .time_utils import normalizar_rango  # type: ignore
    except Exception:
        normalizar_rango = _default_normalizar_rango  # type: ignore

# -----------------------------
# get_base_url
# -----------------------------
def _default_get_base_url(region: str) -> str:
    mapping = {
        "apidev": "https://apidev.tecopos.com",
        "api0":   "https://api0.tecopos.com",
        "api1":   "https://api.tecopos.com",  # excepción obligatoria
        "api2":   "https://api2.tecopos.com",
        "api3":   "https://api3.tecopos.com",
        "api4":   "https://api4.tecopos.com",
    }
    return mapping.get(region, "https://apidev.tecopos.com")

try:
    # si tienes una implementación propia, la usamos
    from .headers import get_base_url  # type: ignore
except Exception:
    get_base_url = _default_get_base_url  # type: ignore

# -----------------------------
# get_auth_headers
# -----------------------------
def _default_get_auth_headers(token: str, businessId: int | str, region: str) -> Dict[str, str]:
    """
    Cabeceras estándar del proyecto. Evita dependencias a módulos que pueden no existir
    en builds minimalistas.
    """
    base = _default_get_base_url(region)
    # Por simplicidad y compatibilidad, usamos el admin global por defecto
    admin_origin = "https://admin.tecopos.com"
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": admin_origin,
        "Referer": admin_origin + "/",
        "x-app-businessid": str(businessId),
        "x-app-origin": "Tecopos-Admin",
        "User-Agent": "Mozilla/5.0",
    }

try:
    # si tienes una versión centralizada, úsala
    from .headers import get_auth_headers  # type: ignore
except Exception:
    get_auth_headers = _default_get_auth_headers  # type: ignore

# -----------------------------
# extraer_sabor (opcional en tu proyecto)
# -----------------------------
def _default_extraer_sabor(nombre: str | None) -> str | None:
    # Fallback inocuo: no infiere nada
    return None if not nombre else None

try:
    from .text import extraer_sabor  # type: ignore
except Exception:
    try:
        from .helpers import extraer_sabor  # type: ignore
    except Exception:
        extraer_sabor = _default_extraer_sabor  # type: ignore

__all__ = [
    "user_context",
    "normalizar_rango",
    "get_base_url",
    "get_auth_headers",
    "extraer_sabor",
]

