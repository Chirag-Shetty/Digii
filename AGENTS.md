# Campus Transport Experience - "Where's My Bus?"

## Problem Statement
During transit disruptions (delays, breakdowns, cancellations), riders flood campus staff with inquiries: *"Where's my bus?"*
This project solves that friction:
- **Staff log an incident once** (e.g. breakdown, delay, cancellation).
- **The system recomputes trip status and ETAs** automatically.
- **Subscribed riders are immediately notified**.
- **Result:** Transparency and trust, proactive communication, and dramatically fewer calls to staff.

---

## Technical Stack
- **Backend**: Python (3.11+), FastAPI, SQLAlchemy 2.x, SQLite
- **Validation**: Pydantic v2
- **Testing**: pytest, pytest-asyncio / HTTPX TestClient
- **Frontend**: Plain HTML + Vanilla JavaScript served statically by FastAPI (no build steps, no node/npm runtime needed)

---

## Non-Goals (Out of Scope)
- Live GPS tracking or hardware telemetry
- Machine learning arrival/delay predictions
- Complex multi-tenant authentication/OAuth (simple mock/header-based user references)
- Real external SMS or push notification gateways (in-app/persisted notifications)

---

## Architectural Principles
1. **Business Logic in `app/services`**: All state transitions, incident side-effects, ETA recalculations, and notifications live inside domain services, never in route handlers.
2. **Thin Route Handlers in `app/api`**: FastAPI endpoints only validate input (Pydantic schemas), call services with a database session, and format responses.
3. **Injectable Clock**: Every service accepting or calculating time must take an optional `now: datetime | None = None` parameter defaulting to `datetime.now(timezone.utc)`. This ensures deterministic, reproducible testing.
4. **Simple, Readable Code**: Favor clean, straightforward code over premature abstractions. Explicit is better than implicit.
5. **Idempotency**: Data seeders, database migrations/inits, and event processing should be idempotent wherever possible.

---

## Core Domain Models
- **Route**: `id`, `name`
- **Stop**: `id`, `name`
- **RouteStop**: `id` (or composite `route_id`, `stop_id`), `sequence`, `offset_minutes`
- **Trip**: `id`, `route_id`, `scheduled_departure`, `status` (`SCHEDULED`, `DELAYED`, `BROKEN_DOWN`, `CANCELLED`, `COMPLETED`)
- **Incident**: `id`, `trip_id`, `type` (`DELAY`, `BREAKDOWN`, `CANCELLATION`, `RESOLVED`), `delay_minutes` (nullable), `message`, `created_by`, `created_at`, `is_active`
- **Subscription**: `id`, `user_ref`, `route_id`, `stop_id`
- **Notification**: `id`, `user_ref`, `trip_id`, `message`, `created_at`

---

## Project Layout
```
├── app/
│   ├── api/            # API routers (thin endpoints)
│   ├── services/       # Domain business logic & notification triggers
│   ├── static/         # HTML + Vanilla JS frontend
│   ├── db.py           # Engine, SessionLocal, Base
│   ├── main.py         # FastAPI app factory and lifecycle
│   ├── models.py       # SQLAlchemy ORM models
│   └── schemas.py      # Pydantic v2 models
├── tests/              # Pytest test suite with clock fixtures
├── AGENTS.md           # This document
├── requirements.txt    # Python dependencies
├── seed.py             # Idempotent demo dataset
└── .gitignore
```

