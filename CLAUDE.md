# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database (also auto-runs on first app start)
flask --app app init-db

# Run development server (localhost:5000, debug mode)
python run.py

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_todos.py -v

# Run a single test
pytest tests/test_todos.py::test_create_todo -v
```

## Architecture

Flask app using the **app factory pattern** (`create_app()` in `app/__init__.py`) with two blueprints:

- **`app/auth.py`** — Authentication blueprint (`/auth/` prefix): register, login, logout. Uses `flask-login` for session management and `werkzeug.security` for password hashing.
- **`app/todos.py`** — Todo CRUD blueprint (root prefix): list, create, edit, toggle, delete. All queries enforce `user_id` filtering for cross-user data isolation.

**Database layer** (`app/db.py`): Raw SQLite3 with no ORM. Connection cached on Flask's `g` object per request. Schema has two tables: `users` and `todos` (with foreign key from `todos.user_id` to `users.id`).

**CSRF protection**: Custom implementation in `app/__init__.py` — generates per-session token via `secrets.token_hex(32)`, injects into templates via context processor, validates on all POST requests in `before_request` hook.

**Templates**: Server-rendered Jinja2 with Pico CSS 2.0 via CDN. Base template at `app/templates/base.html`.

## Testing

Tests in `tests/` use pytest fixtures from `tests/conftest.py` that create a fresh app with a temporary SQLite database per test. Helper functions handle registration, login, and CSRF token extraction. Cross-user isolation is extensively tested.

## Conventions

- No ORM — all database access uses raw SQL with parameterized queries
- No external runtime dependencies beyond Flask and flask-login
- POST-only for all state-changing operations
- All todo queries must include `user_id` filtering
- Environment config via `.env` file (`SECRET_KEY`, `DATABASE`)
