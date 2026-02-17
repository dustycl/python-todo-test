from datetime import date, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .db import get_db


def _validate_due_date(raw):
    """Validate and return a due_date string, or None if empty. Raises ValueError on bad format."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    # Validate YYYY-MM-DD format by parsing
    date.fromisoformat(raw)
    return raw

bp = Blueprint("todos", __name__)


@bp.route("/")
@login_required
def list_todos():
    """List all todos for the current user, with optional search and filters."""
    db = get_db()
    today = date.today()

    # Base query — always filter by user
    clauses = ["user_id = ?"]
    params = [current_user.id]

    # Keyword search
    q = request.args.get("q", "").strip()
    if q:
        q_escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("title LIKE ? ESCAPE '\\'")
        params.append(f"%{q_escaped}%")

    # Status filter
    status = request.args.get("status", "all")
    if status == "active":
        clauses.append("completed = 0")
    elif status == "completed":
        clauses.append("completed = 1")

    # Due date filter
    due = request.args.get("due", "all")
    if due == "overdue":
        clauses.append("due_date IS NOT NULL AND due_date < ?")
        params.append(today.isoformat())
    elif due == "today":
        clauses.append("due_date = ?")
        params.append(today.isoformat())
    elif due == "week":
        week_end = (today + timedelta(days=6)).isoformat()
        clauses.append("due_date IS NOT NULL AND due_date >= ? AND due_date <= ?")
        params.append(today.isoformat())
        params.append(week_end)
    elif due == "none":
        clauses.append("due_date IS NULL")

    where = " AND ".join(clauses)
    todos = db.execute(
        f"SELECT * FROM todos WHERE {where} "
        "ORDER BY completed ASC, due_date IS NULL ASC, due_date ASC, created_at DESC",
        params,
    ).fetchall()

    return render_template(
        "todos/list.html",
        todos=todos,
        today=today.isoformat(),
        search_q=q,
        filter_status=status,
        filter_due=due,
    )


@bp.route("/add", methods=["POST"])
@login_required
def add():
    """Add a new todo."""
    title = request.form.get("title", "").strip()
    raw_due_date = request.form.get("due_date", "")

    if not title:
        flash("Title is required.", "error")
    elif len(title) > 200:
        flash("Title must be 200 characters or less.", "error")
    else:
        try:
            due_date = _validate_due_date(raw_due_date)
        except ValueError:
            flash("Invalid due date format. Use YYYY-MM-DD.", "error")
            return redirect(url_for("todos.list_todos"))

        db = get_db()
        db.execute(
            "INSERT INTO todos (user_id, title, due_date) VALUES (?, ?, ?)",
            (current_user.id, title, due_date),
        )
        db.commit()
        flash("Todo added.", "success")

    return redirect(url_for("todos.list_todos"))


@bp.route("/toggle/<int:todo_id>", methods=["POST"])
@login_required
def toggle(todo_id):
    """Toggle a todo's completed status."""
    db = get_db()
    result = db.execute(
        "UPDATE todos SET completed = NOT completed, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ? AND user_id = ?",
        (todo_id, current_user.id),
    )
    db.commit()

    if result.rowcount == 0:
        abort(404)

    return redirect(url_for("todos.list_todos"))


@bp.route("/edit/<int:todo_id>", methods=["GET", "POST"])
@login_required
def edit(todo_id):
    """Edit a todo's title."""
    db = get_db()
    todo = db.execute(
        "SELECT * FROM todos WHERE id = ? AND user_id = ?",
        (todo_id, current_user.id),
    ).fetchone()

    if todo is None:
        abort(404)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        raw_due_date = request.form.get("due_date", "")

        if not title:
            flash("Title is required.", "error")
        elif len(title) > 200:
            flash("Title must be 200 characters or less.", "error")
        else:
            try:
                due_date = _validate_due_date(raw_due_date)
            except ValueError:
                flash("Invalid due date format. Use YYYY-MM-DD.", "error")
                return render_template("todos/edit.html", todo=todo)

            db.execute(
                "UPDATE todos SET title = ?, due_date = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                (title, due_date, todo_id, current_user.id),
            )
            db.commit()
            flash("Todo updated.", "success")
            return redirect(url_for("todos.list_todos"))

    return render_template("todos/edit.html", todo=todo)


@bp.route("/delete/<int:todo_id>", methods=["POST"])
@login_required
def delete(todo_id):
    """Delete a todo."""
    db = get_db()
    result = db.execute(
        "DELETE FROM todos WHERE id = ? AND user_id = ?",
        (todo_id, current_user.id),
    )
    db.commit()

    if result.rowcount == 0:
        abort(404)

    flash("Todo deleted.", "success")
    return redirect(url_for("todos.list_todos"))
