import logging
from datetime import date, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .db import get_db

logger = logging.getLogger(__name__)


def _validate_due_date(raw):
    """Validate and return a due_date string, or None if empty. Raises ValueError on bad format."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    # Validate YYYY-MM-DD format by parsing
    date.fromisoformat(raw)
    return raw


def _parse_tags(raw):
    """Split comma-separated tag input into a deduplicated list of tag names."""
    if not raw or not raw.strip():
        return []
    seen = set()
    tags = []
    for part in raw.split(","):
        name = part.strip().lower()
        if name and len(name) <= 50 and name not in seen:
            seen.add(name)
            tags.append(name)
    return tags


def _sync_tags(db, user_id, todo_id, tag_names):
    """Create any new tags and set the todo's tags to exactly tag_names."""
    # Remove existing associations
    db.execute("DELETE FROM todo_tags WHERE todo_id = ?", (todo_id,))

    for name in tag_names:
        # Insert tag if it doesn't exist for this user
        db.execute(
            "INSERT OR IGNORE INTO tags (user_id, name) VALUES (?, ?)",
            (user_id, name),
        )
        tag = db.execute(
            "SELECT id FROM tags WHERE user_id = ? AND name = ?",
            (user_id, name),
        ).fetchone()
        db.execute(
            "INSERT INTO todo_tags (todo_id, tag_id) VALUES (?, ?)",
            (todo_id, tag["id"]),
        )


def _get_user_tags(db, user_id):
    """Return all tag names for a user, ordered alphabetically."""
    rows = db.execute(
        "SELECT DISTINCT name FROM tags WHERE user_id = ? ORDER BY name",
        (user_id,),
    ).fetchall()
    return [row["name"] for row in rows]


def _get_todo_tags(db, todo_id):
    """Return tag names for a specific todo."""
    rows = db.execute(
        "SELECT t.name FROM tags t "
        "JOIN todo_tags tt ON t.id = tt.tag_id "
        "WHERE tt.todo_id = ? ORDER BY t.name",
        (todo_id,),
    ).fetchall()
    return [row["name"] for row in rows]


def _get_tags_for_todos(db, todo_ids):
    """Return a dict mapping todo_id -> list of tag names."""
    if not todo_ids:
        return {}
    placeholders = ",".join("?" * len(todo_ids))
    rows = db.execute(
        f"SELECT tt.todo_id, t.name FROM tags t "
        f"JOIN todo_tags tt ON t.id = tt.tag_id "
        f"WHERE tt.todo_id IN ({placeholders}) ORDER BY t.name",
        todo_ids,
    ).fetchall()
    result = {tid: [] for tid in todo_ids}
    for row in rows:
        result[row["todo_id"]].append(row["name"])
    return result


bp = Blueprint("todos", __name__)


@bp.route("/")
@login_required
def list_todos():
    """List all todos for the current user, with optional search and filters."""
    db = get_db()
    today = date.today()

    # Base query — always filter by user (qualified for JOIN compatibility)
    clauses = ["todos.user_id = ?"]
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

    # Tag filter
    tag = request.args.get("tag", "all")
    join_clause = ""
    if tag and tag != "all":
        join_clause = (
            " JOIN todo_tags tt ON todos.id = tt.todo_id"
            " JOIN tags tg ON tt.tag_id = tg.id"
        )
        clauses.append("tg.user_id = ? AND tg.name = ?")
        params.append(current_user.id)
        params.append(tag)

    where = " AND ".join(clauses)
    todos = db.execute(
        f"SELECT todos.* FROM todos{join_clause} WHERE {where} "
        "ORDER BY completed ASC, due_date IS NULL ASC, due_date ASC, created_at DESC",
        params,
    ).fetchall()

    # Fetch tags for all returned todos
    todo_ids = [t["id"] for t in todos]
    tags_map = _get_tags_for_todos(db, todo_ids)

    # All user tags for the filter dropdown and datalist
    all_tags = _get_user_tags(db, current_user.id)

    return render_template(
        "todos/list.html",
        todos=todos,
        today=today.isoformat(),
        search_q=q,
        filter_status=status,
        filter_due=due,
        filter_tag=tag,
        all_tags=all_tags,
        tags_map=tags_map,
    )


@bp.route("/add", methods=["POST"])
@login_required
def add():
    """Add a new todo."""
    title = request.form.get("title", "").strip()
    raw_due_date = request.form.get("due_date", "")
    description = request.form.get("description", "").strip() or None

    if not title:
        flash("Title is required.", "error")
    elif len(title) > 200:
        flash("Title must be 200 characters or less.", "error")
    elif description and len(description) > 2000:
        flash("Description must be 2000 characters or less.", "error")
    else:
        try:
            due_date = _validate_due_date(raw_due_date)
        except ValueError:
            flash("Invalid due date format. Use YYYY-MM-DD.", "error")
            return redirect(url_for("todos.list_todos"))

        tag_names = _parse_tags(request.form.get("tags", ""))

        try:
            db = get_db()
            cursor = db.execute(
                "INSERT INTO todos (user_id, title, due_date, description) VALUES (?, ?, ?, ?)",
                (current_user.id, title, due_date, description),
            )
            if tag_names:
                _sync_tags(db, current_user.id, cursor.lastrowid, tag_names)
            db.commit()
            logger.info("Todo created by user %s: %r", current_user.id, title)
            flash("Todo added.", "success")
        except Exception:
            logger.error("Failed to create todo for user %s", current_user.id, exc_info=True)
            flash("An error occurred while adding the todo.", "error")

    return redirect(url_for("todos.list_todos"))


@bp.route("/toggle/<int:todo_id>", methods=["POST"])
@login_required
def toggle(todo_id):
    """Toggle a todo's completed status."""
    try:
        db = get_db()
        result = db.execute(
            "UPDATE todos SET completed = NOT completed, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ?",
            (todo_id, current_user.id),
        )
        db.commit()
    except Exception:
        logger.error("Failed to toggle todo %s for user %s", todo_id, current_user.id, exc_info=True)
        flash("An error occurred while toggling the todo.", "error")
        return redirect(url_for("todos.list_todos"))

    if result.rowcount == 0:
        logger.warning("Toggle failed: todo %s not found for user %s", todo_id, current_user.id)
        abort(404)

    logger.info("Todo %s toggled by user %s", todo_id, current_user.id)
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
        logger.warning("Edit failed: todo %s not found for user %s", todo_id, current_user.id)
        abort(404)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        raw_due_date = request.form.get("due_date", "")
        description = request.form.get("description", "").strip() or None

        if not title:
            flash("Title is required.", "error")
        elif len(title) > 200:
            flash("Title must be 200 characters or less.", "error")
        elif description and len(description) > 2000:
            flash("Description must be 2000 characters or less.", "error")
        else:
            try:
                due_date = _validate_due_date(raw_due_date)
            except ValueError:
                flash("Invalid due date format. Use YYYY-MM-DD.", "error")
                return render_template("todos/edit.html", todo=todo,
                                       todo_tags=_get_todo_tags(db, todo_id),
                                       all_tags=_get_user_tags(db, current_user.id))

            tag_names = _parse_tags(request.form.get("tags", ""))

            try:
                db.execute(
                    "UPDATE todos SET title = ?, due_date = ?, description = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND user_id = ?",
                    (title, due_date, description, todo_id, current_user.id),
                )
                _sync_tags(db, current_user.id, todo_id, tag_names)
                db.commit()
                logger.info("Todo %s edited by user %s: %r", todo_id, current_user.id, title)
                flash("Todo updated.", "success")
                return redirect(url_for("todos.list_todos"))
            except Exception:
                logger.error("Failed to edit todo %s for user %s", todo_id, current_user.id, exc_info=True)
                flash("An error occurred while updating the todo.", "error")

    todo_tags = _get_todo_tags(db, todo_id)
    all_tags = _get_user_tags(db, current_user.id)
    return render_template("todos/edit.html", todo=todo, todo_tags=todo_tags, all_tags=all_tags)


@bp.route("/delete/<int:todo_id>", methods=["POST"])
@login_required
def delete(todo_id):
    """Delete a todo."""
    try:
        db = get_db()
        result = db.execute(
            "DELETE FROM todos WHERE id = ? AND user_id = ?",
            (todo_id, current_user.id),
        )
        db.commit()
    except Exception:
        logger.error("Failed to delete todo %s for user %s", todo_id, current_user.id, exc_info=True)
        flash("An error occurred while deleting the todo.", "error")
        return redirect(url_for("todos.list_todos"))

    if result.rowcount == 0:
        logger.warning("Delete failed: todo %s not found for user %s", todo_id, current_user.id)
        abort(404)

    logger.info("Todo %s deleted by user %s", todo_id, current_user.id)
    flash("Todo deleted.", "success")
    return redirect(url_for("todos.list_todos"))
