import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__, url_prefix="/auth")


class User(UserMixin):
    """Simple user class for flask-login integration."""

    def __init__(self, id, username):
        self.id = id
        self.username = username


def init_login_manager(app):
    """Configure flask-login's LoginManager on the app."""
    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        db = get_db()
        row = db.execute(
            "SELECT id, username FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return None
        return User(row["id"], row["username"])


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
            db = get_db()
            try:
                db.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, generate_password_hash(password)),
                )
                db.commit()
            except db.IntegrityError:
                error = f"Username '{username}' is already taken."
            except Exception:
                logger.error("Failed to register user: %s", username, exc_info=True)
                error = "An error occurred during registration."
            else:
                logger.info("User registered: %s", username)
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
            row = db.execute(
                "SELECT id, username, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()
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
