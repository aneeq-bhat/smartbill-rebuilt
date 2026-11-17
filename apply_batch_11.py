from pathlib import Path
import re

root = Path(__file__).resolve().parent
app = root / 'app.py'
text = app.read_text()
if 'from blueprints.payments import payments_bp' not in text:
    anchor = 'from blueprints.consumer import consumer_bp'
    if anchor not in text:
        raise SystemExit('Could not find consumer blueprint import in app.py; no files changed.')
    text = text.replace(anchor, anchor + '\nfrom blueprints.payments import payments_bp', 1)
if 'app.register_blueprint(payments_bp)' not in text:
    anchor = 'app.register_blueprint(consumer_bp)'
    if anchor not in text:
        raise SystemExit('Could not find consumer blueprint registration in app.py; no files changed.')
    text = text.replace(anchor, anchor + '\n    app.register_blueprint(payments_bp)', 1)
# Add an idempotent migration CLI command without rewriting the existing init-db command.
if 'def init_payments()' not in text:
    marker = '    @app.cli.command("create-superadmin")'
    command = '''    @app.cli.command("init-payments")
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

'''
    if marker not in text:
        raise SystemExit('Could not find create-superadmin CLI insertion point; no files changed.')
    text = text.replace(marker, command + marker, 1)
app.write_text(text)

req = root / 'requirements.txt'
req_text = req.read_text()
if not re.search(r'^razorpay\s*[<=>]', req_text, re.M):
    req.write_text(req_text.rstrip() + '\nrazorpay>=1.4,<2\n')

cart = root / 'templates' / 'cart.html'
if cart.exists():
    c = cart.read_text()
    old = "url_for('consumer.checkout')"
    if old in c:
        c = c.replace(old, "url_for('payments.create_payment')")
        c = c.replace('>Place order <span', '>Continue to secure payment <span')
        c = c.replace('Payment and delivery are not yet integrated. Checkout places your order with the shop.', 'Secure online payment is powered by Razorpay. Orders are confirmed only after payment verification.')
        cart.write_text(c)

print('Batch 11 files integrated. Review app.py and cart.html before running the migration.')
