# Gym Management SaaS

A multi-tenant gym and fitness management platform
built to manage multiple gyms through a single application.

## Overview

The platform allows gym owners to manage their gyms,
members, trainers, memberships, attendance, and payments.

## Technology Stack

- Python
- FastAPI
- PostgreSQL
- SQLAlchemy (Async)
- Alembic

## Architecture

Multi-tenant architecture with a shared database
and shared schema.

## Project Status

Currently under development.

## Authentication and authorization

Authentication uses short-lived JWT access tokens and rotating opaque refresh
tokens stored in server-side sessions. Both authentication tokens are delivered
only as HttpOnly cookies; they are not returned in API response bodies.
State-changing cookie-authenticated requests require the signed double-submit
CSRF token in the X-CSRF-Token header.

### Local Swagger testing

1. Apply database migrations:

   ```
   ENV_FILE=.env.test alembic upgrade head
   ```

   Use .env instead of .env.test when applying migrations to your
   development database.

2. Start the API and open /docs on the same host and port.
3. Register an organization through POST /auth/register, or log in through
   POST /auth/login. The browser stores the access, refresh, and CSRF cookies.
4. Copy the data.csrf_token value from the login/register response.
5. For POST, PUT, PATCH, and DELETE operations, provide that value in the
   X-CSRF-Token header. Swagger exposes this header on protected operations.
6. Use POST /auth/refresh to rotate the refresh token, and
   POST /auth/logout to revoke the current session.

Organization registration creates the first owner. Owners/admins create
employees through /organizations/{organization_id}/employees and assign
employees to individual gyms through /gyms/{gym_id}/staff. Employees can be
created with organization_role="admin" to grant organization-wide admin access.
The owner/admin can deactivate an employee; deactivation revokes that user's
active sessions. A user can change their password through /auth/change-password.

Password reset uses one-time, hashed, 30-minute tokens. Configure SMTP before
using /auth/forgot-password:
- SMTP_HOST and SMTP_FROM_EMAIL
- SMTP_PORT (587 by default)
- SMTP_USERNAME and SMTP_PASSWORD when authentication is required
- SMTP_STARTTLS=true for STARTTLS, or SMTP_USE_SSL=true for implicit TLS

The reset email contains the one-time token to submit to /auth/reset-password.

### Cookie and CORS configuration

Local HTTP development defaults to COOKIE_SECURE=false and
COOKIE_SAMESITE=lax. Production must set:

- COOKIE_SECURE=true
- COOKIE_SAMESITE=lax for same-site frontend/API deployments
- CORS_ORIGINS='["https://app.example.com"]' for the exact frontend origin
- COOKIE_DOMAIN only if a shared parent-domain cookie is deliberately needed
- SMTP_HOST, SMTP_PORT, SMTP_FROM_EMAIL, and SMTP authentication/TLS values for password reset

CORS credentials are enabled only for the configured origins. Never use a
wildcard origin with credentialed cookies. Keep JWT_SECRET_KEY private and
at least 32 characters long.

### Automated tests

Always run the test suite against the test database:

```
ENV_FILE=.env.test pytest -q
```
