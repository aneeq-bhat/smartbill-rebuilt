import hmac
import secrets
import time
from functools import wraps

from flask import abort, flash, redirect, request, session, url_for

# Process-local throttling is a development/MVP safeguard. Use a shared store
# (Redis or an edge/WAF limiter) before running multiple production workers.
_attempts = {}


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def csrf_protect():
    if request.method == "POST":
        supplied = request.form.get("csrf_token", "")
        expected = session.get("_csrf", "")
        if not expected or not hmac.compare_digest(supplied, expected):
            abort(400, description="Your form session expired. Refresh the page and try again.")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in first.", "warning")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    """Require a live, active database account and the required role.

    Session role data is not authoritative: status/role changes in the
    database take effect on the next protected request.
    """
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            from db import query_one

            user = query_one(
                "SELECT id, name, role, status FROM users WHERE id=%s",
                (session.get("user_id"),),
            )
            if not user or user["status"] != "active":
                session.clear()
                flash("Your account is inactive. Please contact support.", "warning")
                return redirect(url_for("home"))
            if user["role"] not in roles or user["role"] != session.get("role"):
                abort(403)

            # Keep the display name current without trusting stale session data.
            session["name"] = user["name"]
            return view(*args, **kwargs)
        return wrapped
    return decorator


def rotate_session(user):
    session.clear()
    session["user_id"] = user["id"]
    session["role"] = user["role"]
    session["name"] = user["name"]
    session.permanent = True
    session["_csrf"] = secrets.token_urlsafe(32)


def login_limited(key):
    now = time.time()
    # Periodically discard stale keys to prevent unbounded process memory growth.
    if len(_attempts) > 5000:
        for old_key, timestamps in list(_attempts.items()):
            recent = [stamp for stamp in timestamps if now - stamp < 300]
            if recent:
                _attempts[old_key] = recent
            else:
                _attempts.pop(old_key, None)

    history = [stamp for stamp in _attempts.get(key, []) if now - stamp < 300]
    if len(history) >= 10:
        _attempts[key] = history
        return False
    history.append(now)
    _attempts[key] = history
    return True


def reset_login_attempts(key):
    _attempts.pop(key, None)
