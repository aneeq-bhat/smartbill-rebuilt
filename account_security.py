"""Token and SMTP helpers for SmartBill account verification and recovery."""
from __future__ import annotations

import hashlib
import secrets
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone

from flask import current_app, url_for
from db import get_db


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_token(user_id: int, purpose: str, hours: int) -> str:
    token = secrets.token_urlsafe(40)
    conn = get_db()
    cur = conn.cursor()
    try:
        # Invalidate previous outstanding tokens of the same purpose.
        cur.execute(
            "UPDATE account_security_tokens SET used_at=CURRENT_TIMESTAMP "
            "WHERE user_id=%s AND purpose=%s AND used_at IS NULL",
            (user_id, purpose),
        )
        expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=hours)
        cur.execute(
            "INSERT INTO account_security_tokens "
            "(user_id,purpose,token_hash,expires_at) VALUES (%s,%s,%s,%s)",
            (user_id, purpose, _token_hash(token), expires),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return token


def consume_token(token: str, purpose: str):
    """Atomically consume a valid token and return its user id, else None."""
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        conn.commit()
        conn.start_transaction()
        cur.execute(
            "SELECT id,user_id FROM account_security_tokens "
            "WHERE token_hash=%s AND purpose=%s AND used_at IS NULL "
            "AND expires_at>CURRENT_TIMESTAMP FOR UPDATE",
            (_token_hash(token), purpose),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return None
        cur.execute(
            "UPDATE account_security_tokens SET used_at=CURRENT_TIMESTAMP "
            "WHERE id=%s AND used_at IS NULL",
            (row["id"],),
        )
        conn.commit()
        return row["user_id"]
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def _send_email(recipient: str, subject: str, body: str) -> bool:
    cfg = current_app.config
    host = cfg.get("MAIL_SERVER")
    sender = cfg.get("MAIL_DEFAULT_SENDER")
    if not host or not sender:
        current_app.logger.warning("Email delivery skipped: SMTP is not configured.")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body)

    port = int(cfg.get("MAIL_PORT", 587))
    username = cfg.get("MAIL_USERNAME") or ""
    password = cfg.get("MAIL_PASSWORD") or ""
    use_ssl = bool(cfg.get("MAIL_USE_SSL"))
    use_tls = bool(cfg.get("MAIL_USE_TLS"))

    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
            if username:
                smtp.login(username, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.ehlo()
            if use_tls:
                smtp.starttls()
                smtp.ehlo()
            if username:
                smtp.login(username, password)
            smtp.send_message(msg)
    return True


def send_verification_email(user_id: int, email: str) -> bool:
    token = _issue_token(user_id, "verify_email", 24)
    link = url_for("account_security.verify_email", token=token, _external=True)
    body = (
        "Welcome to SmartBill. Verify your email address using this link:\n\n"
        f"{link}\n\nThis link expires in 24 hours. If you did not create this account, ignore this email."
    )
    return _send_email(email, "Verify your SmartBill email", body)


def send_password_reset_email(user_id: int, email: str) -> bool:
    token = _issue_token(user_id, "reset_password", 1)
    link = url_for("account_security.reset_password", token=token, _external=True)
    body = (
        "A password reset was requested for your SmartBill account. Use this link:\n\n"
        f"{link}\n\nThis link expires in one hour. If you did not request this, ignore this email."
    )
    return _send_email(email, "Reset your SmartBill password", body)
