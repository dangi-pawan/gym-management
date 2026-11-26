# Membership Management

This document defines the domain boundaries, organization/gym ownership rules, data model, lifecycle, authorization expectations, document handling, migration strategy, and verification checklist.

## Implementation status

The first application implementation is present on `feature/membership-management`. Migration `e41b7c9d2a60` adds organization ownership to existing members, backfills their current gym assignment, adds gym timezones, and creates the membership domain tables. Existing member IDs and the legacy `members.gym_id` field are preserved.

Implemented capabilities include organization-owned plans, gym availability and price overrides, structured rules, versioned terms, member-to-gym assignments, subscription snapshots and access-gym snapshots, manual payment recording, invoices, private PDF agreements/invoices/receipts, authorized document downloads, subscription renewal/cancellation, and gym-local access checks.

The membership feature and its payment-hardening follow-up are implemented on the feature branch. Before merge, apply all migrations to the test database, run the complete suite, and complete the documented Razorpay/S3 staging checks. See the deployment limitations in section 10.

## 1. Confirmed product decisions

| Decision | Contract |
|---|---|
| Plan creation | Organization owner/admin creates and owns plans |
| Gym pricing | Organization defines the default; a gym may have an optional override |
| Membership access | Each plan selects home-gym, all-organization-gyms, or selected-gyms access |
| Membership rules | Structured, validated database fields |
| Documents | Versioned terms plus generated member-specific agreement, invoice, and receipt PDFs |
| Member identity | A member belongs to one organization; gym associations are separate |
| Subscription | A member purchases a plan at a specific gym; the subscription records that purchasing gym |

An organization is the tenant boundary. A gym is a branch of exactly one organization. A member is a customer record belonging to one organization, not an employee User account.

## 2. Domain concepts

- **MembershipPlan**: reusable offer owned by an organization.
- **GymMembershipPlan**: makes an organization plan available at a gym and optionally overrides its price or joining fee.
- **MembershipPlanAccessGym**: the set of gyms configured on a selected-gyms plan.
- **MembershipPlanRules**: structured policies attached to a plan.
- **MembershipTerms**: immutable, versioned terms and conditions published by an organization.
- **MemberGymAssignment**: association between an organization member and a gym.
- **MemberSubscription**: a member's purchase/assignment of a plan at a purchasing gym.
- **SubscriptionAccessGym**: immutable-at-purchase snapshot of gyms granted to a subscription.
- **SubscriptionTermsAcceptance**: evidence of the terms version accepted for a subscription.
- **Payment**: money received or attempted; separate from subscription state.
- **Invoice / Receipt**: financial documents; separate from payment and subscription records.
- **MembershipDocument**: metadata for generated/private documents; file bytes live in private object storage, not PostgreSQL.

## 3. Ownership and relationship model

1. An organization owns its membership plans, terms versions, and member records.
2. A gym belongs to one organization.
3. A plan may be offered at zero or more gyms through GymMembershipPlan.
4. A member belongs to exactly one organization and may be associated with multiple gyms.
5. A subscription belongs to one organization member and one plan, and records the gym where it was purchased.
6. A subscription's allowed gyms are materialized at purchase in SubscriptionAccessGym. Later plan or branch changes do not silently rewrite existing access.
7. All tenant identifiers used for authorization come from the authenticated user's organization and verified database relationships, never from client-supplied IDs alone.

### Access types

| Value | Meaning | Purchase-time access snapshot |
|---|---|---|
| home_gym | Only the gym where the subscription is purchased | Purchasing gym |
| all_gyms | All gyms eligible under the organization at purchase time | All eligible organization gyms at purchase time |
| selected_gyms | Only gyms explicitly configured on the plan | Selected gyms, subject to the purchasing gym being eligible |

The purchasing gym must be an eligible gym for the plan. If the product later needs dynamic access to newly opened gyms, that must be an explicit policy/version change, not an accidental side effect.

## 4. Proposed database model

All tables use the project's SQLAlchemy naming conventions and PostgreSQL types. Monetary amounts use Numeric(12, 2), never float. Timestamps are timezone-aware UTC. Membership start/end are date values interpreted using the gym's configured IANA timezone. Existing gyms default to `Asia/Kolkata`; the gym create/update API validates timezone names.

### 4.1 membership_plans

Organization-owned catalog.

| Column | Type / rule | Notes |
|---|---|---|
| id | PK | |
| organization_id | FK, NOT NULL | Tenant owner |
| name | VARCHAR(100), NOT NULL | |
| description | TEXT, nullable | |
| duration_value | INTEGER, > 0 | |
| duration_unit | enum: day/week/month/year | Calendar-aware duration |
| base_price | NUMERIC(12,2), >= 0 | Organization default |
| joining_fee | NUMERIC(12,2), >= 0 | Default joining fee |
| currency | CHAR(3), NOT NULL | Initially INR; store explicitly |
| access_type | enum | home_gym/all_gyms/selected_gyms |
| terms_id | FK, nullable | Published terms version applicable to new purchases |
| status | enum | draft/active/archived |
| created_by | FK users.id | Audit |
| created_at / updated_at | timestamptz | |

Recommended constraints/indexes:
- Unique (id, organization_id) to support composite tenant foreign keys.
- Index (organization_id, status).
- Check duration_value > 0; prices >= 0.
- Archived plans cannot be selected for new subscriptions.

### 4.2 gym_membership_plans

Plan availability and branch-specific price.

| Column | Type / rule | Notes |
|---|---|---|
| id | PK | |
| organization_id | FK, NOT NULL | Composite tenant consistency |
| gym_id | FK, NOT NULL | |
| membership_plan_id | FK, NOT NULL | |
| is_available | BOOLEAN, NOT NULL, default true | |
| price_override | NUMERIC(12,2), nullable, >= 0 | NULL means plan base_price |
| joining_fee_override | NUMERIC(12,2), nullable, >= 0 | NULL means plan joining_fee |
| created_at / updated_at | timestamptz | |

Constraints:
- Unique (gym_id, membership_plan_id).
- Composite foreign keys ensure gym and plan belong to organization_id.
- A disabled association cannot be used for a new purchase.
- Effective price is price_override if present, otherwise membership_plans.base_price. Joining fee follows the same rule.

### 4.3 membership_plan_access_gyms

Used when access_type is selected_gyms.

| Column | Type / rule |
|---|---|
| id | PK |
| organization_id | FK, NOT NULL |
| membership_plan_id | FK, NOT NULL |
| gym_id | FK, NOT NULL |

Constraints:
- Unique (membership_plan_id, gym_id).
- Composite foreign keys enforce same-organization membership.
- For selected_gyms, at least one eligible gym must be configured before the plan can be activated.
- The purchasing gym must be among the configured gyms.

### 4.4 membership_plan_rules

Structured plan policy. Initial fields:

| Column | Type / rule |
|---|---|
| id | PK |
| membership_plan_id | unique FK, NOT NULL |
| freeze_allowed | BOOLEAN, default false |
| max_freeze_days | INTEGER, nullable, >= 0 |
| transfer_allowed | BOOLEAN, default false |
| cancellation_allowed | BOOLEAN, default true |
| refund_allowed | BOOLEAN, default false |
| auto_renew_allowed | BOOLEAN, default false |
| created_at / updated_at | timestamptz |

Validation: max_freeze_days must be zero/NULL when freezing is disabled; if freezing is enabled, it must be a positive configured limit. More complex policy fields should be added deliberately with explicit validation, not hidden in arbitrary JSON.

### 4.5 membership_terms

Versioned organization terms and conditions.

| Column | Type / rule |
|---|---|
| id | PK |
| organization_id | FK, NOT NULL |
| version | INTEGER, > 0 |
| title | VARCHAR(150), NOT NULL |
| content | TEXT, NOT NULL |
| content_hash | VARCHAR(64), NOT NULL |
| status | enum: draft/published/retired |
| effective_from | timestamptz, nullable until publication |
| created_by | FK users.id |
| created_at | timestamptz |

Constraints:
- Unique (organization_id, version).
- Published versions are immutable. Corrections create a new version.
- A plan references the terms version used for future purchases.

### 4.6 member_gym_assignments

Separates the organization-level member identity from branch associations.

| Column | Type / rule |
|---|---|
| id | PK |
| organization_id | FK, NOT NULL |
| member_id | FK, NOT NULL |
| gym_id | FK, NOT NULL |
| is_primary | BOOLEAN, default false |
| status | enum: active/inactive |
| created_at | timestamptz |

Constraints:
- Unique (member_id, gym_id).
- Composite foreign keys ensure member and gym share organization_id.
- At most one active primary gym per member (partial unique index where supported).
- Removing an assignment must not erase subscription or payment history.

### 4.7 member_subscriptions

Purchase/assignment record.

| Column | Type / rule | Notes |
|---|---|---|
| id | PK | |
| organization_id | FK, NOT NULL | Tenant |
| member_id | FK, NOT NULL | |
| membership_plan_id | FK, NOT NULL | Original plan reference |
| purchased_at_gym_id | FK, NOT NULL | Branch that sold/assigned it |
| status | enum | pending_payment/active/expired/cancelled |
| start_date / end_date | DATE, NOT NULL | Inclusive/exclusive policy must be consistent; use end_date as exclusive in application logic |
| plan_name_snapshot | VARCHAR(100), NOT NULL | Preserve purchased display name |
| duration_value_snapshot / duration_unit_snapshot | | |
| plan_price_snapshot / joining_fee_snapshot | NUMERIC(12,2) | Purchased amounts |
| currency_snapshot | CHAR(3) | |
| access_type_snapshot | enum | Purchased access policy |
| rules_snapshot | JSONB | Immutable normalized policy snapshot for audit |
| created_by | FK users.id | Staff who recorded purchase |
| activated_at / cancelled_at | timestamptz, nullable | |
| created_at / updated_at | timestamptz | |

Constraints:
- Composite foreign keys enforce member, plan, and purchasing gym belong to organization_id.
- end_date must be after start_date.
- Subscription snapshots are never recalculated from a subsequently edited plan.
- No assumption that one member can have only one subscription; overlapping-subscription policy must be enforced explicitly by service logic once product rules are confirmed.

### 4.8 subscription_access_gyms

Purchase-time access grant.

| Column | Type / rule |
|---|---|
| id | PK |
| organization_id | FK, NOT NULL |
| subscription_id | FK, NOT NULL |
| gym_id | FK, NOT NULL |
| created_at | timestamptz |

Constraints:
- Unique (subscription_id, gym_id).
- Composite foreign keys ensure subscription and gym belong to organization_id.
- This is the authoritative access list for a subscription.
- Any later access adjustment must be an explicit audited operation.

### 4.9 subscription_terms_acceptances

| Column | Type / rule |
|---|---|
| id | PK |
| organization_id | FK, NOT NULL |
| subscription_id | unique FK, NOT NULL |
| membership_terms_id | FK, NOT NULL |
| terms_version_snapshot | INTEGER, NOT NULL |
| terms_content_hash_snapshot | VARCHAR(64), NOT NULL |
| accepted_at | timestamptz, NOT NULL |
| accepted_by_member_id | FK, nullable where staff-assisted acceptance is supported |
| acceptance_method | enum/string | e.g. member_portal/staff_assisted |
| ip_address / user_agent | nullable audit metadata | |

The exact legal and evidentiary requirements for electronic acceptance require separate review before production rollout.

### 4.10 payments, invoices, and documents

Keep these as separate concepts and features.

**payments** should record organization_id, subscription_id, amount, currency, payment_method, provider, provider_reference, status (pending/succeeded/failed/refunded/partially_refunded), paid_at, and audit timestamps. Add idempotency/provider-reference uniqueness where applicable. Do not mark a payment successful based only on a client request.

**invoices** should record organization_id, subscription_id, invoice_number, subtotal, tax_amount, total_amount, currency, status, issued_at, and document reference. Invoice numbering must be unique within the organization's chosen numbering scope.

**membership_documents** should record organization_id, optional subscription_id, document_type, storage_key, content_type, checksum, generated_at, and metadata. Store bytes in private object storage, not PostgreSQL. Use short-lived authorized download URLs or an authenticated download endpoint. Do not expose public bucket URLs.

## 5. Member model migration and backward compatibility

The current members table has a required gym_id and existing member APIs are nested under /gyms/{gym_id}/members. Do not drop or repurpose this column in the first migration.

Safe migration strategy:
1. Add members.organization_id as nullable initially.
2. Backfill it from gyms.organization_id using the existing members.gym_id relationship.
3. Add a non-null constraint after verifying no orphan rows.
4. Create member_gym_assignments and backfill one active assignment per existing member using its current gym_id.
5. Preserve members.gym_id as the legacy/home-gym reference during the compatibility period. Document it as the current primary/home gym and do not treat it as the complete list of gym associations.
6. Update member read/write services to validate organization_id and assignments before any later deprecation/removal of the legacy field.
7. Add composite unique keys and foreign keys in a follow-up migration only after validating existing data.

Every migration must be tested against a disposable/test database. Never reset or recreate the user's development database. Existing member IDs and relationships must be preserved.

## 6. Lifecycle and service rules

### Plan lifecycle
- Organization owner/admin creates and manages plans.
- A plan is draft until fully configured.
- Activation requires valid duration, prices, rules, and access configuration.
- A plan must be offered at a gym before purchase there.
- Archive instead of deleting a plan with history.
- Changes apply to future purchases only; active subscriptions use snapshots.

### Purchase lifecycle
1. Resolve the authenticated user's organization from the current user.
2. Verify member, plan, and purchasing gym all belong to that organization.
3. Verify plan is active and available at the purchasing gym.
4. Resolve effective price and joining fee from gym override or organization default.
5. Resolve allowed gyms and validate purchasing gym eligibility.
6. Capture plan, price, access, rules, and applicable terms version snapshots.
7. Create a pending_payment subscription when payment is required; otherwise activate only through an explicitly authorized/manual-payment workflow.
8. Record terms acceptance and generated documents as applicable.
9. Grant access only according to the subscription's stored access-gym rows and valid subscription dates/status.

### Subscription statuses
- pending_payment: created but not yet eligible for access.
- active: paid/authorized and within its validity period.
- expired: validity period ended.
- cancelled: cancelled under an authorized policy.
Payment status and subscription status are independent.

### Date semantics
Use end_date as an exclusive boundary in application logic: a subscription starting 2026-12-01 for 30 calendar days has an exclusive end boundary 2026-12-31. Define gym-local timezone for check-in decisions. Test month-end, leap-year, and daylight-saving boundaries where relevant.

## 7. Authorization matrix

| Action | Organization owner/admin | Gym manager | Receptionist | Trainer |
|---|---:|---:|---:|---:|
| Create/update/archive organization plan | Yes | No | No | No |
| Configure gym plan availability/pricing | Yes | No (unless separately granted later) | No | No |
| View plans available at assigned gym | Yes | Yes | Yes | Yes |
| Create/assign member subscription | Yes | Yes, assigned gym only | Yes, assigned gym only | No |
| View subscription at assigned gym | Yes | Yes | Yes | Read-only only if explicitly required |
| Record manual payment | Yes | Yes, assigned gym only | Yes, assigned gym only | No |
| Publish organization terms | Yes | No | No | No |
| Download authorized member agreement/invoice | Yes | Assigned gym scope | Assigned gym scope | No by default |

Use existing role dependencies. All queries must include organization scope and gym authorization. Cross-tenant resources should return 404 where consistent with the existing authorization contract.

## 8. Implemented API reference

All routes require the existing cookie authentication and CSRF behavior. Organization plan/terms/assignment management requires owner or admin. Gym-level subscription operations require the gym manager or receptionist; read-only membership and access checks also allow trainers. Existing owner/admin organization-role bypasses remain in effect for gyms inside the authenticated organization.

### Plans and gym availability

- `POST /organizations/{organization_id}/membership-plans` — create a draft plan.
- `GET /organizations/{organization_id}/membership-plans` — list organization plans.
- `GET /organizations/{organization_id}/membership-plans/{plan_id}` — get a plan.
- `PATCH /organizations/{organization_id}/membership-plans/{plan_id}` — update a draft/active plan; subscription snapshots are unaffected.
- `POST /organizations/{organization_id}/membership-plans/{plan_id}/activate` — validate and activate.
- `POST /organizations/{organization_id}/membership-plans/{plan_id}/archive` — archive for future sales without deleting history.
- `PUT /gyms/{gym_id}/membership-plans/{plan_id}` — configure gym availability and optional price/joining-fee overrides.
- `GET /gyms/{gym_id}/membership-plans` — list active plans available at the gym, including effective prices.

### Terms and member-gym assignments

- `POST /organizations/{organization_id}/membership-terms` — create a draft terms version.
- `GET /organizations/{organization_id}/membership-terms` — list versions.
- `POST /organizations/{organization_id}/membership-terms/{terms_id}/publish` — publish an immutable version.
- `POST /organizations/{organization_id}/members/{member_id}/gym-assignments` — assign a member to another organization gym; optional primary assignment.
- `GET /organizations/{organization_id}/members/{member_id}/gym-assignments` — list assignments.
- `DELETE /organizations/{organization_id}/members/{member_id}/gym-assignments/{gym_id}` — deactivate an assignment without deleting the organization-level member record.

### Subscriptions, payments, invoices, and access

- `POST /gyms/{gym_id}/members/{member_id}/subscriptions` — create a pending-payment subscription (or activate a zero-value subscription).
- `GET /gyms/{gym_id}/members/{member_id}/subscriptions` — list subscriptions accessible at that gym.
- `GET /gyms/{gym_id}/subscriptions/{subscription_id}` — get a subscription at any gym included in its access snapshot.
- `POST /gyms/{gym_id}/subscriptions/{subscription_id}/payments/manual` — record the full manual payment and activate the subscription.
- `POST /gyms/{gym_id}/subscriptions/{subscription_id}/cancel` — cancel where the plan policy allows.
- `POST /gyms/{gym_id}/subscriptions/{subscription_id}/renew` — create a non-overlapping renewal using the original plan.
- `GET /gyms/{gym_id}/subscriptions/{subscription_id}/invoice` — retrieve the issued invoice record.
- `GET /gyms/{gym_id}/subscriptions/{subscription_id}/documents` — list authorized private document metadata.
- `GET /gyms/{gym_id}/subscriptions/{subscription_id}/documents/{document_id}` — download an authorized private PDF.
- `GET /gyms/{gym_id}/members/{member_id}/membership-access` — evaluate access using the gym's local date and the subscription's materialized access-gym list.

A manual payment amount is derived server-side from the stored subscription price and joining-fee snapshots; the client cannot choose the amount. A payment reference is unique for the manual provider. Pending subscriptions do not grant access. A subscription is eligible only when its status is active and the gym-local date is within the inclusive start/exclusive end interval.

The existing `DELETE /gyms/{gym_id}/members/{member_id}` operation now deactivates that member's gym assignment rather than deleting the organization-level member identity or subscription history.

## 9. Documentation and test requirements

Keep this document updated with actual implemented behavior. Add:
- endpoint request/response examples and status codes;
- migration revision and upgrade instructions;
- role/permission matrix;
- Swagger walkthrough using .env.test;
- automated test scenarios;
- operational notes for private document storage and retention.

Required automated scenarios before merge:
- Concurrent duplicate webhook deliveries produce one durable event claim and one business-state transition.
- Refund webhooks can recover a pending refund when the provider response was lost, using the internal refund ID in Razorpay notes.
- Refund webhook payment ID, amount, currency, and provider refund ID must match the persisted refund before state changes.
- A failed refund request remains pending with its reserved amount; retry reuses the same persisted Razorpay idempotency key.
- A delayed refund.failed event cannot downgrade a processed refund.
- Concurrent manual payment attempts cannot activate or invoice the same pending subscription twice.
- Organization tenant isolation for plans, members, gyms, subscriptions, payments, and documents.
- Gym-specific plan availability and price override fallback.
- Invalid, negative, and zero prices/durations rejected.
- Selected-gym plan must include the purchasing gym.
- Cross-organization references rejected.
- Subscription price/rules/access/terms snapshots remain unchanged after plan edits.
- Member can be associated with multiple gyms without duplicate assignments.
- Existing members are preserved by migration and backfilled to their current gym.
- Pending payment does not grant membership access.
- Failed/refunded payment does not incorrectly activate a subscription.
- End-date boundary and renewal scenarios.
- Unauthorized roles cannot create plans, assign subscriptions, or record payments.
- Private document access is tenant-authorized and does not expose storage credentials.

Always run tests against the test database:

```bash
ENV_FILE=.env.test alembic upgrade head
ENV_FILE=.env.test pytest -q
```

Do not merge until migrations, the complete automated suite, and manual Swagger scenarios pass. Do not run destructive database commands against the development database.

## 10. Implementation notes and rollout limitations

Implemented persistence and service behavior is covered by `tests/test_memberships.py`, including plan creation, gym price overrides, terms publication/acceptance, subscription snapshots, manual payment activation, invoice and PDF generation, selected-gym restrictions, multi-gym member assignments, and organization-wide access snapshots. The full test suite and migration must still be run locally before merge:

```bash
ENV_FILE=.env.test alembic upgrade head
ENV_FILE=.env.test pytest -q
```

Migration chain now includes `b7e8c9d0a1f2_add_refund_idempotency_key.py`, which backfills a unique idempotency key for every existing refund before enforcing NOT NULL/UNIQUE. Never reset or recreate the test or development database to apply it.

Current MVP boundaries that must be understood before production rollout:

- Razorpay one-time checkout, signed webhooks, captured-amount/currency checks, refund initiation, and refund webhooks are implemented. Only verified provider events activate subscriptions. Refunds with an uncertain provider response remain pending and must be reconciled before another refund is attempted.
- Automatic recurring renewal is deliberately disabled. Razorpay mandate creation, member consent, recurring charge webhooks, per-cycle invoices, retries, and mandate cancellation are not implemented. Do not advertise or enable automatic charging.
- Person-to-person membership transfer is prohibited by both request validation and a database constraint. Member-to-gym assignments are separate and do not transfer subscription ownership.
- GST arithmetic is configurable and purchase-time/invoice snapshots are retained. The correct GST rate, SAC, place-of-supply treatment, registration and invoice wording must be confirmed by the organization's tax professional before real tax invoices are issued.
- Private S3-compatible object storage is required in production. Local private storage is only a development/test fallback. Production deployments must configure bucket access policy, encryption, backups, retention and monitoring.
- Terms acceptance, cancellation/refund wording and document retention require legal review before launch. The expiry command should be scheduled periodically for reporting consistency.

Do not merge until the test database migration, complete automated suite, and manual Swagger scenarios pass. Never reset or recreate the development database.

## 11. Manual Swagger walkthrough

Use only the test database for this walkthrough.

1. Apply the migration and start the API:
   ```bash
   ENV_FILE=.env.test alembic upgrade head
   ENV_FILE=.env.test uvicorn app.main:app --reload
   ```
2. Open `http://127.0.0.1:8000/docs`, register or log in as an organization owner, and retain the returned CSRF token for write requests.
3. Create two gyms. Confirm their timezone defaults to `Asia/Kolkata`, then optionally update one with another valid IANA timezone.
4. Create a member at the first gym. Use the organization member gym-assignment endpoint to assign that member to the second gym and mark it primary. Confirm the member appears in both gyms' member lists.
5. Create membership terms, publish the terms version, and create a membership plan referencing that published terms version.
6. Configure the plan as available at the first gym with a gym-specific price override, then activate the plan.
7. Create a subscription for the member. Confirm its price, joining fee, rules, terms hash/version, and allowed gym IDs are captured as snapshots.
8. Check membership access before payment; it must be false while the subscription is pending payment.
9. Record a manual payment using a test reference. Confirm the payment is succeeded, the subscription is active, and an invoice is issued.
10. Check membership access again; it must now be true at each gym in the subscription's access snapshot.
11. List the subscription documents and download the agreement, invoice, and receipt PDFs through the authenticated document endpoint.
12. Try a selected-gyms plan that excludes the purchasing gym; the purchase must be rejected. Also verify that a trainer cannot create plans, subscriptions, or payments.

After the walkthrough, run the full test suite. Do not point the API at the development database for these checks.


## 11. Extended billing and operational workflows

The follow-up implementation adds:

- **Razorpay one-time checkout:** the server creates the order from the subscription's immutable amount/tax snapshot. A subscription stays pending_payment until a valid payment.captured webhook is received. The webhook HMAC is verified using RAZORPAY_WEBHOOK_SECRET; the captured amount and currency must match the server-side order. Webhook event IDs are claimed atomically with a PostgreSQL unique constraint/upsert, so concurrent duplicate deliveries cannot both process the same event. Payment/subscription rows are locked while state transitions occur. Manual payment activation also locks the pending subscription so simultaneous staff requests cannot record duplicate payments or issue duplicate invoices. Browser callbacks never activate access.
- **GST snapshots:** each organization can configure a GST percentage, GSTIN and tax mode (intra_state or inter_state). New subscriptions snapshot this policy. Intra-state tax is split into CGST/SGST; inter-state tax is IGST. Later tax-setting changes do not rewrite existing subscription quotes or invoices. The default GST rate is zero. The rate, place-of-supply treatment, SAC classification, invoice wording, GST registration and filing treatment must be confirmed by the organization's tax professional before issuing real tax invoices.
- **Refunds:** full or partial refunds can be initiated for captured Razorpay payments only when the purchased plan allows refunds. Each refund persists a stable UUID idempotency key before the provider request and sends it as Razorpay's `X-Refund-Idempotency` header. A timeout/5xx leaves the refund pending and reserves its amount; it must not be treated as failed or refunded again with a new key. Razorpay refund webhooks are matched by provider refund ID or the internal refund ID in notes, then validated against the stored payment ID, amount, and currency before state changes. If the initial response was ambiguous and no provider refund ID was saved, an authorized manager/receptionist can retry the pending operation at `POST /gyms/{gym_id}/refunds/{refund_id}/retry`; the same key and identical payload are reused. If a provider refund ID is already stored, wait for the webhook/reconciliation rather than submitting another request. Cash/UPI/card/bank-transfer manual refunds must be executed outside this API and reconciled by staff; the API does not claim to send those funds.
- **Subscription freezes:** staff can apply a non-overlapping freeze period to an active subscription when the plan allows it. The configured maximum is enforced, the subscription end date is extended by the frozen days, and access checks deny entry during the frozen interval.
- **Membership expiry job:** run ENV_FILE=.env python3 -m scripts.expire_memberships periodically (for example, every 15 minutes using cron or a managed scheduler). It is idempotent and evaluates each subscription using its purchasing gym's IANA timezone.
- **Private S3-compatible documents:** when MEMBERSHIP_S3_BUCKET is set, PDF bytes are written to a private S3-compatible bucket and served only through the authenticated application endpoint. In development/test, local private storage remains available. Production settings reject startup without an S3 bucket.

### Added configuration

Razorpay:
- RAZORPAY_KEY_ID
- RAZORPAY_KEY_SECRET
- RAZORPAY_WEBHOOK_SECRET
- RAZORPAY_API_BASE_URL

S3-compatible storage:
- MEMBERSHIP_S3_BUCKET
- MEMBERSHIP_S3_REGION
- MEMBERSHIP_S3_ENDPOINT_URL (optional for AWS S3; set for compatible providers)
- MEMBERSHIP_S3_ACCESS_KEY_ID / MEMBERSHIP_S3_SECRET_ACCESS_KEY (optional when workload IAM credentials are used)
- MEMBERSHIP_S3_PREFIX

Organization GST:
- PUT /organizations/{organization_id}/membership-tax-settings

Online payment:
- POST /gyms/{gym_id}/subscriptions/{subscription_id}/payments/razorpay-order
- POST /payments/razorpay/webhook (configure this exact URL in the Razorpay dashboard and subscribe to payment.captured, payment.failed, refund.processed and refund.failed)

Freeze:
- POST /gyms/{gym_id}/subscriptions/{subscription_id}/freeze

Refund:
- POST /gyms/{gym_id}/payments/{payment_id}/refunds

### Explicitly unsupported / production gates

- **Person-to-person membership transfer is prohibited.** The API schema rejects transfer_allowed=true; gym access assignments remain a separate operation.
- **Automatic recurring renewal is not yet enabled.** Auto-renew is deliberately disabled: the API rejects auto_renew_allowed=true and the database enforces false. Recurring Razorpay mandate creation, customer authorization, recurring charge webhooks, per-cycle invoices, retries and mandate cancellation are not implemented. Do not enable or advertise automatic charging until this workflow is built and tested with explicit member mandate consent.
- Razorpay and S3 credentials, a webhook endpoint reachable by Razorpay, bucket private-access policy, encryption, backups, retention and monitoring must be configured in the deployment environment. Never commit credentials.
- Razorpay refunds are provider-driven. Pending refunds with an unknown outcome remain reserved and can be safely retried only through the dedicated retry endpoint, which reuses the persisted idempotency key. Pending refunds that already have a provider refund ID must be reconciled through provider webhooks/settlement reports. Monitor aged pending refunds operationally; a future worker/scheduler can automate reconciliation, but Celery/Redis are intentionally not part of this membership PR.
- The tax implementation provides configurable arithmetic and snapshots; it is not tax/legal advice and does not determine the correct GST rate, SAC code, place of supply or registration obligations.
- Terms acceptance, GST treatment, refund/cancellation wording and document retention require Indian legal/accounting review before production launch.
