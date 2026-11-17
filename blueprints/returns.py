"""Return requests and cancellation review. Refunds remain separately controlled."""
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from db import get_db, query_all, query_one
from security import roles_required

returns_bp = Blueprint('returns', __name__)

@returns_bp.get('/consumer/returns')
@roles_required('consumer')
def consumer_returns():
    rows = query_all('''SELECT r.id,r.order_id,r.reason,r.details,r.status,r.admin_note,r.created_at,
                               o.total,o.status order_status,s.name shop_name
                        FROM order_return_requests r JOIN orders o ON o.id=r.order_id
                        JOIN shops s ON s.id=o.shop_id WHERE r.consumer_user_id=%s
                        ORDER BY r.id DESC''', (session['user_id'],))
    return render_template('consumer_returns.html', returns=rows)

@returns_bp.post('/consumer/orders/<int:order_id>/return')
@roles_required('consumer')
def request_return(order_id):
    reason = (request.form.get('reason') or '').strip()[:120]
    details = (request.form.get('details') or '').strip()[:2000]
    if not reason:
        abort(400, description='Select a return reason.')
    order = query_one('''SELECT id,status FROM orders WHERE id=%s AND consumer_user_id=%s''',
                      (order_id, session['user_id']))
    if not order:
        abort(404)
    if order['status'] not in ('completed',):
        flash('Return requests are available only after an order is marked completed.', 'warning')
        return redirect(url_for('consumer.order_detail', order_id=order_id))
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute('''INSERT INTO order_return_requests
            (order_id,consumer_user_id,reason,details,status) VALUES (%s,%s,%s,%s,'requested')''',
            (order_id, session['user_id'], reason, details or None))
        conn.commit()
        from blueprints.notifications import notify_superadmins
        notify_superadmins("return_request", "New return request",
                           f"A return was requested for order #{order_id}.",
                           "/admin/returns", f"return-request:{order_id}")
        flash('Return request submitted. Refunds are reviewed separately by SmartBill administration.', 'success')
    except Exception as exc:
        conn.rollback()
        if getattr(exc, 'errno', None) == 1062:
            flash('A return request already exists for this order.', 'info')
        else:
            raise
    finally:
        cur.close()
    return redirect(url_for('returns.consumer_returns'))

@returns_bp.get('/admin/returns')
@roles_required('super_admin')
def admin_returns():
    rows = query_all('''SELECT r.*,o.total,o.status order_status,s.name shop_name,u.name consumer_name,u.email
                        FROM order_return_requests r JOIN orders o ON o.id=r.order_id
                        JOIN shops s ON s.id=o.shop_id JOIN users u ON u.id=r.consumer_user_id
                        ORDER BY CASE r.status WHEN 'requested' THEN 0 ELSE 1 END,r.id DESC LIMIT 300''')
    return render_template('admin_returns.html', returns=rows)

@returns_bp.post('/admin/returns/<int:return_id>/review')
@roles_required('super_admin')
def review_return(return_id):
    status = request.form.get('status')
    if status not in ('approved','rejected','received'):
        abort(400)
    note = (request.form.get('admin_note') or '').strip()[:1000] or None
    conn=get_db(); cur=conn.cursor(dictionary=True)
    try:
        conn.commit(); conn.start_transaction()
        cur.execute('SELECT * FROM order_return_requests WHERE id=%s FOR UPDATE',(return_id,))
        row=cur.fetchone()
        if not row:
            abort(404)
        if row['status'] not in ('requested','approved','received'):
            raise ValueError('This return request is already closed.')
        if status == 'received' and row['status'] != 'approved':
            raise ValueError('A return must be approved before marking goods received.')
        cur.execute('UPDATE order_return_requests SET status=%s,admin_note=%s,reviewed_by=%s WHERE id=%s',
                    (status,note,session['user_id'],return_id))
        consumer_user_id = row["consumer_user_id"]
        order_id = row["order_id"]
        conn.commit()
        from blueprints.notifications import notify_user
        notify_user(consumer_user_id, "return_update", "Return request updated",
                    f"Your return request for order #{order_id} is now {status}.",
                    "/consumer/returns", f"return-status:{return_id}:{status}")
        flash('Return request updated. If approved, process any eligible payment refund separately in Refunds.', 'success')
    except ValueError as exc:
        conn.rollback(); flash(str(exc),'warning')
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close()
    return redirect(url_for('returns.admin_returns'))
