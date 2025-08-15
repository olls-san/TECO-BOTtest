"""
Authentication and business selection endpoints.

This module contains endpoints for user login and the selection of a
specific business to operate against.  By isolating these operations
into their own router, changes to authentication or business
selection logic can be made without impacting other parts of the
application.
"""

from __future__ import annotations

import requests
from fastapi import APIRouter, HTTPException

from .. import models
from ..utils import user_context, get_base_url, get_origin_url

router = APIRouter()


@router.post("/login-tecopos")
def login_tecopos(data: models.LoginData):
    """Authenticate a user against the Tecopos API and store their context.

    This endpoint performs a login against the Tecopos security API,
    retrieves the user's business ID, stores the authentication token
    and business context in memory, and returns the list of available
    branches (if any) for the user to choose from.
    """
    usuario = data.usuario.strip().lower()
    region = data.region
    base_url = get_base_url(region)
    origin = get_origin_url(region)
    login_url = f"{base_url}/api/v1/security/login"
    userinfo_url = f"{base_url}/api/v1/security/user"
    branches_url = f"{base_url}/api/v1/administration/my-branches"
    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": origin,
        "Referer": origin + "/",
        "x-app-origin": "Tecopos-Admin",
        "User-Agent": "Mozilla/5.0",
    }
    res = requests.post(login_url, headers=headers, json={"username": usuario, "password": data.password})
    if res.status_code != 200:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    token = res.json().get("token")
    headers["Authorization"] = f"Bearer {token}"
    info_res = requests.get(userinfo_url, headers=headers)
    if info_res.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudo obtener la información del usuario")
    business_id = info_res.json().get("businessId")
    if not token or not business_id:
        raise HTTPException(status_code=500, detail="No se pudo obtener token o businessId")
    # Store user context
    user_context[usuario] = {"token": token, "businessId": business_id, "region": region}
    branches_res = requests.get(branches_url, headers=headers)
    if branches_res.status_code != 200:
        raise HTTPException(status_code=500, detail="Error al obtener las sucursales del usuario")
    branches = branches_res.json()
    # If no branches, return success directly
    if not branches:
        return {
            "status": "ok",
            "mensaje": "Login exitoso. Usando negocio principal.",
            "businessId": business_id,
        }
    # Save available branches for later selection
    user_context[usuario]["negocios"] = {b["name"]: b["id"] for b in branches if "name" in b and "id" in b}
    return {
        "status": "seleccion-necesaria",
        "mensaje": "Selecciona un negocio para continuar",
        "negocios_disponibles": list(user_context[usuario]["negocios"].keys()),
    }


@router.post("/seleccionar-negocio")
def seleccionar_negocio(data: models.SeleccionNegocio):
    """Select a specific business to work with after login.

    This endpoint validates that the user has previously logged in,
    fetches the list of available branches from the Tecopos API, and
    stores the selected business ID in the in-memory context.
    """
    usuario = data.usuario.strip().lower()
    negocio_nombre = data.nombre_negocio.strip().lower()
    if usuario not in user_context:
        raise HTTPException(status_code=401, detail="Sesión no iniciada o expirada")
    token = user_context[usuario]["token"]
    region = user_context[usuario]["region"]
    base_url = get_base_url(region)
    origin = get_origin_url(region)
    branches_url = f"{base_url}/api/v1/administration/my-branches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": origin,
        "Referer": origin + "/",
        "x-app-origin": "Tecopos-Admin",
        "User-Agent": "Mozilla/5.0",
    }
    res = requests.get(branches_url, headers=headers)
    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="No se pudieron obtener los negocios del usuario")
    negocios = res.json()
    negocio = next((n for n in negocios if n["name"].strip().lower() == negocio_nombre), None)
    if not negocio:
        nombres_disponibles = [n["name"] for n in negocios]
        raise HTTPException(status_code=404, detail=f"No se encontró el negocio “{data.nombre_negocio}”. Opciones: {', '.join(nombres_disponibles)}")
    user_context[usuario]["businessId"] = negocio["id"]
    return {
        "status": "ok",
        "mensaje": f"Negocio “{negocio['name']}” seleccionado correctamente",
        "businessId": negocio["id"],
    }