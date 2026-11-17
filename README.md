# SmartBill — Rebuilt starter application

A clean multi-tenant SmartBill foundation using Flask, MySQL/TiDB, Bootstrap 5 and server-rendered templates.

## Included in this release
- Separate Super Admin, Shopkeeper and Consumer roles
- Shopkeeper self-registration with manual Super Admin approval
- Super Admin account created through a CLI command (no public admin signup)
- Shop-scoped products, customers, invoices and invoice items
- Consumer marketplace catalogue and order placement
- Password hashing, CSRF protection, session hardening, login throttling
- SQL schema, environment example, Render start command and basic tests

## Important scope
This is a working **foundation/MVP**, not a finished commercial marketplace. It does not include payment gateway integration, shipping integrations, GST e-invoicing/e-way bill compliance, email/SMS OTP delivery, refunds, or production-grade observability. Do not advertise those capabilities until implemented and tested.

The database starts empty. The schema creates new tables and does not import or alter your old SmartBill database.

## 1. Requirements
- Python 3.11+
- MySQL 8+ or TiDB Cloud
- Git and GitHub account
- Render account

## 2. Run locally on macOS

Open Terminal in this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set your database connection values. Do not share `.env` or commit it to GitHub.

Create an empty database/schema in TiDB first, then run:

```bash
flask --app app init-db
flask --app app create-superadmin
flask --app app run --debug
```

The create-superadmin command prompts for the username and password securely. Use a unique password. The command creates the account only if one does not already exist.

Open http://127.0.0.1:5000

## 3. GitHub
1. Create a **new private GitHub repository** named `smartbill-rebuilt`.
2. Upload the contents of this ZIP (not the ZIP itself).
3. Confirm `.env` is not uploaded. `.gitignore` excludes it.
4. Never commit database passwords, secret keys, API keys or real customer data.

## 4. Render deployment
- Create a new Web Service connected to the new repository.
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Add all variables from `.env.example` in Render Environment.
- Set `FLASK_ENV=production`.
- Set a long random `SECRET_KEY`.
- Run `flask --app app init-db` once against the new empty database, then run `flask --app app create-superadmin` once from a secure shell/one-off job. Do not expose an admin creation route.
- Enable HTTPS. `SESSION_COOKIE_SECURE=1` is required in production.

## 5. First workflow
1. Sign in as Super Admin at `/admin/login`.
2. Register a shopkeeper at `/shopkeeper/register`.
3. As Super Admin, approve the shopkeeper at `/admin/shops`.
4. The shopkeeper signs in at `/shopkeeper/login` and adds products.
5. A consumer registers at `/consumer/register`, browses `/marketplace`, and places an order.

## 6. Security and production checklist
Before real customers use this:
- Configure managed database backups and restore testing.
- Use a dedicated least-privilege DB user; restrict network access.
- Set `SECRET_KEY` to a cryptographically random value and keep it stable.
- Add email/phone verification and password reset delivery.
- Add MFA for Super Admin.
- Add audit logs, monitoring, alerting, backups and incident procedures.
- Add pagination, search, rate limits at the edge, and automated security tests.
- Review privacy policy, terms, retention and Indian tax/legal requirements with qualified professionals.
- Perform independent security review and load testing.
- Implement payment, refunds and order fulfilment only after selecting providers and workflows.

## 7. Database notes
`schema.sql` creates a fresh schema. Run it only against a **new empty database** for this rebuild. It does not drop tables, but it will fail if incompatible tables with the same names already exist. Do not point it at your old production database.

## 8. Project structure
```text
smartbill/
  app.py
  config.py
  extensions.py
  security.py
  db.py
  schema.sql
  requirements.txt
  .env.example
  blueprints/
  templates/
  static/
  tests/
```


## Batch 17 — GST invoicing
See `INSTALL_BATCH_17.txt` for migration and setup instructions. GST rates and HSN/SAC classifications must be verified by the seller; the built-in report is not a statutory GST return.
