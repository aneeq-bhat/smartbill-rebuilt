from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash, generate_password_hash
from db import query_one, execute
from security import rotate_session, login_limited

auth_bp = Blueprint("auth", __name__)

def login_form(role, endpoint, title):
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        key = f"{role}:{request.remote_addr}:{email}"
        if not login_limited(key):
            flash("Too many attempts. Wait five minutes and try again.", "danger")
            return render_template("login.html", title=title, endpoint=endpoint)
        user = query_one("SELECT * FROM users WHERE email=%s AND role=%s", (email, role))
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Email or password is incorrect.", "danger")
        elif user["status"] != "active":
            flash("Your account is not active. Shopkeeper accounts require Super Admin approval.", "warning")
        else:
            rotate_session(user)
            return redirect(url_for({"super_admin":"admin.dashboard","shopkeeper":"shop.dashboard","consumer":"consumer.dashboard"}[role]))
    return render_template("login.html", title=title, endpoint=endpoint)

@auth_bp.route("/admin/login", methods=["GET","POST"])
def admin_login():
    return login_form("super_admin", "auth.admin_login", "Super Admin sign in")

@auth_bp.route("/shopkeeper/login", methods=["GET","POST"])
def shop_login():
    return login_form("shopkeeper", "auth.shop_login", "Shopkeeper sign in")

@auth_bp.route("/consumer/login", methods=["GET","POST"])
def consumer_login():
    return login_form("consumer", "auth.consumer_login", "Consumer sign in")

@auth_bp.route("/shopkeeper/register", methods=["GET","POST"])
def shop_register():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        shop = request.form.get("shop_name","").strip()
        if not all([name,email,password,shop]) or len(password) < 12:
            flash("Complete every field. Password must be at least 12 characters.", "danger")
        elif query_one("SELECT id FROM users WHERE email=%s",(email,)):
            flash("An account with that email already exists.", "danger")
        else:
            slug = "".join(c.lower() if c.isalnum() else "-" for c in shop).strip("-")
            slug = "-".join(filter(None,slug.split("-")))[:160]
            try:
                conn = __import__("db").get_db()
                cur = conn.cursor()
                cur.execute("INSERT INTO users (name,email,password_hash,role,status) VALUES (%s,%s,%s,'shopkeeper','pending')",
                            (name,email,generate_password_hash(password)))
                uid = cur.lastrowid
                cur.execute("INSERT INTO shops (owner_user_id,name,slug,status) VALUES (%s,%s,%s,'pending')",(uid,shop,f"{slug}-{uid}"))
                conn.commit()
                flash("Registration submitted. Wait for Super Admin approval.", "success")
                return redirect(url_for("auth.shop_login"))
            except Exception:
                __import__("db").get_db().rollback()
                raise
            finally:
                cur.close()
    return render_template("register_shop.html")

@auth_bp.route("/consumer/register", methods=["GET","POST"])
def consumer_register():
    if request.method == "POST":
        name=request.form.get("name","").strip()
        email=request.form.get("email","").strip().lower()
        password=request.form.get("password","")
        if not all([name,email,password]) or len(password)<12:
            flash("Complete every field. Password must be at least 12 characters.","danger")
        elif query_one("SELECT id FROM users WHERE email=%s",(email,)):
            flash("An account with that email already exists.","danger")
        else:
            execute("INSERT INTO users (name,email,password_hash,role,status) VALUES (%s,%s,%s,'consumer','active')",
                    (name,email,generate_password_hash(password)))
            flash("Account created. You can sign in.","success")
            return redirect(url_for("auth.consumer_login"))
    return render_template("register_consumer.html")

@auth_bp.post("/logout")
def logout():
    session.clear()
    flash("You have signed out.","info")
    return redirect(url_for("home"))
