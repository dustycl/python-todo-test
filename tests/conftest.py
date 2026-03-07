import os
import uuid

import psycopg2
import pytest

from app import create_app
from app.db import init_db

# Base Postgres URL for creating/dropping test databases.
# Defaults to a local Postgres instance (e.g. from Docker Compose).
_BASE_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
)


def _create_test_db():
    """Create a unique temporary test database and return its URL."""
    db_name = f"test_{uuid.uuid4().hex[:12]}"
    conn = psycopg2.connect(_BASE_DB_URL)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f'CREATE DATABASE "{db_name}"')
    cur.close()
    conn.close()

    # Build the URL for the new database
    parts = _BASE_DB_URL.rsplit("/", 1)
    return parts[0] + "/" + db_name, db_name


def _drop_test_db(db_name):
    """Drop the temporary test database."""
    conn = psycopg2.connect(_BASE_DB_URL)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    cur.close()
    conn.close()


@pytest.fixture
def app():
    """Create an app instance with a temporary PostgreSQL database for each test."""
    db_url, db_name = _create_test_db()

    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": db_url,
            "SECRET_KEY": "test-secret-key",
        }
    )

    with app.app_context():
        init_db()

    yield app

    _drop_test_db(db_name)


@pytest.fixture
def client(app):
    """A Flask test client for sending requests."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """A CLI test runner for testing Flask CLI commands."""
    return app.test_cli_runner()
