import sqlite3

from app.db import get_db, init_db


def test_get_db_returns_same_connection(app):
    """get_db should return the same connection within a request context."""
    with app.app_context():
        db = get_db()
        assert db is get_db()


def test_connection_closes_after_context(app):
    """The database connection should be closed after the app context ends."""
    with app.app_context():
        db = get_db()

    # After context closes, the connection should be unusable
    try:
        db.execute("SELECT 1")
        assert False, "Expected ProgrammingError"
    except sqlite3.ProgrammingError:
        pass


def test_init_db_creates_tables(app):
    """init_db should create the users and todos tables."""
    with app.app_context():
        db = get_db()
        # Check users table exists and has expected columns
        cursor = db.execute("PRAGMA table_info(users)")
        columns = {row["name"] for row in cursor.fetchall()}
        assert columns == {"id", "username", "password_hash", "created_at"}

        # Check todos table exists and has expected columns
        cursor = db.execute("PRAGMA table_info(todos)")
        columns = {row["name"] for row in cursor.fetchall()}
        assert columns == {"id", "user_id", "title", "completed", "due_date", "created_at", "updated_at"}


def test_foreign_keys_enabled(app):
    """Foreign key enforcement should be active."""
    with app.app_context():
        db = get_db()
        result = db.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1


def test_todos_user_id_index_exists(app):
    """The idx_todos_user_id index should be created."""
    with app.app_context():
        db = get_db()
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_todos_user_id'"
        )
        assert cursor.fetchone() is not None


def test_init_db_command(runner):
    """The init-db CLI command should run without error."""
    result = runner.invoke(args=["init-db"])
    assert "up to date" in result.output or "migration" in result.output


def test_users_table_unique_username(app):
    """The username column should enforce uniqueness."""
    with app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            ("alice", "hash1"),
        )
        db.commit()

        try:
            db.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                ("alice", "hash2"),
            )
            db.commit()
            assert False, "Expected IntegrityError"
        except sqlite3.IntegrityError:
            pass


def test_todos_foreign_key_constraint(app):
    """Inserting a todo with a nonexistent user_id should fail."""
    with app.app_context():
        db = get_db()
        try:
            db.execute(
                "INSERT INTO todos (user_id, title) VALUES (?, ?)",
                (9999, "orphan todo"),
            )
            db.commit()
            assert False, "Expected IntegrityError"
        except sqlite3.IntegrityError:
            pass
