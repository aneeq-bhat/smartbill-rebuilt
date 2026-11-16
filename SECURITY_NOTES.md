# Security notes and known MVP limitations

- Passwords are hashed with Werkzeug's password hashing functions.
- CSRF tokens protect all POST requests.
- Session cookies are HTTP-only and SameSite=Lax; set secure cookies in production.
- Super Admin creation is CLI-only; no public route exists.
- Shopkeeper access requires active shop approval.
- Product and order queries are scoped to the signed-in user or selected shop.
- This MVP's login attempt limiter is process-local and resets on restart. Replace with Redis or edge-level rate limiting before production.
- Email verification, password reset, MFA, audit trails and payment controls are not implemented.
- The current consumer order flow is a basic cash/manual order placeholder; it is not a payment system.
- Do not store card data. Use a regulated payment provider and verified webhooks if payments are added.
- Validate and test every new route. Never rely on hiding UI links for authorization.
