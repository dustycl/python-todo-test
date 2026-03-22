import logging
from datetime import date, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .db import get_db
from . import posthog_client

logger = logging.getLogger(__name__)


def _validate_due_date(raw):
    """Validate and return a due_date string, or None if empty.

    Raises ValueError on bad format.
    """
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
    cur = db.cursor()
    # Remove existing associations
    cur.execute("DELETE FROM todo_tags WHERE todo_id = %s", (todo_id,))

    for name in tag_names:
        # Insert tag if it doesn't exist for this user
        cur.execute(
            "INSERT INTO tags (user_id, name) VALUES (%s, %s) "
            "ON CONFLICT (user_id, name) DO NOTHING",
            (user_id, name),
        )
        cur.execute(
            "SELECT id FROM tags WHERE user_id = %s AND name = %s",
            (user_id, name),
        )
        tag = cur.fetchone()
        cur.execute(
            "INSERT INTO todo_tags (todo_id, tag_id) VALUES (%s, %s)",
            (todo_id, tag["id"]),
        )


def _get_user_tags(db, user_id):
    """Return all tag names for a user, ordered alphabetically."""
    cur = db.cursor()
    cur.execute(
        "SELECT DISTINCT name FROM tags WHERE user_id = %s ORDER BY name",
        (user_id,),
    )
    return [row["name"] for row in cur.fetchall()]


def _get_todo_tags(db, todo_id):
    """Return tag names for a specific todo."""
    cur = db.cursor()
    cur.execute(
        "SELECT t.name FROM tags t "
        "JOIN todo_tags tt ON t.id = tt.tag_id "
        "WHERE tt.todo_id = %s ORDER BY t.name",
        (todo_id,),
    )
    return [row["name"] for row in cur.fetchall()]


def _get_tags_for_todos(db, todo_ids):
    """Return a dict mapping todo_id -> list of tag names."""
    if not todo_ids:
        return {}
    cur = db.cursor()
    placeholders = ",".join("%s" for _ in todo_ids)
    cur.execute(
        f"SELECT tt.todo_id, t.name FROM tags t "
        f"JOIN todo_tags tt ON t.id = tt.tag_id "
        f"WHERE tt.todo_id IN ({placeholders}) ORDER BY t.name",
        todo_ids,
    )
    result = {tid: [] for tid in todo_ids}
    for row in cur.fetchall():
        result[row["todo_id"]].append(row["name"])
    return result


bp = Blueprint("todos", __name__)


@bp.route("/")
@login_required
def list_todos():
    """List all todos for the current user, with optional search and filters."""
    db = get_db()
    cur = db.cursor()
    today = date.today()

    # Base query — always filter by user (qualified for JOIN compatibility)
    clauses = ["todos.user_id = %s", "todos.deleted_at IS NULL"]
    params = [current_user.id]

    # Keyword search
    q = request.args.get("q", "").strip()
    if q:
        q_escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("title ILIKE %s ESCAPE '\\'")
        params.append(f"%{q_escaped}%")

    # Status filter
    status = request.args.get("status", "all")
    if status == "active":
        clauses.append("completed = false")
    elif status == "completed":
        clauses.append("completed = true")

    # Due date filter
    due = request.args.get("due", "all")
    if due == "overdue":
        clauses.append("due_date IS NOT NULL AND due_date < %s")
        params.append(today.isoformat())
    elif due == "today":
        clauses.append("due_date = %s")
        params.append(today.isoformat())
    elif due == "week":
        week_end = (today + timedelta(days=6)).isoformat()
        clauses.append("due_date IS NOT NULL AND due_date >= %s AND due_date <= %s")
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
        clauses.append("tg.user_id = %s AND tg.name = %s")
        params.append(current_user.id)
        params.append(tag)

    where = " AND ".join(clauses)
    cur.execute(
        f"SELECT todos.* FROM todos{join_clause} WHERE {where} "
        "ORDER BY completed ASC, due_date IS NULL ASC, due_date ASC, created_at DESC",
        params,
    )
    todos = cur.fetchall()

    # Fetch tags for all returned todos
    todo_ids = [t["id"] for t in todos]
    tags_map = _get_tags_for_todos(db, todo_ids)

    # All user tags for the filter dropdown and datalist
    all_tags = _get_user_tags(db, current_user.id)

    return render_template(
        "todos/list.html",
        todos=todos,
        today=today,
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
            cur = db.cursor()
            cur.execute(
                "INSERT INTO todos (user_id, title, due_date, description)"
                " VALUES (%s, %s, %s, %s) RETURNING id",
                (current_user.id, title, due_date, description),
            )
            todo_id = cur.fetchone()["id"]
            if tag_names:
                _sync_tags(db, current_user.id, todo_id, tag_names)
            db.commit()
            posthog_client.capture(current_user.id, "todo_created", {
                "has_due_date": due_date is not None,
                "has_tags": len(tag_names) > 0,
                "has_description": description is not None,
            })
            logger.info("Todo created by user %s: %r", current_user.id, title)
            flash("Todo added.", "success")
        except Exception:
            db.rollback()
            logger.error(
                "Failed to create todo for user %s", current_user.id, exc_info=True
            )
            flash("An error occurred while adding the todo.", "error")

    return redirect(url_for("todos.list_todos"))


@bp.route("/toggle/<int:todo_id>", methods=["POST"])
@login_required
def toggle(todo_id):
    """Toggle a todo's completed status."""
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "UPDATE todos SET completed = NOT completed,"
            " updated_at = CURRENT_TIMESTAMP,"
            " completed_at = CASE WHEN completed = false THEN CURRENT_TIMESTAMP ELSE NULL END"
            " WHERE id = %s AND user_id = %s AND deleted_at IS NULL",
            (todo_id, current_user.id),
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.error(
            "Failed to toggle todo %s for user %s",
            todo_id,
            current_user.id,
            exc_info=True,
        )
        flash("An error occurred while toggling the todo.", "error")
        return redirect(url_for("todos.list_todos"))

    if cur.rowcount == 0:
        logger.warning(
            "Toggle failed: todo %s not found for user %s", todo_id, current_user.id
        )
        abort(404)

    logger.info("Todo %s toggled by user %s", todo_id, current_user.id)
    return redirect(url_for("todos.list_todos"))


@bp.route("/edit/<int:todo_id>", methods=["GET", "POST"])
@login_required
def edit(todo_id):
    """Edit a todo's title."""
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT * FROM todos WHERE id = %s AND user_id = %s AND deleted_at IS NULL",
        (todo_id, current_user.id),
    )
    todo = cur.fetchone()

    if todo is None:
        logger.warning(
            "Edit failed: todo %s not found for user %s", todo_id, current_user.id
        )
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
                return render_template(
                    "todos/edit.html",
                    todo=todo,
                    todo_tags=_get_todo_tags(db, todo_id),
                    all_tags=_get_user_tags(db, current_user.id),
                )

            tag_names = _parse_tags(request.form.get("tags", ""))

            try:
                cur.execute(
                    "UPDATE todos SET title = %s, due_date = %s,"
                    " description = %s, updated_at = CURRENT_TIMESTAMP"
                    " WHERE id = %s AND user_id = %s AND deleted_at IS NULL",
                    (title, due_date, description, todo_id, current_user.id),
                )
                _sync_tags(db, current_user.id, todo_id, tag_names)
                db.commit()
                logger.info(
                    "Todo %s edited by user %s: %r", todo_id, current_user.id, title
                )
                flash("Todo updated.", "success")
                return redirect(url_for("todos.list_todos"))
            except Exception:
                db.rollback()
                logger.error(
                    "Failed to edit todo %s for user %s",
                    todo_id,
                    current_user.id,
                    exc_info=True,
                )
                flash("An error occurred while updating the todo.", "error")

    todo_tags = _get_todo_tags(db, todo_id)
    all_tags = _get_user_tags(db, current_user.id)
    return render_template(
        "todos/edit.html", todo=todo, todo_tags=todo_tags, all_tags=all_tags
    )


@bp.route("/delete/<int:todo_id>", methods=["POST"])
@login_required
def delete(todo_id):
    """Soft-delete a todo (sets deleted_at instead of removing the row)."""
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "UPDATE todos SET deleted_at = NOW() "
            "WHERE id = %s AND user_id = %s AND deleted_at IS NULL",
            (todo_id, current_user.id),
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.error(
            "Failed to delete todo %s for user %s",
            todo_id,
            current_user.id,
            exc_info=True,
        )
        flash("An error occurred while deleting the todo.", "error")
        return redirect(url_for("todos.list_todos"))

    if cur.rowcount == 0:
        logger.warning(
            "Delete failed: todo %s not found for user %s", todo_id, current_user.id
        )
        abort(404)

    posthog_client.capture(current_user.id, "todo_deleted")
    logger.info("Todo %s soft-deleted by user %s", todo_id, current_user.id)
    undo_url = url_for("todos.restore", todo_id=todo_id)
    flash(
        f'Todo deleted. <a href="#" class="undo-link"'
        f' data-restore-url="{undo_url}">Undo</a>',
        "success",
    )
    return redirect(url_for("todos.list_todos"))


@bp.route("/restore/<int:todo_id>", methods=["POST"])
@login_required
def restore(todo_id):
    """Restore a soft-deleted todo (undo delete)."""
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "UPDATE todos SET deleted_at = NULL "
            "WHERE id = %s AND user_id = %s AND deleted_at IS NOT NULL",
            (todo_id, current_user.id),
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.error(
            "Failed to restore todo %s for user %s",
            todo_id,
            current_user.id,
            exc_info=True,
        )
        flash("An error occurred while restoring the todo.", "error")
        return redirect(url_for("todos.list_todos"))

    if cur.rowcount == 0:
        logger.warning(
            "Restore failed: todo %s not found or not deleted for user %s",
            todo_id,
            current_user.id,
        )
        abort(404)

    logger.info("Todo %s restored by user %s", todo_id, current_user.id)
    flash("Todo restored.", "success")
    return redirect(url_for("todos.list_todos"))
