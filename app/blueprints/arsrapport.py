"""
Arsrapport (yearly report) endpoints.

Thin route handlers — business logic belongs in data_access.py.
See ADR-0007 for blueprint conventions.
"""

from flask import Blueprint

arsrapport_bp = Blueprint("arsrapport", __name__, url_prefix="/api")
