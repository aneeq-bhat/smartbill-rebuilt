from pathlib import Path
root = Path(__file__).resolve().parent

app = root / 'app.py'
s = app.read_text()
if 'from blueprints.settlements import settlements_bp' not in s:
    s = s.replace('from blueprints.refunds import refunds_bp', 'from blueprints.refunds import refunds_bp\nfrom blueprints.settlements import settlements_bp', 1)
if 'app.register_blueprint(settlements_bp)' not in s:
    s = s.replace('app.register_blueprint(refunds_bp)', 'app.register_blueprint(refunds_bp)\n    app.register_blueprint(settlements_bp)', 1)
if 'def init_seller_settlements()' not in s:
    marker = '    @app.cli.command("create-superadmin")'
    command = '''    @app.cli.command("init-seller-settlements")
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

'''
    if marker not in s:
        raise SystemExit('CLI insertion point not found')
    s = s.replace(marker, command + marker, 1)
app.write_text(s)

payments = root / 'blueprints' / 'payments.py'
s = payments.read_text()
anchor = '        cur.execute(\n            "UPDATE payment_transactions SET status=\'paid\',razorpay_payment_id=%s,order_ids=%s WHERE id=%s",'
if 'INSERT INTO seller_ledger' not in s:
    if anchor not in s:
        raise SystemExit('Payment finalization insertion point not found')
    addition = '''        cur.execute("SELECT commission_bps FROM platform_commission_settings WHERE id=1")
        commission_row = cur.fetchone()
        commission_bps = int(commission_row["commission_bps"]) if commission_row else 0
        for ledger_order_id, (ledger_shop_id, ledger_items) in zip(order_ids, grouped.items()):
            ledger_gross = sum((Decimal(str(prod["price"])) * qty for prod, qty in ledger_items), Decimal("0.00"))
            gross_paise = int((ledger_gross * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            commission_paise = int((Decimal(gross_paise) * commission_bps / Decimal("10000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            cur.execute(
                "INSERT INTO seller_ledger (shop_id,order_id,payment_transaction_id,gross_paise,commission_bps,commission_paise,net_paise,status) VALUES (%s,%s,%s,%s,%s,%s,%s,'pending') ON DUPLICATE KEY UPDATE order_id=VALUES(order_id)",
                (ledger_shop_id, ledger_order_id, payment["id"], gross_paise, commission_bps, commission_paise, gross_paise - commission_paise),
            )
'''
    s = s.replace(anchor, addition + anchor, 1)
    payments.write_text(s)

shop = root / 'blueprints' / 'shopkeeper.py'
s = shop.read_text()
anchor = '            cur.execute(\n                """UPDATE orders\n                   SET status=%s, stock_restored=1\n                   WHERE id=%s AND shop_id=%s""",\n                (new_status, order_id, shop["id"])\n            )'
if "UPDATE seller_ledger SET status='reversed'" not in s:
    if anchor not in s:
        raise SystemExit('Order rejection insertion point not found')
    s = s.replace(anchor, anchor + '\n            cur.execute("UPDATE seller_ledger SET status=\'reversed\' WHERE order_id=%s AND status IN (\'pending\',\'held\',\'eligible\')", (order_id,))', 1)
    shop.write_text(s)

base = root / 'templates' / 'base.html'
s = base.read_text()
if "url_for('settlements.seller_portal')" not in s:
    s = s.replace("{% if session.get('role')=='shopkeeper' %}", "{% if session.get('role')=='shopkeeper' %}<a class=\"btn btn-sm btn-outline-light\" href=\"{{ url_for('settlements.seller_portal') }}\">Settlements</a>", 1)
if "url_for('settlements.admin_settlements')" not in s:
    s = s.replace("{% if session.get('role')=='super_admin' %}", "{% if session.get('role')=='super_admin' %}<a class=\"btn btn-sm btn-outline-light\" href=\"{{ url_for('settlements.admin_settlements') }}\">Seller settlements</a>", 1)
base.write_text(s)
print('Batch 13 integrated.')
