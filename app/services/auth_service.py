"""
services/auth_service.py
------------------------

Business logic for user authentication and business selection. These
functions orchestrate calls to Tecopos to authenticate a user and
initialise session context. They use the shared HTTP client for
outbound requests and update the global user context accordingly.
"""

from __future__ import annotations

from typing import Any, Dict
from fastapi import HTTPException

from app.clients.http_client import HTTPClient
from app.core.auth import get_base_url, get_origin_url, build_auth_headers
from app.core.context import set_user_context, get_user_context
from app.schemas.auth import LoginData, SeleccionNegocio


def login_user(data: LoginData, http_client: HTTPClient) -> Dict[str, Any]:
    """Authenticate the user with Tecopos and store session context.

    This function mirrors the behaviour of the original ``/login-tecopos``
    endpoint. It performs three calls: login, user info and branches.
    On success the user context is stored in memory and a response
    indicating whether business selection is required is returned.

    :param data: login credentials and region
    :param http_client: shared HTTP client
    :raises HTTPException: if authentication fails
    :return: response payload
    """
    username = data.usuario.strip().lower()
    region = data.region
    base_url = get_base_url(region)
    origin = get_origin_url(region)

    login_url = f"{base_url}/api/v1/security/login"
    userinfo_url = f"{base_url}/api/v1/security/user"
    branches_url = f"{base_url}/api/v1/administration/my-branches"

    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": origin,
        "Referer": f"{origin}/",
        "x-app-origin": "Tecopos-Admin",
        "User-Agent": "Mozilla/5.0",
    }

    # 🔹 LOGIN CON username
    res = http_client.request("POST", login_url, headers=headers, json={
        "username": username,
        "password": data.password,
    })  # CHANGED: use http_client for pooling & timeout
    if res.status_code != 200:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    token = res.json().get("token")
    if not token:
        raise HTTPException(status_code=500, detail="Token no proporcionado en respuesta de login")

    # include token for subsequent calls
    headers["Authorization"] = f"Bearer {token}"

    # 🔹 OBTENER businessId REAL
    info_res = http_client.request("GET", userinfo_url, headers=headers)
    if info_res.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudo obtener la información del usuario")
    business_id = info_res.json().get("businessId")
    if not business_id:
        raise HTTPException(status_code=500, detail="No se pudo obtener businessId del usuario")

    # store context
    context = {
        "token": token,
        "businessId": business_id,
        "region": region,
    }
    # 🔹 VERIFICAR SUCURSALES
    branches_res = http_client.request("GET", branches_url, headers=headers)
    if branches_res.status_code != 200:
        raise HTTPException(status_code=500, detail="Error al obtener las sucursales del usuario")
    branches = branches_res.json()

    if not branches:
        # single branch – set context and return
        set_user_context(username, context)
        return {
            "status": "ok",
            "mensaje": "Login exitoso. Usando negocio principal.",
            "businessId": business_id,
        }

    # multiple branches – store available options
    context["negocios"] = {b["name"]: b["id"] for b in branches if "name" in b and "id" in b}
    set_user_context(username, context)
    return {
        "status": "seleccion-necesaria",
        "mensaje": "Selecciona un negocio para continuar",
        "negocios_disponibles": list(context["negocios"].keys()),
    }


def seleccionar_negocio(data: SeleccionNegocio, http_client: HTTPClient) -> Dict[str, Any]:
    """Select a specific business for the authenticated user.

    This function looks up the user's available businesses and updates
    the session context with the chosen business ID. It returns a
    confirmation response or raises an error if the business is not
    found.

    :param data: selection request
    :param http_client: shared HTTP client (unused here but kept for consistency)
    :raises HTTPException: if the user is not authenticated or the business is invalid
    :return: response payload
    """
    username = data.usuario.strip().lower()
    negocio_nombre = data.nombre_negocio.strip().lower()
    ctx = get_user_context(username)
    if not ctx:
        raise HTTPException(status_code=401, detail="Sesión no iniciada o expirada")

    region = ctx["region"]
    token = ctx["token"]
    base_url = get_base_url(region)
    origin = get_origin_url(region)

    # refresh branches – although context may already have them
    branches_url = f"{base_url}/api/v1/administration/my-branches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": origin,
        "Referer": f"{origin}/",
        "x-app-origin": "Tecopos-Admin",
        "User-Agent": "Mozilla/5.0",
    }
    res = http_client.request("GET", branches_url, headers=headers)
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudieron obtener los negocios del usuario")
    negocios = res.json()

    negocio = next((n for n in negocios if n["name"].strip().lower() == negocio_nombre), None)
    if not negocio:
        nombres_disponibles = [n["name"] for n in negocios]
        raise HTTPException(status_code=404, detail=f"No se encontró el negocio “{data.nombre_negocio}”. Opciones: {', '.join(nombres_disponibles)}")

    # update businessId
    ctx["businessId"] = negocio["id"]
    set_user_context(username, ctx)
    return {
        "status": "ok",
        "mensaje": f"Negocio “{negocio['name']}” seleccionado correctamente",
        "businessId": negocio["id"],
    }