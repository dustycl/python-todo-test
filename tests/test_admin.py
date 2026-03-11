from app.db import get_db


def get_csrf(client):
    """Get CSRF token from the current session."""
    with client.session_transaction() as sess:
        return sess.get("csrf_token", "")


def register_and_login(client, username="testuser", password="password123"):
    """Register a user and log them in. Returns the CSRF token."""
    client.get("/auth/login")
    csrf = get_csrf(client)

    client.post(
        "/auth/register",
        data={
            "csrf_token": csrf,
            "username": username,
            "password": password,
            "confirm": password,
        },
    )

    client.post(
        "/auth/login",
        data={
            "csrf_token": csrf,
            "username": username,
            "password": password,
        },
    )

    return csrf


def make_admin(app, username):
    """Promote a user to admin in the database."""
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "UPDATE users SET is_admin = TRUE WHERE username = %s", (username,)
        )
        db.commit()


def test_non_admin_gets_403(client):
    """Regular users cannot access the admin dashboard."""
    register_and_login(client)
    resp = client.get("/admin/")
    assert resp.status_code == 403


def test_anonymous_redirects_to_login(client):
    """Anonymous users are redirected to login."""
    resp = client.get("/admin/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_admin_can_access_dashboard(app, client):
    """Admin users can access the dashboard."""
    register_and_login(client)
    make_admin(app, "testuser")
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert b"Admin Dashboard" in resp.data


def test_dashboard_shows_user_count(app, client):
    """Dashboard displays the correct total user count."""
    register_and_login(client, username="admin1")
    make_admin(app, "admin1")

    # Create a second user via a separate client
    client2 = app.test_client()
    register_and_login(client2, username="regular1")

    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert b"admin1" in resp.data
    assert b"regular1" in resp.data


def test_admin_link_visible_for_admins(app, client):
    """Admin nav link is visible only for admin users."""
    register_and_login(client)

    # Non-admin: no admin link
    resp = client.get("/")
    assert b"/admin/" not in resp.data

    # Promote and check again
    make_admin(app, "testuser")
    resp = client.get("/")
    assert b"/admin/" in resp.data


def create_invite(app, client):
    """Create an admin invite and return the invite code."""
    csrf = get_csrf(client)
    resp = client.post(
        "/admin/invites",
        data={"csrf_token": csrf},
        follow_redirects=True,
    )
    # Extract code from the flashed invite URL
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "SELECT code FROM admin_invites ORDER BY created_at DESC LIMIT 1"
        )
        return cur.fetchone()["code"]


def test_non_admin_cannot_create_invite(client):
    """Regular users cannot create invites."""
    register_and_login(client)
    csrf = get_csrf(client)
    resp = client.post("/admin/invites", data={"csrf_token": csrf})
    assert resp.status_code == 403


def test_admin_can_create_invite(app, client):
    """Admin users can generate invite codes."""
    register_and_login(client)
    make_admin(app, "testuser")
    code = create_invite(app, client)
    assert code is not None
    assert len(code) > 0


def test_invite_shows_on_dashboard(app, client):
    """Generated invites appear on the dashboard."""
    register_and_login(client)
    make_admin(app, "testuser")
    code = create_invite(app, client)

    resp = client.get("/admin/")
    assert code.encode() in resp.data


def test_register_with_valid_invite_creates_admin(app, client):
    """Registering with a valid invite code creates an admin user."""
    register_and_login(client, username="admin1")
    make_admin(app, "admin1")
    code = create_invite(app, client)

    # Register a new user with the invite code
    client2 = app.test_client()
    client2.get("/auth/login")
    csrf = get_csrf(client2)
    client2.post(
        f"/auth/register?invite={code}",
        data={
            "csrf_token": csrf,
            "username": "invitee",
            "password": "password123",
            "confirm": "password123",
        },
    )

    with app.app_context():
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT is_admin FROM users WHERE username = %s", ("invitee",))
        assert cur.fetchone()["is_admin"] is True


def test_invite_is_single_use(app, client):
    """An invite code can only be used once."""
    register_and_login(client, username="admin1")
    make_admin(app, "admin1")
    code = create_invite(app, client)

    # First use — should become admin
    client2 = app.test_client()
    client2.get("/auth/login")
    csrf2 = get_csrf(client2)
    client2.post(
        f"/auth/register?invite={code}",
        data={
            "csrf_token": csrf2,
            "username": "first",
            "password": "password123",
            "confirm": "password123",
        },
    )

    # Second use — same code, should NOT become admin
    client3 = app.test_client()
    client3.get("/auth/login")
    csrf3 = get_csrf(client3)
    client3.post(
        f"/auth/register?invite={code}",
        data={
            "csrf_token": csrf3,
            "username": "second",
            "password": "password123",
            "confirm": "password123",
        },
    )

    with app.app_context():
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT is_admin FROM users WHERE username = %s", ("first",))
        assert cur.fetchone()["is_admin"] is True
        cur.execute("SELECT is_admin FROM users WHERE username = %s", ("second",))
        assert cur.fetchone()["is_admin"] is False


def test_invalid_invite_code_creates_normal_user(app, client):
    """An invalid invite code results in a normal (non-admin) user."""
    client2 = app.test_client()
    client2.get("/auth/login")
    csrf = get_csrf(client2)
    client2.post(
        "/auth/register?invite=bogus_code_123",
        data={
            "csrf_token": csrf,
            "username": "normaluser",
            "password": "password123",
            "confirm": "password123",
        },
    )

    with app.app_context():
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT is_admin FROM users WHERE username = %s", ("normaluser",))
        assert cur.fetchone()["is_admin"] is False
