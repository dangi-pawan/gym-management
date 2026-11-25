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

Authentication uses HttpOnly access/refresh cookies, signed double-submit CSRF
protection, email verification, one-time employee invitations, password reset,
refresh-token rotation and revocation, and PostgreSQL-backed rate limiting.
Authorization is tenant-scoped with organization owner/admin roles and
gym-specific manager/trainer/receptionist roles.

See [Authentication and RBAC documentation](docs/AUTHENTICATION_AND_RBAC.md)
for the complete endpoint reference, role matrix, environment configuration,
Swagger workflow, and manual scenario checklist. Copy `.env.example` for local
configuration. Local Swagger testing requires an SMTP sink or test SMTP account
for registration verification, employee invitations, and password reset.

### Automated tests

Always run the test suite against the test database:

```
ENV_FILE=.env.test pytest -q
```
