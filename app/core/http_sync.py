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

import requests

# Default timeouts for requests: (connect timeout, read timeout)
DEFAULT_TIMEOUT: Tuple[float, float] = (10.0, 30.0)

# HTTP status codes that should trigger a retry
RETRY_STATUS = {429, 502, 503, 504}

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
    while True:
        resp = requests.request(method=method, url=url, headers=headers, params=params, json=json, timeout=timeout)
        if resp.status_code in RETRY_STATUS and attempt < retries:
            attempt += 1
            time.sleep(backoff_base * (2 ** (attempt - 1)))
            continue
        return resp