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

## Membership Management

The membership domain, organization/gym ownership rules, database design, lifecycle, API direction, migration strategy, and implementation checklist are documented in [Membership Management documentation](docs/MEMBERSHIP_MANAGEMENT.md). This feature is being implemented incrementally on `feature/membership-management`.


## Run with Docker Compose

Docker Compose starts the FastAPI application, PostgreSQL, and Redis. PostgreSQL
and Redis data are stored in named volumes. The API container waits for both
services to become healthy, runs Alembic migrations, and then starts Uvicorn.

1. Copy the example environment file and configure the required secrets:

   ```bash
   cp .env.example .env
   ```

   Set unique values for `JWT_SECRET_KEY`, `CSRF_SECRET_KEY`, and
   `POSTGRES_PASSWORD`. Use URL-safe characters for the PostgreSQL password
   because it is embedded in the container's database URL. Use secrets of at
   least 32 characters for the JWT and CSRF keys. Do not commit `.env`.
   The example maps PostgreSQL to host port 5433 and Redis to 6380 to avoid
   colliding with locally installed services; change `POSTGRES_PORT` or
   `REDIS_PORT` in `.env` if needed.

2. Build and start the stack:

   ```bash
   docker compose up --build -d
   ```

3. Check service status and API health:

   ```bash
   docker compose ps
   curl http://localhost:8000/
   curl http://localhost:8000/health/database
   curl http://localhost:8000/health/redis
   ```

4. Follow application logs:

   ```bash
   docker compose logs -f api
   ```

5. Stop the services (named data volumes are retained):

   ```bash
   docker compose down
   ```

To remove the containers and all persisted database, Redis, and private-document
data, run `docker compose down -v`. This permanently deletes those local volumes.

The Compose configuration is intended for local development. Do not expose its
database or Redis ports publicly or reuse its development settings in production.
