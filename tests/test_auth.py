from werkzeug.security import generate_password_hash

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


def register(client, email="test@example.com", first_name="Test", last_name="User",
             password="password123", confirm=None):
    """Helper to register a user with CSRF token."""
    csrf = get_csrf_token(client)
    return client.post(
        "/auth/register",
        data={
            "csrf_token": csrf,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "password": password,
            "confirm": confirm or password,
        },
        follow_redirects=True,
    )


def login(client, email="test@example.com", password="password123"):
    """Helper to log in a user with CSRF token."""
    csrf = get_csrf_token(client)
    return client.post(
        "/auth/login",
        data={
            "csrf_token": csrf,
            "email": email,
            "password": password,
        },
        follow_redirects=True,
    )


def create_legacy_user(app, username="legacyuser", password="password123"):
    """Insert a user with username only (no email) to simulate pre-migration user."""
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (username, generate_password_hash(password)),
        )
        db.commit()


# --- Registration tests ---


def test_register_page_loads(client):
    response = client.get("/auth/register")
    assert response.status_code == 200
    assert b"Register" in response.data


def test_register_success(client):
    response = register(client)
    assert b"Registration successful" in response.data


def test_register_duplicate_email(client):
    register(client, email="alice@example.com")
    response = register(client, email="alice@example.com")
    assert b"already exists" in response.data


def test_register_empty_email(client):
    response = register(client, email="")
    assert b"Email is required" in response.data


def test_register_invalid_email(client):
    response = register(client, email="notanemail")
    assert b"valid email" in response.data


def test_register_empty_first_name(client):
    response = register(client, first_name="")
    assert b"First name is required" in response.data


def test_register_empty_last_name(client):
    response = register(client, last_name="")
    assert b"Last name is required" in response.data


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
    assert b"Invalid email or password" in response.data


def test_login_nonexistent_user(client):
    response = login(client, email="nobody@example.com")
    assert b"Invalid email or password" in response.data


def test_legacy_user_login_with_username(app, client):
    """Legacy users can still log in with their username."""
    create_legacy_user(app, username="olduser", password="password123")
    csrf = get_csrf_token(client)
    response = client.post(
        "/auth/login",
        data={
            "csrf_token": csrf,
            "email": "olduser",
            "password": "password123",
        },
        follow_redirects=True,
    )
    # Should be redirected to complete profile
    assert b"Complete Your Profile" in response.data


# --- Profile completion tests ---


def test_legacy_user_redirected_to_complete_profile(app, client):
    """Legacy users without email are redirected to complete their profile."""
    create_legacy_user(app)
    csrf = get_csrf_token(client)
    client.post(
        "/auth/login",
        data={
            "csrf_token": csrf,
            "email": "legacyuser",
            "password": "password123",
        },
    )
    response = client.get("/", follow_redirects=True)
    assert b"Complete Your Profile" in response.data


def test_complete_profile_success(app, client):
    """Legacy user can complete their profile with email and name."""
    create_legacy_user(app)
    csrf = get_csrf_token(client)
    client.post(
        "/auth/login",
        data={
            "csrf_token": csrf,
            "email": "legacyuser",
            "password": "password123",
        },
    )
    with client.session_transaction() as sess:
        csrf = sess["csrf_token"]
    response = client.post(
        "/auth/complete-profile",
        data={
            "csrf_token": csrf,
            "email": "legacy@example.com",
            "first_name": "Legacy",
            "last_name": "User",
        },
        follow_redirects=True,
    )
    assert b"Profile completed" in response.data


def test_complete_profile_duplicate_email(app, client):
    """Profile completion rejects an email already in use."""
    # Register a normal user with an email
    register(client, email="taken@example.com")

    # Create and log in a legacy user
    create_legacy_user(app)
    client2 = app.test_client()
    client2.get("/auth/login")
    with client2.session_transaction() as sess:
        csrf = sess["csrf_token"]
    client2.post(
        "/auth/login",
        data={
            "csrf_token": csrf,
            "email": "legacyuser",
            "password": "password123",
        },
    )
    with client2.session_transaction() as sess:
        csrf = sess["csrf_token"]
    response = client2.post(
        "/auth/complete-profile",
        data={
            "csrf_token": csrf,
            "email": "taken@example.com",
            "first_name": "Legacy",
            "last_name": "User",
        },
        follow_redirects=True,
    )
    assert b"already in use" in response.data


def test_complete_profile_missing_fields(app, client):
    """Profile completion validates required fields."""
    create_legacy_user(app)
    csrf = get_csrf_token(client)
    client.post(
        "/auth/login",
        data={
            "csrf_token": csrf,
            "email": "legacyuser",
            "password": "password123",
        },
    )
    with client.session_transaction() as sess:
        csrf = sess["csrf_token"]
    response = client.post(
        "/auth/complete-profile",
        data={
            "csrf_token": csrf,
            "email": "",
            "first_name": "",
            "last_name": "",
        },
        follow_redirects=True,
    )
    assert b"Email is required" in response.data


def test_completed_profile_not_redirected(client):
    """Users with a complete profile are not redirected to complete-profile."""
    register(client)
    login(client)
    response = client.get("/")
    assert response.status_code == 200
    assert b"Complete Your Profile" not in response.data


# --- Logout tests ---


def test_logout(client):
    register(client)
    login(client)
    # Get CSRF token from the session cookie
    with client.session_transaction() as sess:
        csrf = sess["csrf_token"]
    response = client.post(
        "/auth/logout",
        data={
            "csrf_token": csrf,
        },
        follow_redirects=True,
    )
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
    response = client.post(
        "/auth/login",
        data={
            "email": "test@example.com",
            "password": "test",
        },
    )
    assert response.status_code == 400


def test_post_with_wrong_csrf_fails(client):
    response = client.post(
        "/auth/login",
        data={
            "csrf_token": "wrong-token",
            "email": "test@example.com",
            "password": "test",
        },
    )
    assert response.status_code == 400
