"""Utility helpers for caching, pagination and other common tasks."""

# app/utils/__init__.py

# Re-export helpers centrales para que "from app.utils import ..." funcione en todo el proyecto.

# user_context
try:
    from .context import user_context  # si está en utils/context.py
except Exception:
    try:
        from .user_context import user_context  # si está en utils/user_context.py
    except Exception:
        # fallback: dict vacío; el service devolverá 403 si no hay sesión
        user_context = {}  # type: ignore

# normalizar_rango
try:
    from .dates import normalizar_rango  # si está en utils/dates.py
except Exception:
    try:
        from .time_utils import normalizar_rango  # alternativa común
    except Exception:
        # fallback mínimo (respeta 00:01–23:59)
        from datetime import datetime, time
        def normalizar_rango(fi: datetime, ff: datetime):
            inicio = datetime.combine(fi.date(), time(0, 1))
            fin = datetime.combine(ff.date(), time(23, 59))
            return (
                inicio.strftime("%Y-%m-%d %H:%M"),
                fin.strftime("%Y-%m-%d %H:%M"),
            )

# get_base_url / get_auth_headers (si no estaban re-exportados)
try:
    from .headers import get_base_url, get_auth_headers
except Exception:
    from .helpers import get_base_url, get_auth_headers  # fallback típico
