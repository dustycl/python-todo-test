"""Tests for the completed todos windowed section.

These tests insert todos directly into the database with backdated completed_at
timestamps, bypassing the UI, so we can simulate a long completion history without
needing a real account with months of data.
"""
from datetime import datetime, timezone, timedelta

from app.db import get_db
from tests.test_todos import _fetchone, get_csrf, register_and_login


def _insert_completed(app, title, days_ago=1):
    """Insert a completed todo with a backdated completed_at timestamp."""
    completed_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    with app.app_context():
        db = get_db()
        user_id = _fetchone(db, "SELECT id FROM users")["id"]
        cur = db.cursor()
        cur.execute(
            "INSERT INTO todos (user_id, title, completed, completed_at) "
            "VALUES (%s, %s, true, %s)",
            (user_id, title, completed_at),
        )
        db.commit()


# --- Default window (7 days) ---


def test_default_shows_recent_completed(app, client):
    """Completed tasks from the last 7 days appear by default."""
    register_and_login(client)
    _insert_completed(app, "Recent task", days_ago=2)

    response = client.get("/")
    assert b"Recent task" in response.data


def test_default_hides_old_completed(app, client):
    """Completed tasks older than 7 days are hidden by default."""
    register_and_login(client)
    _insert_completed(app, "Old task", days_ago=30)

    response = client.get("/")
    assert b"Old task" not in response.data


def test_default_window_label(app, client):
    """The completed section shows a 'last 7 days' label in default view."""
    register_and_login(client)
    _insert_completed(app, "Some task", days_ago=1)

    response = client.get("/")
    assert b"last 7 days" in response.data


def test_show_older_link_present_when_old_todos_exist(app, client):
    """'Show older tasks' link appears when tasks exist outside the 7-day window."""
    register_and_login(client)
    _insert_completed(app, "Recent task", days_ago=1)
    _insert_completed(app, "Old task", days_ago=30)

    response = client.get("/")
    assert b"Show older tasks" in response.data


def test_show_older_link_absent_when_all_recent(app, client):
    """'Show older tasks' link is hidden when all completed tasks are within 7 days."""
    register_and_login(client)
    _insert_completed(app, "Recent task 1", days_ago=1)
    _insert_completed(app, "Recent task 2", days_ago=3)

    response = client.get("/")
    assert b"Show older tasks" not in response.data


def test_no_completed_section_when_none_exist(client):
    """No completed section is rendered when there are no completed tasks."""
    register_and_login(client)

    response = client.get("/")
    assert b"Show older tasks" not in response.data
    assert b"completed-section" not in response.data


# --- completed_window=all ---


def test_window_all_shows_old_completed(app, client):
    """completed_window=all reveals tasks older than 7 days."""
    register_and_login(client)
    _insert_completed(app, "Old task", days_ago=30)

    response = client.get("/?completed_window=all")
    assert b"Old task" in response.data


def test_window_all_shows_show_recent_only_link(app, client):
    """'Show recent only' link appears when completed_window=all."""
    register_and_login(client)
    _insert_completed(app, "Some task", days_ago=30)

    response = client.get("/?completed_window=all")
    assert b"Show recent only" in response.data


def test_window_all_hides_show_older_link(app, client):
    """'Show older tasks' link is not shown when already viewing all."""
    register_and_login(client)
    _insert_completed(app, "Old task", days_ago=30)

    response = client.get("/?completed_window=all")
    assert b"Show older tasks" not in response.data


def test_show_recent_only_absent_in_default_view(app, client):
    """'Show recent only' link is not shown in the default 7-day view."""
    register_and_login(client)
    _insert_completed(app, "Recent task", days_ago=1)

    response = client.get("/")
    assert b"Show recent only" not in response.data


def test_window_all_also_shows_recent(app, client):
    """completed_window=all shows both recent and old tasks."""
    register_and_login(client)
    _insert_completed(app, "Recent task", days_ago=2)
    _insert_completed(app, "Old task", days_ago=30)

    response = client.get("/?completed_window=all")
    data = response.data.decode()
    assert "Recent task" in data
    assert "Old task" in data


# --- Load more ---


def test_load_more_absent_at_exact_limit(app, client):
    """'Load more' is absent when completed count is exactly at the limit (20)."""
    register_and_login(client)
    for i in range(20):
        _insert_completed(app, f"Task {i:02d}", days_ago=1)

    response = client.get("/")
    assert b"Load more" not in response.data


def test_load_more_present_when_over_limit(app, client):
    """'Load more' link appears when there are more than 20 completed tasks."""
    register_and_login(client)
    for i in range(21):
        _insert_completed(app, f"Task {i:02d}", days_ago=1)

    response = client.get("/")
    assert b"Load more" in response.data


def test_load_more_shows_additional_items(app, client):
    """Increasing completed_limit via the load more link reveals more items."""
    register_and_login(client)
    for i in range(25):
        _insert_completed(app, f"Task {i:02d}", days_ago=1)

    # Default shows 20 of the 25
    response = client.get("/")
    html = response.data.decode()
    shown = sum(1 for i in range(25) if f"Task {i:02d}" in html)
    assert shown == 20

    # With limit=40, all 25 are visible
    response2 = client.get("/?completed_limit=40")
    html2 = response2.data.decode()
    shown2 = sum(1 for i in range(25) if f"Task {i:02d}" in html2)
    assert shown2 == 25
    assert b"Load more" not in response2.data


def test_completed_summary_shows_plus_when_more(app, client):
    """Summary count shows 'N+' when items are truncated by the limit."""
    register_and_login(client)
    for i in range(21):
        _insert_completed(app, f"Task {i}", days_ago=1)

    response = client.get("/")
    assert b"20+" in response.data


# --- status=completed filter path is unaffected ---


def test_status_completed_filter_ignores_window(app, client):
    """The status=completed filter path always shows all completed tasks."""
    register_and_login(client)
    _insert_completed(app, "Old task", days_ago=30)

    # Default view hides it
    assert b"Old task" not in client.get("/").data

    # status=completed shows it regardless of age
    assert b"Old task" in client.get("/?status=completed").data


def test_status_completed_filter_not_capped_at_20(app, client):
    """The status=completed filter path is not subject to the 20-item cap."""
    register_and_login(client)
    for i in range(25):
        _insert_completed(app, f"Task {i:02d}", days_ago=1)

    response = client.get("/?status=completed")
    html = response.data.decode()
    shown = sum(1 for i in range(25) if f"Task {i:02d}" in html)
    assert shown == 25


# --- NULL completed_at edge case ---


def _insert_completed_null_at(app, title):
    """Insert a completed todo with NULL completed_at (simulates pre-migration data)."""
    with app.app_context():
        db = get_db()
        user_id = _fetchone(db, "SELECT id FROM users")["id"]
        cur = db.cursor()
        cur.execute(
            "INSERT INTO todos (user_id, title, completed, completed_at) "
            "VALUES (%s, %s, true, NULL)",
            (user_id, title),
        )
        db.commit()


def test_null_completed_at_hidden_in_default_window(app, client):
    """Todos with completed_at=NULL are hidden in the default 7-day window."""
    register_and_login(client)
    _insert_completed_null_at(app, "Legacy task")

    response = client.get("/")
    assert b"Legacy task" not in response.data


def test_null_completed_at_shown_with_window_all(app, client):
    """Todos with completed_at=NULL appear when viewing completed_window=all."""
    register_and_login(client)
    _insert_completed_null_at(app, "Legacy task")

    response = client.get("/?completed_window=all")
    assert b"Legacy task" in response.data


def test_null_completed_at_triggers_show_older_link(app, client):
    """A NULL completed_at todo causes 'Show older tasks' to appear."""
    register_and_login(client)
    _insert_completed(app, "Recent task", days_ago=1)
    _insert_completed_null_at(app, "Legacy task")

    response = client.get("/")
    assert b"Show older tasks" in response.data
