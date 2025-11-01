"""
Synchronous HTTP client wrapper with retries and timeouts for Tecopos.

Drop-in replacement for direct ``requests.*`` calls. It provides sane
defaults such as connection/read timeouts and exponential backoff on
transient errors like 429 (Too Many Requests) and 5xx responses.

Usage example:

    from app.core.http_sync import teco_request
    resp = teco_request("GET", url, headers=headers, params={"page": 1})
"""

from __future__ import annotations

import time
from typing import Dict, Any, Optional, Tuple
import httpx
from fastapi import HTTPException
import requests
import json
import time

# Import logging helpers to record outbound requests.  These
# functions remove sensitive information from headers and serialise
# messages as JSON.  See app/logging_config.py for details.
from app.logging_config import log_http_request, logger

# Default timeouts for requests: (connect timeout, read timeout)
DEFAULT_TIMEOUT: Tuple[float, float] = (10.0, 30.0)

# HTTP status codes that should trigger a retry
RETRY_STATUS = {429, 502, 503, 504}


# Cliente HTTP singleton para inyección con Depends(get_http_client)
_client: Optional[httpx.Client] = None

def get_http_client() -> httpx.Client:
    """
    Proveedor de cliente HTTP síncrono (inyección FastAPI).
    Usa pool y http2; timeouts razonables para servicios externos (Tecopos).
    """
    global _client
    if _client is None:
        _client = httpx.Client(
            http2=True,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=40),
            verify=True,
        )
    return _client




def teco_request(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
    retries: int = 2,
    backoff_base: float = 0.5,
) -> requests.Response:
    """
    Perform an HTTP request with automatic retries and timeouts.

    Parameters
    ----------
    method : str
        The HTTP method (e.g. ``"GET"``, ``"POST"``, etc).
    url : str
        The absolute URL to request.
    headers : dict
        HTTP headers to include in the request.
    params : dict, optional
        Query string parameters for GET requests.
    json : dict, optional
        JSON payload for POST/PUT/PATCH requests.
    timeout : tuple, optional
        A (connect_timeout, read_timeout) tuple in seconds.
    retries : int, optional
        The maximum number of retry attempts on transient errors.
    backoff_base : float, optional
        Base delay in seconds used for exponential backoff.

    Returns
    -------
    requests.Response
        The final HTTP response.
    """
    attempt = 0
    # Ensure we do not leak sensitive headers
    safe_headers = {k: v for k, v in headers.items() if k.lower() not in {"authorization", "x-app-businessid"}}
    start_time = time.time()
    # Log the request at debug level before sending
    log_http_request(method.upper(), url, headers=safe_headers, params=params, json_body=json)
    while True:
        try:
            resp = requests.request(method=method, url=url, headers=headers, params=params, json=json, timeout=timeout)
        except Exception as exc:
            # Log the exception
            duration_ms = (time.time() - start_time) * 1000
            logger.error(json.dumps({
                "event": "http_error",
                "method": method.upper(),
                "url": url,
                "detail": str(exc),
            }), exc_info=True)
            log_http_request(method.upper(), url, headers=safe_headers, params=params, json_body=json, status=None, duration_ms=duration_ms)
            raise
        # Check if retry is needed
        if resp.status_code in RETRY_STATUS and attempt < retries:
            attempt += 1
            time.sleep(backoff_base * (2 ** (attempt - 1)))
            continue
        # Log completion
        duration_ms = (time.time() - start_time) * 1000
        log_http_request(method.upper(), url, headers=safe_headers, params=params, json_body=json, status=resp.status_code, duration_ms=duration_ms)
        return resp
