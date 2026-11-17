from collections import defaultdict
from decimal import Decimal
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from db import query_all, query_one, get_db
from security import roles_required

consumer_bp = Blueprint("consumer", __name__)


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


@consumer_bp.get("/marketplace")
def marketplace():
    search = request.args.get("q", "").strip()[:80]
    sort = request.args.get("sort", "relevance")
    order_by = {
        "price_low": "p.price ASC, p.name ASC",
        "price_high": "p.price DESC, p.name ASC",
        "name": "p.name ASC, s.name ASC",
        "shop": "s.name ASC, p.name ASC",
        "relevance": "s.name ASC, p.name ASC",
    }.get(sort, "s.name ASC, p.name ASC")
    sql = """SELECT p.id,p.name,p.description,p.price,p.stock_qty,s.name shop_name,s.id shop_id
             FROM products p JOIN shops s ON s.id=p.shop_id
             WHERE p.is_listed=1 AND p.stock_qty>0 AND s.status='active'"""
    params = []
    if search:
        sql += " AND (p.name LIKE %s OR COALESCE(p.description,'') LIKE %s OR s.name LIKE %s)"
        term = f"%{search}%"
        params.extend([term, term, term])
    sql += f" ORDER BY {order_by} LIMIT 100"
    products = query_all(sql, tuple(params))
    return render_template("marketplace.html", products=products, cart_count=sum(_cart().values()), search=search, sort=sort)


@consumer_bp.get("/marketplace/product/<int:product_id>")
def product_detail(product_id):
    product = query_one("""SELECT p.id,p.name,p.description,p.price,p.stock_qty,s.name shop_name,
                                s.id shop_id,s.address shop_address,s.description shop_description
                         FROM products p JOIN shops s ON s.id=p.shop_id
                         WHERE p.id=%s AND p.is_listed=1 AND p.stock_qty>0 AND s.status='active'""", (product_id,))
    if not product:
        abort(404)
    return render_template("product_detail.html", product=product, cart_count=sum(_cart().values()))


@consumer_bp.get("/cart")
@roles_required("consumer")
def cart():
    items = []
    cart_data = _cart()
    if cart_data:
        ids = [int(pid) for pid in cart_data]
        marks = ",".join(["%s"] * len(ids))
        rows = query_all(f"""SELECT p.id,p.name,p.price,p.stock_qty,p.shop_id,s.name shop_name,s.status shop_status,p.is_listed
                             FROM products p JOIN shops s ON s.id=p.shop_id
                             WHERE p.id IN ({marks})""", tuple(ids))
        by_id = {str(row["id"]): row for row in rows}
        for pid, qty in cart_data.items():
            product = by_id.get(pid)
            if not product or not product["is_listed"] or product["shop_status"] != "active":
                continue
            quantity = min(qty, int(product["stock_qty"]))
            if quantity < 1:
                continue
            product["quantity"] = quantity
            product["line_total"] = Decimal(str(product["price"])) * quantity
            items.append(product)
    subtotal = sum((item["line_total"] for item in items), Decimal("0.00"))
    return render_template("cart.html", items=items, subtotal=subtotal, cart_count=sum(_cart().values()))


@consumer_bp.post("/cart/add/<int:product_id>")
@roles_required("consumer")
def cart_add(product_id):
    product = query_one("""SELECT p.id,p.stock_qty FROM products p JOIN shops s ON s.id=p.shop_id
                           WHERE p.id=%s AND p.is_listed=1 AND s.status='active'""", (product_id,))
    if not product or int(product["stock_qty"]) < 1:
        flash("This product is currently unavailable.", "warning")
        return redirect(url_for("consumer.marketplace"))
    try:
        quantity = int(request.form.get("quantity", "1"))
    except ValueError:
        quantity = 0
    if quantity < 1 or quantity > 100:
        abort(400)
    cart_data = _cart()
    cart_data[str(product_id)] = min(int(product["stock_qty"]), cart_data.get(str(product_id), 0) + quantity)
    session["cart"] = cart_data
    session.modified = True
    flash("Added to your cart.", "success")
    return redirect(url_for("consumer.cart"))


@consumer_bp.post("/cart/update/<int:product_id>")
@roles_required("consumer")
def cart_update(product_id):
    cart_data = _cart()
    if str(product_id) not in cart_data:
        abort(404)
    try:
        quantity = int(request.form.get("quantity", "1"))
    except ValueError:
        quantity = 0
    if quantity <= 0:
        cart_data.pop(str(product_id), None)
    elif quantity > 100:
        abort(400)
    else:
        cart_data[str(product_id)] = quantity
    session["cart"] = cart_data
    session.modified = True
    return redirect(url_for("consumer.cart"))


@consumer_bp.post("/cart/remove/<int:product_id>")
@roles_required("consumer")
def cart_remove(product_id):
    cart_data = _cart()
    cart_data.pop(str(product_id), None)
    session["cart"] = cart_data
    session.modified = True
    flash("Item removed from cart.", "info")
    return redirect(url_for("consumer.cart"))


@consumer_bp.post("/cart/checkout")
@roles_required("consumer")
def checkout():
    cart_data = _cart()
    if not cart_data:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("consumer.cart"))
    ids = sorted(int(pid) for pid in cart_data)
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        conn.commit()
        conn.start_transaction()
        placeholders = ",".join(["%s"] * len(ids))
        cur.execute(f"""SELECT p.id,p.name,p.price,p.stock_qty,p.shop_id,s.status shop_status,p.is_listed
                         FROM products p JOIN shops s ON s.id=p.shop_id
                         WHERE p.id IN ({placeholders}) ORDER BY p.id FOR UPDATE""", tuple(ids))
        rows = cur.fetchall()
        products = {int(row["id"]): row for row in rows}
        grouped = defaultdict(list)
        for pid in ids:
            product = products.get(pid)
            qty = int(cart_data[str(pid)])
            if not product or not product["is_listed"] or product["shop_status"] != "active":
                raise ValueError("A product in your cart is no longer available. Review your cart.")
            if int(product["stock_qty"]) < qty:
                raise ValueError(f"Insufficient stock for {product['name']}. Update your cart quantity.")
            grouped[int(product["shop_id"])].append((product, qty))
        order_ids = []
        for shop_id, shop_items in grouped.items():
            total = sum((Decimal(str(p["price"])) * qty for p, qty in shop_items), Decimal("0.00"))
            cur.execute("INSERT INTO orders (consumer_user_id,shop_id,total) VALUES (%s,%s,%s)",
                        (session["user_id"], shop_id, total))
            order_id = cur.lastrowid
            order_ids.append(order_id)
            for product, qty in shop_items:
                price = Decimal(str(product["price"]))
                line_total = price * qty
                cur.execute("""INSERT INTO order_items (order_id,product_id,product_name,quantity,unit_price,line_total)
                               VALUES (%s,%s,%s,%s,%s,%s)""",
                            (order_id, product["id"], product["name"], qty, price, line_total))
                cur.execute("UPDATE products SET stock_qty=stock_qty-%s WHERE id=%s AND shop_id=%s",
                            (qty, product["id"], shop_id))
        conn.commit()
        session["cart"] = {}
        session.modified = True
        flash("Checkout complete. Order reference(s): " + ", ".join(f"#{oid}" for oid in order_ids) + ". Payment and delivery are not integrated yet.", "success")
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "warning")
        return redirect(url_for("consumer.cart"))
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return redirect(url_for("consumer.dashboard"))


@consumer_bp.get("/consumer")
@roles_required("consumer")
def dashboard():
    orders = query_all("""SELECT o.id,o.status,o.total,o.created_at,s.name shop_name,
                               (SELECT COUNT(*) FROM order_items oi WHERE oi.order_id=o.id) item_count
                        FROM orders o JOIN shops s ON s.id=o.shop_id
                        WHERE o.consumer_user_id=%s ORDER BY o.id DESC""", (session["user_id"],))
    return render_template("consumer_dashboard.html", orders=orders, cart_count=sum(_cart().values()))


@consumer_bp.post("/marketplace/order/<int:product_id>")
@roles_required("consumer")
def place_order(product_id):
    # Backward-compatible endpoint: send the old single-item order form through cart checkout.
    try:
        qty = int(request.form.get("quantity", "1"))
    except ValueError:
        qty = 0
    if qty < 1 or qty > 100:
        abort(400)
    cart_data = _cart()
    cart_data[str(product_id)] = min(100, cart_data.get(str(product_id), 0) + qty)
    session["cart"] = cart_data
    session.modified = True
    return redirect(url_for("consumer.cart"))


@consumer_bp.get("/consumer/wishlist")
@roles_required("consumer")
def wishlist():
    items = query_all("""SELECT p.id,p.name,p.price,p.stock_qty,s.name shop_name
                        FROM wishlist_items w JOIN products p ON p.id=w.product_id
                        JOIN shops s ON s.id=p.shop_id
                        WHERE w.user_id=%s AND p.is_listed=1 AND s.status='active'
                        ORDER BY w.created_at DESC""", (session["user_id"],))
    return render_template("wishlist.html", items=items, cart_count=sum(_cart().values()))


@consumer_bp.post("/consumer/wishlist/<int:product_id>/add")
@roles_required("consumer")
def wishlist_add(product_id):
    product = query_one("""SELECT p.id FROM products p JOIN shops s ON s.id=p.shop_id
                           WHERE p.id=%s AND p.is_listed=1 AND p.stock_qty>0 AND s.status='active'""", (product_id,))
    if not product:
        abort(404)
    from db import execute
    execute("INSERT IGNORE INTO wishlist_items (user_id,product_id) VALUES (%s,%s)",
            (session["user_id"], product_id))
    flash("Saved to your wishlist.", "success")
    return redirect(request.referrer or url_for("consumer.wishlist"))


@consumer_bp.post("/consumer/wishlist/<int:product_id>/remove")
@roles_required("consumer")
def wishlist_remove(product_id):
    from db import execute
    execute("DELETE FROM wishlist_items WHERE user_id=%s AND product_id=%s",
            (session["user_id"], product_id))
    flash("Removed from your wishlist.", "info")
    return redirect(url_for("consumer.wishlist"))


@consumer_bp.route("/consumer/addresses", methods=["GET", "POST"])
@roles_required("consumer")
def addresses():
    if request.method == "POST":
        fields = {key: request.form.get(key, "").strip() for key in
                  ("label", "recipient_name", "phone", "address_line1", "address_line2", "city", "state", "postal_code")}
        required = ("recipient_name", "phone", "address_line1", "city", "state", "postal_code")
        if any(not fields[k] for k in required):
            flash("Complete all required address fields.", "danger")
        elif any(len(fields[k]) > limit for k, limit in (("recipient_name",120),("phone",40),("address_line1",255),("address_line2",255),("city",100),("state",100),("postal_code",20),("label",40))):
            flash("One or more address fields are too long.", "danger")
        else:
            conn = get_db()
            cur = conn.cursor()
            try:
                cur.execute("SELECT COUNT(*) FROM customer_addresses WHERE user_id=%s", (session["user_id"],))
                count = cur.fetchone()[0]
                make_default = request.form.get("is_default") == "1" or count == 0
                if make_default:
                    cur.execute("UPDATE customer_addresses SET is_default=0 WHERE user_id=%s", (session["user_id"],))
                cur.execute("""INSERT INTO customer_addresses
                    (user_id,label,recipient_name,phone,address_line1,address_line2,city,state,postal_code,is_default)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (session["user_id"], fields["label"] or "Home", fields["recipient_name"], fields["phone"],
                     fields["address_line1"], fields["address_line2"] or None, fields["city"], fields["state"],
                     fields["postal_code"], make_default))
                conn.commit()
                flash("Address saved.", "success")
                return redirect(url_for("consumer.addresses"))
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()
    saved = query_all("SELECT * FROM customer_addresses WHERE user_id=%s ORDER BY is_default DESC, id DESC", (session["user_id"],))
    return render_template("addresses.html", addresses=saved, cart_count=sum(_cart().values()))


@consumer_bp.post("/consumer/addresses/<int:address_id>/default")
@roles_required("consumer")
def address_default(address_id):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE customer_addresses SET is_default=0 WHERE user_id=%s", (session["user_id"],))
        cur.execute("UPDATE customer_addresses SET is_default=1 WHERE id=%s AND user_id=%s", (address_id, session["user_id"]))
        if cur.rowcount != 1:
            conn.rollback()
            abort(404)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    flash("Default address updated.", "success")
    return redirect(url_for("consumer.addresses"))


@consumer_bp.post("/consumer/addresses/<int:address_id>/delete")
@roles_required("consumer")
def address_delete(address_id):
    from db import execute
    execute("DELETE FROM customer_addresses WHERE id=%s AND user_id=%s", (address_id, session["user_id"]))
    flash("Address removed.", "info")
    return redirect(url_for("consumer.addresses"))


@consumer_bp.route("/consumer/profile", methods=["GET", "POST"])
@roles_required("consumer")
def profile():
    user = query_one("SELECT id,name,email FROM users WHERE id=%s AND role='consumer'", (session["user_id"],))
    if not user:
        abort(404)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name or len(name) > 120:
            flash("Enter a name of up to 120 characters.", "danger")
        else:
            from db import execute
            execute("UPDATE users SET name=%s WHERE id=%s AND role='consumer'", (name, session["user_id"]))
            session["name"] = name
            flash("Profile updated.", "success")
            return redirect(url_for("consumer.profile"))
    return render_template("profile.html", user=user, cart_count=sum(_cart().values()))


@consumer_bp.get("/consumer/orders/<int:order_id>")
@roles_required("consumer")
def order_detail(order_id):
    order = query_one("""SELECT o.id,o.status,o.total,o.created_at,s.name shop_name,s.address shop_address
                         FROM orders o JOIN shops s ON s.id=o.shop_id
                         WHERE o.id=%s AND o.consumer_user_id=%s""", (order_id, session["user_id"]))
    if not order:
        abort(404)
    items = query_all("SELECT product_name,quantity,unit_price,line_total FROM order_items WHERE order_id=%s", (order_id,))
    stages = ["placed", "accepted", "packed", "completed"]
    stage_index = stages.index(order["status"]) if order["status"] in stages else -1
    return render_template("order_detail.html", order=order, items=items, stages=stages, stage_index=stage_index,
                           cart_count=sum(_cart().values()))
