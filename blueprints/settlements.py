from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from db import get_db, query_all, query_one
from security import roles_required

settlements_bp = Blueprint("settlements", __name__)


def _shop_for_user():
    shop = query_one(
        "SELECT id,name,status FROM shops WHERE owner_user_id=%s",
        (session.get("user_id"),),
    )
    if not shop or shop["status"] != "active":
        abort(403)
    return shop


@settlements_bp.route("/shopkeeper/settlements", methods=["GET", "POST"])
@roles_required("shopkeeper")
def seller_portal():
    shop = _shop_for_user()
    if request.method == "POST":
        legal_name = request.form.get("legal_business_name", "").strip()[:180]
        business_type = request.form.get("business_type", "").strip()[:80] or None
        phone = request.form.get("contact_phone", "").strip()[:40] or None
        address = request.form.get("business_address", "").strip() or None
        if not legal_name:
            flash("Enter the legal business name.", "danger")
        else:
            from db import execute
            execute(
                """INSERT INTO seller_onboarding
                   (shop_id,legal_business_name,business_type,contact_phone,business_address)
                   VALUES (%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE legal_business_name=VALUES(legal_business_name),
                   business_type=VALUES(business_type),contact_phone=VALUES(contact_phone),
                   business_address=VALUES(business_address)""",
                (shop["id"], legal_name, business_type, phone, address),
            )
            flash("Business profile saved. Document verification remains pending.", "success")
            return redirect(url_for("settlements.seller_portal"))

    onboarding = query_one("SELECT * FROM seller_onboarding WHERE shop_id=%s", (shop["id"],))
    ledger = query_all(
        """SELECT id,order_id,gross_paise,commission_paise,net_paise,status,created_at
           FROM seller_ledger WHERE shop_id=%s ORDER BY id DESC LIMIT 200""",
        (shop["id"],),
    )
    totals = query_one(
        """SELECT COALESCE(SUM(net_paise),0) net_total,
                  COALESCE(SUM(CASE WHEN status IN ('pending','eligible','held') THEN net_paise ELSE 0 END),0) outstanding,
                  COALESCE(SUM(CASE WHEN status='manual_paid' THEN net_paise ELSE 0 END),0) recorded_paid
           FROM seller_ledger WHERE shop_id=%s""", (shop["id"],)
    )
    return render_template("seller_settlements.html", shop=shop, onboarding=onboarding,
                           ledger=ledger, totals=totals)


@settlements_bp.get("/admin/settlements")
@roles_required("super_admin")
def admin_settlements():
    rows = query_all(
        """SELECT l.id,l.order_id,l.gross_paise,l.commission_paise,l.net_paise,l.status,l.created_at,
                  s.id shop_id,s.name shop_name,u.email,
                  o.status order_status,so.route_status,so.legal_business_name
           FROM seller_ledger l JOIN shops s ON s.id=l.shop_id
           JOIN users u ON u.id=s.owner_user_id JOIN orders o ON o.id=l.order_id
           LEFT JOIN seller_onboarding so ON so.shop_id=s.id
           ORDER BY l.id DESC LIMIT 500"""
    )
    settings = query_one("SELECT commission_bps FROM platform_commission_settings WHERE id=1")
    sellers = query_all(
        """SELECT s.id shop_id,s.name shop_name,u.email,so.legal_business_name,
                  so.pan_status,so.bank_status,so.address_status,so.route_status,
                  so.route_linked_account_id,so.admin_notes
           FROM shops s JOIN users u ON u.id=s.owner_user_id
           LEFT JOIN seller_onboarding so ON so.shop_id=s.id
           ORDER BY s.created_at DESC LIMIT 300"""
    )
    return render_template("admin_settlements.html", ledger=rows, sellers=sellers,
                           commission_bps=(settings or {}).get("commission_bps", 0))


@settlements_bp.post("/admin/settlements/commission")
@roles_required("super_admin")
def update_commission():
    try:
        rate = Decimal(request.form.get("commission_percent", "0"))
    except (InvalidOperation, TypeError):
        abort(400, description="Invalid commission percentage.")
    if not rate.is_finite() or rate < 0 or rate > 30:
        abort(400, description="Commission must be between 0 and 30 percent.")
    bps = int((rate * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    from db import execute
    execute(
        """INSERT INTO platform_commission_settings (id,commission_bps,updated_by)
           VALUES (1,%s,%s) ON DUPLICATE KEY UPDATE commission_bps=VALUES(commission_bps),
           updated_by=VALUES(updated_by)""",
        (bps, session["user_id"]),
    )
    flash("Commission setting updated. It applies to future paid orders only.", "success")
    return redirect(url_for("settlements.admin_settlements"))


@settlements_bp.post("/admin/settlements/<int:ledger_id>/hold")
@roles_required("super_admin")
def hold_ledger(ledger_id):
    from db import execute
    changed = execute(
        "UPDATE seller_ledger SET status='held' WHERE id=%s AND status IN ('pending','eligible')",
        (ledger_id,),
    )
    flash("Ledger entry placed on hold." if changed else "Ledger entry was not eligible for hold.", "info")
    return redirect(url_for("settlements.admin_settlements"))


@settlements_bp.post("/admin/settlements/<int:ledger_id>/release")
@roles_required("super_admin")
def release_ledger(ledger_id):
    from db import execute
    changed = execute(
        "UPDATE seller_ledger SET status='eligible' WHERE id=%s AND status='held'",
        (ledger_id,),
    )
    flash("Ledger entry marked eligible for manual settlement." if changed else "Ledger entry was not on hold.", "success")
    return redirect(url_for("settlements.admin_settlements"))


@settlements_bp.post("/admin/settlements/<int:ledger_id>/record-manual-payment")
@roles_required("super_admin")
def record_manual_payment(ledger_id):
    reference = request.form.get("payment_reference", "").strip()[:120]
    note = request.form.get("note", "").strip()[:500] or None
    if not reference:
        abort(400, description="Enter the external bank/UPI transfer reference.")
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        conn.commit()
        conn.start_transaction()
        cur.execute("SELECT * FROM seller_ledger WHERE id=%s FOR UPDATE", (ledger_id,))
        item = cur.fetchone()
        if not item or item["status"] not in ("pending", "eligible"):
            raise ValueError("Only pending or eligible ledger entries can be marked as manually paid.")
        cur.execute(
            """INSERT INTO seller_manual_settlements
               (ledger_id,amount_paise,payment_reference,note,recorded_by)
               VALUES (%s,%s,%s,%s,%s)""",
            (ledger_id, item["net_paise"], reference, note, session["user_id"]),
        )
        cur.execute("UPDATE seller_ledger SET status='manual_paid' WHERE id=%s", (ledger_id,))
        cur.execute("SELECT owner_user_id FROM shops WHERE id=%s", (item["shop_id"],))
        seller_owner = cur.fetchone()
        conn.commit()
        if seller_owner:
            from blueprints.notifications import notify_user
            notify_user(seller_owner["owner_user_id"], "settlement", "Settlement recorded",
                        f"A manual settlement for order #{item['order_id']} has been recorded in SmartBill.",
                        "/shopkeeper/settlements", f"seller-settlement:{ledger_id}:manual-paid")
        flash("Manual settlement recorded. No transfer was initiated by SmartBill.", "success")
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return redirect(url_for("settlements.admin_settlements"))


@settlements_bp.post("/admin/settlements/shops/<int:shop_id>/onboarding")
@roles_required("super_admin")
def update_onboarding(shop_id):
    allowed = {
        "pan_status": {"not_submitted", "submitted", "verified", "rejected"},
        "bank_status": {"not_submitted", "submitted", "verified", "rejected"},
        "address_status": {"not_submitted", "submitted", "verified", "rejected"},
        "route_status": {"not_applied", "submitted", "under_review", "approved", "rejected", "not_eligible"},
    }
    values = {}
    for field, choices in allowed.items():
        value = request.form.get(field, "not_submitted" if field != "route_status" else "not_applied")
        if value not in choices:
            abort(400, description=f"Invalid {field}.")
        values[field] = value
    notes = request.form.get("admin_notes", "").strip()[:2000] or None
    linked_id = request.form.get("route_linked_account_id", "").strip()[:100] or None
    if values["route_status"] != "approved":
        linked_id = None
    from db import execute
    execute(
        """INSERT INTO seller_onboarding
           (shop_id,pan_status,bank_status,address_status,route_status,route_linked_account_id,admin_notes)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE pan_status=VALUES(pan_status),bank_status=VALUES(bank_status),
           address_status=VALUES(address_status),route_status=VALUES(route_status),
           route_linked_account_id=VALUES(route_linked_account_id),admin_notes=VALUES(admin_notes)""",
        (shop_id, values["pan_status"], values["bank_status"], values["address_status"],
         values["route_status"], linked_id, notes),
    )
    flash("Seller onboarding status updated. Verify documents outside SmartBill before marking them verified.", "success")
    return redirect(url_for("settlements.admin_settlements"))
