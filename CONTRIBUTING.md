# Contributing

## Development Setup

1. Clone the repository and install dependencies:

```bash
pip install -r requirements.txt
```

2. Initialize the database:

```bash
flask --app app init-db
```

3. Run the dev server:

```bash
python run.py
```

## Running Tests

```bash
pytest tests/ -v
```

Tests use a temporary SQLite database per test, so they never touch your development data.

## Code Organization

The app uses Flask's **app factory pattern** and **blueprints**:

- `app/__init__.py` -- `create_app()` wires everything together
- `app/auth.py` -- Auth blueprint (`/auth/register`, `/auth/login`, `/auth/logout`)
- `app/todos.py` -- Todos blueprint (`/`, `/add`, `/toggle/<id>`, `/edit/<id>`, `/delete/<id>`)
- `app/db.py` -- Database helpers and schema

## Adding a New Route

1. Add the route function in the appropriate blueprint (`auth.py` or `todos.py`).
2. If the route renders HTML, create a template in `app/templates/`.
3. All POST forms must include `<input type="hidden" name="csrf_token" value="{{ csrf_token }}">`.
4. Todo routes must use `@login_required` and filter queries with `AND user_id = ?`.
5. Write tests in the corresponding test file under `tests/`.

## Testing Expectations

- All routes should have tests.
- Todo operations must have cross-user isolation tests (user A cannot access user B's data).
- Tests use the `app` and `client` fixtures from `tests/conftest.py`.

## Style

- No external runtime dependencies beyond Flask and flask-login.
- Raw SQL via `sqlite3` -- no ORM.
- Server-rendered templates with Jinja2. No JavaScript frameworks.
