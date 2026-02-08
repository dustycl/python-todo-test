import os
import secrets

from flask import Flask

from . import db


def create_app(test_config=None):
    """Create and configure the Flask application.

    Args:
        test_config: Optional dict of config overrides for testing.
    """
    app = Flask(__name__, instance_relative_config=True)

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev"),
        DATABASE=os.path.join(app.instance_path, "todo.db"),
    )

    if test_config is not None:
        app.config.from_mapping(test_config)

    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)

    # Initialize database
    db.init_app(app)

    # Auto-create tables if the database file doesn't exist yet
    db_path = app.config["DATABASE"]
    if not os.path.exists(db_path):
        with app.app_context():
            db.init_db()

    return app
