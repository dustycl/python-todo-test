import pytest

from app.db import get_db


def extract_csrf(response):
    """Extract CSRF token from a response's HTML."""
    text = response.data.decode()
    marker = 'name="csrf_token" value="'
    start = text.find(marker) + len(marker)
    end = text.find('"', start)
    return text[start:end]


def get_csrf_token(client):
    """Fetch the login page to establish a session and get a CSRF token."""
    response = client.get("/auth/login")
    return extract_csrf(response)


def register(client, username="testuser", password="password123", confirm=None):
    """Helper to register a user with CSRF token."""
    csrf = get_csrf_token(client)
    return client.post("/auth/register", data={
        "csrf_token": csrf,
        "username": username,
        "password": password,
        "confirm": confirm or password,
    }, follow_redirects=True)


def login(client, username="testuser", password="password123"):
    """Helper to log in a user with CSRF token."""
    csrf = get_csrf_token(client)
    return client.post("/auth/login", data={
        "csrf_token": csrf,
        "username": username,
        "password": password,
    }, follow_redirects=True)


# --- Registration tests ---

def test_register_page_loads(client):
    response = client.get("/auth/register")
    assert response.status_code == 200
    assert b"Register" in response.data


def test_register_success(client):
    response = register(client)
    assert b"Registration successful" in response.data


def test_register_duplicate_username(client):
    register(client, username="alice")
    response = register(client, username="alice")
    assert b"already taken" in response.data


def test_register_empty_username(client):
    response = register(client, username="")
    assert b"Username is required" in response.data


def test_register_short_username(client):
    response = register(client, username="ab")
    assert b"between 3 and 30" in response.data


def test_register_non_alphanumeric_username(client):
    response = register(client, username="bad user!")
    assert b"alphanumeric" in response.data


def test_register_empty_password(client):
    response = register(client, password="")
    assert b"Password is required" in response.data


def test_register_short_password(client):
    response = register(client, password="short")
    assert b"at least 8 characters" in response.data


def test_register_password_mismatch(client):
    response = register(client, password="password123", confirm="password456")
    assert b"do not match" in response.data


# --- Login tests ---

def test_login_page_loads(client):
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert b"Log In" in response.data


def test_login_success(client):
    register(client)
    response = login(client)
    assert response.status_code == 200
    # After login, we should be on the todo list page
    assert b"Todo" in response.data


def test_login_wrong_password(client):
    register(client)
    response = login(client, password="wrongpassword")
    assert b"Invalid username or password" in response.data


def test_login_nonexistent_user(client):
    response = login(client, username="nobody")
    assert b"Invalid username or password" in response.data


# --- Logout tests ---

def test_logout(client):
    register(client)
    login(client)
    # Get CSRF token from the session cookie
    with client.session_transaction() as sess:
        csrf = sess["csrf_token"]
    response = client.post("/auth/logout", data={
        "csrf_token": csrf,
    }, follow_redirects=True)
    assert b"logged out" in response.data


# --- Access control tests ---

def test_unauthenticated_redirect(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_authenticated_register_redirects(client):
    register(client)
    login(client)
    response = client.get("/auth/register")
    assert response.status_code == 302


def test_authenticated_login_redirects(client):
    register(client)
    login(client)
    response = client.get("/auth/login")
    assert response.status_code == 302


# --- CSRF tests ---

def test_post_without_csrf_fails(client):
    response = client.post("/auth/login", data={
        "username": "test",
        "password": "test",
    })
    assert response.status_code == 400


def test_post_with_wrong_csrf_fails(client):
    response = client.post("/auth/login", data={
        "csrf_token": "wrong-token",
        "username": "test",
        "password": "test",
    })
    assert response.status_code == 400
