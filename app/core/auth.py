"""
core/auth.py
-------------

Utility functions for building authenticated requests to Tecopos.

These helpers centralise construction of the base URLs and HTTP
headers required to call Tecopos APIs. They encapsulate knowledge
about region‑specific domains and ensure that sensitive information
(such as bearer tokens) is not inadvertently logged elsewhere in the
application. Use these functions in services when making requests.
"""

from __future__ import annotations

from typing import Dict
from fastapi import HTTPException


def get_origin_url(region: str) -> str:
    """Return the web origin for a given Tecopos region.

    The origin is used in the HTTP ``Origin`` and ``Referer`` headers
    when performing authenticated calls. The region parameter is
    normalised to lower‑case and stripped of surrounding whitespace.

    :param region: human‑friendly region identifier (e.g. ``apidev``, ``api1``)
    :raises HTTPException: if the region is not supported
    :return: the origin URL (without trailing slash)
    """
    region = region.lower().strip()
    if region == "apidev":
        return "https://admindev.tecopos.com"
    if region == "api1":
        return "https://admin.tecopos.com"
    # api0 – api4 map to the same admin domain
    if region in [f"api{i}" for i in range(5)] or region == "api0":
        return "https://admin.tecopos.com"
    raise HTTPException(status_code=400, detail="Región inválida")


def get_base_url(region: str) -> str:
    """Return the API base URL for a given Tecopos region.

    The returned URL does not include a trailing slash. This helper is
    used throughout the application to build endpoint URLs. Region
    values are normalised to lower‑case. If the region is not
    recognised an HTTP error is raised.

    :param region: region name (e.g. ``apidev`` or ``api1``)
    :raises HTTPException: if the region is invalid
    :return: the base API URL
    """
    region = region.lower().strip()
    if region == "apidev":
        return "https://apidev.tecopos.com"
    if region == "api1":
        return "https://api.tecopos.com"
    # handle api0..api4
    if region in [f"api{i}" for i in range(5)] or region == "api0":
        return f"https://{region}.tecopos.com"
    raise HTTPException(status_code=400, detail="Región inválida")


def build_auth_headers(token: str, business_id: int, region: str) -> Dict[str, str]:
    """Create a dictionary of HTTP headers required for an authenticated call.

    The token is included as a Bearer token and the business ID is
    supplied via the ``x-app-businessid`` header. Origin information is
    derived from the region. A static user agent is used. Additional
    headers can be provided by the caller and will override any
    automatically generated values.

    :param token: the JWT or session token for the authenticated user
    :param business_id: the business identifier returned by Tecopos
    :param region: the region in which the call is being made
    :return: a dictionary of headers suitable for use with httpx
    """
    origin = get_origin_url(region)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": origin,
        "Referer": f"{origin}/",
        "x-app-businessid": str(business_id),
        "x-app-origin": "Tecopos-Admin",
        "User-Agent": "Mozilla/5.0",
    }