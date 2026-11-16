from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from db import query_all, query_one
from security import roles_required

consumer_bp=Blueprint("consumer",__name__)

@consumer_bp.get("/marketplace")
def marketplace():
    products=query_all("""SELECT p.id,p.name,p.description,p.price,p.stock_qty,s.name shop_name,s.id shop_id
                          FROM products p JOIN shops s ON s.id=p.shop_id
                          WHERE p.is_listed=1 AND p.stock_qty>0 AND s.status='active'
                          ORDER BY s.name,p.name""")
    return render_template("marketplace.html",products=products)

@consumer_bp.get("/consumer")
@roles_required("consumer")
def dashboard():
    orders=query_all("""SELECT o.id,o.status,o.total,o.created_at,s.name shop_name
                        FROM orders o JOIN shops s ON s.id=o.shop_id
                        WHERE o.consumer_user_id=%s ORDER BY o.id DESC""",(session["user_id"],))
    return render_template("consumer_dashboard.html",orders=orders)

@consumer_bp.post("/marketplace/order/<int:product_id>")
@roles_required("consumer")
def place_order(product_id):
    try: qty=int(request.form.get("quantity","1"))
    except ValueError: qty=0
    if qty<1 or qty>100: abort(400)
    conn=__import__("db").get_db()
    cur=conn.cursor(dictionary=True)
    try:
        cur.execute("""SELECT p.id,p.name,p.price,p.stock_qty,p.shop_id
                       FROM products p JOIN shops s ON s.id=p.shop_id
                       WHERE p.id=%s AND p.is_listed=1 AND s.status='active' FOR UPDATE""",(product_id,))
        p=cur.fetchone()
        if not p or p["stock_qty"]<qty:
            flash("Product unavailable or insufficient stock.","danger")
            return redirect(url_for("consumer.marketplace"))
        total=float(p["price"])*qty
        cur2=conn.cursor()
        cur2.execute("INSERT INTO orders (consumer_user_id,shop_id,total) VALUES (%s,%s,%s)",
                     (session["user_id"],p["shop_id"],total))
        oid=cur2.lastrowid
        cur2.execute("""INSERT INTO order_items (order_id,product_id,product_name,quantity,unit_price,line_total)
                        VALUES (%s,%s,%s,%s,%s,%s)""",
                     (oid,p["id"],p["name"],qty,p["price"],total))
        cur2.execute("UPDATE products SET stock_qty=stock_qty-%s WHERE id=%s AND shop_id=%s",
                     (qty,p["id"],p["shop_id"]))
        conn.commit()
        flash(f"Order #{oid} placed. Payment and delivery are not yet integrated.","success")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return redirect(url_for("consumer.dashboard"))
