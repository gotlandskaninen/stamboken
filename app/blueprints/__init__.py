"""
Flask Blueprint registration.

See ADR-0007 for blueprint conventions and migration plan.
"""

from .admin import admin_bp
from .arsrapport import arsrapport_bp
from .audit import audit_bp
from .breeding import breeding_bp
from .breeding_v2 import breeding_v2_bp
from .bunny_v2 import bunny_v2_bp
from .certificates import certificates_bp
from .herd_tracking import herd_tracking_bp
from .individual_v2_create import individual_v2_create_bp
from .individuals import individuals_bp
from .member_applications import member_applications_bp
from .members import members_bp
from .memberships import memberships_bp
from .pedigree import pedigree_bp
from .testbreed_v2 import testbreed_v2_bp
from .tokens import tokens_bp
from .uploads import uploads_bp


def register_blueprints(app):
    """Register all domain blueprints with the Flask app."""
    app.register_blueprint(admin_bp)
    app.register_blueprint(arsrapport_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(breeding_bp)
    app.register_blueprint(breeding_v2_bp)
    app.register_blueprint(bunny_v2_bp)
    app.register_blueprint(certificates_bp)
    app.register_blueprint(herd_tracking_bp)
    app.register_blueprint(individual_v2_create_bp)
    app.register_blueprint(individuals_bp)
    app.register_blueprint(member_applications_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(memberships_bp)
    app.register_blueprint(pedigree_bp)
    app.register_blueprint(testbreed_v2_bp)
    app.register_blueprint(tokens_bp)
    app.register_blueprint(uploads_bp)
