# Authentication and RBAC

This document is the implementation contract for authentication and authorization
in Gym Management SaaS. Authentication establishes the employee identity and
session. Authorization is checked by the API on every protected request and is
scoped to the employee's organization and, where applicable, assigned gym.

## 1. Identity and tenancy model

- An **organization** is the tenant boundary.
- A **gym** is a branch belonging to exactly one organization.
- A **user** is an employee identity scoped to one organization. Email addresses
  are unique inside an organization, not globally.
- **OrganizationStaff** stores the user's organization-level role.
- **GymStaff** stores a user's role at a specific gym. A user may be assigned to
  multiple gyms and may have a different role at each gym.
- Composite foreign keys prevent assigning a user to a gym in another
  organization.

The organization ID is always taken from the authenticated user. A client
supplied organization ID is never accepted as proof of tenant access.

## 2. Authentication lifecycle

### Organization owner registration

1. Call `POST /auth/register` with organization name, owner name, email, and a
   password of at least 12 characters.
2. The API creates the organization, an inactive-for-login owner identity
   (the account record is active, but email is not verified), and a one-time
   verification token.
3. The verification email contains the raw token. Only its SHA-256 digest is
   stored in PostgreSQL. The token expires after 24 hours.
4. Submit the token to `POST /auth/verify-email`.
5. Successful verification marks the email verified and creates the first
   authenticated session. The response sets cookies.

Unverified accounts cannot log in. If the email did not arrive, use
`POST /auth/resend-verification`; responses do not reveal whether an account
exists.

### Employee invitation

1. An organization owner or admin calls
   `POST /organizations/{organization_id}/employees/invitations` with the
   employee name and email. The optional `organization_role` is `admin`.
2. Only an owner may invite another organization admin.
3. The employee account is created inactive, with an unusable random password.
   The administrator never chooses or receives the employee's password.
4. The invitation email contains a one-time token. Only its hash is stored;
   invitations expire after 48 hours.
5. The employee calls `POST /auth/accept-invitation` with the token and their
   own password (minimum 12 characters).
6. The account becomes active and email-verified. The employee can then log in.

After acceptance, an owner/admin assigns gym-level roles through
`POST /gyms/{gym_id}/staff/`. Employees may be assigned to multiple gyms.

### Login and cookies

Call `POST /auth/login` with organization slug, email, and password. Tokens
are never returned in the JSON body.

| Cookie | HttpOnly | Path | Purpose |
|---|---:|---|---|
| `access_token` | Yes | `/` | Short-lived JWT used for API authentication |
| `refresh_token` | Yes | `/auth` | Opaque refresh token used only by auth endpoints |
| `csrf_token` | No | `/` | Signed token copied into the CSRF request header |

The access token lasts 15 minutes by default. The opaque refresh token lasts
14 days at a time, with a 30-day absolute session lifetime by default.
Refresh rotates the opaque token; its hash is stored server-side. Reuse of an
already-used refresh token revokes the complete session.

### CSRF

All state-changing requests authenticated by cookies require the
`X-CSRF-Token` header. Its value must exactly match the signed
`csrf_token` cookie. The CSRF cookie is intentionally readable by browser
JavaScript; access and refresh cookies are not.

- After registration email verification or login, copy `data.csrf_token`.
- Send it as `X-CSRF-Token` on authenticated POST, PUT, PATCH, and DELETE
  requests.
- `POST /auth/refresh` also requires the current CSRF token.
- Refresh returns a new CSRF token. Replace the header value after each refresh.
- Logout, logout-all, and password change clear the authentication cookies.

Safe methods (GET, HEAD, OPTIONS, TRACE) do not require the CSRF header.

## 3. Authentication endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/auth/register` | Create organization and unverified owner |
| POST | `/auth/verify-email` | Verify owner email and start session |
| POST | `/auth/resend-verification` | Resend verification email (generic response) |
| POST | `/auth/accept-invitation` | Accept employee invitation and set password |
| POST | `/auth/login` | Authenticate and set cookies |
| POST | `/auth/refresh` | Rotate refresh token and access cookie |
| POST | `/auth/logout` | Revoke current session |
| POST | `/auth/logout-all` | Revoke all sessions for current user |
| GET | `/auth/me` | Return current user and role assignments |
| POST | `/auth/change-password` | Change password; revoke all sessions |
| POST | `/auth/forgot-password` | Request password reset email |
| POST | `/auth/reset-password` | Consume one-time reset token and set password |

Password-reset tokens are stored hashed, expire after 30 minutes, and are
single-use. Resetting a password revokes all sessions in the same database
transaction as the password update. Password reset responses do not disclose
whether the supplied organization/email pair exists.

## 4. RBAC policy

Organization roles take precedence over gym roles for gyms inside the same
organization. An owner/admin does not gain access to a different tenant.

### Organization roles

| Capability | Owner | Admin |
|---|:---:|:---:|
| Read/update organization profile | Yes | Yes |
| Create gyms | Yes | Yes |
| View all gyms in organization | Yes | Yes |
| Invite standard employees | Yes | Yes |
| Invite organization admins | Yes | No |
| Assign/remove gym staff | Yes | Yes |
| List employees | Yes | Yes |
| Deactivate employees | Yes | Yes, except owners |
| Transfer organization ownership | Yes | No |
| Delete organization | Yes | No |

The last active owner cannot be deactivated. Ownership transfer requires an
active, email-verified employee in the same organization. The previous owner
becomes an organization admin.

### Gym roles

| Capability | Manager | Trainer | Receptionist |
|---|:---:|:---:|:---:|
| Read assigned gym | Yes | Yes | Yes |
| Update/delete assigned gym | Yes | No | No |
| Create members | Yes | No | Yes |
| Read members | Yes | Yes | Yes |
| Update members | Yes | No | Yes |
| Delete members | Yes | No | No |
| Assign/remove gym staff | No | No | No |

Only organization owners/admins can assign or remove gym staff. A gym role
applies only to the gym assignment that stores it. A staff member without an
active assignment cannot access that gym.

## 5. Authorization and tenant-isolation rules

- Protected routes use `get_current_user` and/or the role dependencies.
- Organization role checks always query an active
  `OrganizationStaff` row for the current user and organization.
- Gym role checks first verify that the gym belongs to the current user's
  organization. They then allow an owner/admin or require an active
  `GymStaff` assignment with an allowed role.
- A gym outside the current organization returns 404 to avoid disclosing
  another tenant's resources.
- Member queries include both gym ID and member ID where applicable.
- Deactivating a user revokes their active sessions and pending invitations.
- Removing a gym assignment blocks the next request that requires that gym role.
- The API never trusts role names, organization IDs, or gym IDs supplied in
  request bodies as authorization evidence.

## 6. Rate limits and password rules

Defaults are configurable:

| Operation | Limit | Window |
|---|---:|---:|
| Failed login | 5 | 15 minutes |
| Organization registration | 3 | 60 minutes per client IP |
| Password reset request | 3 | 60 minutes per client IP and identity |
| Verification resend | 3 | 60 minutes per client IP and identity |

Login attempts use a dummy Argon2 hash for unknown users to reduce account
enumeration through response timing. Rate-limit counters are stored in
PostgreSQL so they are shared across application workers.

Passwords must be 12–128 characters. Passwords are hashed with Argon2 via
pwdlib. Raw verification, invitation, reset, and refresh tokens are never
stored in the database.

## 7. Environment configuration

Required in every environment:

- `DATABASE_URL`
- `JWT_SECRET_KEY` (at least 32 characters; keep private)

Recommended separate signing key:

- `CSRF_SECRET_KEY` (at least 32 characters; if omitted, the JWT key is used)

Cookie settings:

- Development/Swagger over local HTTP: `APP_ENV=development`,
  `COOKIE_SECURE=false`, `COOKIE_SAMESITE=lax`.
- Production: `APP_ENV=production`, `COOKIE_SECURE=true`,
  `COOKIE_SAMESITE=lax`, and exact `CORS_ORIGINS`.
- `COOKIE_DOMAIN` should normally be omitted (host-only cookies). Set it only
  when a deliberate shared parent-domain cookie is required.
- `COOKIE_SAMESITE=none` requires `COOKIE_SECURE=true`.

Email delivery:

- `SMTP_HOST`, `SMTP_PORT`, and `SMTP_FROM_EMAIL`
- Optional `SMTP_USERNAME` and `SMTP_PASSWORD`
- `SMTP_STARTTLS=true` for STARTTLS, or `SMTP_USE_SSL=true` for implicit TLS

The application intentionally refuses production startup configuration when
secure cookies are disabled or CORS origins are empty. Use exact frontend
origins; never use wildcard origins with credentialed cookies.

## 8. Swagger testing

For safe local testing, use the test database:

```bash
ENV_FILE=.env.test alembic upgrade head
ENV_FILE=.env.test uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` using the same host and port as the API.

1. Configure a local SMTP sink or test SMTP account in `.env.test`.
2. Call `POST /auth/register`; retrieve the verification token from the test
   email inbox.
3. Call `POST /auth/verify-email`; the browser receives auth cookies.
4. Copy `data.csrf_token` into the `X-CSRF-Token` header for write operations.
5. Create a gym, invite an employee, retrieve the invitation token from email,
   and call `POST /auth/accept-invitation` with a password chosen by that
   employee.
6. Assign the employee a role at a gym and log in as that employee.
7. Try both allowed and forbidden operations from the matrix above.
8. Test refresh rotation, logout, logout-all, password change, password reset,
   email verification expiry/reuse, invitation expiry/reuse, and deactivation.

Swagger UI sends cookies automatically when it is served from the same origin
as the API. If the browser does not retain cookies, verify the scheme, host,
port, cookie Secure setting, and browser cookie policy before testing RBAC.

## 9. Required scenario checklist

### Registration and email verification
- [ ] Valid registration creates one organization and one owner.
- [ ] Duplicate organization slug is handled without duplicate data.
- [ ] Owner cannot log in before email verification.
- [ ] Valid verification token verifies email and starts a session.
- [ ] Expired, malformed, and reused verification tokens are rejected.
- [ ] Resend verification is rate-limited and does not reveal account existence.

### Login, cookies, CSRF, and sessions
- [ ] Correct credentials set access, refresh, and CSRF cookies.
- [ ] Access and refresh cookies are HttpOnly; CSRF cookie is not.
- [ ] Tokens are absent from JSON response bodies.
- [ ] Wrong password, unknown organization, inactive user, and unverified user
      do not authenticate.
- [ ] Login throttling returns 429 after the configured threshold.
- [ ] Missing, mismatched, or invalid CSRF token rejects a write request.
- [ ] Refresh rotates the refresh token and returns a new CSRF token.
- [ ] Reusing an old refresh token revokes the session.
- [ ] Absolute session expiry cannot be extended by repeated refreshes.
- [ ] Logout revokes the current session; logout-all revokes every session.
- [ ] Password change/reset revokes all active sessions.

### Password reset and invitations
- [ ] Forgot-password returns a generic response for existing and unknown users.
- [ ] Reset token is hashed at rest, expires, and can be used only once.
- [ ] Invitation creates an inactive user with no administrator-known password.
- [ ] Invitation acceptance sets the employee's own password and verifies email.
- [ ] Expired/reused invitation tokens are rejected.
- [ ] Deactivating a pending invite invalidates its invitation token.

### Organization and gym authorization
- [ ] Owner can invite employees, assign gym roles, and transfer ownership.
- [ ] Admin cannot invite another organization admin or transfer ownership.
- [ ] Admin cannot deactivate an owner.
- [ ] The last active owner cannot be deactivated.
- [ ] New owner must be active, verified, and in the same organization.
- [ ] User cannot access a different organization's gym by guessing its ID.
- [ ] Employee sees only gyms with active assignments.
- [ ] Gym role grants access only to its assigned gym.
- [ ] Trainer can read members but cannot create, update, or delete members.
- [ ] Receptionist can create/read/update but cannot delete members.
- [ ] Manager can manage members and the assigned gym.
- [ ] Removing a gym assignment blocks subsequent gym access.
- [ ] Deactivating an employee blocks login and revokes sessions.

Run all tests against the test database:

```bash
ENV_FILE=.env.test pytest -q
```

Do not merge this milestone until migrations, the full automated suite, and the
manual Swagger scenarios above have been verified.
