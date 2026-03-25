import psycopg2

from app.db import get_db


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
        cur = db.cursor()
        cur.execute("SELECT 1")
        assert False, "Expected InterfaceError"
    except psycopg2.InterfaceError:
        pass


def test_init_db_creates_tables(app):
    """init_db should create the users and todos tables."""
    with app.app_context():
        db = get_db()
        cur = db.cursor()

        # Check users table exists and has expected columns
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'users'"
        )
        columns = {row["column_name"] for row in cur.fetchall()}
        assert columns == {"id", "username", "email", "first_name", "last_name", "password_hash", "created_at", "is_admin"}

        # Check todos table exists and has expected columns
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'todos'"
        )
        columns = {row["column_name"] for row in cur.fetchall()}
        assert columns == {
            "id",
            "user_id",
            "title",
            "completed",
            "completed_at",
            "due_date",
            "description",
            "deleted_at",
            "created_at",
            "updated_at",
        }


def test_foreign_keys_enforced(app):
    """Foreign key constraints should be enforced in PostgreSQL."""
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        try:
            cur.execute(
                "INSERT INTO todos (user_id, title) VALUES (%s, %s)",
                (9999, "orphan todo"),
            )
            db.commit()
            assert False, "Expected IntegrityError"
        except psycopg2.IntegrityError:
            db.rollback()


def test_todos_user_id_index_exists(app):
    """The idx_todos_user_id index should be created."""
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = 'idx_todos_user_id'"
        )
        assert cur.fetchone() is not None


def test_init_db_command(runner):
    """The init-db CLI command should run without error."""
    result = runner.invoke(args=["init-db"])
    assert "up to date" in result.output or "migration" in result.output


def test_users_table_unique_username(app):
    """The username column should enforce uniqueness."""
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            ("alice", "hash1"),
        )
        db.commit()

        try:
            cur.execute(
                "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                ("alice", "hash2"),
            )
            db.commit()
            assert False, "Expected IntegrityError"
        except psycopg2.IntegrityError:
            db.rollback()


def test_users_table_unique_email(app):
    """The email column should enforce uniqueness (via partial unique index)."""
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
            ("test@example.com", "hash1"),
        )
        db.commit()

        try:
            cur.execute(
                "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
                ("test@example.com", "hash2"),
            )
            db.commit()
            assert False, "Expected IntegrityError"
        except psycopg2.IntegrityError:
            db.rollback()


def test_todos_foreign_key_constraint(app):
    """Inserting a todo with a nonexistent user_id should fail."""
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        try:
            cur.execute(
                "INSERT INTO todos (user_id, title) VALUES (%s, %s)",
                (9999, "orphan todo"),
            )
            db.commit()
            assert False, "Expected IntegrityError"
        except psycopg2.IntegrityError:
            db.rollback()
