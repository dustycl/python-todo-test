from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .db import get_db

bp = Blueprint("todos", __name__)


@bp.route("/")
@login_required
def list_todos():
    """List all todos for the current user."""
    db = get_db()
    todos = db.execute(
        "SELECT * FROM todos WHERE user_id = ? ORDER BY completed ASC, created_at DESC",
        (current_user.id,),
    ).fetchall()
    return render_template("todos/list.html", todos=todos)


@bp.route("/add", methods=["POST"])
@login_required
def add():
    """Add a new todo."""
    title = request.form.get("title", "").strip()

    if not title:
        flash("Title is required.", "error")
    elif len(title) > 200:
        flash("Title must be 200 characters or less.", "error")
    else:
        db = get_db()
        db.execute(
            "INSERT INTO todos (user_id, title) VALUES (?, ?)",
            (current_user.id, title),
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

        if not title:
            flash("Title is required.", "error")
        elif len(title) > 200:
            flash("Title must be 200 characters or less.", "error")
        else:
            db.execute(
                "UPDATE todos SET title = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                (title, todo_id, current_user.id),
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
