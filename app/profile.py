import logging

import psycopg2
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from . import posthog_client
from .db import get_db

logger = logging.getLogger(__name__)

bp = Blueprint("profile", __name__, url_prefix="/settings")


@bp.route("")
@login_required
def settings():
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT id, email, first_name, last_name FROM users WHERE id = %s",
        (current_user.id,),
    )
    user = cur.fetchone()
    return render_template("profile/settings.html", user=user)


@bp.route("/profile", methods=["POST"])
@login_required
def update_profile():
    first_name = request.form.get("first_name", "").strip()
    last_name = request.form.get("last_name", "").strip()
    email = request.form.get("email", "").strip().lower()

    error = None
    if not first_name:
        error = "First name is required."
    elif len(first_name) > 100:
        error = "First name must be 100 characters or less."
    elif not last_name:
        error = "Last name is required."
    elif len(last_name) > 100:
        error = "Last name must be 100 characters or less."
    elif not email:
        error = "Email is required."
    elif "@" not in email or "." not in email.split("@")[-1]:
        error = "Please enter a valid email address."
    elif len(email) > 254:
        error = "Email must be 254 characters or less."

    if error is None:
        db = get_db()
        try:
            cur = db.cursor()
            cur.execute(
                "UPDATE users SET first_name = %s, last_name = %s, email = %s WHERE id = %s",
                (first_name, last_name, email, current_user.id),
            )
            db.commit()
        except psycopg2.IntegrityError:
            db.rollback()
            flash("That email is already in use by another account.", "error")
            return redirect(url_for("profile.settings") + "#profile")
        except Exception:
            db.rollback()
            logger.error("Failed to update profile for user id=%s", current_user.id, exc_info=True)
            flash("An error occurred. Please try again.", "error")
            return redirect(url_for("profile.settings") + "#profile")
        else:
            current_user.first_name = first_name
            current_user.last_name = last_name
            current_user.email = email
            posthog_client.capture(current_user.id, "profile_updated")
            flash("Profile updated successfully.", "success")
            return redirect(url_for("profile.settings") + "#profile")

    flash(error, "error")
    return redirect(url_for("profile.settings") + "#profile")


@bp.route("/password", methods=["POST"])
@login_required
def change_password():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT password_hash FROM users WHERE id = %s", (current_user.id,))
    row = cur.fetchone()

    error = None
    if not check_password_hash(row["password_hash"], current_password):
        error = "Current password is incorrect."
    elif not new_password:
        error = "New password is required."
    elif len(new_password) < 8:
        error = "New password must be at least 8 characters."
    elif new_password != confirm_password:
        error = "New passwords do not match."

    if error is None:
        try:
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (generate_password_hash(new_password), current_user.id),
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.error("Failed to change password for user id=%s", current_user.id, exc_info=True)
            flash("An error occurred. Please try again.", "error")
            return redirect(url_for("profile.settings") + "#password")
        else:
            posthog_client.capture(current_user.id, "password_changed")
            flash("Password changed successfully.", "success")
            return redirect(url_for("profile.settings") + "#password")

    flash(error, "error")
    return redirect(url_for("profile.settings") + "#password")


@bp.route("/delete-account", methods=["POST"])
@login_required
def delete_account():
    confirm_email = request.form.get("confirm_email", "").strip().lower()

    if confirm_email != (current_user.email or "").lower():
        flash("Email address did not match. Account was not deleted.", "error")
        return redirect(url_for("profile.settings") + "#danger")

    user_id = current_user.id
    posthog_client.capture(user_id, "account_deleted")

    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        db.commit()
    except Exception:
        db.rollback()
        logger.error("Failed to delete account for user id=%s", user_id, exc_info=True)
        flash("An error occurred. Please try again.", "error")
        return redirect(url_for("profile.settings") + "#danger")

    logout_user()
    flash("Your account has been permanently deleted.", "success")
    return redirect(url_for("auth.register"))
