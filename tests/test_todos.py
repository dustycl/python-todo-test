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


def add_todo(client, title="Test todo", due_date=None, tags=None, description=None):
    """Add a todo and return the CSRF token used."""
    csrf = get_csrf(client)
    data = {"csrf_token": csrf, "title": title}
    if due_date is not None:
        data["due_date"] = due_date
    if tags is not None:
        data["tags"] = tags
    if description is not None:
        data["description"] = description
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
    assert b"Undo" in response.data

    with app.app_context():
        db = get_db()
        # Row still exists but is soft-deleted
        todo = db.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        assert todo is not None
        assert todo["deleted_at"] is not None
        # Not visible in normal queries
        count = db.execute(
            "SELECT COUNT(*) FROM todos WHERE deleted_at IS NULL"
        ).fetchone()[0]
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


# --- Search tests ---

def test_search_by_keyword(client):
    """Search should return only todos matching the keyword."""
    register_and_login(client)
    add_todo(client, "Buy groceries")
    add_todo(client, "Walk the dog")
    add_todo(client, "Buy birthday present")

    response = client.get("/?q=Buy")
    data = response.data.decode()
    assert "Buy groceries" in data
    assert "Buy birthday present" in data
    assert "Walk the dog" not in data


def test_search_case_insensitive(client):
    """Search should be case-insensitive."""
    register_and_login(client)
    add_todo(client, "Buy Groceries")

    response = client.get("/?q=buy")
    assert b"Buy Groceries" in response.data


def test_search_empty_query_returns_all(client):
    """Empty search query should return all todos."""
    register_and_login(client)
    add_todo(client, "Todo one")
    add_todo(client, "Todo two")

    response = client.get("/?q=")
    assert b"Todo one" in response.data
    assert b"Todo two" in response.data


def test_search_no_results(client):
    """Search with no matches should show filtered empty state."""
    register_and_login(client)
    add_todo(client, "Buy groceries")

    response = client.get("/?q=nonexistent")
    assert b"Buy groceries" not in response.data
    assert b"No todos match your filters" in response.data


# --- Status filter tests ---

def test_filter_status_active(client, app):
    """Status=active should show only incomplete todos."""
    register_and_login(client)
    add_todo(client, "Active todo")
    add_todo(client, "Done todo")

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT id FROM todos WHERE title = 'Done todo'").fetchone()
        todo_id = todo["id"]

    csrf = get_csrf(client)
    client.post(f"/toggle/{todo_id}", data={"csrf_token": csrf})

    response = client.get("/?status=active")
    data = response.data.decode()
    assert "Active todo" in data
    assert "Done todo" not in data


def test_filter_status_completed(client, app):
    """Status=completed should show only completed todos."""
    register_and_login(client)
    add_todo(client, "Active todo")
    add_todo(client, "Done todo")

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT id FROM todos WHERE title = 'Done todo'").fetchone()
        todo_id = todo["id"]

    csrf = get_csrf(client)
    client.post(f"/toggle/{todo_id}", data={"csrf_token": csrf})

    response = client.get("/?status=completed")
    data = response.data.decode()
    assert "Done todo" in data
    assert "Active todo" not in data


# --- Due date filter tests ---

def test_filter_due_overdue(client):
    """Due=overdue should show only todos with past due dates."""
    register_and_login(client)
    add_todo(client, "Overdue task", due_date="2020-01-01")
    add_todo(client, "Future task", due_date="2099-12-31")
    add_todo(client, "No date task")

    response = client.get("/?due=overdue")
    data = response.data.decode()
    assert "Overdue task" in data
    assert "Future task" not in data
    assert "No date task" not in data


def test_filter_due_today(client):
    """Due=today should show only todos due today."""
    from datetime import date
    register_and_login(client)
    today_str = date.today().isoformat()
    add_todo(client, "Today task", due_date=today_str)
    add_todo(client, "Future task", due_date="2099-12-31")

    response = client.get("/?due=today")
    data = response.data.decode()
    assert "Today task" in data
    assert "Future task" not in data


def test_filter_due_week(client):
    """Due=week should show todos due within the next 7 days."""
    from datetime import date, timedelta
    register_and_login(client)
    today = date.today()
    add_todo(client, "This week task", due_date=(today + timedelta(days=3)).isoformat())
    add_todo(client, "Far future task", due_date="2099-12-31")
    add_todo(client, "Past task", due_date="2020-01-01")

    response = client.get("/?due=week")
    data = response.data.decode()
    assert "This week task" in data
    assert "Far future task" not in data
    assert "Past task" not in data


def test_filter_due_none(client):
    """Due=none should show only todos without a due date."""
    register_and_login(client)
    add_todo(client, "Has date", due_date="2026-06-01")
    add_todo(client, "No date todo")

    response = client.get("/?due=none")
    data = response.data.decode()
    assert "No date todo" in data
    assert "Has date" not in data


# --- Combined filter tests ---

def test_combined_search_and_status(client, app):
    """Search and status filter should work together."""
    register_and_login(client)
    add_todo(client, "Buy groceries")
    add_todo(client, "Buy present")

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT id FROM todos WHERE title = 'Buy groceries'").fetchone()
        todo_id = todo["id"]

    csrf = get_csrf(client)
    client.post(f"/toggle/{todo_id}", data={"csrf_token": csrf})

    response = client.get("/?q=Buy&status=active")
    data = response.data.decode()
    assert "Buy present" in data
    assert "Buy groceries" not in data


def test_invalid_filter_values_default_to_all(client):
    """Unknown filter values should behave like 'all'."""
    register_and_login(client)
    add_todo(client, "Some todo")

    response = client.get("/?status=bogus&due=invalid")
    assert b"Some todo" in response.data


def test_search_respects_user_isolation(client):
    """Search should never return another user's todos."""
    register_and_login(client, username="alice")
    add_todo(client, "Alice secret task")

    csrf = get_csrf(client)
    client.post("/auth/logout", data={"csrf_token": csrf})
    register_and_login(client, username="bob")
    add_todo(client, "Bob public task")

    response = client.get("/?q=secret")
    data = response.data.decode()
    assert "Alice" not in data
    assert "Bob" not in data


# --- Tag tests ---

def test_add_todo_with_tags(client, app):
    """Adding a todo with tags should store them."""
    register_and_login(client)
    add_todo(client, "Tagged todo", tags="work, personal")

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT id FROM todos").fetchone()
        tags = db.execute(
            "SELECT t.name FROM tags t JOIN todo_tags tt ON t.id = tt.tag_id "
            "WHERE tt.todo_id = ? ORDER BY t.name",
            (todo["id"],),
        ).fetchall()
        assert [r["name"] for r in tags] == ["personal", "work"]


def test_tags_display_on_list(client):
    """Tags should appear on the todo list page."""
    register_and_login(client)
    add_todo(client, "Tagged todo", tags="work, urgent")

    response = client.get("/")
    data = response.data.decode()
    assert "work" in data
    assert "urgent" in data


def test_filter_by_tag(client):
    """Filtering by tag should show only matching todos."""
    register_and_login(client)
    add_todo(client, "Work task", tags="work")
    add_todo(client, "Home task", tags="home")

    response = client.get("/?tag=work")
    data = response.data.decode()
    assert "Work task" in data
    assert "Home task" not in data


def test_edit_tags(client, app):
    """Editing a todo should update its tags."""
    register_and_login(client)
    add_todo(client, "Change tags", tags="old")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    client.post(f"/edit/{todo_id}", data={
        "csrf_token": csrf,
        "title": "Change tags",
        "tags": "new, updated",
    }, follow_redirects=True)

    with app.app_context():
        db = get_db()
        tags = db.execute(
            "SELECT t.name FROM tags t JOIN todo_tags tt ON t.id = tt.tag_id "
            "WHERE tt.todo_id = ? ORDER BY t.name",
            (todo_id,),
        ).fetchall()
        assert [r["name"] for r in tags] == ["new", "updated"]


def test_edit_clear_tags(client, app):
    """Editing with empty tags should remove all tags."""
    register_and_login(client)
    add_todo(client, "Remove tags", tags="old")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    client.post(f"/edit/{todo_id}", data={
        "csrf_token": csrf,
        "title": "Remove tags",
        "tags": "",
    }, follow_redirects=True)

    with app.app_context():
        db = get_db()
        count = db.execute(
            "SELECT COUNT(*) FROM todo_tags WHERE todo_id = ?", (todo_id,)
        ).fetchone()[0]
        assert count == 0


def test_delete_todo_preserves_tags(client, app):
    """Soft-deleting a todo should preserve its tag associations for restore."""
    register_and_login(client)
    add_todo(client, "Delete me", tags="cleanup")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    client.post(f"/delete/{todo_id}", data={"csrf_token": csrf}, follow_redirects=True)

    with app.app_context():
        db = get_db()
        count = db.execute(
            "SELECT COUNT(*) FROM todo_tags WHERE todo_id = ?", (todo_id,)
        ).fetchone()[0]
        assert count == 1


def test_duplicate_tags_deduplicated(client, app):
    """Duplicate tag names should be deduplicated."""
    register_and_login(client)
    add_todo(client, "Dupes", tags="work, work, WORK")

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT id FROM todos").fetchone()
        tags = db.execute(
            "SELECT t.name FROM tags t JOIN todo_tags tt ON t.id = tt.tag_id "
            "WHERE tt.todo_id = ?",
            (todo["id"],),
        ).fetchall()
        assert len(tags) == 1
        assert tags[0]["name"] == "work"


def test_empty_tags_ignored(client, app):
    """Empty or whitespace-only tags should be ignored."""
    register_and_login(client)
    add_todo(client, "Empty tags", tags=",  , ,valid")

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT id FROM todos").fetchone()
        tags = db.execute(
            "SELECT t.name FROM tags t JOIN todo_tags tt ON t.id = tt.tag_id "
            "WHERE tt.todo_id = ?",
            (todo["id"],),
        ).fetchall()
        assert len(tags) == 1
        assert tags[0]["name"] == "valid"


def test_cross_user_tag_isolation(client, app):
    """User B should not see User A's tags in the filter dropdown."""
    register_and_login(client, username="alice")
    add_todo(client, "Alice task", tags="secret-tag")

    csrf = get_csrf(client)
    client.post("/auth/logout", data={"csrf_token": csrf})
    register_and_login(client, username="bob")

    response = client.get("/")
    assert b"secret-tag" not in response.data


def test_edit_page_shows_current_tags(client, app):
    """The edit page should pre-populate the tags field."""
    register_and_login(client)
    add_todo(client, "Edit me", tags="work, urgent")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    response = client.get(f"/edit/{todo_id}")
    data = response.data.decode()
    assert "urgent" in data
    assert "work" in data


# --- Description tests ---


def test_add_todo_with_description(client, app):
    """Adding a todo with a description stores it in the database."""
    register_and_login(client)
    add_todo(client, "Described todo", description="Some details here")

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT * FROM todos").fetchone()
        assert todo["description"] == "Some details here"


def test_add_todo_without_description(client, app):
    """Adding a todo without a description stores NULL."""
    register_and_login(client)
    add_todo(client, "No description")

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT * FROM todos").fetchone()
        assert todo["description"] is None


def test_add_todo_long_description(client):
    """A description over 2000 characters is rejected."""
    register_and_login(client)
    response = client.post("/add", data={
        "csrf_token": get_csrf(client),
        "title": "Long desc",
        "description": "x" * 2001,
    }, follow_redirects=True)
    assert b"2000 characters or less" in response.data


def test_edit_description(client, app):
    """Editing a todo can update the description."""
    register_and_login(client)
    add_todo(client, "Edit desc", description="Original")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    client.post(f"/edit/{todo_id}", data={
        "csrf_token": csrf,
        "title": "Edit desc",
        "description": "Updated",
    }, follow_redirects=True)

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        assert todo["description"] == "Updated"


def test_edit_clear_description(client, app):
    """Editing a todo can clear the description."""
    register_and_login(client)
    add_todo(client, "Clear desc", description="Will be cleared")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    client.post(f"/edit/{todo_id}", data={
        "csrf_token": csrf,
        "title": "Clear desc",
        "description": "",
    }, follow_redirects=True)

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        assert todo["description"] is None


def test_description_displayed_on_list(client):
    """The description should appear on the todo list page."""
    register_and_login(client)
    add_todo(client, "Visible desc", description="Check this text")

    response = client.get("/")
    assert b"Check this text" in response.data


def test_edit_page_shows_current_description(client, app):
    """The edit page should pre-populate the description field."""
    register_and_login(client)
    add_todo(client, "Edit page desc", description="Pre-filled text")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    response = client.get(f"/edit/{todo_id}")
    assert b"Pre-filled text" in response.data


# --- Soft delete / restore tests ---


def test_restore_todo(client, app):
    """Restoring a soft-deleted todo should make it visible again."""
    register_and_login(client)
    add_todo(client, "Restore me")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    client.post(f"/delete/{todo_id}", data={"csrf_token": csrf})

    response = client.post(f"/restore/{todo_id}", data={
        "csrf_token": csrf,
    }, follow_redirects=True)
    assert b"Todo restored" in response.data
    assert b"Restore me" in response.data

    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        assert todo["deleted_at"] is None


def test_restore_nonexistent_todo(client):
    """Restore should 404 for non-existent todos."""
    register_and_login(client)
    csrf = get_csrf(client)
    response = client.post("/restore/9999", data={"csrf_token": csrf})
    assert response.status_code == 404


def test_restore_non_deleted_todo(client, app):
    """Restore should 404 for a todo that isn't deleted."""
    register_and_login(client)
    add_todo(client, "Not deleted")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    response = client.post(f"/restore/{todo_id}", data={"csrf_token": csrf})
    assert response.status_code == 404


def test_deleted_todo_not_in_list(client, app):
    """Soft-deleted todos should not appear in the list view."""
    register_and_login(client)
    add_todo(client, "Visible todo")
    add_todo(client, "Deleted todo")

    with app.app_context():
        db = get_db()
        todo_id = db.execute(
            "SELECT id FROM todos WHERE title = 'Deleted todo'"
        ).fetchone()["id"]

    csrf = get_csrf(client)
    client.post(f"/delete/{todo_id}", data={"csrf_token": csrf})

    response = client.get("/")
    assert b"Visible todo" in response.data
    assert b"Deleted todo" not in response.data


def test_cannot_edit_deleted_todo(client, app):
    """Editing a soft-deleted todo should return 404."""
    register_and_login(client)
    add_todo(client, "Delete then edit")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    client.post(f"/delete/{todo_id}", data={"csrf_token": csrf})

    response = client.get(f"/edit/{todo_id}")
    assert response.status_code == 404


def test_cannot_toggle_deleted_todo(client, app):
    """Toggling a soft-deleted todo should return 404."""
    register_and_login(client)
    add_todo(client, "Delete then toggle")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    client.post(f"/delete/{todo_id}", data={"csrf_token": csrf})

    response = client.post(f"/toggle/{todo_id}", data={"csrf_token": csrf})
    assert response.status_code == 404


def test_user_cannot_restore_other_users_todo(client, app):
    """User B should not be able to restore User A's deleted todo."""
    register_and_login(client, username="alice")
    add_todo(client, "Alice's todo")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]

    csrf = get_csrf(client)
    client.post(f"/delete/{todo_id}", data={"csrf_token": csrf})

    client.post("/auth/logout", data={"csrf_token": csrf})
    register_and_login(client, username="bob")

    csrf = get_csrf(client)
    response = client.post(f"/restore/{todo_id}", data={"csrf_token": csrf})
    assert response.status_code == 404

    # Verify it's still soft-deleted
    with app.app_context():
        db = get_db()
        todo = db.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
        assert todo["deleted_at"] is not None


def test_soft_delete_preserves_tags(client, app):
    """Soft delete should preserve tag associations for restore."""
    register_and_login(client)
    add_todo(client, "Tagged todo", tags="work, urgent")

    with app.app_context():
        db = get_db()
        todo_id = db.execute("SELECT id FROM todos").fetchone()["id"]
        tag_count_before = db.execute(
            "SELECT COUNT(*) FROM todo_tags WHERE todo_id = ?", (todo_id,)
        ).fetchone()[0]
        assert tag_count_before == 2

    csrf = get_csrf(client)
    client.post(f"/delete/{todo_id}", data={"csrf_token": csrf})

    with app.app_context():
        db = get_db()
        tag_count_after = db.execute(
            "SELECT COUNT(*) FROM todo_tags WHERE todo_id = ?", (todo_id,)
        ).fetchone()[0]
        assert tag_count_after == tag_count_before

    # Restore and verify tags are still there
    client.post(f"/restore/{todo_id}", data={"csrf_token": csrf}, follow_redirects=True)

    response = client.get("/")
    assert b"work" in response.data
    assert b"urgent" in response.data
