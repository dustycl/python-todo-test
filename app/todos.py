from flask import Blueprint, render_template
from flask_login import login_required

bp = Blueprint("todos", __name__)


@bp.route("/")
@login_required
def list_todos():
    """Placeholder -- full implementation in Phase 3."""
    return "Todo list (coming soon)"
