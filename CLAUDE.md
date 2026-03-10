# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Start local PostgreSQL (requires Docker)
docker compose up -d db

# Run pending database migrations (also auto-runs on app start)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/todo_db flask --app app migrate

# Run development server (localhost:5000, debug mode)
python run.py

# Run all tests (requires PostgreSQL running locally or via Docker Compose)
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

**Database layer** (`app/db.py`): Raw SQL via `psycopg2` against PostgreSQL with no ORM. Connection cached on Flask's `g` object per request using `RealDictCursor` for dict-like row access. Uses `%s` parameterized placeholders. Schema has tables: `users`, `todos`, `tags`, and `todo_tags` (with foreign keys). Schema changes are managed via forward-only numbered SQL migrations in `migrations/` tracked by a `schema_migrations` table.

**Configuration**: `DATABASE_URL` environment variable for PostgreSQL connection string (default: `postgresql://postgres:postgres@localhost:5432/todo_db`). `SECRET_KEY` for session security.

**CSRF protection**: Custom implementation in `app/__init__.py` — generates per-session token via `secrets.token_hex(32)`, injects into templates via context processor, validates on all POST requests in `before_request` hook.

**Templates**: Server-rendered Jinja2 with Pico CSS 2.0 via CDN. Base template at `app/templates/base.html`.

## Testing

Tests in `tests/` use pytest fixtures from `tests/conftest.py` that create a fresh PostgreSQL test database per test (via `CREATE DATABASE` / `DROP DATABASE`). Requires a running PostgreSQL instance — use `docker compose up -d db` or set `TEST_DATABASE_URL` to point to your Postgres server. Helper functions handle registration, login, and CSRF token extraction. Cross-user isolation is extensively tested.

## Deployment

**Local with Docker Compose**: `docker compose up` starts both the Postgres database and the web app. Set `SECRET_KEY` in `.env` (see `.env.example`).

**Railway**: Connect the GitHub repo in Railway, add a PostgreSQL plugin, and set `SECRET_KEY` as an environment variable. Railway auto-injects `DATABASE_URL` from the Postgres plugin and sets `PORT` dynamically. The `Procfile` handles the start command.

Required environment variables for production:
- `SECRET_KEY` — random secret for session signing
- `DATABASE_URL` — PostgreSQL connection string (auto-set by Railway's Postgres plugin)

## Conventions

- No ORM — all database access uses raw SQL with `psycopg2` parameterized queries (`%s` placeholders)
- No external runtime dependencies beyond Flask, flask-login, and psycopg2
- POST-only for all state-changing operations
- All todo queries must include `user_id` filtering
- Environment config via `.env` file (`SECRET_KEY`, `DATABASE_URL`)
- Schema changes must be done via migration files in `migrations/` (e.g. `003_description.sql`), never by editing the schema directly — migrations run automatically on app startup
