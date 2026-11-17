"""In-app notification centre and small, idempotent event helpers."""
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from db import get_db, query_all, query_one
from security import roles_required

notifications_bp = Blueprint("notifications", __name__)


def notify_user(user_id, category, title, body, target_url=None, dedupe_key=None):
    """Create an in-app notification. A dedupe key makes webhook retries safe."""
    if not user_id:
        return
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT IGNORE INTO notifications
               (user_id,category,title,body,target_url,dedupe_key)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (int(user_id), category[:40], title[:160], body[:500],
             (target_url or "")[:500] or None, (dedupe_key or "")[:160] or None),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        current_app.logger.exception("Could not persist SmartBill notification")
    finally:
        cur.close()


def notify_superadmins(category, title, body, target_url=None, dedupe_key=None):
    try:
        rows = query_all("SELECT id FROM users WHERE role='super_admin' AND status='active'")
        for row in rows:
            key = f"{dedupe_key}:{row['id']}" if dedupe_key else None
            notify_user(row["id"], category, title, body, target_url, key)
    except Exception:
        current_app.logger.exception("Could not fan out SmartBill admin notification")


@notifications_bp.get("/notifications")
@roles_required("super_admin", "shopkeeper", "consumer")
def inbox():
    rows = query_all(
        """SELECT id,category,title,body,target_url,read_at,created_at
           FROM notifications WHERE user_id=%s
           ORDER BY created_at DESC,id DESC LIMIT 100""",
        (session["user_id"],),
    )
    unread = query_one(
        "SELECT COUNT(*) AS n FROM notifications WHERE user_id=%s AND read_at IS NULL",
        (session["user_id"],),
    )["n"]
    return render_template("notifications.html", notifications=rows, unread_count=unread)


@notifications_bp.post("/notifications/<int:notification_id>/read")
@roles_required("super_admin", "shopkeeper", "consumer")
def mark_read(notification_id):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE notifications SET read_at=CURRENT_TIMESTAMP WHERE id=%s AND user_id=%s AND read_at IS NULL",
            (notification_id, session["user_id"]),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    row = query_one(
        "SELECT target_url FROM notifications WHERE id=%s AND user_id=%s",
        (notification_id, session["user_id"]),
    )
    target = row.get("target_url") if row else None
    # Only redirect to local application paths; reject protocol-relative/external URLs.
    if target and target.startswith("/") and not target.startswith("//"):
        return redirect(target)
    return redirect(url_for("notifications.inbox"))


@notifications_bp.post("/notifications/read-all")
@roles_required("super_admin", "shopkeeper", "consumer")
def mark_all_read():
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE notifications SET read_at=CURRENT_TIMESTAMP WHERE user_id=%s AND read_at IS NULL",
            (session["user_id"],),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    flash("All notifications marked as read.", "success")
    return redirect(url_for("notifications.inbox"))
