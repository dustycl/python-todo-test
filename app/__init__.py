import logging
import os
import secrets
import time
from logging.handlers import RotatingFileHandler

from flask import Flask, g, render_template, request, session

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

    # Configure logging
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if not app.debug and not app.testing:
        file_handler = RotatingFileHandler(
            os.path.join(app.instance_path, "app.log"),
            maxBytes=1_000_000,
            backupCount=5,
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.DEBUG if app.debug else logging.INFO)

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
    def start_timer():
        g.start_time = time.time()

    @app.before_request
    def check_csrf():
        if request.method == "POST":
            token = request.form.get("csrf_token")
            if not token or token != session.get("csrf_token"):
                app.logger.warning(
                    "CSRF validation failed: %s %s", request.method, request.path
                )
                from flask import abort
                abort(400, "CSRF token missing or invalid.")

    @app.after_request
    def log_request(response):
        duration = time.time() - g.get("start_time", time.time())
        app.logger.info(
            "%s %s %s %.3fs",
            request.method,
            request.path,
            response.status_code,
            duration,
        )
        return response

    # Error handlers
    @app.errorhandler(404)
    def not_found(e):
        app.logger.warning("404 Not Found: %s %s", request.method, request.path)
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        app.logger.error(
            "500 Internal Server Error: %s %s", request.method, request.path,
            exc_info=e,
        )
        return render_template("500.html"), 500

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(todos_bp)

    # Run any pending database migrations
    with app.app_context():
        db.run_migrations()

    return app
