import functools
import logging
import secrets

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .db import get_db

logger = logging.getLogger(__name__)

bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    """Decorator that requires the current user to be an admin."""

    @functools.wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)

    return decorated


@bp.route("/")
@admin_required
def dashboard():
    db = get_db()
    cur = db.cursor()

    cur.execute("SELECT COUNT(*) AS total FROM users")
    total_users = cur.fetchone()["total"]

    cur.execute(
        "SELECT COUNT(*) AS recent FROM users "
        "WHERE created_at >= NOW() - INTERVAL '30 days'"
    )
    recent_signups = cur.fetchone()["recent"]

    cur.execute(
        "SELECT u.id, u.username, u.created_at, u.is_admin, "
        "COUNT(t.id) AS todo_count "
        "FROM users u "
        "LEFT JOIN todos t ON t.user_id = u.id AND t.deleted_at IS NULL "
        "GROUP BY u.id "
        "ORDER BY u.created_at DESC"
    )
    users = cur.fetchall()

    # Active (unused) invites
    cur.execute(
        "SELECT i.code, i.created_at, u.username AS created_by_username "
        "FROM admin_invites i "
        "JOIN users u ON u.id = i.created_by "
        "WHERE i.used_by IS NULL "
        "ORDER BY i.created_at DESC"
    )
    active_invites = cur.fetchall()

    # Used invites
    cur.execute(
        "SELECT i.code, i.created_at, i.used_at, "
        "c.username AS created_by_username, "
        "u.username AS used_by_username "
        "FROM admin_invites i "
        "JOIN users c ON c.id = i.created_by "
        "JOIN users u ON u.id = i.used_by "
        "WHERE i.used_by IS NOT NULL "
        "ORDER BY i.used_at DESC"
    )
    used_invites = cur.fetchall()

    return render_template(
        "admin/dashboard.html",
        total_users=total_users,
        recent_signups=recent_signups,
        users=users,
        active_invites=active_invites,
        used_invites=used_invites,
    )


@bp.route("/invites", methods=["POST"])
@admin_required
def create_invite():
    code = secrets.token_urlsafe(32)
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute(
            "INSERT INTO admin_invites (code, created_by) VALUES (%s, %s)",
            (code, current_user.id),
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.error("Failed to create admin invite", exc_info=True)
        flash("Failed to create invite.", "error")
        return redirect(url_for("admin.dashboard"))

    invite_url = url_for("auth.register", invite=code, _external=True)
    flash(f'Invite created: <code>{invite_url}</code>', "success")
    logger.info(
        "Admin invite created by %s (id=%s)", current_user.username, current_user.id
    )
    return redirect(url_for("admin.dashboard"))
