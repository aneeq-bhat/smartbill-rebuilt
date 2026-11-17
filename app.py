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
from blueprints.payments import payments_bp
from blueprints.refunds import refunds_bp
from blueprints.settlements import settlements_bp
from blueprints.account_security import account_security_bp
from blueprints.notifications import notifications_bp
from blueprints.returns import returns_bp

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
    app.register_blueprint(payments_bp)
    app.register_blueprint(refunds_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(account_security_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(returns_bp)

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
            # Keep the order schema compatible on both fresh and existing databases.
            _ensure_order_schema(conn)
            click.echo("Database schema created and order schema verified successfully.")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    @app.cli.command("upgrade-consumer-features")
    def upgrade_consumer_features():
        """Create wishlist and saved-address tables (safe to rerun)."""
        import pathlib
        sql = pathlib.Path(app.root_path, "migrations", "002_consumer_experience.sql").read_text()
        conn = get_db()
        cur = conn.cursor()
        try:
            for statement in sql.split(";"):
                if statement.strip():
                    cur.execute(statement)
            conn.commit()
            click.echo("Consumer experience tables are ready.")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    @app.cli.command("init-payments")
    def init_payments():
        """Create Razorpay transaction storage and link orders to payments."""
        from pathlib import Path
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("""CREATE TABLE IF NOT EXISTS payment_transactions (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                consumer_user_id BIGINT NOT NULL,
                razorpay_order_id VARCHAR(80) NOT NULL UNIQUE,
                razorpay_payment_id VARCHAR(80) NULL UNIQUE,
                amount_paise BIGINT NOT NULL,
                currency CHAR(3) NOT NULL DEFAULT 'INR',
                status ENUM('created','paid','failed','paid_stock_conflict') NOT NULL DEFAULT 'created',
                cart_snapshot LONGTEXT NOT NULL,
                order_ids LONGTEXT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_payment_consumer (consumer_user_id),
                CONSTRAINT fk_payment_consumer FOREIGN KEY (consumer_user_id) REFERENCES users(id)
            )""")
            cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='orders' AND COLUMN_NAME='payment_transaction_id'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE orders ADD COLUMN payment_transaction_id BIGINT NULL")
            cur.execute("SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='orders' AND INDEX_NAME='idx_orders_payment_transaction'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE orders ADD INDEX idx_orders_payment_transaction (payment_transaction_id)")
            cur.execute("SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='orders' AND CONSTRAINT_NAME='fk_orders_payment_transaction'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE orders ADD CONSTRAINT fk_orders_payment_transaction FOREIGN KEY (payment_transaction_id) REFERENCES payment_transactions(id)")
            conn.commit()
            click.echo("Razorpay payment tables and order linkage are ready.")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    @app.cli.command("init-refunds")
    def init_refunds():
        """Create durable refund records for Razorpay refund operations."""
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("""CREATE TABLE IF NOT EXISTS payment_refunds (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                payment_transaction_id BIGINT NOT NULL,
                razorpay_refund_id VARCHAR(80) NULL UNIQUE,
                amount_paise BIGINT NOT NULL,
                reason VARCHAR(200) NOT NULL,
                status ENUM('created','pending','processed','failed','unknown') NOT NULL DEFAULT 'created',
                idempotency_key VARCHAR(64) NOT NULL UNIQUE,
                response_json LONGTEXT NULL,
                last_error TEXT NULL,
                created_by BIGINT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_refunds_payment (payment_transaction_id),
                CONSTRAINT fk_refunds_payment FOREIGN KEY (payment_transaction_id) REFERENCES payment_transactions(id),
                CONSTRAINT fk_refunds_admin FOREIGN KEY (created_by) REFERENCES users(id)
            )""")
            conn.commit()
            click.echo("Razorpay refund records are ready.")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    @app.cli.command("init-seller-settlements")
    def init_seller_settlements():
        """Create seller onboarding and settlement tables."""
        import pathlib
        sql = pathlib.Path(app.root_path, "migrations", "013_seller_settlements.sql").read_text()
        conn = get_db()
        cur = conn.cursor()
        try:
            for statement in sql.split(";"):
                if statement.strip():
                    cur.execute(statement)
            conn.commit()
            click.echo("Seller onboarding and settlement ledger tables are ready.")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    @app.cli.command("init-account-security")
    def init_account_security():
        """Add email verification and one-time password recovery storage."""
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='users' AND COLUMN_NAME='email_verified'"
            )
            if not cur.fetchone():
                # Existing accounts remain verified; new registrations explicitly set this to 0.
                cur.execute("ALTER TABLE users ADD COLUMN email_verified TINYINT(1) NOT NULL DEFAULT 1")
            cur.execute("""CREATE TABLE IF NOT EXISTS account_security_tokens (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                user_id BIGINT NOT NULL,
                purpose ENUM('verify_email','reset_password') NOT NULL,
                token_hash CHAR(64) NOT NULL UNIQUE,
                expires_at DATETIME NOT NULL,
                used_at DATETIME NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_account_tokens_user_purpose (user_id,purpose,used_at),
                INDEX idx_account_tokens_expiry (expires_at),
                CONSTRAINT fk_account_tokens_user FOREIGN KEY (user_id) REFERENCES users(id)
            )""")
            conn.commit()
            click.echo("Email verification and password recovery tables are ready.")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    @app.cli.command("init-notifications")
    def init_notifications():
        """Create the in-app notification table."""
        import pathlib
        sql = pathlib.Path(app.root_path, "migrations", "015_notifications.sql").read_text()
        conn = get_db()
        cur = conn.cursor()
        try:
            for statement in sql.split(";"):
                if statement.strip():
                    cur.execute(statement)
            conn.commit()
            click.echo("Notification storage is ready.")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    @app.cli.command("init-returns")
    def init_returns():
        """Create order return request storage."""
        import pathlib
        sql = pathlib.Path(app.root_path, "migrations", "014_returns.sql").read_text()
        conn = get_db()
        cur = conn.cursor()
        try:
            for statement in sql.split(";"):
                if statement.strip():
                    cur.execute(statement)
            conn.commit()
            click.echo("Return request storage is ready.")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    @app.cli.command("init-gst-invoicing")
    def init_gst_invoicing():
        """Add GST configuration and immutable invoice tax snapshots; safe to rerun."""
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        additions = {
            "shops": [("gstin", "VARCHAR(15) NULL"), ("state_code", "CHAR(2) NULL"), ("state_name", "VARCHAR(80) NULL"), ("gst_registered", "BOOLEAN NOT NULL DEFAULT FALSE")],
            "products": [("hsn_sac", "VARCHAR(8) NULL"), ("gst_rate", "DECIMAL(5,2) NOT NULL DEFAULT 0")],
            "customers": [("gstin", "VARCHAR(15) NULL"), ("state_code", "CHAR(2) NULL")],
            "invoices": [("cgst_total", "DECIMAL(12,2) NOT NULL DEFAULT 0"), ("sgst_total", "DECIMAL(12,2) NOT NULL DEFAULT 0"), ("igst_total", "DECIMAL(12,2) NOT NULL DEFAULT 0"), ("place_of_supply_state", "CHAR(2) NULL"), ("customer_gstin", "VARCHAR(15) NULL")],
            "invoice_items": [("hsn_sac", "VARCHAR(8) NULL"), ("gst_rate", "DECIMAL(5,2) NOT NULL DEFAULT 0"), ("taxable_value", "DECIMAL(12,2) NOT NULL DEFAULT 0"), ("cgst_amount", "DECIMAL(12,2) NOT NULL DEFAULT 0"), ("sgst_amount", "DECIMAL(12,2) NOT NULL DEFAULT 0"), ("igst_amount", "DECIMAL(12,2) NOT NULL DEFAULT 0")]
        }
        try:
            for table, columns in additions.items():
                for column, definition in columns:
                    cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s", (table, column))
                    if not cur.fetchone():
                        cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")
            conn.commit()
            click.echo("GST invoicing schema is ready. Existing invoices remain unchanged and retain zero GST breakdown until amended through a separate credit/debit workflow.")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    @app.cli.command("init-inventory-analytics")
    def init_inventory_analytics():
        """Add reorder thresholds and stock movement ledger; safe to rerun."""
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='products' AND COLUMN_NAME='reorder_level'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE products ADD COLUMN reorder_level INT NOT NULL DEFAULT 5")
            cur.execute("""CREATE TABLE IF NOT EXISTS inventory_movements (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                shop_id BIGINT NOT NULL,
                product_id BIGINT NOT NULL,
                movement_type ENUM('stock_in','stock_out') NOT NULL,
                quantity_delta INT NOT NULL,
                stock_before INT NOT NULL,
                stock_after INT NOT NULL,
                reason VARCHAR(240) NOT NULL,
                created_by BIGINT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_inventory_shop_created (shop_id,created_at),
                INDEX idx_inventory_product_created (product_id,created_at),
                CONSTRAINT fk_inventory_shop FOREIGN KEY (shop_id) REFERENCES shops(id),
                CONSTRAINT fk_inventory_product FOREIGN KEY (product_id) REFERENCES products(id),
                CONSTRAINT fk_inventory_user FOREIGN KEY (created_by) REFERENCES users(id)
            )""")
            conn.commit()
            click.echo("Inventory thresholds and stock movement ledger are ready.")
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

def _ensure_order_schema(conn):
    """Apply the order-management schema additions safely and repeatedly.

    TiDB exposes table metadata through information_schema. Checking first
    avoids failing when this command is run against an already-migrated DB.
    """
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'orders' "
            "AND COLUMN_NAME = 'status'"
        )
        status_column = cur.fetchone()
        if status_column and "rejected" not in status_column["COLUMN_TYPE"]:
            cur.execute(
                "ALTER TABLE orders MODIFY COLUMN status "
                "ENUM('placed','accepted','packed','completed','cancelled','rejected') "
                "NOT NULL DEFAULT 'placed'"
            )

        cur.execute(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'orders' "
            "AND COLUMN_NAME = 'stock_restored'"
        )
        if not cur.fetchone():
            cur.execute(
                "ALTER TABLE orders ADD COLUMN stock_restored TINYINT(1) "
                "NOT NULL DEFAULT 0"
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()

app = create_app()
