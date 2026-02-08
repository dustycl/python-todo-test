import os
import tempfile

import pytest

from app import create_app
from app.db import get_db, init_db


@pytest.fixture
def app():
    """Create an app instance with a temporary database for each test."""
    db_fd, db_path = tempfile.mkstemp()

    app = create_app({
        "TESTING": True,
        "DATABASE": db_path,
        "SECRET_KEY": "test-secret-key",
    })

    with app.app_context():
        init_db()

    yield app

    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    """A Flask test client for sending requests."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """A CLI test runner for testing Flask CLI commands."""
    return app.test_cli_runner()
