"""Super-admin controlled Razorpay refund operations for SmartBill."""
import base64
import json
import os
import uuid
import urllib.error
import urllib.request
from decimal import Decimal

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from db import get_db, query_all, query_one
from security import roles_required

refunds_bp = Blueprint("refunds", __name__, url_prefix="/admin/refunds")


def _razorpay_request(payment_id, amount_paise, reason, idem_key):
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not key_secret:
        raise RuntimeError("Razorpay API credentials are not configured.")
    token = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
    payload = json.dumps({
        "amount": amount_paise,
        "receipt": idem_key[:40],
        "notes": {"smartbill_reason": reason[:200]},
    }).encode()
    req = urllib.request.Request(
        f"https://api.razorpay.com/v1/payments/{payment_id}/refund",
        data=payload,
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "X-Refund-Idempotency": idem_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"Razorpay rejected the refund request (HTTP {exc.code}): {body[:500]}") from exc


def _send_refund(refund_id):
    """Submit/retry a persisted refund using the same idempotency key and payload."""
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        conn.commit()
        conn.start_transaction()
        cur.execute("SELECT * FROM payment_refunds WHERE id=%s FOR UPDATE", (refund_id,))
        refund = cur.fetchone()
        if not refund:
            raise LookupError("Refund record not found.")
        if refund["status"] in ("processed", "failed"):
            conn.commit()
            return refund["status"]
        cur.execute("SELECT razorpay_payment_id,status FROM payment_transactions WHERE id=%s FOR UPDATE", (refund["payment_transaction_id"],))
        payment = cur.fetchone()
        if not payment or payment["status"] != "paid" or not payment["razorpay_payment_id"]:
            raise ValueError("Only captured, paid transactions can be refunded.")
        conn.commit()
    finally:
        cur.close()

    try:
        result = _razorpay_request(
            payment["razorpay_payment_id"], int(refund["amount_paise"]),
            refund["reason"], refund["idempotency_key"],
        )
        status = result.get("status", "pending")
        if status not in ("pending", "processed", "failed"):
            status = "pending"
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE payment_refunds SET razorpay_refund_id=%s,status=%s,response_json=%s WHERE id=%s",
                (result.get("id"), status, json.dumps(result), refund_id),
            )
            conn.commit()
        finally:
            cur.close()
        return status
    except Exception as exc:
        # Network failures are ambiguous: preserve the same idempotency key for safe retry.
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("UPDATE payment_refunds SET status='unknown',last_error=%s WHERE id=%s", (str(exc)[:1000], refund_id))
            conn.commit()
        finally:
            cur.close()
        raise


@refunds_bp.get("")
@roles_required("super_admin")
def index():
    rows = query_all(
        "SELECT r.id,r.payment_transaction_id,r.razorpay_refund_id,r.amount_paise,r.status,r.reason,r.created_at,"
        "p.razorpay_order_id,p.razorpay_payment_id,p.consumer_user_id,u.email "
        "FROM payment_refunds r JOIN payment_transactions p ON p.id=r.payment_transaction_id "
        "JOIN users u ON u.id=p.consumer_user_id ORDER BY r.created_at DESC LIMIT 200"
    )
    payments = query_all(
        "SELECT p.id,p.razorpay_payment_id,p.razorpay_order_id,p.amount_paise,p.consumer_user_id,u.email,"
        "COALESCE((SELECT SUM(r.amount_paise) FROM payment_refunds r WHERE r.payment_transaction_id=p.id AND r.status IN ('created','pending','processed','unknown')),0) refunded_paise "
        "FROM payment_transactions p JOIN users u ON u.id=p.consumer_user_id "
        "WHERE p.status='paid' AND p.razorpay_payment_id IS NOT NULL ORDER BY p.created_at DESC LIMIT 200"
    )
    for p in payments:
        p["remaining_paise"] = max(0, int(p["amount_paise"]) - int(p["refunded_paise"]))
    return render_template("admin_refunds.html", refunds=rows, payments=payments)


@refunds_bp.post("/create")
@roles_required("super_admin")
def create():
    try:
        payment_transaction_id = int(request.form.get("payment_transaction_id", ""))
        amount_paise = int(Decimal(request.form.get("amount_rupees", "0")) * 100)
        reason = (request.form.get("reason") or "Customer refund").strip()[:200]
    except Exception:
        abort(400, description="Enter a valid payment and refund amount.")
    if amount_paise <= 0 or not reason:
        abort(400, description="Refund amount and reason are required.")

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        conn.commit()
        conn.start_transaction()
        cur.execute("SELECT * FROM payment_transactions WHERE id=%s FOR UPDATE", (payment_transaction_id,))
        payment = cur.fetchone()
        if not payment or payment["status"] != "paid" or not payment["razorpay_payment_id"]:
            raise ValueError("Select a successfully captured payment.")
        cur.execute(
            "SELECT COALESCE(SUM(amount_paise),0) total FROM payment_refunds "
            "WHERE payment_transaction_id=%s AND status IN ('created','pending','processed','unknown') FOR UPDATE",
            (payment_transaction_id,),
        )
        already = int(cur.fetchone()["total"])
        remaining = int(payment["amount_paise"]) - already
        if amount_paise > remaining:
            raise ValueError(f"Refund exceeds remaining refundable balance (₹{remaining / 100:.2f}).")
        idem = "sbref_" + uuid.uuid4().hex
        cur.execute(
            "INSERT INTO payment_refunds (payment_transaction_id,amount_paise,reason,status,idempotency_key,created_by) "
            "VALUES (%s,%s,%s,'created',%s,%s)",
            (payment_transaction_id, amount_paise, reason, idem, session.get("user_id")),
        )
        refund_id = cur.lastrowid
        conn.commit()
    except Exception as exc:
        conn.rollback()
        flash(str(exc), "danger")
        return redirect(url_for("refunds.index"))
    finally:
        cur.close()

    try:
        status = _send_refund(refund_id)
        flash(f"Refund submitted to Razorpay. Current status: {status}.", "success")
    except Exception:
        current_app.logger.exception("Refund submission failed; refund record retained for safe retry")
        flash("Refund outcome is uncertain or failed. The record is retained; use Retry with the same idempotency key.", "warning")
    return redirect(url_for("refunds.index"))


@refunds_bp.post("/<int:refund_id>/retry")
@roles_required("super_admin")
def retry(refund_id):
    try:
        status = _send_refund(refund_id)
        flash(f"Refund status: {status}.", "success")
    except Exception:
        current_app.logger.exception("Refund retry failed")
        flash("Refund could not be confirmed. The same idempotent operation remains recorded.", "warning")
    return redirect(url_for("refunds.index"))


@refunds_bp.post("/webhook")
def webhook():
    import hashlib, hmac, os
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").encode()
    supplied = request.headers.get("X-Razorpay-Signature", "")
    body = request.get_data(cache=True)
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest() if secret else ""
    if not secret or not hmac.compare_digest(expected, supplied):
        abort(400)
    event = request.get_json(silent=True) or {}
    name = event.get("event")
    entity = (((event.get("payload") or {}).get("refund") or {}).get("entity") or {})
    if name in ("refund.processed", "refund.failed") and entity.get("id"):
        status = "processed" if name == "refund.processed" else "failed"
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("UPDATE payment_refunds SET status=%s,response_json=%s WHERE razorpay_refund_id=%s",
                        (status, json.dumps(entity), entity["id"]))
            cur.execute(
                """SELECT p.consumer_user_id,r.id FROM payment_refunds r
                   JOIN payment_transactions p ON p.id=r.payment_transaction_id
                   WHERE r.razorpay_refund_id=%s""", (entity["id"],)
            )
            refund_owner = cur.fetchone()
            conn.commit()
            if refund_owner:
                from blueprints.notifications import notify_user
                notify_user(refund_owner["consumer_user_id"], "refund_update", "Refund status updated",
                            f"Your refund is now marked {status}.",
                            "/consumer", f"refund-status:{refund_owner['id']}:{status}")
        finally:
            cur.close()
    return "ok", 200
