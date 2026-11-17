from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort, Response
from decimal import Decimal, InvalidOperation
from datetime import date, timedelta
from io import StringIO
import csv
import re

from db import query_all, query_one, execute, get_db
from security import roles_required
from gst_calculations import split_gst, money

shop_bp = Blueprint("shop", __name__, url_prefix="/shopkeeper")


def current_shop():
    shop = query_one(
        "SELECT id, name, status FROM shops WHERE owner_user_id=%s",
        (session["user_id"],)
    )
    if not shop or shop["status"] != "active":
        abort(403)
    return shop


@shop_bp.get("/")
@roles_required("shopkeeper")
def dashboard():
    shop = current_shop()
    stats = {
        "products": query_one(
            "SELECT COUNT(*) n FROM products WHERE shop_id=%s",
            (shop["id"],)
        )["n"],
        "invoices": query_one(
            "SELECT COUNT(*) n FROM invoices WHERE shop_id=%s",
            (shop["id"],)
        )["n"],
        "customers": query_one(
            "SELECT COUNT(*) n FROM customers WHERE shop_id=%s",
            (shop["id"],)
        )["n"],
        "orders": query_one(
            "SELECT COUNT(*) n FROM orders WHERE shop_id=%s",
            (shop["id"],)
        )["n"]
    }
    return render_template("shop_dashboard.html", shop=shop, stats=stats)


@shop_bp.route("/products", methods=["GET", "POST"])
@roles_required("shopkeeper")
def products():
    shop = current_shop()

    if request.method == "POST":
        name = request.form.get("name", "").strip()

        try:
            price = float(request.form.get("price", "0"))
        except ValueError:
            price = 0

        try:
            stock = int(request.form.get("stock", "0"))
        except ValueError:
            stock = -1

        if not name or price < 0 or stock < 0:
            flash("Enter a product name, valid price and non-negative stock.", "danger")
        else:
            hsn = request.form.get("hsn_sac", "").strip() or None
            try:
                gst_rate = Decimal(request.form.get("gst_rate", "0"))
                if not gst_rate.is_finite() or gst_rate < 0 or gst_rate > 100:
                    raise ValueError
            except (InvalidOperation, ValueError):
                flash("Enter a valid GST rate between 0 and 100.", "danger")
                return redirect(url_for("shop.products"))
            execute(
                "INSERT INTO products (shop_id, name, price, stock_qty, hsn_sac, gst_rate) VALUES (%s,%s,%s,%s,%s,%s)",
                (shop["id"], name, price, stock, hsn, gst_rate)
            )
            flash("Product added.", "success")
            return redirect(url_for("shop.products"))

    rows = query_all(
        """SELECT id, name, price, stock_qty, is_listed, hsn_sac, gst_rate
           FROM products WHERE shop_id=%s ORDER BY id DESC""",
        (shop["id"],)
    )
    return render_template("products.html", shop=shop, products=rows)


@shop_bp.post("/products/<int:product_id>/update")
@roles_required("shopkeeper")
def update_product(product_id):
    shop = current_shop()
    name = request.form.get("name", "").strip()
    try:
        price = Decimal(request.form.get("price", ""))
        stock = int(request.form.get("stock", ""))
        gst_rate = Decimal(request.form.get("gst_rate", "0"))
        if not gst_rate.is_finite() or gst_rate < 0 or gst_rate > 100:
            raise ValueError
        hsn = request.form.get("hsn_sac", "").strip() or None
    except (InvalidOperation, TypeError, ValueError):
        flash("Enter a valid price and stock quantity.", "danger")
        return redirect(url_for("shop.products"))

    if not name or not price.is_finite() or price < 0 or stock < 0:
        flash("Product name, non-negative price and non-negative stock are required.", "danger")
        return redirect(url_for("shop.products"))

    changed = execute(
        """UPDATE products SET name=%s, price=%s, stock_qty=%s, hsn_sac=%s, gst_rate=%s
           WHERE id=%s AND shop_id=%s""",
        (name, price, stock, hsn, gst_rate, product_id, shop["id"])
    )
    # MySQL connector reports affected rows; zero can also mean unchanged data.
    product = query_one(
        "SELECT id FROM products WHERE id=%s AND shop_id=%s",
        (product_id, shop["id"])
    )
    if not product:
        abort(404)
    flash("Product updated.", "success")
    return redirect(url_for("shop.products"))


@shop_bp.post("/products/<int:product_id>/toggle")
@roles_required("shopkeeper")
def toggle_product_listing(product_id):
    shop = current_shop()
    product = query_one(
        "SELECT id, is_listed FROM products WHERE id=%s AND shop_id=%s",
        (product_id, shop["id"])
    )
    if not product:
        abort(404)
    execute(
        "UPDATE products SET is_listed=%s WHERE id=%s AND shop_id=%s",
        (not bool(product["is_listed"]), product_id, shop["id"])
    )
    flash("Product listing updated.", "success")
    return redirect(url_for("shop.products"))


@shop_bp.get("/orders")
@roles_required("shopkeeper")
def orders():
    shop = current_shop()

    rows = query_all(
        """SELECT o.id, o.status, o.total, o.created_at,
                  u.name AS consumer_name,
                  (SELECT COUNT(*) FROM order_items oi
                   WHERE oi.order_id=o.id) AS item_count
           FROM orders o
           JOIN users u ON u.id=o.consumer_user_id
           WHERE o.shop_id=%s
           ORDER BY o.id DESC""",
        (shop["id"],)
    )

    return render_template("shop_orders.html", shop=shop, orders=rows)


@shop_bp.post("/orders/<int:order_id>/<action>")
@roles_required("shopkeeper")
def update_order(order_id, action):
    shop = current_shop()

    transitions = {
        "accept": ("placed", "accepted"),
        "pack": ("accepted", "packed"),
        "complete": ("packed", "completed"),
        "reject": ("placed", "rejected")
    }

    if action not in transitions:
        abort(400)

    expected_status, new_status = transitions[action]

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        # End the read transaction used to identify the current shop.
        conn.commit()
        conn.start_transaction()

        cur.execute(
            """SELECT id, consumer_user_id, status, stock_restored
               FROM orders
               WHERE id=%s AND shop_id=%s
               FOR UPDATE""",
            (order_id, shop["id"])
        )
        order = cur.fetchone()

        if not order:
            conn.rollback()
            abort(404)

        if order["status"] != expected_status:
            conn.rollback()
            flash("This order can no longer be updated with that action.", "warning")
            return redirect(url_for("shop.orders"))

        if action == "reject":
            if order["stock_restored"]:
                conn.rollback()
                flash("Stock has already been restored for this order.", "warning")
                return redirect(url_for("shop.orders"))

            cur.execute(
                """SELECT product_id, quantity
                   FROM order_items
                   WHERE order_id=%s""",
                (order_id,)
            )
            items = cur.fetchall()

            for item in items:
                cur.execute(
                    """UPDATE products
                       SET stock_qty = stock_qty + %s
                       WHERE id=%s AND shop_id=%s""",
                    (item["quantity"], item["product_id"], shop["id"])
                )

            cur.execute(
                """UPDATE orders
                   SET status=%s, stock_restored=1
                   WHERE id=%s AND shop_id=%s""",
                (new_status, order_id, shop["id"])
            )
            cur.execute("UPDATE seller_ledger SET status='reversed' WHERE order_id=%s AND status IN ('pending','held','eligible')", (order_id,))
        else:
            cur.execute(
                """UPDATE orders
                   SET status=%s
                   WHERE id=%s AND shop_id=%s""",
                (new_status, order_id, shop["id"])
            )

        conn.commit()
        from blueprints.notifications import notify_user
        notify_user(order["consumer_user_id"], "order_update", "Order status updated",
                    f"Your order #{order_id} is now {new_status.replace('_', ' ')}.",
                    "/consumer", f"order-status:{order_id}:{new_status}")
        flash(f"Order #{order_id} updated to {new_status}.", "success")

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()

    return redirect(url_for("shop.orders"))


@shop_bp.route("/customers", methods=["GET", "POST"])
@roles_required("shopkeeper")
def customers():
    shop = current_shop()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip() or None
        email = request.form.get("email", "").strip().lower() or None
        if not name or len(name) > 120:
            flash("Enter a customer name (maximum 120 characters).", "danger")
        elif email and ("@" not in email or len(email) > 190):
            flash("Enter a valid email address.", "danger")
        else:
            gstin = request.form.get("gstin", "").strip().upper() or None
            state_code = request.form.get("state_code", "").strip() or None
            if gstin and not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", gstin):
                flash("Customer GSTIN format is invalid.", "danger")
                return redirect(url_for("shop.customers"))
            if state_code and not re.fullmatch(r"[0-9]{2}", state_code):
                flash("Customer state code must contain two digits.", "danger")
                return redirect(url_for("shop.customers"))
            execute("INSERT INTO customers (shop_id,name,phone,email,gstin,state_code) VALUES (%s,%s,%s,%s,%s,%s)",
                    (shop["id"], name, phone, email, gstin, state_code))
            flash("Customer added.", "success")
            return redirect(url_for("shop.customers"))
    rows = query_all(
        """SELECT c.id,c.name,c.phone,c.email,c.created_at,
                  (SELECT COUNT(*) FROM invoices i WHERE i.customer_id=c.id AND i.shop_id=c.shop_id) invoice_count
           FROM customers c WHERE c.shop_id=%s ORDER BY c.id DESC""", (shop["id"],))
    return render_template("customers.html", shop=shop, customers=rows)


@shop_bp.route("/gst-settings", methods=["GET", "POST"])
@roles_required("shopkeeper")
def gst_settings():
    shop = current_shop()
    if request.method == "POST":
        gstin = request.form.get("gstin", "").strip().upper() or None
        state_code = request.form.get("state_code", "").strip() or None
        state_name = request.form.get("state_name", "").strip() or None
        registered = 1 if request.form.get("gst_registered") == "1" else 0
        if gstin and not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", gstin):
            flash("GSTIN format is invalid. Verify it before saving.", "danger")
            return redirect(url_for("shop.gst_settings"))
        if state_code and not re.fullmatch(r"[0-9]{2}", state_code):
            flash("State code must contain two digits.", "danger")
            return redirect(url_for("shop.gst_settings"))
        if registered and (not gstin or not state_code or not state_name):
            flash("Registered businesses must provide GSTIN, state code and state name.", "danger")
            return redirect(url_for("shop.gst_settings"))
        execute("UPDATE shops SET gstin=%s,state_code=%s,state_name=%s,gst_registered=%s WHERE id=%s", (gstin,state_code,state_name,registered,shop["id"]))
        flash("GST business settings saved.", "success")
        return redirect(url_for("shop.gst_settings"))
    settings = query_one("SELECT gstin,state_code,state_name,gst_registered FROM shops WHERE id=%s", (shop["id"],))
    return render_template("gst_settings.html", shop=shop, settings=settings)


@shop_bp.get("/invoices")
@roles_required("shopkeeper")
def invoices():
    shop = current_shop()
    rows = query_all(
        """SELECT i.id,i.invoice_number,i.subtotal,i.tax_total,i.grand_total,i.created_at,
                  COALESCE(c.name,'Walk-in customer') customer_name
           FROM invoices i LEFT JOIN customers c ON c.id=i.customer_id
           WHERE i.shop_id=%s ORDER BY i.id DESC""", (shop["id"],))
    return render_template("invoices.html", shop=shop, invoices=rows)


@shop_bp.route("/invoices/new", methods=["GET", "POST"])
@roles_required("shopkeeper")
def create_invoice():
    shop = current_shop()
    product_rows = query_all(
        "SELECT id,name,price,stock_qty,hsn_sac,gst_rate FROM products WHERE shop_id=%s ORDER BY name", (shop["id"],))
    customer_rows = query_all(
        "SELECT id,name,phone,gstin,state_code FROM customers WHERE shop_id=%s ORDER BY name", (shop["id"],))
    if request.method == "GET":
        return render_template("invoice_new.html", shop=shop, products=product_rows, customers=customer_rows)

    from datetime import datetime
    import secrets
    customer_raw = request.form.get("customer_id", "").strip()
    place_state = request.form.get("place_of_supply_state", "").strip()
    customer_gstin = request.form.get("customer_gstin", "").strip().upper() or None
    try:
        customer_id = int(customer_raw) if customer_raw else None
    except ValueError:
        flash("Invalid customer selection.", "danger")
        return redirect(url_for("shop.create_invoice"))
    if customer_id and not query_one("SELECT id FROM customers WHERE id=%s AND shop_id=%s", (customer_id, shop["id"])):
        abort(400, description="Invalid customer for this shop.")
    shop_gst = query_one("SELECT gstin,state_code,gst_registered FROM shops WHERE id=%s", (shop["id"],))
    if shop_gst and shop_gst.get("gst_registered") and not shop_gst.get("gstin"):
        flash("Add your GSTIN in GST settings before issuing a GST invoice.", "danger")
        return redirect(url_for("shop.gst_settings"))
    if shop_gst and shop_gst.get("gst_registered") and not shop_gst.get("state_code"):
        flash("Set your business state in GST settings before issuing a GST invoice.", "danger")
        return redirect(url_for("shop.gst_settings"))
    if not place_state:
        place_state = (shop_gst or {}).get("state_code") or ""
    if not re.fullmatch(r"[0-9]{2}", place_state):
        flash("Select a valid two-digit state code for place of supply.", "danger")
        return redirect(url_for("shop.create_invoice"))
    if customer_gstin and not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", customer_gstin):
        flash("Customer GSTIN format is invalid.", "danger")
        return redirect(url_for("shop.create_invoice"))
    requested = []
    try:
        for pid_raw, qty_raw in zip(request.form.getlist("product_id[]"), request.form.getlist("quantity[]")):
            if not pid_raw and not qty_raw:
                continue
            pid, qty = int(pid_raw), int(qty_raw)
            if pid <= 0 or qty <= 0:
                raise ValueError
            requested.append((pid, qty))
    except ValueError:
        flash("Choose valid products and positive quantities.", "danger")
        return redirect(url_for("shop.create_invoice"))
    if not requested:
        flash("Add at least one invoice item.", "danger")
        return redirect(url_for("shop.create_invoice"))
    # Merge repeated product rows before stock validation and deduction.
    quantities = {}
    for pid, qty in requested:
        quantities[pid] = quantities.get(pid, 0) + qty
    requested = list(quantities.items())

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        conn.commit()
        conn.start_transaction()
        lines, subtotal = [], Decimal("0.00")
        for pid, qty in requested:
            cur.execute("SELECT id,name,price,stock_qty,hsn_sac,gst_rate FROM products WHERE id=%s AND shop_id=%s FOR UPDATE", (pid, shop["id"]))
            product = cur.fetchone()
            if not product:
                raise ValueError("A selected product does not belong to this shop.")
            if int(product["stock_qty"]) < qty:
                raise ValueError(f"Insufficient stock for {product['name']}.")
            unit = Decimal(str(product["price"]))
            line_total = (unit * qty).quantize(Decimal("0.01"))
            subtotal += line_total
            effective_rate = (product.get("gst_rate") or 0) if (shop_gst or {}).get("gst_registered") else 0
            tax = split_gst(line_total, effective_rate, (shop_gst or {}).get("state_code"), place_state)
            lines.append((pid, product["name"], qty, unit, line_total, product.get("hsn_sac"), tax))
        tax_total = sum((line[6]["tax_total"] for line in lines), Decimal("0.00"))
        cgst_total = sum((line[6]["cgst"] for line in lines), Decimal("0.00"))
        sgst_total = sum((line[6]["sgst"] for line in lines), Decimal("0.00"))
        igst_total = sum((line[6]["igst"] for line in lines), Decimal("0.00"))
        grand_total = subtotal + tax_total
        invoice_number = f"SB-{shop['id']}-{datetime.now().strftime('%y%m%d%H%M%S')}-{secrets.token_hex(2).upper()}"
        cur.execute(
            "INSERT INTO invoices (shop_id,customer_id,invoice_number,subtotal,tax_total,grand_total,cgst_total,sgst_total,igst_total,place_of_supply_state,customer_gstin) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (shop["id"], customer_id, invoice_number, subtotal, tax_total, grand_total, cgst_total, sgst_total, igst_total, place_state or None, customer_gstin))
        invoice_id = cur.lastrowid
        for pid, item_name, qty, unit, line_total, hsn, tax in lines:
            cur.execute("INSERT INTO invoice_items (invoice_id,product_id,item_name,quantity,unit_price,line_total,hsn_sac,gst_rate,taxable_value,cgst_amount,sgst_amount,igst_amount) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (invoice_id, pid, item_name, qty, unit, line_total, hsn, tax["gst_rate"], tax["taxable_value"], tax["cgst"], tax["sgst"], tax["igst"]))
            cur.execute("UPDATE products SET stock_qty=stock_qty-%s WHERE id=%s AND shop_id=%s", (qty, pid, shop["id"]))
        conn.commit()
        flash(f"Invoice {invoice_number} created.", "success")
        return redirect(url_for("shop.invoice_detail", invoice_id=invoice_id))
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")
        return redirect(url_for("shop.create_invoice"))
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


@shop_bp.get("/invoices/<int:invoice_id>")
@roles_required("shopkeeper")
def invoice_detail(invoice_id):
    shop = current_shop()
    invoice = query_one(
        """SELECT i.*,COALESCE(c.name,'Walk-in customer') customer_name,c.phone customer_phone,c.email customer_email,
                  s.name shop_name,s.gstin shop_gstin,s.state_code supplier_state_code,s.state_name supplier_state_name
           FROM invoices i LEFT JOIN customers c ON c.id=i.customer_id
           JOIN shops s ON s.id=i.shop_id WHERE i.id=%s AND i.shop_id=%s""", (invoice_id, shop["id"]))
    if not invoice:
        abort(404)
    items = query_all("SELECT item_name,quantity,unit_price,line_total,hsn_sac,gst_rate,taxable_value,cgst_amount,sgst_amount,igst_amount FROM invoice_items WHERE invoice_id=%s ORDER BY id", (invoice_id,))
    return render_template("invoice_detail.html", shop=shop, invoice=invoice, items=items)


def _report_dates():
    """Validate optional ISO date filters; default to the current calendar month."""
    today = date.today()
    first = today.replace(day=1)
    raw_start = request.args.get("start", first.isoformat())
    raw_end = request.args.get("end", today.isoformat())
    try:
        start_date = date.fromisoformat(raw_start)
        end_date = date.fromisoformat(raw_end)
    except ValueError:
        abort(400, description="Dates must use YYYY-MM-DD format.")
    if start_date > end_date or (end_date - start_date).days > 366:
        abort(400, description="Choose a valid date range of no more than 367 days.")
    return start_date, end_date


@shop_bp.get("/gst-reports")
@roles_required("shopkeeper")
def gst_reports():
    shop = current_shop()
    start_date, end_date = _report_dates()
    params = (shop["id"], start_date, end_date)
    date_filter = "shop_id=%s AND DATE(created_at) BETWEEN %s AND %s"
    summary = query_one(f"""SELECT COUNT(*) invoice_count,COALESCE(SUM(subtotal),0) taxable_value,
        COALESCE(SUM(cgst_total),0) cgst,COALESCE(SUM(sgst_total),0) sgst,
        COALESCE(SUM(igst_total),0) igst,COALESCE(SUM(grand_total),0) invoice_value
        FROM invoices WHERE {date_filter}""", params)
    rates = query_all("""SELECT ii.gst_rate,COUNT(*) line_count,COALESCE(SUM(ii.taxable_value),0) taxable_value,
        COALESCE(SUM(ii.cgst_amount),0) cgst,COALESCE(SUM(ii.sgst_amount),0) sgst,
        COALESCE(SUM(ii.igst_amount),0) igst
        FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id
        WHERE i.shop_id=%s AND DATE(i.created_at) BETWEEN %s AND %s
        GROUP BY ii.gst_rate ORDER BY ii.gst_rate""", params)
    hsn = query_all("""SELECT COALESCE(NULLIF(ii.hsn_sac,''),'Not set') hsn_sac,
        SUM(ii.quantity) quantity,COUNT(*) line_count,COALESCE(SUM(ii.taxable_value),0) taxable_value,
        COALESCE(SUM(ii.cgst_amount),0) cgst,COALESCE(SUM(ii.sgst_amount),0) sgst,
        COALESCE(SUM(ii.igst_amount),0) igst
        FROM invoice_items ii JOIN invoices i ON i.id=ii.invoice_id
        WHERE i.shop_id=%s AND DATE(i.created_at) BETWEEN %s AND %s
        GROUP BY COALESCE(NULLIF(ii.hsn_sac,''),'Not set') ORDER BY hsn_sac""", params)
    return render_template("gst_reports.html", shop=shop, summary=summary, rates=rates,
                           hsn=hsn, start_date=start_date.isoformat(), end_date=end_date.isoformat())


@shop_bp.get("/gst-reports/export.csv")
@roles_required("shopkeeper")
def gst_reports_export():
    shop = current_shop()
    start_date, end_date = _report_dates()
    rows = query_all("""SELECT i.invoice_number,DATE_FORMAT(i.created_at,'%%Y-%%m-%%d %%H:%%i:%%s') invoice_date,
        COALESCE(c.name,'Walk-in customer') customer_name,i.customer_gstin,i.place_of_supply_state,
        ii.item_name,ii.hsn_sac,ii.quantity,ii.gst_rate,ii.taxable_value,
        ii.cgst_amount,ii.sgst_amount,ii.igst_amount,ii.line_total
        FROM invoices i JOIN invoice_items ii ON ii.invoice_id=i.id
        LEFT JOIN customers c ON c.id=i.customer_id
        WHERE i.shop_id=%s AND DATE(i.created_at) BETWEEN %s AND %s
        ORDER BY i.created_at,i.id,ii.id""", (shop["id"], start_date, end_date))
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Invoice number","Invoice date","Customer","Customer GSTIN","Place of supply","Item","HSN/SAC","Quantity","GST rate %","Taxable value INR","CGST INR","SGST INR","IGST INR","Line total INR"])
    for row in rows:
        writer.writerow([row.get(k) for k in ("invoice_number","invoice_date","customer_name","customer_gstin","place_of_supply_state","item_name","hsn_sac","quantity","gst_rate","taxable_value","cgst_amount","sgst_amount","igst_amount","line_total")])
    filename = f"smartbill-gst-{start_date.isoformat()}-to-{end_date.isoformat()}.csv"
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@shop_bp.get("/inventory")
@roles_required("shopkeeper")
def inventory():
    shop = current_shop()
    products = query_all("""SELECT id,name,sku,stock_qty,reorder_level,price
        FROM products WHERE shop_id=%s ORDER BY (stock_qty<=reorder_level) DESC,stock_qty,name""", (shop["id"],))
    movements = query_all("""SELECT m.id,m.movement_type,m.quantity_delta,m.stock_before,m.stock_after,
        m.reason,m.created_at,p.name product_name
        FROM inventory_movements m JOIN products p ON p.id=m.product_id
        WHERE m.shop_id=%s ORDER BY m.id DESC LIMIT 30""", (shop["id"],))
    return render_template("inventory.html", shop=shop, products=products, movements=movements)


@shop_bp.post("/inventory/<int:product_id>/adjust")
@roles_required("shopkeeper")
def adjust_inventory(product_id):
    shop = current_shop()
    try:
        delta = int(request.form.get("quantity_delta", ""))
        reorder_level = int(request.form.get("reorder_level", "5"))
    except ValueError:
        flash("Quantity and reorder level must be whole numbers.", "danger")
        return redirect(url_for("shop.inventory"))
    reason = request.form.get("reason", "").strip()
    if delta == 0 or abs(delta) > 100000 or reorder_level < 0 or reorder_level > 100000 or not reason or len(reason) > 240:
        flash("Enter a non-zero adjustment, valid reorder level and reason.", "danger")
        return redirect(url_for("shop.inventory"))
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        conn.commit()
        conn.start_transaction()
        cur.execute("SELECT id,stock_qty FROM products WHERE id=%s AND shop_id=%s FOR UPDATE", (product_id, shop["id"]))
        product = cur.fetchone()
        if not product:
            conn.rollback()
            abort(404)
        before = int(product["stock_qty"])
        after = before + delta
        if after < 0:
            conn.rollback()
            flash("Stock adjustment would make inventory negative.", "danger")
            return redirect(url_for("shop.inventory"))
        cur.execute("UPDATE products SET stock_qty=%s,reorder_level=%s WHERE id=%s AND shop_id=%s", (after,reorder_level,product_id,shop["id"]))
        cur.execute("""INSERT INTO inventory_movements
            (shop_id,product_id,movement_type,quantity_delta,stock_before,stock_after,reason,created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (shop["id"],product_id,"stock_in" if delta>0 else "stock_out",delta,before,after,reason,session["user_id"]))
        conn.commit()
        flash(f"Stock updated: {before} → {after} units.", "success")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return redirect(url_for("shop.inventory"))


@shop_bp.get("/analytics")
@roles_required("shopkeeper")
def analytics():
    """Shop-scoped analytics with a validated date range."""
    shop = current_shop()
    start_date, end_date = _report_dates()
    params = (shop["id"], start_date, end_date)
    summary = query_one("""SELECT COUNT(*) invoice_count,COALESCE(SUM(grand_total),0) invoice_revenue,
        COALESCE(AVG(grand_total),0) average_invoice FROM invoices
        WHERE shop_id=%s AND DATE(created_at) BETWEEN %s AND %s""", params)
    order_summary = query_one("""SELECT COUNT(*) order_count,COALESCE(SUM(total),0) order_value
        FROM orders WHERE shop_id=%s AND DATE(created_at) BETWEEN %s AND %s
        AND status NOT IN ('cancelled','rejected')""", params)
    inventory = query_one("""SELECT COUNT(*) product_count,COALESCE(SUM(stock_qty),0) units_in_stock,
        COALESCE(SUM(CASE WHEN stock_qty<=reorder_level THEN 1 ELSE 0 END),0) low_stock_count,
        COALESCE(SUM(CASE WHEN stock_qty=0 THEN 1 ELSE 0 END),0) out_of_stock_count
        FROM products WHERE shop_id=%s""", (shop["id"],))
    top_products = query_all("""SELECT oi.product_name,SUM(oi.quantity) units_sold,SUM(oi.line_total) sales_value
        FROM order_items oi JOIN orders o ON o.id=oi.order_id
        WHERE o.shop_id=%s AND DATE(o.created_at) BETWEEN %s AND %s
        AND o.status NOT IN ('cancelled','rejected')
        GROUP BY oi.product_id,oi.product_name ORDER BY units_sold DESC LIMIT 10""", params)
    daily_sales = query_all("""SELECT DATE(created_at) sales_day,COUNT(*) invoice_count,
        COALESCE(SUM(grand_total),0) revenue FROM invoices
        WHERE shop_id=%s AND DATE(created_at) BETWEEN %s AND %s
        GROUP BY DATE(created_at) ORDER BY sales_day""", params)
    recent_orders = query_all("""SELECT id,status,total,created_at FROM orders
        WHERE shop_id=%s AND DATE(created_at) BETWEEN %s AND %s
        ORDER BY created_at DESC LIMIT 10""", params)
    low_stock = query_all("""SELECT id,name,stock_qty,reorder_level,price FROM products
        WHERE shop_id=%s AND stock_qty<=reorder_level ORDER BY stock_qty ASC,name LIMIT 15""", (shop["id"],))
    return render_template("shop_analytics.html", shop=shop, summary=summary,
                           order_summary=order_summary, inventory=inventory,
                           top_products=top_products, recent_orders=recent_orders,
                           low_stock=low_stock, daily_sales=daily_sales,
                           start_date=start_date.isoformat(), end_date=end_date.isoformat())
