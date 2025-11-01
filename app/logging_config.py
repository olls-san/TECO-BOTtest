"""
logging_config.py
------------------

This module defines a shared logging configuration and utilities for
structured logging throughout the Tecopos API wrapper.  It uses
Python's built‑in ``logging`` module rather than ``print`` so that
log output can be captured by standard logging handlers or external
systems such as ELK, Grafana or Datadog.  Messages are serialised as
JSON to make them easier to parse downstream.

To use this module, import ``logger`` and call its methods instead
of ``logging.info`` directly.  The ``log_call`` decorator can be
applied to functions to record entry and exit points at the DEBUG
level without leaking sensitive information such as tokens or
passwords.
"""

from __future__ import annotations

import json
import logging
import sys
from functools import wraps
from typing import Any, Callable, Dict

# -----------------------------------------------------------------------------
# Configure global logging
# -----------------------------------------------------------------------------

# Set up the root logger once.  We direct log output to stdout and format
# messages with a timestamp, log level and the raw message.  The message
# itself should be a JSON string so downstream consumers can parse it easily.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# Expose a module level logger.  Code elsewhere can import this and log
# messages without repeatedly instantiating new Logger instances.
logger = logging.getLogger("tecopos")


def _sanitize(obj: Any) -> Any:
    """Recursively sanitise objects for logging.

    The goal of this helper is to prevent sensitive information such as
    authentication tokens, passwords or binary payloads from ending up in
    the logs.  Dictionaries will have keys containing 'token', 'password'
    or 'secret' removed.  Lists and tuples are processed element‑wise.  All
    other objects are returned unchanged.

    Parameters
    ----------
    obj : Any
        Arbitrary Python object to sanitise.

    Returns
    -------
    Any
        A sanitised representation of the input suitable for JSON serialisation.
    """
    # Avoid logging file contents or byte strings directly
    if isinstance(obj, (bytes, bytearray)):
        return f"<binary {len(obj)} bytes>"
    if isinstance(obj, dict):
        clean: Dict[str, Any] = {}
        for k, v in obj.items():
            if any(keyword in str(k).lower() for keyword in ("token", "password", "secret")):
                continue
            clean[k] = _sanitize(v)
        return clean
    if isinstance(obj, (list, tuple)):
        return [_sanitize(i) for i in obj]
    # For objects with a dict representation (e.g. Pydantic models), attempt to
    # use that for logging.  If conversion fails just return the repr.
    try:
        if hasattr(obj, "dict"):
            return _sanitize(obj.dict())  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        return json.loads(json.dumps(obj))  # ensure JSON serialisable
    except Exception:
        return str(obj)


def log_call(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to log entry and exit of functions.

    This decorator logs a DEBUG level message before a function is executed
    and another after it returns.  The messages include the function name
    and a sanitised snapshot of the arguments and return value.  Sensitive
    information is stripped via the ``_sanitize`` helper.  Use this to wrap
    service functions and internal helpers to aid debugging without
    polluting INFO level logs.

    Examples
    --------

    >>> @log_call
    ... def add(a, b):
    ...     return a + b
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Wrapper function that logs entry and exit of the wrapped callable.

        The wrapper emits a ``call_start`` event prior to invoking the decorated
        function and a ``call_end`` event afterwards.  All arguments and the
        return value are passed through the ``_sanitize`` helper to strip
        sensitive information.  Any errors during logging are silently
        ignored so as not to impact application behaviour.
        """
        try:
            args_repr = _sanitize(args)
            kwargs_repr = _sanitize(kwargs)
            logger.debug(json.dumps({
                "event": "call_start",
                "function": func.__name__,
                "args": args_repr,
                "kwargs": kwargs_repr,
            }))
        except Exception:
            # If sanitisation or logging fails, still proceed with the call
            logger.debug(json.dumps({"event": "call_start", "function": func.__name__}))
        # Invoke the actual function
        result = func(*args, **kwargs)
        try:
            result_repr = _sanitize(result)
            logger.debug(json.dumps({
                "event": "call_end",
                "function": func.__name__,
                "result": result_repr,
            }))
        except Exception:
            logger.debug(json.dumps({"event": "call_end", "function": func.__name__}))
        return result

    # Copy the signature of the wrapped function so FastAPI and other
    # introspection tools see the original parameters and annotations.
    try:
        import inspect  # imported here to avoid a global dependency
        wrapper.__signature__ = inspect.signature(func)
    except Exception:
        pass

    # Merge the global namespace of the wrapped function into the wrapper's
    # globals.  Without this, annotations defined in the original module (e.g.
    # Pydantic models like ``LoginData``) may not be resolvable when the
    # wrapper is inspected by FastAPI.  See https://errors.pydantic.dev/2.8/u/undefined-annotation
    try:
        wrapper.__globals__.update(func.__globals__)
    except Exception:
        pass

    return wrapper


def log_http_request(method: str, url: str, *, headers: Dict[str, Any] | None = None,
                     params: Dict[str, Any] | None = None, json_body: Dict[str, Any] | None = None,
                     status: int | None = None, duration_ms: float | None = None) -> None:
    """Log an outbound HTTP request at DEBUG level.

    This helper centralises HTTP request logging so that tokens are
    automatically removed from headers and only high‑level information
    (method, URL, status and duration) is recorded.  It should be
    invoked by the HTTP client wrapper before and after performing
    requests.

    Parameters
    ----------
    method : str
        The HTTP method (GET, POST, etc.)
    url : str
        The URL being requested.
    headers : dict, optional
        Request headers.  Sensitive keys are removed.
    params : dict, optional
        Query parameters for GET requests.
    json_body : dict, optional
        JSON payload for non‑GET requests.
    status : int, optional
        Response status code (log end only).
    duration_ms : float, optional
        Time taken in milliseconds (log end only).
    """
    data: Dict[str, Any] = {
        "event": "http_request",
        "method": method,
        "url": url,
    }
    if headers is not None:
        data["headers"] = {k: v for k, v in headers.items() if k.lower() not in {"authorization", "x-app-businessid"}}
    if params:
        data["params"] = params
    if json_body:
        data["json"] = _sanitize(json_body)
    if status is not None:
        data["status"] = status
    if duration_ms is not None:
        data["duration_ms"] = round(duration_ms, 2)
    logger.debug(json.dumps(data))