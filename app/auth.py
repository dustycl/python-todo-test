import logging
import secrets

import psycopg2
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .email import send_password_reset_email, send_welcome_email
from . import posthog_client

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.before_app_request
def require_profile_completion():
    if not current_user.is_authenticated:
        return
    if request.endpoint in ("auth.complete_profile", "auth.logout", "auth.forgot_password", "auth.reset_password", "static"):
        return
    if not current_user.profile_complete:
        return redirect(url_for("auth.complete_profile"))


class User(UserMixin):
    """Simple user class for flask-login integration."""

    def __init__(self, id, username, email=None, first_name=None, last_name=None, is_admin=False):
        self.id = id
        self.username = username
        self.email = email
        self.first_name = first_name
        self.last_name = last_name
        self.is_admin = is_admin

    @property
    def display_name(self):
        if self.first_name:
            return self.first_name
        if self.username:
            return self.username
        if self.email:
            return self.email.split("@")[0]
        return "User"

    @property
    def profile_complete(self):
        return self.email is not None


def init_login_manager(app):
    """Configure flask-login's LoginManager on the app."""
    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.login_message = None
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "SELECT id, username, email, first_name, last_name, is_admin "
            "FROM users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return User(
            row["id"], row["username"], row["email"],
            row["first_name"], row["last_name"], row["is_admin"],
        )


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("todos.list_todos"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        error = None
        if not email:
            error = "Email is required."
        elif "@" not in email or "." not in email.split("@")[-1]:
            error = "Please enter a valid email address."
        elif len(email) > 254:
            error = "Email must be 254 characters or less."
        elif not first_name:
            error = "First name is required."
        elif len(first_name) > 100:
            error = "First name must be 100 characters or less."
        elif not last_name:
            error = "Last name is required."
        elif len(last_name) > 100:
            error = "Last name must be 100 characters or less."
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
                    "INSERT INTO users (email, first_name, last_name, password_hash, is_admin) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (email, first_name, last_name, generate_password_hash(password), is_admin),
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
                error = "An account with this email already exists."
            except Exception:
                db.rollback()
                logger.error("Failed to register user: %s", email, exc_info=True)
                error = "An error occurred during registration."
            else:
                logger.info("User registered: %s (admin=%s)", email, is_admin)
                send_welcome_email(email, first_name)
                user = User(new_user_id, None, email, first_name, last_name, is_admin)
                posthog_client.capture(new_user_id, "user_signed_up", {"email": email})
                login_user(user)
                flash("Welcome to Todooly!", "success")
                return redirect(url_for("todos.list_todos"))

        flash(error, "error")

    return render_template("auth/register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("todos.list_todos"))

    if request.method == "POST":
        identifier = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        try:
            db = get_db()
            cur = db.cursor()
            # Try email first, fall back to username for legacy users
            if "@" in identifier:
                cur.execute(
                    "SELECT id, username, email, first_name, last_name, password_hash, is_admin "
                    "FROM users WHERE email = %s",
                    (identifier.lower(),),
                )
            else:
                cur.execute(
                    "SELECT id, username, email, first_name, last_name, password_hash, is_admin "
                    "FROM users WHERE username = %s",
                    (identifier,),
                )
            row = cur.fetchone()
        except Exception:
            logger.error(
                "Database error during login for: %s", identifier, exc_info=True
            )
            flash("An error occurred during login.", "error")
            return render_template("auth/login.html")

        if row is None or not check_password_hash(row["password_hash"], password):
            logger.warning("Failed login attempt for: %s", identifier)
            flash("Invalid email or password.", "error")
        else:
            user = User(
                row["id"], row["username"], row["email"],
                row["first_name"], row["last_name"], row["is_admin"],
            )
            posthog_client.capture(user.id, "user_logged_in")
            login_user(user)
            logger.info("User logged in: %s (id=%s)", identifier, user.id)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("todos.list_todos"))

    return render_template("auth/login.html")


@bp.route("/complete-profile", methods=["GET", "POST"])
@login_required
def complete_profile():
    if current_user.profile_complete:
        return redirect(url_for("todos.list_todos"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()

        error = None
        if not email:
            error = "Email is required."
        elif "@" not in email or "." not in email.split("@")[-1]:
            error = "Please enter a valid email address."
        elif len(email) > 254:
            error = "Email must be 254 characters or less."
        elif not first_name:
            error = "First name is required."
        elif len(first_name) > 100:
            error = "First name must be 100 characters or less."
        elif not last_name:
            error = "Last name is required."
        elif len(last_name) > 100:
            error = "Last name must be 100 characters or less."

        if error is None:
            db = get_db()
            try:
                cur = db.cursor()
                cur.execute(
                    "UPDATE users SET email = %s, first_name = %s, last_name = %s "
                    "WHERE id = %s",
                    (email, first_name, last_name, current_user.id),
                )
                db.commit()
            except psycopg2.IntegrityError:
                db.rollback()
                error = "This email is already in use."
            except Exception:
                db.rollback()
                error = "An error occurred. Please try again."
            else:
                current_user.email = email
                current_user.first_name = first_name
                current_user.last_name = last_name
                flash("Profile completed successfully!", "success")
                return redirect(url_for("todos.list_todos"))

        flash(error, "error")

    return render_template("auth/complete_profile.html")


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("todos.list_todos"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        if email and "@" in email:
            db = get_db()
            cur = db.cursor()
            cur.execute("SELECT id, first_name FROM users WHERE email = %s", (email,))
            user = cur.fetchone()

            if user:
                # Clean up expired tokens for this user
                cur.execute(
                    "DELETE FROM password_reset_tokens "
                    "WHERE user_id = %s AND expires_at < NOW()",
                    (user["id"],),
                )
                token = secrets.token_urlsafe(32)
                cur.execute(
                    "INSERT INTO password_reset_tokens (user_id, token, expires_at) "
                    "VALUES (%s, %s, NOW() + INTERVAL '1 hour')",
                    (user["id"], token),
                )
                db.commit()
                reset_url = url_for("auth.reset_password", token=token, _external=True)
                send_password_reset_email(email, user["first_name"] or "there", reset_url)
                logger.info("Password reset requested for user id=%s", user["id"])
            else:
                logger.info("Password reset requested for unknown email: %s", email)

        # Always show same message to prevent email enumeration
        flash("If an account exists for that email, a reset link has been sent.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("todos.list_todos"))

    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT id, user_id FROM password_reset_tokens "
        "WHERE token = %s AND expires_at > NOW() AND used_at IS NULL",
        (token,),
    )
    token_row = cur.fetchone()

    if token_row is None:
        flash("This reset link is invalid or has expired. Please request a new one.", "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

        error = None
        if not new_password:
            error = "Password is required."
        elif len(new_password) < 8:
            error = "Password must be at least 8 characters."
        elif new_password != confirm:
            error = "Passwords do not match."

        if error is None:
            from werkzeug.security import generate_password_hash
            # Re-validate token still valid (race condition guard)
            cur.execute(
                "SELECT id FROM password_reset_tokens "
                "WHERE token = %s AND expires_at > NOW() AND used_at IS NULL",
                (token,),
            )
            if cur.fetchone() is None:
                flash("This reset link is invalid or has expired.", "error")
                return redirect(url_for("auth.forgot_password"))

            cur.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (generate_password_hash(new_password), token_row["user_id"]),
            )
            cur.execute(
                "UPDATE password_reset_tokens SET used_at = NOW() WHERE token = %s",
                (token,),
            )
            # Invalidate any other unused tokens for this user
            cur.execute(
                "DELETE FROM password_reset_tokens "
                "WHERE user_id = %s AND used_at IS NULL AND token != %s",
                (token_row["user_id"], token),
            )
            db.commit()
            logger.info("Password reset completed for user id=%s", token_row["user_id"])
            flash("Your password has been reset. Please log in.", "success")
            return redirect(url_for("auth.login"))

        flash(error, "error")

    return render_template("auth/reset_password.html", token=token)


@bp.route("/logout", methods=["POST"])
def logout():
    logger.info("User logged out: %s", current_user.display_name)
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))
