from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from db import query_all, query_one, execute
from security import roles_required

shop_bp=Blueprint("shop",__name__,url_prefix="/shopkeeper")

def current_shop():
    shop=query_one("SELECT id,name,status FROM shops WHERE owner_user_id=%s",(session["user_id"],))
    if not shop or shop["status"]!="active": abort(403)
    return shop

@shop_bp.get("/")
@roles_required("shopkeeper")
def dashboard():
    shop=current_shop()
    stats={
      "products":query_one("SELECT COUNT(*) n FROM products WHERE shop_id=%s",(shop["id"],))["n"],
      "invoices":query_one("SELECT COUNT(*) n FROM invoices WHERE shop_id=%s",(shop["id"],))["n"],
      "customers":query_one("SELECT COUNT(*) n FROM customers WHERE shop_id=%s",(shop["id"],))["n"]
    }
    return render_template("shop_dashboard.html",shop=shop,stats=stats)

@shop_bp.route("/products",methods=["GET","POST"])
@roles_required("shopkeeper")
def products():
    shop=current_shop()
    if request.method=="POST":
        name=request.form.get("name","").strip()
        try: price=float(request.form.get("price","0"))
        except ValueError: price=0
        try: stock=int(request.form.get("stock","0"))
        except ValueError: stock=-1
        if not name or price<0 or stock<0:
            flash("Enter a product name, valid price and non-negative stock.","danger")
        else:
            execute("INSERT INTO products (shop_id,name,price,stock_qty) VALUES (%s,%s,%s,%s)",
                    (shop["id"],name,price,stock))
            flash("Product added.","success")
            return redirect(url_for("shop.products"))
    rows=query_all("SELECT id,name,price,stock_qty,is_listed FROM products WHERE shop_id=%s ORDER BY id DESC",(shop["id"],))
    return render_template("products.html",shop=shop,products=rows)
