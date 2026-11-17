from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort

from db import query_all, query_one, execute, get_db
from security import roles_required

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
            execute(
                "INSERT INTO products (shop_id, name, price, stock_qty) VALUES (%s,%s,%s,%s)",
                (shop["id"], name, price, stock)
            )
            flash("Product added.", "success")
            return redirect(url_for("shop.products"))

    rows = query_all(
        """SELECT id, name, price, stock_qty, is_listed
           FROM products WHERE shop_id=%s ORDER BY id DESC""",
        (shop["id"],)
    )
    return render_template("products.html", shop=shop, products=rows)


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
            """SELECT id, status, stock_restored
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
        else:
            cur.execute(
                """UPDATE orders
                   SET status=%s
                   WHERE id=%s AND shop_id=%s""",
                (new_status, order_id, shop["id"])
            )

        conn.commit()
        flash(f"Order #{order_id} updated to {new_status}.", "success")

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()

    return redirect(url_for("shop.orders"))
