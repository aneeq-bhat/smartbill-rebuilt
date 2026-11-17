"""Razorpay payment collection for SmartBill.

This first phase collects one customer payment for a multi-shop cart. Seller
splits/payouts are deliberately not attempted; those require Razorpay Route
activation and linked-account onboarding.
"""
import hashlib
import hmac
import json
import os
import uuid
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, abort, current_app, flash, redirect, request, session, url_for
from db import get_db, query_one
from security import roles_required

payments_bp = Blueprint("payments", __name__, url_prefix="/payments")


def _client():
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not key_secret:
        raise RuntimeError("Razorpay is not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.")
    try:
        import razorpay
    except ImportError as exc:
        raise RuntimeError("Razorpay SDK is missing. Install requirements.txt.") from exc
    return razorpay.Client(auth=(key_id, key_secret))


def _cart():
    raw = session.get("cart", {})
    if not isinstance(raw, dict):
        return {}
    clean = {}
    for key, value in raw.items():
        try:
            pid, qty = int(key), int(value)
            if pid > 0 and 1 <= qty <= 100:
                clean[str(pid)] = qty
        except (TypeError, ValueError):
            continue
    return clean


def _signature_valid(order_id, payment_id, signature):
    secret = os.getenv("RAZORPAY_KEY_SECRET", "").encode()
    message = f"{order_id}|{payment_id}".encode()
    expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return bool(secret and hmac.compare_digest(expected, signature or ""))


def _finalize_paid_order(razorpay_order_id, razorpay_payment_id):
    """Create per-shop orders exactly once after Razorpay payment is captured."""
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        conn.commit()
        conn.start_transaction()
        cur.execute("SELECT * FROM payment_transactions WHERE razorpay_order_id=%s FOR UPDATE", (razorpay_order_id,))
        payment = cur.fetchone()
        if not payment:
            raise LookupError("Payment reference was not found.")
        if payment["status"] == "paid":
            conn.commit()
            return True, "This payment has already been processed."
        if int(payment["consumer_user_id"]) != int(session.get("user_id", payment["consumer_user_id"])):
            raise PermissionError("This payment belongs to another account.")

        snapshot = json.loads(payment["cart_snapshot"])
        ids = sorted(int(item["product_id"]) for item in snapshot)
        if not ids:
            raise ValueError("The payment has no cart items.")
        marks = ",".join(["%s"] * len(ids))
        cur.execute(
            f"SELECT p.id,p.name,p.price,p.stock_qty,p.shop_id,p.is_listed,s.status shop_status "
            f"FROM products p JOIN shops s ON s.id=p.shop_id WHERE p.id IN ({marks}) ORDER BY p.id FOR UPDATE",
            tuple(ids),
        )
        rows = {int(row["id"]): row for row in cur.fetchall()}
        grouped = defaultdict(list)
        for item in snapshot:
            pid, qty = int(item["product_id"]), int(item["quantity"])
            product = rows.get(pid)
            if not product or not product["is_listed"] or product["shop_status"] != "active" or int(product["stock_qty"]) < qty:
                cur.execute("UPDATE payment_transactions SET status='paid_stock_conflict', razorpay_payment_id=%s WHERE id=%s",
                            (razorpay_payment_id, payment["id"]))
                conn.commit()
                return False, "Payment was received, but stock changed before order confirmation. Contact support for a refund."
            grouped[int(product["shop_id"])].append((product, qty))

        order_ids = []
        for shop_id, shop_items in grouped.items():
            total = sum((Decimal(str(p["price"])) * qty for p, qty in shop_items), Decimal("0.00"))
            cur.execute(
                "INSERT INTO orders (consumer_user_id,shop_id,total,payment_transaction_id) VALUES (%s,%s,%s,%s)",
                (payment["consumer_user_id"], shop_id, total, payment["id"]),
            )
            order_id = cur.lastrowid
            order_ids.append(order_id)
            for product, qty in shop_items:
                price = Decimal(str(product["price"]))
                cur.execute(
                    "INSERT INTO order_items (order_id,product_id,product_name,quantity,unit_price,line_total) VALUES (%s,%s,%s,%s,%s,%s)",
                    (order_id, product["id"], product["name"], qty, price, price * qty),
                )
                cur.execute("UPDATE products SET stock_qty=stock_qty-%s WHERE id=%s AND stock_qty>=%s",
                            (qty, product["id"], qty))
                if cur.rowcount != 1:
                    raise ValueError("Stock changed during order confirmation. Please contact support.")
        cur.execute("SELECT commission_bps FROM platform_commission_settings WHERE id=1")
        commission_row = cur.fetchone()
        commission_bps = int(commission_row["commission_bps"]) if commission_row else 0
        for ledger_order_id, (ledger_shop_id, ledger_items) in zip(order_ids, grouped.items()):
            ledger_gross = sum((Decimal(str(prod["price"])) * qty for prod, qty in ledger_items), Decimal("0.00"))
            gross_paise = int((ledger_gross * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            commission_paise = int((Decimal(gross_paise) * commission_bps / Decimal("10000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            cur.execute(
                "INSERT INTO seller_ledger (shop_id,order_id,payment_transaction_id,gross_paise,commission_bps,commission_paise,net_paise,status) VALUES (%s,%s,%s,%s,%s,%s,%s,'pending') ON DUPLICATE KEY UPDATE order_id=VALUES(order_id)",
                (ledger_shop_id, ledger_order_id, payment["id"], gross_paise, commission_bps, commission_paise, gross_paise - commission_paise),
            )
        cur.execute(
            "UPDATE payment_transactions SET status='paid',razorpay_payment_id=%s,order_ids=%s WHERE id=%s",
            (razorpay_payment_id, json.dumps(order_ids), payment["id"]),
        )
        shop_ids = list(grouped.keys())
        shop_marks = ",".join(["%s"] * len(shop_ids))
        cur.execute(f"SELECT id,name,owner_user_id FROM shops WHERE id IN ({shop_marks})", tuple(shop_ids))
        shop_owners = cur.fetchall()
        low_stock = []
        for shop_id, shop_items in grouped.items():
            for product, qty in shop_items:
                if int(product["stock_qty"]) - qty <= 5:
                    owner = next((s for s in shop_owners if int(s["id"]) == shop_id), None)
                    if owner:
                        low_stock.append((owner["owner_user_id"], product["id"], product["name"], int(product["stock_qty"]) - qty))
        conn.commit()
        from blueprints.notifications import notify_user
        consumer_target = "/consumer"
        notify_user(payment["consumer_user_id"], "payment", "Payment received",
                    f"Your payment was verified and order(s) {', '.join('#'+str(x) for x in order_ids)} were placed.",
                    consumer_target, f"payment-paid:{payment['id']}")
        for shop in shop_owners:
            shop_order_ids = []
            for order_id, (shop_id, _items) in zip(order_ids, grouped.items()):
                if int(shop_id) == int(shop["id"]):
                    shop_order_ids.append(order_id)
            if shop_order_ids:
                notify_user(shop["owner_user_id"], "new_order", "New paid order",
                            f"SmartBill received paid order(s) {', '.join('#'+str(x) for x in shop_order_ids)} for {shop['name']}.",
                            "/shopkeeper/orders", f"new-paid-order:{payment['id']}:shop:{shop['id']}")
        for owner_id, product_id, product_name, remaining in low_stock:
            notify_user(owner_id, "inventory", "Low stock alert",
                        f"{product_name} has {remaining} unit(s) remaining.",
                        "/shopkeeper/products", f"low-stock:{payment['id']}:{product_id}")
        if session.get("user_id") == int(payment["consumer_user_id"]):
            session["cart"] = {}
            session.modified = True
        return True, "Payment verified. Your order has been placed."
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


@payments_bp.post("/create")
@roles_required("consumer")
def create_payment():
    cart = _cart()
    if not cart:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("consumer.cart"))
    ids = sorted(int(pid) for pid in cart)
    rows = query_one("SELECT COUNT(*) AS total FROM products WHERE id IN (" + ",".join(["%s"] * len(ids)) + ")", tuple(ids))
    if not rows or int(rows["total"]) != len(ids):
        flash("A product in your cart is no longer available. Refresh your cart.", "warning")
        return redirect(url_for("consumer.cart"))

    marks = ",".join(["%s"] * len(ids))
    from db import query_all
    products = query_all(
        f"SELECT p.id,p.name,p.price,p.stock_qty,p.shop_id,p.is_listed,s.status shop_status "
        f"FROM products p JOIN shops s ON s.id=p.shop_id WHERE p.id IN ({marks})", tuple(ids)
    )
    by_id = {int(p["id"]): p for p in products}
    snapshot, total = [], Decimal("0.00")
    for pid in ids:
        p, qty = by_id.get(pid), int(cart[str(pid)])
        if not p or not p["is_listed"] or p["shop_status"] != "active" or int(p["stock_qty"]) < qty:
            flash("A product is unavailable or has insufficient stock. Update your cart.", "warning")
            return redirect(url_for("consumer.cart"))
        unit = Decimal(str(p["price"]))
        total += unit * qty
        snapshot.append({"product_id": pid, "quantity": qty})

    paise = int((total * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if paise < 100:
        flash("The minimum Razorpay payment amount is ₹1.00.", "warning")
        return redirect(url_for("consumer.cart"))
    try:
        client = _client()
        rz_order = client.order.create({"amount": paise, "currency": "INR", "receipt": f"sb_{uuid.uuid4().hex[:20]}",
                                        "notes": {"consumer_user_id": str(session["user_id"])}})
    except Exception as exc:
        current_app.logger.exception("Razorpay order creation failed")
        flash("Payment service is temporarily unavailable. Your cart has not been placed.", "danger")
        return redirect(url_for("consumer.cart"))

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO payment_transactions (consumer_user_id,razorpay_order_id,amount_paise,currency,status,cart_snapshot) "
            "VALUES (%s,%s,%s,'INR','created',%s)",
            (session["user_id"], rz_order["id"], paise, json.dumps(snapshot)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        current_app.logger.exception("Could not persist Razorpay order")
        flash("Could not start checkout. Please try again.", "danger")
        return redirect(url_for("consumer.cart"))
    finally:
        cur.close()

    return __import__("flask").render_template(
        "payment_checkout.html", key_id=os.getenv("RAZORPAY_KEY_ID"),
        razorpay_order_id=rz_order["id"], amount=paise, amount_rupees=total,
        name=session.get("name", "SmartBill customer"), email=query_one("SELECT email FROM users WHERE id=%s", (session["user_id"],))["email"],
        csrf=__import__("security").csrf_token(),
    )


@payments_bp.post("/verify")
@roles_required("consumer")
def verify_payment():
    order_id = request.form.get("razorpay_order_id", "")
    payment_id = request.form.get("razorpay_payment_id", "")
    signature = request.form.get("razorpay_signature", "")
    if not _signature_valid(order_id, payment_id, signature):
        abort(400, description="Razorpay payment signature verification failed.")
    try:
        client = _client()
        payment = client.payment.fetch(payment_id)
        if payment.get("order_id") != order_id:
            abort(400, description="Payment does not match the checkout order.")
        if payment.get("status") == "authorized":
            payment = client.payment.capture(payment_id, payment.get("amount"))
        if payment.get("status") != "captured":
            flash("Payment is not captured yet. Check your payment status before retrying.", "warning")
            return redirect(url_for("consumer.cart"))
        ok, message = _finalize_paid_order(order_id, payment_id)
        flash(message, "success" if ok else "danger")
    except (ValueError, LookupError, PermissionError) as exc:
        flash(str(exc), "danger")
    except Exception:
        current_app.logger.exception("Razorpay payment verification failed")
        flash("We could not verify this payment. If money was deducted, contact support with your Razorpay payment ID.", "danger")
    return redirect(url_for("consumer.dashboard"))


@payments_bp.post("/webhook")
def webhook():
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").encode()
    supplied = request.headers.get("X-Razorpay-Signature", "")
    body = request.get_data(cache=True)
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest() if secret else ""
    if not secret or not hmac.compare_digest(expected, supplied):
        abort(400)
    event = request.get_json(silent=True) or {}
    event_name = event.get("event")
    entity = ((event.get("payload") or {}).get("payment") or {}).get("entity") or {}
    if event_name == "payment.captured" and entity.get("order_id") and entity.get("id"):
        try:
            _finalize_paid_order(entity["order_id"], entity["id"])
        except Exception:
            current_app.logger.exception("Razorpay captured-payment webhook could not finalize order")
            return "retry", 500
    elif event_name == "payment.failed" and entity.get("order_id"):
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("UPDATE payment_transactions SET status='failed' WHERE razorpay_order_id=%s AND status='created'",
                        (entity["order_id"],))
            cur.execute("SELECT consumer_user_id,id FROM payment_transactions WHERE razorpay_order_id=%s",
                        (entity["order_id"],))
            failed_payment = cur.fetchone()
            conn.commit()
            if failed_payment:
                from blueprints.notifications import notify_user
                notify_user(failed_payment["consumer_user_id"], "payment", "Payment was not completed",
                            "Your payment attempt was not completed. You can return to your cart and try again.",
                            "/cart", f"payment-failed:{failed_payment['id']}")
        finally:
            cur.close()
    return "ok", 200
