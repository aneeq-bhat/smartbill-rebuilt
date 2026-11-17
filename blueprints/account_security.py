"""Email verification and password recovery routes."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash
from db import get_db, query_one
from security import login_limited
from account_security import consume_token, send_password_reset_email

account_security_bp = Blueprint("account_security", __name__)


@account_security_bp.route("/account/verify/<token>", methods=["GET", "POST"])
def verify_email(token):
    from account_security import _token_hash
    valid = query_one(
        """SELECT id FROM account_security_tokens
           WHERE token_hash=%s AND purpose='verify_email'
             AND used_at IS NULL AND expires_at>CURRENT_TIMESTAMP""",
        (_token_hash(token),),
    )
    if not valid:
        flash("That verification link is invalid, expired, or already used. Request a new one.", "warning")
        return redirect(url_for("account_security.resend_verification"))
    if request.method == "GET":
        return render_template("verify_email.html", token=token)

    user_id = consume_token(token, "verify_email")
    if not user_id:
        flash("That verification link has expired or already been used.", "warning")
        return redirect(url_for("account_security.resend_verification"))
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET email_verified=1 WHERE id=%s", (user_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    flash("Your email is verified. You can now sign in.", "success")
    return redirect(url_for("home"))


@account_security_bp.route("/account/verify/resend", methods=["GET", "POST"])
def resend_verification():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        if not login_limited(f"verify-resend:{request.remote_addr}:{email}"):
            flash("Please wait before requesting another verification email.", "warning")
            return redirect(url_for("auth.consumer_login"))
        user = query_one(
            "SELECT id,email,email_verified FROM users WHERE email=%s",
            (email,),
        ) if email else None
        if user and not user["email_verified"]:
            try:
                from account_security import send_verification_email
                sent = send_verification_email(user["id"], user["email"])
                if not sent:
                    flash("Email delivery is not configured yet. Contact the site administrator.", "warning")
                else:
                    flash("If the account needs verification, a new link has been sent.", "success")
            except Exception:
                from flask import current_app
                current_app.logger.exception("Verification email delivery failed")
                flash("Email delivery is temporarily unavailable. Try again later.", "warning")
        else:
            flash("If the account needs verification, a new link has been sent.", "info")
        return redirect(url_for("auth.consumer_login"))
    return render_template("resend_verification.html")


@account_security_bp.route("/account/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        allowed = login_limited(f"password-reset:{request.remote_addr}:{email}")
        user = query_one("SELECT id,email FROM users WHERE email=%s AND status='active'", (email,)) if email and allowed else None
        # Always show the same response to avoid account enumeration.
        if user:
            try:
                sent = send_password_reset_email(user["id"], user["email"])
                if not sent:
                    from flask import current_app
                    current_app.logger.warning("Password reset requested but SMTP is not configured.")
            except Exception:
                from flask import current_app
                current_app.logger.exception("Password reset email delivery failed")
        flash("If an active account exists for that email, password reset instructions will be sent.", "info")
        return redirect(url_for("auth.consumer_login"))
    return render_template("forgot_password.html")


@account_security_bp.route("/account/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    # Check token without consuming it on GET; consume only after a valid POST.
    from account_security import _token_hash
    user = query_one(
        """SELECT t.id,t.user_id FROM account_security_tokens t
           WHERE t.token_hash=%s AND t.purpose='reset_password'
             AND t.used_at IS NULL AND t.expires_at>CURRENT_TIMESTAMP""",
        (_token_hash(token),),
    )
    if not user:
        flash("That password reset link is invalid, expired, or already used.", "warning")
        return redirect(url_for("account_security.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if len(password) < 12:
            flash("Use a password with at least 12 characters.", "danger")
        elif password != confirm:
            flash("The passwords do not match.", "danger")
        else:
            conn = get_db()
            cur = conn.cursor(dictionary=True)
            try:
                conn.commit()
                conn.start_transaction()
                cur.execute(
                    """SELECT id,user_id FROM account_security_tokens
                       WHERE token_hash=%s AND purpose='reset_password'
                         AND used_at IS NULL AND expires_at>CURRENT_TIMESTAMP FOR UPDATE""",
                    (_token_hash(token),),
                )
                token_row = cur.fetchone()
                if not token_row:
                    conn.rollback()
                    flash("That password reset link has already been used or expired.", "warning")
                    return redirect(url_for("account_security.forgot_password"))
                cur.execute(
                    "UPDATE users SET password_hash=%s WHERE id=%s AND status='active'",
                    (generate_password_hash(password), token_row["user_id"]),
                )
                if cur.rowcount != 1:
                    conn.rollback()
                    flash("The account could not be updated. Contact support.", "danger")
                    return redirect(url_for("account_security.forgot_password"))
                # Consume this token and invalidate every other outstanding reset link atomically.
                cur.execute(
                    """UPDATE account_security_tokens SET used_at=CURRENT_TIMESTAMP
                       WHERE user_id=%s AND purpose='reset_password' AND used_at IS NULL""",
                    (token_row["user_id"],),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()
            flash("Password updated. Sign in with your new password.", "success")
            return redirect(url_for("auth.consumer_login"))
    return render_template("reset_password.html")
