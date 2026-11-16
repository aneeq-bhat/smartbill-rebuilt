import click
from flask import Flask, render_template, redirect, url_for, session, request, flash
from werkzeug.security import generate_password_hash
from extensions import configure_app
from db import get_db, close_db, query_one
from security import csrf_token, csrf_protect
from blueprints.auth import auth_bp
from blueprints.admin import admin_bp
from blueprints.shopkeeper import shop_bp
from blueprints.consumer import consumer_bp

def create_app():
    app = Flask(__name__)
    configure_app(app)
    app.teardown_appcontext(close_db)
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def protect_posts():
        csrf_protect()

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(shop_bp)
    app.register_blueprint(consumer_bp)

    @app.get("/")
    def home():
        return render_template("home.html")

    @app.cli.command("init-db")
    def init_db():
        """Create tables in the configured NEW database."""
        import pathlib
        sql = pathlib.Path(app.root_path, "schema.sql").read_text()
        conn = get_db()
        cur = conn.cursor()
        try:
            # Schema contains independent CREATE TABLE statements.
            for statement in sql.split(";"):
                if statement.strip():
                    cur.execute(statement)
            conn.commit()
            click.echo("Database schema created successfully.")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    @app.cli.command("create-superadmin")
    @click.option("--username", prompt="Super Admin email")
    def create_superadmin(username):
        """Create the first Super Admin. This is not a public route."""
        from werkzeug.security import generate_password_hash
        user = query_one("SELECT id FROM users WHERE role='super_admin' LIMIT 1")
        if user:
            raise click.ClickException("A Super Admin already exists.")
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
        if len(password) < 14:
            raise click.ClickException("Use at least 14 characters.")
        name = click.prompt("Display name")
        cur = get_db().cursor()
        try:
            cur.execute(
                "INSERT INTO users (name,email,password_hash,role,status) VALUES (%s,%s,%s,'super_admin','active')",
                (name, username.strip().lower(), generate_password_hash(password))
            )
            get_db().commit()
            click.echo("Super Admin created.")
        except Exception:
            get_db().rollback()
            raise
        finally:
            cur.close()

    return app

app = create_app()
