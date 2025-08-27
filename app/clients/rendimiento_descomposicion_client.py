from __future__ import annotations

from typing import Any, Dict, Generator, List, Optional, Tuple
from fastapi import HTTPException

from app.core.http_sync import teco_request
from app.utils import get_base_url, get_auth_headers


class RendimientoDescomposicionClient:
    """
    Cliente para orquestar llamadas a Tecopos relacionadas con rendimiento de descomposición.
    Cumple con:
    - Headers centralizados (get_auth_headers)
    - Base URL por región (get_base_url)
    - Paginación explícita con ?page=
    - Propagación de errores HTTP
    """

    def __init__(self, *, region: str, token: str, business_id: int):
        self.region = region
        self.token = token
        self.business_id = business_id
        self.base_url = get_base_url(region)
        self.headers = get_auth_headers(token, business_id, region)

    # --------------------------
    # ÁREAS
    # --------------------------
    def resolve_area_by_name(self, area_name: str) -> Optional[Dict[str, Any]]:
        """
        Busca un área de tipo STOCK por nombre exacto.
        GET /api/v1/administration/area?page=N&type=STOCK

        Devuelve {"id": int, "name": str} o None si no existe.
        """
        page = 1
        while True:
            params = {"page": page, "type": "STOCK"}
            url = f"{self.base_url}/api/v1/administration/area"
            resp = teco_request("GET", url, headers=self.headers, params=params)
            if not (200 <= resp.status_code < 300):
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            data = resp.json()
            items = data if isinstance(data, list) else data.get("items") or []
            if not items:
                break
            for it in items:
                if (it.get("name") or "").strip() == area_name.strip():
                    return {"id": it.get("id"), "name": it.get("name")}
            page += 1
        return None

    # --------------------------
    # MOVIMIENTOS (PADRES)
    # --------------------------
    def iter_parent_movements(
        self,
        *,
        area_id: int,
        date_from: str,
        date_to: str,
    ) -> Generator[List[Dict[str, Any]], None, None]:
        """
        Itera páginas de movimientos padre OUT/DESCOMPOSITION de un rango.
        GET /api/v1/administration/movement?areaId=...&all_data=true&dateFrom=...&dateTo=...&operation=OUT&category=DESCOMPOSITION&page=X
        """
        page = 1
        base_params = {
            "areaId": area_id,
            "all_data": "true",
            "dateFrom": date_from,
            "dateTo": date_to,
            "operation": "OUT",
            "category": "DESCOMPOSITION",
        }
        url = f"{self.base_url}/api/v1/administration/movement"
        while True:
            params = dict(base_params)
            params["page"] = page
            resp = teco_request("GET", url, headers=self.headers, params=params)
            if not (200 <= resp.status_code < 300):
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            data = resp.json()
            items = data.get("items") if isinstance(data, dict) else None
            if not items:
                break
            yield items
            page += 1

    # --------------------------
    # DETALLE MOVIMIENTO
    # --------------------------
    def get_movement_detail(self, movement_id: int) -> Dict[str, Any]:
        """
        GET /api/v1/administration/movement/{movementId}
        """
        url = f"{self.base_url}/api/v1/administration/movement/{movement_id}"
        resp = teco_request("GET", url, headers=self.headers)
        if not (200 <= resp.status_code < 300):
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()
