"""Bounded retry with exponential backoff for outbound API calls.

Gmail and Gemini can return transient rate-limit / server errors (HTTP 429, 5xx,
or RESOURCE_EXHAUSTED). Without backoff, a scan that hits a 429 either fails the
whole run or, worse, gets retried by the caller in a tight loop. This helper
retries only *transient* failures, a bounded number of times, with exponential
backoff + jitter — and re-raises anything non-retryable immediately.
"""

import time
import random
import logging
from typing import Callable, TypeVar

T = TypeVar("T")

DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BASE_DELAY = 1.0     # seconds
DEFAULT_MAX_DELAY = 30.0     # seconds

# HTTP statuses worth retrying (rate limit + transient server errors).
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_RETRYABLE_TEXT = (
    "rate limit", "ratelimit", "resource_exhausted", "resource exhausted",
    "too many requests", "deadline", "unavailable", "temporarily",
)


def _http_status(exc: Exception):
    """Best-effort extraction of an HTTP status code from common client errors."""
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    if status is None:
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def is_retryable(exc: Exception) -> bool:
    """True for transient rate-limit / server errors, False for everything else."""
    if _http_status(exc) in _RETRYABLE_STATUS:
        return True
    msg = str(exc).lower()
    return any(tok in msg for tok in _RETRYABLE_TEXT)


def call_with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    what: str = "API call",
) -> T:
    """Calls `fn`, retrying transient failures with exponential backoff + jitter.

    Re-raises immediately on non-retryable errors or once attempts are exhausted.
    This is a blocking call (uses time.sleep); run it in a thread for async code.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — we re-raise non-retryable below
            if attempt >= max_attempts or not is_retryable(e):
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay += random.uniform(0, delay * 0.25)  # jitter to avoid thundering herd
            logging.warning(
                f"{what} transient failure (attempt {attempt}/{max_attempts}); "
                f"retrying in {delay:.1f}s: {e}"
            )
            time.sleep(delay)


def execute_with_retry(request, **kwargs):
    """Retry wrapper around a googleapiclient request's `.execute()`."""
    return call_with_retry(lambda: request.execute(), what="Gmail API", **kwargs)
