"""
LangSmith tracing helpers.

The integration is optional: when LANGSMITH_TRACING is disabled or the
langsmith package is not installed, these helpers become no-ops.
"""

import functools
import os
from contextlib import contextmanager
from typing import Any, Callable, Dict, Optional

from config import config


_ENV_CONFIGURED = False


def _configure_env() -> None:
    global _ENV_CONFIGURED
    if _ENV_CONFIGURED:
        return
    _ENV_CONFIGURED = True

    os.environ.setdefault("NO_PROXY", "api.smith.langchain.com")
    os.environ.setdefault("no_proxy", "api.smith.langchain.com")
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(key, "")
        if "127.0.0.1:2802" in value or "localhost:2802" in value:
            os.environ.pop(key, None)

    if config.LANGSMITH_TRACING:
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    if config.LANGSMITH_API_KEY:
        os.environ.setdefault("LANGSMITH_API_KEY", config.LANGSMITH_API_KEY)
    project = getattr(config, "LANGSMITH_PROJECT", None)
    if project:
        os.environ.setdefault("LANGSMITH_PROJECT", project)
    endpoint = getattr(config, "LANGSMITH_ENDPOINT", None)
    if endpoint:
        os.environ.setdefault("LANGSMITH_ENDPOINT", endpoint)


def is_enabled() -> bool:
    _configure_env()
    return bool(config.LANGSMITH_TRACING and config.LANGSMITH_API_KEY)


def traceable(name: Optional[str] = None, run_type: str = "chain", metadata: Optional[Dict[str, Any]] = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        if not is_enabled():
            return func
        try:
            from langsmith import traceable as langsmith_traceable
        except Exception:
            return func
        return langsmith_traceable(name=name or func.__name__, run_type=run_type, metadata=metadata)(func)

    return decorator


@contextmanager
def trace_context(name: str, run_type: str = "chain", inputs: Optional[Dict[str, Any]] = None, metadata: Optional[Dict[str, Any]] = None):
    if not is_enabled():
        yield None
        return
    try:
        from langsmith import tracing_context
    except Exception:
        yield None
        return
    with tracing_context(enabled=True, project_name=getattr(config, "LANGSMITH_PROJECT", None)):
        yield None


def mask_secret(value: Optional[str]) -> str:
    if not value:
        return "missing"
    return f"set:{len(value)}chars"
