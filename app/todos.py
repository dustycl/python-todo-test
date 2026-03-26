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


COMPLETED_DEFAULT_LIMIT = 20


@bp.route("/")
@login_required
def list_todos():
    """List all todos for the current user, with optional search and filters."""
    db = get_db()
    cur = db.cursor()
    today = date.today()

    # Keyword search
    q = request.args.get("q", "").strip()
    q_escaped = None
    if q:
        q_escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    # Status filter
    status = request.args.get("status", "all")

    # Due date filter
    due = request.args.get("due", "all")

    # Tag filter
    tag = request.args.get("tag", "all")

    # Completed section controls (only used when status == 'all')
    completed_window = request.args.get("completed_window", "7")
    try:
        completed_limit = max(1, min(200, int(request.args.get("completed_limit", COMPLETED_DEFAULT_LIMIT))))
    except ValueError:
        completed_limit = COMPLETED_DEFAULT_LIMIT

    if status != "all":
        # Filtered view: single query, existing behaviour
        clauses = ["todos.user_id = %s", "todos.deleted_at IS NULL"]
        params = [current_user.id]

        if q_escaped:
            clauses.append("title ILIKE %s ESCAPE '\\'")
            params.append(f"%{q_escaped}%")

        if status == "active":
            clauses.append("completed = false")
        elif status == "completed":
            clauses.append("completed = true")

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
        todo_ids = [t["id"] for t in todos]
        tags_map = _get_tags_for_todos(db, todo_ids)
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
            # Not used in filtered view
            active_todos=None,
            completed_todos=None,
            has_more_completed=False,
            has_older_completed=False,
            completed_window=completed_window,
            completed_limit=completed_limit,
        )

    # Default two-section view (status == 'all')
    # Build shared filter conditions for search and tag
    def _shared_clauses_params():
        clauses = ["todos.user_id = %s", "todos.deleted_at IS NULL"]
        params = [current_user.id]
        join = ""
        if q_escaped:
            clauses.append("title ILIKE %s ESCAPE '\\'")
            params.append(f"%{q_escaped}%")
        if tag and tag != "all":
            join = (
                " JOIN todo_tags tt ON todos.id = tt.todo_id"
                " JOIN tags tg ON tt.tag_id = tg.id"
            )
            clauses.append("tg.user_id = %s AND tg.name = %s")
            params.append(current_user.id)
            params.append(tag)
        return clauses, params, join

    # Active todos query (with due-date filter)
    a_clauses, a_params, a_join = _shared_clauses_params()
    a_clauses.append("completed = false")
    if due == "overdue":
        a_clauses.append("due_date IS NOT NULL AND due_date < %s")
        a_params.append(today.isoformat())
    elif due == "today":
        a_clauses.append("due_date = %s")
        a_params.append(today.isoformat())
    elif due == "week":
        week_end = (today + timedelta(days=6)).isoformat()
        a_clauses.append("due_date IS NOT NULL AND due_date >= %s AND due_date <= %s")
        a_params.append(today.isoformat())
        a_params.append(week_end)
    elif due == "none":
        a_clauses.append("due_date IS NULL")

    a_where = " AND ".join(a_clauses)
    cur.execute(
        f"SELECT todos.* FROM todos{a_join} WHERE {a_where} "
        "ORDER BY due_date IS NULL ASC, due_date ASC, created_at DESC",
        a_params,
    )
    active_todos = cur.fetchall()

    # Completed todos query (windowed + capped)
    c_clauses, c_params, c_join = _shared_clauses_params()
    c_clauses.append("completed = true")
    if completed_window == "7":
        c_clauses.append("completed_at >= NOW() - INTERVAL '7 days'")

    c_where = " AND ".join(c_clauses)
    cur.execute(
        f"SELECT todos.* FROM todos{c_join} WHERE {c_where} "
        "ORDER BY completed_at DESC NULLS LAST "
        f"LIMIT %s",
        c_params + [completed_limit + 1],
    )
    completed_rows = cur.fetchall()
    has_more_completed = len(completed_rows) > completed_limit
    completed_todos = completed_rows[:completed_limit]

    # Check if there are any completed todos older than 7 days (to show "Show older" link)
    has_older_completed = False
    if completed_window == "7":
        o_clauses, o_params, o_join = _shared_clauses_params()
        o_clauses.append("completed = true")
        o_clauses.append("(completed_at IS NULL OR completed_at < NOW() - INTERVAL '7 days')")
        o_where = " AND ".join(o_clauses)
        cur.execute(
            f"SELECT 1 FROM todos{o_join} WHERE {o_where} LIMIT 1",
            o_params,
        )
        has_older_completed = cur.fetchone() is not None

    # Combine for tags lookup
    all_todos = list(active_todos) + list(completed_todos)
    todo_ids = [t["id"] for t in all_todos]
    tags_map = _get_tags_for_todos(db, todo_ids)
    all_tags = _get_user_tags(db, current_user.id)

    # todos is used by the has_filters result count — combine both sections
    todos = all_todos

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
        active_todos=active_todos,
        completed_todos=completed_todos,
        has_more_completed=has_more_completed,
        has_older_completed=has_older_completed,
        completed_window=completed_window,
        completed_limit=completed_limit,
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
