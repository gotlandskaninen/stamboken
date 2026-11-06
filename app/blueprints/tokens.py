"""
Token management endpoints.

Thin route handlers — business logic belongs in data_access.py.
See ADR-0007 for blueprint conventions.
"""

from flask import Blueprint

tokens_bp = Blueprint("tokens", __name__, url_prefix="/api")
