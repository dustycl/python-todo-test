import logging

import psycopg2
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__, url_prefix="/auth")


class User(UserMixin):
    """Simple user class for flask-login integration."""

    def __init__(self, id, username, is_admin=False):
        self.id = id
        self.username = username
        self.is_admin = is_admin


def init_login_manager(app):
    """Configure flask-login's LoginManager on the app."""
    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT id, username, is_admin FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return User(row["id"], row["username"], row["is_admin"])


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("todos.list_todos"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        error = None
        if not username:
            error = "Username is required."
        elif len(username) < 3 or len(username) > 30:
            error = "Username must be between 3 and 30 characters."
        elif not username.isalnum():
            error = "Username must be alphanumeric."
        elif not password:
            error = "Password is required."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirm:
            error = "Passwords do not match."

        if error is None:
            invite_code = request.args.get("invite")
            db = get_db()
            try:
                cur = db.cursor()

                # Check for valid invite code
                invite_row = None
                if invite_code:
                    cur.execute(
                        "SELECT id FROM admin_invites "
                        "WHERE code = %s AND used_by IS NULL",
                        (invite_code,),
                    )
                    invite_row = cur.fetchone()

                is_admin = invite_row is not None
                cur.execute(
                    "INSERT INTO users (username, password_hash, is_admin) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    (username, generate_password_hash(password), is_admin),
                )
                new_user_id = cur.fetchone()["id"]

                # Mark invite as used
                if invite_row:
                    cur.execute(
                        "UPDATE admin_invites SET used_by = %s, used_at = NOW() "
                        "WHERE id = %s",
                        (new_user_id, invite_row["id"]),
                    )

                db.commit()
            except psycopg2.IntegrityError:
                db.rollback()
                error = f"Username '{username}' is already taken."
            except Exception:
                db.rollback()
                logger.error("Failed to register user: %s", username, exc_info=True)
                error = "An error occurred during registration."
            else:
                logger.info("User registered: %s (admin=%s)", username, is_admin)
                flash("Registration successful. Please log in.", "success")
                return redirect(url_for("auth.login"))

        flash(error, "error")

    return render_template("auth/register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("todos.list_todos"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        try:
            db = get_db()
            cur = db.cursor()
            cur.execute(
                "SELECT id, username, password_hash FROM users WHERE username = %s",
                (username,),
            )
            row = cur.fetchone()
        except Exception:
            logger.error(
                "Database error during login for username: %s", username, exc_info=True
            )
            flash("An error occurred during login.", "error")
            return render_template("auth/login.html")

        if row is None or not check_password_hash(row["password_hash"], password):
            logger.warning("Failed login attempt for username: %s", username)
            flash("Invalid username or password.", "error")
        else:
            user = User(row["id"], row["username"])
            login_user(user)
            logger.info("User logged in: %s (id=%s)", user.username, user.id)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("todos.list_todos"))

    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    logger.info("User logged out: %s", current_user.username)
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))
