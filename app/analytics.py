import logging

from flask import Blueprint, render_template
from flask_login import current_user, login_required

from app.db import get_db

logger = logging.getLogger(__name__)

bp = Blueprint("analytics", __name__)


@bp.route("/stats")
@login_required
def stats():
    """Per-user productivity analytics."""
    db = get_db()
    cur = db.cursor()

    # Overall summary stats
    cur.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE deleted_at IS NULL) AS total,
            COUNT(*) FILTER (WHERE completed = true AND deleted_at IS NULL) AS completed,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE completed = true AND deleted_at IS NULL)
                / NULLIF(COUNT(*) FILTER (WHERE deleted_at IS NULL), 0)
            ) AS completion_rate_pct,
            ROUND(AVG(
                EXTRACT(EPOCH FROM (completed_at - created_at)) / 3600
            ) FILTER (WHERE completed = true AND completed_at IS NOT NULL)) AS avg_hours_to_complete,
            COUNT(*) FILTER (
                WHERE due_date < CURRENT_DATE AND completed = false AND deleted_at IS NULL
            ) AS overdue_count
        FROM todos
        WHERE user_id = %s
        """,
        (current_user.id,),
    )
    summary = cur.fetchone()

    # Completion by day of week
    cur.execute(
        """
        SELECT
            TO_CHAR(completed_at, 'Dy') AS day_name,
            EXTRACT(DOW FROM completed_at) AS day_num,
            COUNT(*) AS completions
        FROM todos
        WHERE user_id = %s AND completed = true AND completed_at IS NOT NULL
            AND deleted_at IS NULL
        GROUP BY day_name, day_num
        ORDER BY day_num
        """,
        (current_user.id,),
    )
    by_day = cur.fetchall()

    # Avg time to complete by tag (secondary — only meaningful with enough data)
    cur.execute(
        """
        SELECT
            t.name AS tag,
            ROUND(AVG(
                EXTRACT(EPOCH FROM (todos.completed_at - todos.created_at)) / 3600
            )) AS avg_hours,
            COUNT(*) AS completed_count
        FROM todos
        JOIN todo_tags tt ON tt.todo_id = todos.id
        JOIN tags t ON t.id = tt.tag_id
        WHERE todos.user_id = %s AND todos.completed = true
            AND todos.completed_at IS NOT NULL AND todos.deleted_at IS NULL
        GROUP BY t.name
        HAVING COUNT(*) >= 3
        ORDER BY avg_hours ASC
        """,
        (current_user.id,),
    )
    time_by_tag = cur.fetchall()

    # Overdue rate by tag (secondary)
    cur.execute(
        """
        SELECT
            t.name AS tag,
            COUNT(*) AS total_with_due,
            COUNT(*) FILTER (WHERE todos.due_date < CURRENT_DATE AND todos.completed = false) AS overdue,
            ROUND(100.0 *
                COUNT(*) FILTER (WHERE todos.due_date < CURRENT_DATE AND todos.completed = false)
                / NULLIF(COUNT(*), 0)
            ) AS overdue_pct
        FROM todos
        JOIN todo_tags tt ON tt.todo_id = todos.id
        JOIN tags t ON t.id = tt.tag_id
        WHERE todos.user_id = %s AND todos.due_date IS NOT NULL
            AND todos.deleted_at IS NULL
        GROUP BY t.name
        HAVING COUNT(*) >= 3
        ORDER BY overdue_pct DESC
        """,
        (current_user.id,),
    )
    overdue_by_tag = cur.fetchall()

    # Hour of day: when todos are created
    cur.execute(
        """
        SELECT
            EXTRACT(HOUR FROM created_at)::int AS hour,
            COUNT(*) AS count
        FROM todos
        WHERE user_id = %s AND deleted_at IS NULL
        GROUP BY hour
        ORDER BY hour
        """,
        (current_user.id,),
    )
    hour_of_day_created = cur.fetchall()

    # Hour of day: when todos are completed
    cur.execute(
        """
        SELECT
            EXTRACT(HOUR FROM completed_at)::int AS hour,
            COUNT(*) AS count
        FROM todos
        WHERE user_id = %s AND completed = true AND completed_at IS NOT NULL
            AND deleted_at IS NULL
        GROUP BY hour
        ORDER BY hour
        """,
        (current_user.id,),
    )
    hour_of_day_completed = cur.fetchall()

    # Creation batching: sessions = consecutive todos created within 15 min
    cur.execute(
        """
        WITH gaps AS (
            SELECT id, created_at,
                   LAG(created_at) OVER (ORDER BY created_at) AS prev_created_at
            FROM todos WHERE user_id = %s AND deleted_at IS NULL
        ),
        sessions AS (
            SELECT id,
                   SUM(CASE WHEN prev_created_at IS NULL
                                 OR EXTRACT(EPOCH FROM (created_at - prev_created_at)) > 900
                            THEN 1 ELSE 0 END) OVER (ORDER BY created_at) AS session_id
            FROM gaps
        ),
        session_sizes AS (
            SELECT session_id, COUNT(*) AS session_size FROM sessions GROUP BY session_id
        )
        SELECT
            SUM(session_size) AS total_todos,
            COUNT(*) AS total_sessions,
            ROUND(SUM(session_size)::numeric / NULLIF(COUNT(*), 0), 1) AS avg_session_size,
            SUM(session_size) FILTER (WHERE session_size >= 2) AS todos_in_batches,
            ROUND(100.0 * SUM(session_size) FILTER (WHERE session_size >= 2)
                / NULLIF(SUM(session_size), 0)) AS pct_in_batches,
            ROUND(AVG(session_size) FILTER (WHERE session_size >= 2), 1) AS avg_batch_size
        FROM session_sizes
        """,
        (current_user.id,),
    )
    creation_batching = cur.fetchone()

    # Completion batching: sessions = consecutive completions within 15 min
    cur.execute(
        """
        WITH gaps AS (
            SELECT id, completed_at,
                   LAG(completed_at) OVER (ORDER BY completed_at) AS prev_completed_at
            FROM todos
            WHERE user_id = %s AND completed = true AND completed_at IS NOT NULL
                AND deleted_at IS NULL
        ),
        sessions AS (
            SELECT id,
                   SUM(CASE WHEN prev_completed_at IS NULL
                                 OR EXTRACT(EPOCH FROM (completed_at - prev_completed_at)) > 900
                            THEN 1 ELSE 0 END) OVER (ORDER BY completed_at) AS session_id
            FROM gaps
        ),
        session_sizes AS (
            SELECT session_id, COUNT(*) AS session_size FROM sessions GROUP BY session_id
        )
        SELECT
            SUM(session_size) AS total_todos,
            COUNT(*) AS total_sessions,
            ROUND(SUM(session_size)::numeric / NULLIF(COUNT(*), 0), 1) AS avg_session_size,
            SUM(session_size) FILTER (WHERE session_size >= 2) AS todos_in_batches,
            ROUND(100.0 * SUM(session_size) FILTER (WHERE session_size >= 2)
                / NULLIF(SUM(session_size), 0)) AS pct_in_batches,
            ROUND(AVG(session_size) FILTER (WHERE session_size >= 2), 1) AS avg_batch_size
        FROM session_sizes
        """,
        (current_user.id,),
    )
    completion_batching = cur.fetchone()

    logger.info("Stats page loaded for user %s", current_user.id)

    return render_template(
        "analytics/stats.html",
        summary=summary,
        by_day=by_day,
        time_by_tag=time_by_tag,
        overdue_by_tag=overdue_by_tag,
        hour_of_day_created=hour_of_day_created,
        hour_of_day_completed=hour_of_day_completed,
        creation_batching=creation_batching,
        completion_batching=completion_batching,
    )
