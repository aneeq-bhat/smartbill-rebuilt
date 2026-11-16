# SmartBill implementation roadmap

## Release 1 — foundation (this ZIP)
Role-separated authentication, approval workflow, isolated shop records, product catalogue, basic consumer ordering.

## Release 2 — shop operations
- Customer CRUD and verified consumer linking
- Invoice creation with line items, tax configuration and printable PDF receipts
- Stock adjustment history and low-stock alerts
- Invoice search, date filters and exports
- Shop profile, logo and staff accounts with permissions

## Release 3 — consumer experience
- Search, category filters, shop pages and product images
- Consumer order history and digital invoice linking
- Order acceptance/cancellation workflow for shopkeepers
- Address book and delivery/pickup options

## Release 4 — production commerce
- Payment provider integration, webhook verification, refunds and reconciliation
- Email/SMS verification and notifications
- GST compliance review and compliant invoice numbering
- Privacy, consent, deletion/export and retention workflows

## Release 5 — platform quality
- MFA, audit log, monitoring, backups and restore drills
- Rate limiting using a shared store (not process memory)
- Automated tests, dependency scanning and security assessment
- Performance testing, pagination and caching
