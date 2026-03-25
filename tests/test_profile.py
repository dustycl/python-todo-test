import pytest

from app.db import get_db
from tests.test_auth import extract_csrf, get_csrf_token, login, register


def settings_csrf(client):
    """Get CSRF token from settings page."""
    resp = client.get("/settings")
    return extract_csrf(resp)


# --- Settings page ---


def test_settings_requires_login(client):
    resp = client.get("/settings")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_settings_page_loads(client):
    register(client)
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert b"Profile" in resp.data
    assert b"Change Password" in resp.data


# --- Update profile ---


def test_update_profile_success(client, app):
    register(client)
    csrf = settings_csrf(client)
    resp = client.post(
        "/settings/profile",
        data={
            "csrf_token": csrf,
            "first_name": "Alice",
            "last_name": "Smith",
            "email": "alice@example.com",
        },
        follow_redirects=True,
    )
    assert b"Profile updated" in resp.data
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT first_name, email FROM users WHERE email = 'alice@example.com'")
        row = cur.fetchone()
        assert row is not None
        assert row["first_name"] == "Alice"


def test_update_profile_duplicate_email(client):
    register(client, email="first@example.com")
    # Log out before registering second user (register redirects if authenticated)
    csrf = settings_csrf(client)
    client.post("/auth/logout", data={"csrf_token": csrf})
    register(client, email="second@example.com")
    # second@example.com is now logged in; try to take first's email
    csrf = settings_csrf(client)
    resp = client.post(
        "/settings/profile",
        data={
            "csrf_token": csrf,
            "first_name": "Second",
            "last_name": "User",
            "email": "first@example.com",
        },
        follow_redirects=True,
    )
    assert b"already in use" in resp.data


def test_update_profile_invalid_email(client):
    register(client)
    csrf = settings_csrf(client)
    resp = client.post(
        "/settings/profile",
        data={
            "csrf_token": csrf,
            "first_name": "Test",
            "last_name": "User",
            "email": "not-an-email",
        },
        follow_redirects=True,
    )
    assert b"valid email" in resp.data


def test_update_profile_missing_name(client):
    register(client)
    csrf = settings_csrf(client)
    resp = client.post(
        "/settings/profile",
        data={
            "csrf_token": csrf,
            "first_name": "",
            "last_name": "User",
            "email": "test@example.com",
        },
        follow_redirects=True,
    )
    assert b"required" in resp.data


# --- Change password ---


def test_change_password_success(client):
    register(client, email="test@example.com", password="oldpassword")
    csrf = settings_csrf(client)
    resp = client.post(
        "/settings/password",
        data={
            "csrf_token": csrf,
            "current_password": "oldpassword",
            "new_password": "newpassword123",
            "confirm_password": "newpassword123",
        },
        follow_redirects=True,
    )
    assert b"Password changed" in resp.data
    # Log out (get csrf while still logged in) then log back in with new password
    csrf = settings_csrf(client)
    client.post("/auth/logout", data={"csrf_token": csrf})
    resp = login(client, email="test@example.com", password="newpassword123")
    assert resp.status_code == 200


def test_change_password_wrong_current(client):
    register(client)
    csrf = settings_csrf(client)
    resp = client.post(
        "/settings/password",
        data={
            "csrf_token": csrf,
            "current_password": "wrongpassword",
            "new_password": "newpassword123",
            "confirm_password": "newpassword123",
        },
        follow_redirects=True,
    )
    assert b"incorrect" in resp.data


def test_change_password_mismatch(client):
    register(client)
    csrf = settings_csrf(client)
    resp = client.post(
        "/settings/password",
        data={
            "csrf_token": csrf,
            "current_password": "password123",
            "new_password": "newpassword123",
            "confirm_password": "differentpassword",
        },
        follow_redirects=True,
    )
    assert b"do not match" in resp.data


def test_change_password_too_short(client):
    register(client)
    csrf = settings_csrf(client)
    resp = client.post(
        "/settings/password",
        data={
            "csrf_token": csrf,
            "current_password": "password123",
            "new_password": "short",
            "confirm_password": "short",
        },
        follow_redirects=True,
    )
    assert b"8 characters" in resp.data


# --- Forgot / reset password ---


def test_forgot_password_page_loads(client):
    resp = client.get("/auth/forgot-password")
    assert resp.status_code == 200
    assert b"Forgot Password" in resp.data


def test_forgot_password_unknown_email(client):
    """Unknown email should still show success message (no enumeration)."""
    csrf = get_csrf_token(client)
    resp = client.post(
        "/auth/forgot-password",
        data={"csrf_token": csrf, "email": "nobody@example.com"},
        follow_redirects=True,
    )
    assert b"reset link has been sent" in resp.data


def test_forgot_password_creates_token(client, app):
    register(client, email="test@example.com")
    # Log out first so we can hit the unauthenticated route
    csrf = settings_csrf(client)
    client.post("/auth/logout", data={"csrf_token": csrf})
    csrf = get_csrf_token(client)
    client.post(
        "/auth/forgot-password",
        data={"csrf_token": csrf, "email": "test@example.com"},
        follow_redirects=True,
    )
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "SELECT token FROM password_reset_tokens pt "
            "JOIN users u ON u.id = pt.user_id "
            "WHERE u.email = 'test@example.com'"
        )
        row = cur.fetchone()
        assert row is not None
        assert len(row["token"]) > 10


def _get_reset_token(app, email="test@example.com"):
    """Helper: fetch the latest valid reset token for a user from the DB."""
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "SELECT token FROM password_reset_tokens pt "
            "JOIN users u ON u.id = pt.user_id "
            "WHERE u.email = %s AND used_at IS NULL "
            "ORDER BY pt.created_at DESC LIMIT 1",
            (email,),
        )
        row = cur.fetchone()
        return row["token"] if row else None


def _request_reset(client, email="test@example.com"):
    """Helper: request a password reset for the given email (assumes user is logged in)."""
    # Get CSRF while logged in (settings page), then log out
    csrf = settings_csrf(client)
    client.post("/auth/logout", data={"csrf_token": csrf})
    # Now logged out - get fresh CSRF from login page
    csrf = get_csrf_token(client)
    client.post(
        "/auth/forgot-password",
        data={"csrf_token": csrf, "email": email},
        follow_redirects=True,
    )


def test_reset_password_invalid_token(client):
    resp = client.get("/auth/reset-password/badtoken", follow_redirects=True)
    assert b"invalid or has expired" in resp.data


def test_reset_password_success(client, app):
    register(client, email="test@example.com")
    _request_reset(client, "test@example.com")
    token = _get_reset_token(app, "test@example.com")
    assert token is not None

    csrf = get_csrf_token(client)
    resp = client.post(
        f"/auth/reset-password/{token}",
        data={
            "csrf_token": csrf,
            "new_password": "brandnewpass",
            "confirm_password": "brandnewpass",
        },
        follow_redirects=True,
    )
    assert b"Password has been reset" in resp.data or b"reset" in resp.data.lower()

    resp = login(client, email="test@example.com", password="brandnewpass")
    assert resp.status_code == 200


def test_reset_password_token_used_twice(client, app):
    register(client, email="test@example.com")
    _request_reset(client, "test@example.com")
    token = _get_reset_token(app, "test@example.com")

    csrf = get_csrf_token(client)
    client.post(
        f"/auth/reset-password/{token}",
        data={
            "csrf_token": csrf,
            "new_password": "brandnewpass",
            "confirm_password": "brandnewpass",
        },
        follow_redirects=True,
    )
    # Second use should fail
    csrf = get_csrf_token(client)
    resp = client.post(
        f"/auth/reset-password/{token}",
        data={
            "csrf_token": csrf,
            "new_password": "anothernewpass",
            "confirm_password": "anothernewpass",
        },
        follow_redirects=True,
    )
    assert b"invalid or has expired" in resp.data


def test_reset_password_expired_token(client, app):
    register(client, email="test@example.com")
    _request_reset(client, "test@example.com")
    token = _get_reset_token(app, "test@example.com")

    # Manually expire the token
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "UPDATE password_reset_tokens SET expires_at = NOW() - INTERVAL '1 hour' "
            "WHERE token = %s",
            (token,),
        )
        db.commit()

    resp = client.get(f"/auth/reset-password/{token}", follow_redirects=True)
    assert b"invalid or has expired" in resp.data


# --- Delete account ---


def test_delete_account_wrong_email(client):
    register(client, email="test@example.com")
    csrf = settings_csrf(client)
    resp = client.post(
        "/settings/delete-account",
        data={"csrf_token": csrf, "confirm_email": "wrong@example.com"},
        follow_redirects=True,
    )
    assert b"did not match" in resp.data


def test_delete_account_success(client, app):
    register(client, email="test@example.com")
    csrf = settings_csrf(client)
    resp = client.post(
        "/settings/delete-account",
        data={"csrf_token": csrf, "confirm_email": "test@example.com"},
        follow_redirects=True,
    )
    assert b"deleted" in resp.data
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT id FROM users WHERE email = 'test@example.com'")
        assert cur.fetchone() is None
