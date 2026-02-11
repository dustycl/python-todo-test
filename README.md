# Todo App

A multi-user web todo application built with Flask and SQLite.

## Features

- User registration and login with secure password hashing
- Create, edit, complete, and delete todos
- Per-user todo lists with full data isolation
- CSRF protection on all forms
- Clean UI with Pico CSS

## Prerequisites

- Python 3.10+

## Installation

```bash
pip install -r requirements.txt
```

## Setup

Initialize the database:

```bash
flask --app app init-db
```

## Running

Start the development server:

```bash
python run.py
```

The app will be available at `http://localhost:5000`.

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Session signing key. **Set this in production.** | `dev` |
| `DATABASE` | Path to SQLite database file | `instance/todo.db` |

Set via environment variables:

```bash
SECRET_KEY=your-secret-key python run.py
```

## Running Tests

```bash
pytest tests/ -v
```

## Project Structure

```
app/
    __init__.py       # App factory, CSRF protection, error handlers
    db.py             # Database connection, schema, init-db command
    auth.py           # Registration, login, logout routes
    todos.py          # Todo CRUD routes
    templates/        # Jinja2 templates with Pico CSS
tests/
    conftest.py       # Test fixtures (app, client, runner)
    test_db.py        # Database layer tests
    test_auth.py      # Authentication tests
    test_todos.py     # Todo CRUD and isolation tests
```
