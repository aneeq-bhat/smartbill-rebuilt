from flask import Blueprint, render_template, abort, redirect, url_for, flash
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
