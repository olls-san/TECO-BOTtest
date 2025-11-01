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
from app.logging_config import logger, log_call
import json
from app.core.auth import get_base_url, get_origin_url, build_auth_headers
from app.core.context import set_user_context, get_user_context
from app.schemas.auth import LoginData, SeleccionNegocio


@log_call
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
    # Iniciar proceso de login
    username = data.usuario.strip().lower()
    region = data.region
    # Registramos la intención de login a nivel INFO para trazabilidad
    try:
        logger.info(json.dumps({
            "event": "login_start",
            "usuario": username,
            "region": region,
            "detalle": "Inicio de autenticación del usuario"
        }))
    except Exception:
        pass
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
    try:
        res = http_client.request("POST", login_url, headers=headers, json={
            "username": username,
            "password": data.password,
        })  # CHANGED: use http_client for pooling & timeout
    except Exception as e:
        # error network-level
        logger.error(json.dumps({
            "event": "login_error",
            "usuario": username,
            "detalle": str(e),
        }), exc_info=True)
        raise
    if res.status_code != 200:
        logger.warning(json.dumps({
            "event": "login_failed",
            "usuario": username,
            "status_code": res.status_code,
            "detalle": res.text,
        }))
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    token = res.json().get("token")
    if not token:
        logger.error(json.dumps({
            "event": "login_error",
            "usuario": username,
            "detalle": "Token no proporcionado en respuesta de login",
        }))
        raise HTTPException(status_code=500, detail="Token no proporcionado en respuesta de login")

    # include token for subsequent calls
    headers["Authorization"] = f"Bearer {token}"

    # 🔹 OBTENER businessId REAL
    info_res = http_client.request("GET", userinfo_url, headers=headers)
    if info_res.status_code != 200:
        logger.error(json.dumps({
            "event": "login_error",
            "usuario": username,
            "detalle": "No se pudo obtener la información del usuario",
        }))
        raise HTTPException(status_code=500, detail="No se pudo obtener la información del usuario")
    business_id = info_res.json().get("businessId")
    if not business_id:
        logger.error(json.dumps({
            "event": "login_error",
            "usuario": username,
            "detalle": "No se pudo obtener businessId del usuario",
        }))
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
        logger.error(json.dumps({
            "event": "login_error",
            "usuario": username,
            "detalle": "Error al obtener las sucursales del usuario",
        }))
        raise HTTPException(status_code=500, detail="Error al obtener las sucursales del usuario")
    branches = branches_res.json()

    if not branches:
        # single branch – set context and return
        set_user_context(username, context)
        # Logging de éxito de login con sucursal única
        logger.info(json.dumps({
            "event": "login_success",
            "usuario": username,
            "region": region,
            "businessId": business_id,
            "detalle": "Login exitoso. Usando negocio principal."
        }))
        return {
            "status": "ok",
            "mensaje": "Login exitoso. Usando negocio principal.",
            "businessId": business_id,
        }

    # multiple branches – store available options
    context["negocios"] = {b["name"]: b["id"] for b in branches if "name" in b and "id" in b}
    set_user_context(username, context)
    # Logging de selección necesaria
    logger.info(json.dumps({
        "event": "login_selection",
        "usuario": username,
        "region": region,
        "negocios_disponibles": list(context["negocios"].keys()),
    }))
    return {
        "status": "seleccion-necesaria",
        "mensaje": "Selecciona un negocio para continuar",
        "negocios_disponibles": list(context["negocios"].keys()),
    }


@log_call
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
        logger.warning(json.dumps({
            "event": "seleccionar_negocio",
            "usuario": username,
            "detalle": "Sesión no iniciada o expirada",
        }))
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
        logger.error(json.dumps({
            "event": "seleccionar_negocio_error",
            "usuario": username,
            "detalle": "No se pudieron obtener los negocios del usuario",
        }))
        raise HTTPException(status_code=500, detail="No se pudieron obtener los negocios del usuario")
    negocios = res.json()

    negocio = next((n for n in negocios if n["name"].strip().lower() == negocio_nombre), None)
    if not negocio:
        nombres_disponibles = [n["name"] for n in negocios]
        logger.warning(json.dumps({
            "event": "seleccionar_negocio_no_encontrado",
            "usuario": username,
            "solicitado": data.nombre_negocio,
            "disponibles": nombres_disponibles,
        }))
        raise HTTPException(status_code=404, detail=f"No se encontró el negocio “{data.nombre_negocio}”. Opciones: {', '.join(nombres_disponibles)}")

    # update businessId
    ctx["businessId"] = negocio["id"]
    set_user_context(username, ctx)
    # Logging de selección exitosa
    logger.info(json.dumps({
        "event": "seleccionar_negocio_exito",
        "usuario": username,
        "negocio": negocio.get("name"),
        "businessId": negocio.get("id"),
    }))
    return {
        "status": "ok",
        "mensaje": f"Negocio “{negocio['name']}” seleccionado correctamente",
        "businessId": negocio["id"],
    }