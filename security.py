import hmac
import secrets
import time
from functools import wraps
from flask import abort, flash, redirect, request, session, url_for

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
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if session.get("role") not in roles:
                abort(403)
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
    history = [t for t in _attempts.get(key, []) if now - t < 300]
    if len(history) >= 10:
        return False
    history.append(now)
    _attempts[key] = history
    return True
