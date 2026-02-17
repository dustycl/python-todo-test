import pytest

from app.db import get_db


def get_csrf(client):
    """Get CSRF token from the current session."""
    with client.session_transaction() as sess:
        return sess.get("csrf_token", "")


def register_and_login(client, username="testuser", password="password123"):
    """Register a user and log them in. Returns the CSRF token."""
    # GET login page to establish session with CSRF token
    client.get("/auth/login")
    csrf = get_csrf(client)

    # Register
    client.post("/auth/register", data={
        "csrf_token": csrf,
        "username": username,
        "password": password,
        "confirm": password,
    })

    # Login
    client.post("/auth/login", data={
        "csrf_token": csrf,
        "username": username,
        "password": password,
    })

    return csrf


def add_todo(client, title="Test todo", due_date=None):
    """Add a todo and return the CSRF token used."""
    csrf = get_csrf(client)
    data = {"csrf_token": csrf, "title": title}
    if due_date is not None:
        data["due_date"] = due_date
    client.post("/add", data=data, follow_redirects=True)
    return csrf


# --- List tests ---

def test_list_empty(client):
    register_and_login(client)
    response = client.get("/")
    assert response.status_code == 200
    assert b"No todos yet" in response.data


def test_list_shows_todos(client):
    register_and_login(client)
    add_todo(client, "Buy groceries")
    add_todo(client, "Walk the dog")
    response = client.get("/")
    assert b"Buy groceries" in response.data
    assert b"Walk the dog" in response.data


# --- Add tests ---

def test_add_todo(client):
    register_and_login(client)
    csrf = get_csrf(client)
    response = client.post("/add", data={
        "csrf_token": csrf,
        "title": "New todo",
    }, follow_redirects=True)
    assert b"Todo added" in response.data
    assert b"New todo" in response.data


def test_add_empty_title(client):
    register_and_login(client)
    csrf = get_csrf(client)
    response = client.post("/add", data={
        "csrf_token": csrf,
        "title": "   ",
    }, follow_redirects=True)
    assert b"Title is required" in response.data


def test_add_long_title(client):
    register_and_login(client)
    csrf = get_csrf(client)
    response = client.post("/add", data={
        "csrf_token": csrf,
        "title": "x" * 201,
    }, follow_redirects=True)
    assert b"200 characters or less" in response.data


# --- Toggle tests ---

def test_toggle_complete(client, app):
    register_and_login(client)
    add_todo(client, "Toggle me")

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT * FROM todos").fetchone()
        assert todo["completed"] == 0
        todo_id = todo["id"]

    csrf = get_csrf(client)
    client.post(f"/toggle/{todo_id}", data={"csrf_token": csrf})

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        assert todo["completed"] == 1


def test_toggle_uncomplete(client, app):
    register_and_login(client)
    add_todo(client, "Toggle me twice")

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT * FROM todos").fetchone()
        todo_id = todo["id"]

    csrf = get_csrf(client)
    # Complete
    client.post(f"/toggle/{todo_id}", data={"csrf_token": csrf})
    # Uncomplete
    client.post(f"/toggle/{todo_id}", data={"csrf_token": csrf})

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        assert todo["completed"] == 0


def test_toggle_nonexistent(client):
    register_and_login(client)
    csrf = get_csrf(client)
    response = client.post("/toggle/9999", data={"csrf_token": csrf})
    assert response.status_code == 404


# --- Edit tests ---

def test_edit_page_loads(client, app):
    register_and_login(client)
    add_todo(client, "Edit me")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    response = client.get(f"/edit/{todo_id}")
    assert response.status_code == 200
    assert b"Edit me" in response.data


def test_edit_updates_title(client, app):
    register_and_login(client)
    add_todo(client, "Old title")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    response = client.post(f"/edit/{todo_id}", data={
        "csrf_token": csrf,
        "title": "New title",
    }, follow_redirects=True)
    assert b"Todo updated" in response.data
    assert b"New title" in response.data


def test_edit_empty_title(client, app):
    register_and_login(client)
    add_todo(client, "Keep me")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    response = client.post(f"/edit/{todo_id}", data={
        "csrf_token": csrf,
        "title": "",
    }, follow_redirects=True)
    assert b"Title is required" in response.data


def test_edit_nonexistent(client):
    register_and_login(client)
    response = client.get("/edit/9999")
    assert response.status_code == 404


# --- Delete tests ---

def test_delete_todo(client, app):
    register_and_login(client)
    add_todo(client, "Delete me")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    response = client.post(f"/delete/{todo_id}", data={
        "csrf_token": csrf,
    }, follow_redirects=True)
    assert b"Todo deleted" in response.data

    with app.app_context():
        db = get_db()
        count = db.execute("SELECT COUNT(*) FROM todos").fetchone()[0]
        assert count == 0


def test_delete_nonexistent(client):
    register_and_login(client)
    csrf = get_csrf(client)
    response = client.post("/delete/9999", data={"csrf_token": csrf})
    assert response.status_code == 404


# --- Cross-user isolation tests ---

def test_user_cannot_see_other_users_todos(client, app):
    """User B should not see User A's todos."""
    register_and_login(client, username="alice")
    add_todo(client, "Alice's secret todo")

    # Log out alice, register and login bob
    csrf = get_csrf(client)
    client.post("/auth/logout", data={"csrf_token": csrf})
    register_and_login(client, username="bob")

    response = client.get("/")
    assert b"Alice" not in response.data
    assert b"No todos yet" in response.data


def test_user_cannot_toggle_other_users_todo(client, app):
    """User B should not be able to toggle User A's todo."""
    register_and_login(client, username="alice")
    add_todo(client, "Alice's todo")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    client.post("/auth/logout", data={"csrf_token": csrf})
    register_and_login(client, username="bob")

    csrf = get_csrf(client)
    response = client.post(f"/toggle/{todo_id}", data={"csrf_token": csrf})
    assert response.status_code == 404


def test_user_cannot_edit_other_users_todo(client, app):
    """User B should not be able to edit User A's todo."""
    register_and_login(client, username="alice")
    add_todo(client, "Alice's todo")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    client.post("/auth/logout", data={"csrf_token": csrf})
    register_and_login(client, username="bob")

    response = client.get(f"/edit/{todo_id}")
    assert response.status_code == 404


def test_user_cannot_delete_other_users_todo(client, app):
    """User B should not be able to delete User A's todo."""
    register_and_login(client, username="alice")
    add_todo(client, "Alice's todo")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    client.post("/auth/logout", data={"csrf_token": csrf})
    register_and_login(client, username="bob")

    csrf = get_csrf(client)
    response = client.post(f"/delete/{todo_id}", data={"csrf_token": csrf})
    assert response.status_code == 404

    # Verify Alice's todo is still there
    with app.app_context():
        db = get_db()
        count = db.execute("SELECT COUNT(*) FROM todos").fetchone()[0]
        assert count == 1


# --- Due date tests ---

def test_add_todo_with_due_date(client, app):
    register_and_login(client)
    add_todo(client, "Dated todo", due_date="2026-03-15")

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT * FROM todos").fetchone()
        assert todo["due_date"] == "2026-03-15"


def test_add_todo_without_due_date(client, app):
    register_and_login(client)
    add_todo(client, "No date todo")

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT * FROM todos").fetchone()
        assert todo["due_date"] is None


def test_add_todo_invalid_due_date(client):
    register_and_login(client)
    csrf = get_csrf(client)
    response = client.post("/add", data={
        "csrf_token": csrf,
        "title": "Bad date",
        "due_date": "not-a-date",
    }, follow_redirects=True)
    assert b"Invalid due date" in response.data


def test_edit_due_date(client, app):
    register_and_login(client)
    add_todo(client, "Change my date", due_date="2026-03-15")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    client.post(f"/edit/{todo_id}", data={
        "csrf_token": csrf,
        "title": "Change my date",
        "due_date": "2026-04-01",
    }, follow_redirects=True)

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        assert todo["due_date"] == "2026-04-01"


def test_edit_clear_due_date(client, app):
    register_and_login(client)
    add_todo(client, "Clear my date", due_date="2026-03-15")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    client.post(f"/edit/{todo_id}", data={
        "csrf_token": csrf,
        "title": "Clear my date",
        "due_date": "",
    }, follow_redirects=True)

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        assert todo["due_date"] is None


def test_list_sorts_by_due_date(client, app):
    register_and_login(client)
    add_todo(client, "No date", due_date=None)
    add_todo(client, "Later", due_date="2026-06-01")
    add_todo(client, "Sooner", due_date="2026-03-01")

    response = client.get("/")
    data = response.data.decode()
    # Dated todos come before undated; earlier date first
    assert data.index("Sooner") < data.index("Later") < data.index("No date")
