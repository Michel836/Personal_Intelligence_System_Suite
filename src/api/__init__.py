"""Opt-in local REST API (M019).

Starlette is imported lazily by :func:`create_app`; importing this package does
not require the API dependency, so the rest of the application keeps working
when it is absent.
"""
from __future__ import annotations

from .app import API_SCHEMA, API_VERSION, bind_warning, create_app, main

__all__ = ["create_app", "main", "API_VERSION", "API_SCHEMA", "bind_warning"]
