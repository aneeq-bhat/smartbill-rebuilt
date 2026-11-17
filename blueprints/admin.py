from flask import Blueprint, render_template, abort, redirect, url_for, flash, request
from db import query_all, query_one, execute
from security import roles_required

admin_bp=Blueprint("admin",__name__,url_prefix="/admin")

@admin_bp.get("/")
@roles_required("super_admin")
def dashboard():
    stats={
      "users":query_one("SELECT COUNT(*) n FROM users")["n"],
      "shops":query_one("SELECT COUNT(*) n FROM shops")["n"],
      "pending":query_one("SELECT COUNT(*) n FROM shops WHERE status='pending'")["n"],
      "orders":query_one("SELECT COUNT(*) n FROM orders")["n"]
    }
    return render_template("admin_dashboard.html",stats=stats)

@admin_bp.get("/shops")
@roles_required("super_admin")
def shops():
    rows=query_all("""SELECT s.id,s.name,s.status,s.created_at,u.name owner,u.email
                      FROM shops s JOIN users u ON u.id=s.owner_user_id
                      ORDER BY s.created_at DESC""")
    return render_template("admin_shops.html",shops=rows)

@admin_bp.post("/shops/<int:shop_id>/<action>")
@roles_required("super_admin")
def review_shop(shop_id,action):
    if action not in ("approve","reject"):
        abort(400)
    shop=query_one("SELECT owner_user_id FROM shops WHERE id=%s",(shop_id,))
    if not shop: abort(404)
    status="active" if action=="approve" else "rejected"
    conn=__import__("db").get_db()
    cur=conn.cursor()
    try:
        cur.execute("UPDATE shops SET status=%s WHERE id=%s",(status,shop_id))
        cur.execute("UPDATE users SET status=%s WHERE id=%s",(status,shop["owner_user_id"]))
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close()
    flash(f"Shop {status}.","success")
    return redirect(url_for("admin.shops"))


@admin_bp.get("/users")
@roles_required("super_admin")
def users():
    role = request.args.get("role", "all")
    allowed = {"all", "shopkeeper", "consumer", "super_admin"}
    if role not in allowed:
        abort(400)
    if role == "all":
        rows = query_all("SELECT id,name,email,role,status,created_at FROM users ORDER BY created_at DESC LIMIT 500")
    else:
        rows = query_all("SELECT id,name,email,role,status,created_at FROM users WHERE role=%s ORDER BY created_at DESC LIMIT 500", (role,))
    return render_template("admin_users.html", users=rows, selected_role=role)


@admin_bp.get("/orders")
@roles_required("super_admin")
def orders():
    rows = query_all(
        """SELECT o.id,o.status,o.total,o.created_at,
                  u.name consumer_name,u.email consumer_email,s.name shop_name
           FROM orders o
           JOIN users u ON u.id=o.consumer_user_id
           JOIN shops s ON s.id=o.shop_id
           ORDER BY o.created_at DESC LIMIT 500"""
    )
    return render_template("admin_orders.html", orders=rows)


@admin_bp.get("/analytics")
@roles_required("super_admin")
def analytics():
    """Platform-wide operational analytics for the private Super Admin."""
    overview = {
        "users_30d": query_one(
            "SELECT COUNT(*) n FROM users WHERE created_at >= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 30 DAY)"
        )["n"],
        "orders_30d": query_one(
            "SELECT COUNT(*) n FROM orders WHERE created_at >= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 30 DAY)"
        )["n"],
        "gmv_30d": query_one(
            "SELECT COALESCE(SUM(total), 0) amount FROM orders WHERE created_at >= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 30 DAY) AND status <> 'cancelled'"
        )["amount"],
        "active_shops": query_one(
            "SELECT COUNT(*) n FROM shops WHERE status='active'"
        )["n"],
    }
    order_status = query_all(
        "SELECT status, COUNT(*) total FROM orders GROUP BY status ORDER BY total DESC"
    )
    top_shops = query_all(
        "SELECT s.id, s.name, COUNT(o.id) order_count, COALESCE(SUM(CASE WHEN o.status <> 'cancelled' THEN o.total ELSE 0 END), 0) order_value "
        "FROM shops s LEFT JOIN orders o ON o.shop_id=s.id "
        "GROUP BY s.id, s.name ORDER BY order_value DESC LIMIT 10"
    )
    recent_activity = query_all(
        "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') day, COUNT(*) total "
        "FROM orders WHERE created_at >= DATE_SUB(CURRENT_DATE, INTERVAL 13 DAY) "
        "GROUP BY DATE_FORMAT(created_at, '%Y-%m-%d') ORDER BY day"
    )
    return render_template(
        "admin_analytics.html", overview=overview, order_status=order_status,
        top_shops=top_shops, recent_activity=recent_activity
    )
