import os

import click
import psycopg2
import psycopg2.extras
from flask import current_app, g
from flask.cli import with_appcontext


def get_db():
    """Get a database connection for the current request.

    Stores the connection on Flask's `g` object so the same connection
    is reused within a single request. Returns rows as RealDictRow for
    dict-like access.
    """
    if "db" not in g:
        g.db = psycopg2.connect(
            current_app.config["DATABASE_URL"],
            cursor_factory=psycopg2.extras.RealDictCursor,
            connect_timeout=10,
        )
    return g.db


def close_db(e=None):
    """Close the database connection at the end of a request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ---------------------------------------------------------------------------
# Migration system
# ---------------------------------------------------------------------------


def _get_migrations_dir():
    """Return the path to the migrations/ directory at the project root."""
    app_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(app_dir)
    return os.path.join(project_root, "migrations")


def _ensure_migrations_table(db):
    """Create the schema_migrations tracking table if it doesn't exist."""
    cur = db.cursor()
    cur.execute("SET lock_timeout = '15s'")
    cur.execute("SET statement_timeout = '30s'")
    cur.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  version INTEGER PRIMARY KEY,"
        "  applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    db.commit()


def _get_pending_migrations(db):
    """Return a sorted list of (version, filepath) for unapplied migrations."""
    cur = db.cursor()
    cur.execute("SELECT version FROM schema_migrations")
    applied = {row["version"] for row in cur.fetchall()}

    migrations_dir = _get_migrations_dir()
    if not os.path.exists(migrations_dir):
        return []

    pending = []
    for filename in sorted(os.listdir(migrations_dir)):
        if not filename.endswith(".sql"):
            continue
        try:
            version = int(filename.split("_", 1)[0])
        except ValueError:
            continue
        if version not in applied:
            pending.append((version, os.path.join(migrations_dir, filename)))

    return pending


def _baseline_existing_db(db):
    """Mark all migrations as applied on a pre-migration database.

    If the database already has application tables (e.g. 'users') but an
    empty schema_migrations table, it predates the migration system.  We
    record every known migration as already applied so that ALTER-style
    migrations are not re-run.
    """
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM schema_migrations")
    has_rows = cur.fetchone()["cnt"]
    if has_rows:
        return

    # Check if application tables already exist (Postgres introspection)
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'users'"
    )
    has_tables = cur.fetchone()["cnt"]
    if not has_tables:
        return  # Fresh database — nothing to baseline

    # Mark every migration file as already applied
    migrations_dir = _get_migrations_dir()
    if not os.path.exists(migrations_dir):
        return

    for filename in sorted(os.listdir(migrations_dir)):
        if not filename.endswith(".sql"):
            continue
        try:
            version = int(filename.split("_", 1)[0])
        except ValueError:
            continue
        cur.execute(
            "INSERT INTO schema_migrations (version) VALUES (%s) "
            "ON CONFLICT DO NOTHING",
            (version,),
        )
    db.commit()


def run_migrations():
    """Apply all pending migrations and return the number applied."""
    db = get_db()
    _ensure_migrations_table(db)
    _baseline_existing_db(db)

    pending = _get_pending_migrations(db)
    cur = db.cursor()
    for version, filepath in pending:
        with open(filepath) as f:
            sql = f.read()
        cur.execute(sql)
        cur.execute(
            "INSERT INTO schema_migrations (version) VALUES (%s)",
            (version,),
        )
        db.commit()

    return len(pending)


def init_db():
    """Create/update tables by running all pending migrations."""
    return run_migrations()


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Initialise the database and run pending migrations."""
    count = run_migrations()
    if count:
        click.echo(f"Applied {count} migration(s).")
    else:
        click.echo("Database is up to date.")


@click.command("migrate")
@with_appcontext
def migrate_command():
    """Run pending database migrations."""
    count = run_migrations()
    if count:
        click.echo(f"Applied {count} migration(s).")
    else:
        click.echo("No pending migrations.")


def init_app(app):
    """Register database functions with the Flask app."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(migrate_command)
