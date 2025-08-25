"""
schemas/auth.py
----------------

Pydantic models related to authentication and session selection. The
field names and default values mirror those of the original monolithic
service. These schemas are used for request bodies and response
validation in the ``auth`` routes and services.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class LoginData(BaseModel):
    usuario: str
    password: str
    region: str = "apidev"


class SeleccionNegocio(BaseModel):
    usuario: str
    nombre_negocio: str = Field(alias="negocio")

    model_config = {
        "populate_by_name": True  # allow population by field name or alias
    }