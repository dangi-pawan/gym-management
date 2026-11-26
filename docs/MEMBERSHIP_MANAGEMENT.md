# Membership Management

This document defines the domain boundaries, organization/gym ownership rules, data model, lifecycle, authorization expectations, document handling, migration strategy, and verification checklist.

## Implementation status

The first application implementation is present on `feature/membership-management`. Migration `e41b7c9d2a60` adds organization ownership to existing members, backfills their current gym assignment, adds gym timezones, and creates the membership domain tables. Existing member IDs and the legacy `members.gym_id` field are preserved.

Implemented capabilities include organization-owned plans, gym availability and price overrides, structured rules, versioned terms, member-to-gym assignments, subscription snapshots and access-gym snapshots, manual payment recording, invoices, private PDF agreements/invoices/receipts, authorized document downloads, subscription renewal/cancellation, and gym-local access checks.

The implementation is still subject to local migration and full-suite verification before merge. See the deployment limitations in section 10.

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
- `DELETE /organizations/{organization_id}/members/{member_id}/gym-assignments/{gym_id}` — deactivate an assignment. The final active assignment cannot be removed.

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

## 9. Documentation and test requirements

Keep this document updated with actual implemented behavior. Add:
- endpoint request/response examples and status codes;
- migration revision and upgrade instructions;
- role/permission matrix;
- Swagger walkthrough using .env.test;
- automated test scenarios;
- operational notes for private document storage and retention.

Required automated scenarios before merge:
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

Current MVP boundaries that must be understood before production rollout:

- Payment collection is staff-recorded manual payment (cash/UPI/card/bank transfer/other). There is no Razorpay integration, provider webhook verification, automated UPI reconciliation, refund execution, or partial-refund workflow yet. Do not mark an online provider payment successful from an unverified client callback.
- Freeze, transfer, refund, and auto-renew policy fields are stored in the plan/subscription snapshots. Only cancellation policy is currently enforced as an operation; freeze/transfer/refund/auto-renew workflows remain future implementation work.
- Invoice tax is currently zero. GST configuration, tax calculation, GSTIN, and statutory invoice requirements require product/accounting decisions before production invoicing in India.
- Generated PDFs are stored in a private local filesystem directory configured by `MEMBERSHIP_DOCUMENTS_DIR` (default `.private/membership-documents`), with restrictive directory/file permissions and authenticated downloads. This is suitable for local/MVP deployment on a protected persistent volume, but a production multi-instance deployment must provide a private shared encrypted object-storage adapter, backup, retention, and malware-scanning policy. The current implementation does not publish public file URLs.
- Terms versions are immutable after publication and acceptance evidence stores the terms hash, version, timestamp, method, request IP, and user agent. Legal sufficiency and retention requirements for electronic acceptance must be reviewed before launch.
- Gym timezone defaults to `Asia/Kolkata` and is configurable using a validated IANA timezone. Access checks expire ended subscriptions when evaluated; deployments should also schedule a periodic expiry/cleanup job for reporting consistency.

Do not merge until the test database migration, complete automated suite, and manual Swagger scenarios pass. Never reset or recreate the development database.

No application models, routers, migrations, or tests are implied by this design document alone; those are subsequent implementation steps.
