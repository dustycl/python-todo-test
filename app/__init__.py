import os
import secrets

from flask import Flask, request, session

from . import db
from .auth import bp as auth_bp, init_login_manager
from .todos import bp as todos_bp


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

    # Login manager
    init_login_manager(app)

    # CSRF protection
    @app.context_processor
    def inject_csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(32)
        return {"csrf_token": session["csrf_token"]}

    @app.before_request
    def check_csrf():
        if request.method == "POST":
            token = request.form.get("csrf_token")
            if not token or token != session.get("csrf_token"):
                from flask import abort
                abort(400, "CSRF token missing or invalid.")

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(todos_bp)

    # Auto-create tables if the database file doesn't exist yet
    db_path = app.config["DATABASE"]
    if not os.path.exists(db_path):
        with app.app_context():
            db.init_db()

    return app
