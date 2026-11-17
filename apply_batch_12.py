from pathlib import Path

root = Path(__file__).resolve().parent
app = root / 'app.py'
text = app.read_text()
if 'from blueprints.refunds import refunds_bp' not in text:
    anchor = 'from blueprints.payments import payments_bp'
    if anchor not in text:
        raise SystemExit('Missing payments blueprint import. Install Batch 11 first; no files changed.')
    text = text.replace(anchor, anchor + '\nfrom blueprints.refunds import refunds_bp', 1)
if 'app.register_blueprint(refunds_bp)' not in text:
    anchor = 'app.register_blueprint(payments_bp)'
    if anchor not in text:
        raise SystemExit('Missing payments blueprint registration. No files changed.')
    text = text.replace(anchor, anchor + '\n    app.register_blueprint(refunds_bp)', 1)
if 'def init_refunds()' not in text:
    marker = '    @app.cli.command("create-superadmin")'
    command = '''    @app.cli.command("init-refunds")
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

'''
    if marker not in text:
        raise SystemExit('Could not find CLI insertion point; no files changed.')
    text = text.replace(marker, command + marker, 1)
app.write_text(text)

base = root / 'templates' / 'base.html'
if base.exists():
    b = base.read_text()
    if "url_for('refunds.index')" not in b:
        needle = "{% if session.get('role') == 'super_admin' %}"
        # Avoid brittle navigation rewriting: template route remains directly accessible.
        if needle in b:
            b = b.replace(needle, needle + "\n<a href=\"{{ url_for('refunds.index') }}\">Refunds</a>", 1)
            base.write_text(b)
print('Batch 12 integration complete. Review changes, then run init-refunds.')
