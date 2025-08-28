from __future__ import annotations

from typing import Any, Dict, Generator, List, Optional, Tuple
from fastapi import HTTPException

from app.core.http_sync import teco_request
from app.utils import get_base_url, get_auth_headers

import unicodedata



def _norm(s: str) -> str:
    # lower + sin acentos + espacios colapsados
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = " ".join(s.lower().split())
    return s

class RendimientoDescomposicionClient:
    def __init__(self, *, region: str, token: str, business_id: int):
        self.region = region
        self.token = token
        self.business_id = business_id
        self.base_url = get_base_url(region)
        self.headers = get_auth_headers(token, business_id, region)

    def list_stock_areas(self) -> List[Dict[str, Any]]:
        page = 1
        out: List[Dict[str, Any]] = []
        url = f"{self.base_url}/api/v1/administration/area"
        while True:
            resp = teco_request("GET", url, headers=self.headers, params={"page": page, "type": "STOCK"})
            if not (200 <= resp.status_code < 300):
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            data = resp.json()
            items = data if isinstance(data, list) else data.get("items") or []
            if not items:
                break
            for it in items:
                out.append({"id": it.get("id"), "name": it.get("name")})
            page += 1
        return out

    # NUEVO: candidatos por nombre (exacto/startswith/contains)
    def find_area_candidates(self, area_name: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        target = _norm(area_name)
        areas = self.list_stock_areas()
        normed = [({"id": a["id"], "name": a["name"], "_n": _norm(a["name"])}) for a in areas]

        # 1) exacto normalizado
        exact = [a for a in normed if a["_n"] == target]
        if exact:
            # match único si hay 1 exacto
            if len(exact) == 1:
                a = exact[0]
                return {"id": a["id"], "name": a["name"]}, []
            # si hay varios exactos (raro), tratarlos como candidatas
            cands = [{"id": a["id"], "label": a["name"]} for a in exact]
            return None, cands

        # 2) empieza por
        starts = [a for a in normed if a["_n"].startswith(target)]
        # 3) contiene
        contains = [a for a in normed if target and target in a["_n"]]

        # dedup conservando prioridad (startswith > contains)
        seen = set()
        ranked: List[Dict[str, Any]] = []
        for bucket in (starts, contains):
            for a in bucket:
                if a["id"] in seen:
                    continue
                seen.add(a["id"])
                ranked.append({"id": a["id"], "label": a["name"]})

        if len(ranked) == 1:
            # única candidata razonable → úsala
            only = ranked[0]
            return {"id": only["id"], "name": only["label"]}, []
        elif ranked:
            # ambiguo → devolver candidatas
            return None, ranked

        # 0 coincidencias
        return None, []

    def iter_parent_movements(
        self,
        *,
        area_id: int,
        date_from: str,
        date_to: str,
    ) -> Generator[List[Dict[str, Any]], None, None]:
        page = 1
        df = (date_from or "")[:10]
        dt = (date_to or "")[:10]
        base_params = {
            "areaId": area_id,
            "all_data": True,
            "dateFrom": df,
            "dateTo": dt,
            "operation": "OUT",
            "category": "DESCOMPOSITION",
        }
        url = f"{self.base_url}/api/v1/administration/movement"
        while True:
            params = dict(base_params); params["page"] = page
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
