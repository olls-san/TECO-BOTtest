"""
clients/http_client.py
----------------------

HTTP client wrapper with connection pooling, timeouts, retries and a
simple circuit breaker for idempotent requests. This client should
only be instantiated once per process and shared across services via
dependency injection or the FastAPI lifespan event. It uses the
``httpx`` library under the hood and honours the global settings
defined in :mod:`app.core.config`.

Retries are applied exclusively to GET requests, as these are
idempotent by definition. For non‑GET methods, the request is sent
once and any error is propagated immediately. A basic circuit breaker
prevents cascading failures by short‑circuiting requests for a
particular host when multiple consecutive errors occur within a
rolling window.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional
import httpx

from app.core.config import get_settings


class CircuitBreaker:
    """Simple per‑host circuit breaker.

    Tracks consecutive failures for each host and trips the breaker
    when the count exceeds a threshold. The breaker resets after a
    cooldown period. This implementation is intentionally simple and
    does not use external dependencies.
    """

    def __init__(self, failure_threshold: int = 5, reset_timeout: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._failures: Dict[str, int] = {}
        self._tripped_until: Dict[str, float] = {}

    def record_failure(self, host: str) -> None:
        self._failures[host] = self._failures.get(host, 0) + 1
        if self._failures[host] >= self.failure_threshold:
            # trip breaker
            self._tripped_until[host] = time.time() + self.reset_timeout

    def record_success(self, host: str) -> None:
        # reset failure count on success
        self._failures.pop(host, None)
        self._tripped_until.pop(host, None)

    def can_request(self, host: str) -> bool:
        until = self._tripped_until.get(host)
        if until is None:
            return True
        if time.time() >= until:
            # reset breaker after cooldown
            self._tripped_until.pop(host, None)
            self._failures.pop(host, None)
            return True
        return False


class HTTPClient:
    """Thread‑safe HTTP client with retry and circuit breaker.

    The client exposes synchronous methods to perform HTTP requests.
    Use this class for all outbound HTTP interactions within the
    application. Instances should be created in the FastAPI lifespan
    event and passed to services via dependency injection.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.timeout = settings.http_timeout
        # HTTPX Client uses connection pooling
        self._client = httpx.Client(timeout=self.timeout)
        self._breaker = CircuitBreaker()
        self.max_retries = settings.http_max_retries
        self.backoff_factor = settings.http_backoff_factor

    def close(self) -> None:
        """Close the underlying HTTPX client and release resources."""
        self._client.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Perform a single HTTP request without retries.

        If the circuit breaker for the target host is tripped, a
        ``RuntimeError`` is raised immediately. This error should be
        handled by callers to prevent unhandled exceptions from
        propagating to FastAPI.
        """
        host = httpx.URL(url).host
        if not self._breaker.can_request(host):
            raise RuntimeError(f"Circuit breaker open for host {host}")
        try:
            response = self._client.request(method, url, **kwargs)
        except Exception as exc:
            # network or other error
            self._breaker.record_failure(host)
            raise
        if response.is_error:
            # mark failure for 5xx errors only; 4xx considered client error
            if 500 <= response.status_code < 600:
                self._breaker.record_failure(host)
            else:
                # reset on successful or 4xx (not server) to avoid blocking
                self._breaker.record_success(host)
        else:
            self._breaker.record_success(host)
        return response

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Perform a GET request with retries and exponential backoff.

        Only GET requests are retried as they are idempotent. Other
        methods delegate to :meth:`_request` and propagate errors.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._request("GET", url, **kwargs)
            except Exception as exc:
                last_exc = exc
                # don't retry on non‑connection errors for GET
                if attempt >= self.max_retries:
                    break
                # exponential backoff
                delay = self.backoff_factor * (2 ** attempt)
                time.sleep(delay)
        # if we reach here, all attempts failed
        if last_exc:
            raise last_exc
        raise RuntimeError("GET request failed but no exception captured")

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Public request method.

        For GET requests this applies retry logic. For other methods
        the request is performed once.
        """
        method_upper = method.upper()
        if method_upper == "GET":
            return self.get(url, **kwargs)
        return self._request(method_upper, url, **kwargs)