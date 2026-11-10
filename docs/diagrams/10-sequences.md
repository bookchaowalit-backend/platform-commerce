# 10 — Sequences

## S1 — Authenticated request (ทุก /v1 route)

```mermaid
sequenceDiagram
  participant C as Caller
  participant B as _Boundary (core)
  participant E as CaptureErrors
  participant R as Route (app.py)
  participant V as TokenVerifier
  participant J as Identity JWKS
  participant D as Database pool
  participant P as Neon Postgres
  C->>B: HTTPS request with Authorization Bearer JWT
  B->>B: Content-Length and body <= 16384 bytes, else 413
  B->>E: ASGI call (30 s timeout, else 504)
  E->>R: dispatch
  R->>V: require_scope(scope) verify header
  opt key cache older than 60 s
    V->>J: GET JWKS (5 s timeout, no redirect, <= 1 MiB)
    J-->>V: keys
  end
  alt invalid token
    V-->>C: 401 unauthorized
  else scope missing
    R-->>C: 403 forbidden
  end
  R->>D: transaction(principal.workspace)
  D->>P: set_config app.workspace_id, then SQL under forced RLS
  P-->>D: rows for this workspace only
  D-->>R: result or None
  R-->>B: 200/201 JSON, or fixed 404/409/422
  B-->>C: response plus x-request-id
```

## S2 — Place order (duplicate order protection)

```mermaid
sequenceDiagram
  participant C as Caller (orders:write)
  participant S as CommerceStore.place_order
  participant P as Postgres
  C->>S: Idempotency-Key, cart_id, expected_total_minor
  S->>S: validate key shape, fingerprint = sha256(cart_id, expected_total)
  S->>P: pg_advisory_xact_lock(commerce-order-key:ws:key)
  S->>P: SELECT id, fingerprint FROM commerce_order WHERE idempotency_key
  alt key exists, same fingerprint
    P-->>S: existing order
    S-->>C: 200 replay
  else key exists, different fingerprint
    S-->>C: 409 Idempotency conflict
  else new key
    S->>P: SELECT cart FOR UPDATE
    alt cart not open
      S-->>C: 409 Cart is not open
    end
    S->>P: lines JOIN catalog_item FOR SHARE OF i, promotion FOR SHARE (live check)
    S->>S: pricing.quote
    alt any item inactive
      S-->>C: 409 Item unavailable
    else no lines
      S-->>C: 422 invalid request
    else total differs from expected_total_minor
      S-->>C: 409 Price changed
    else ok
      S->>P: INSERT commerce_order and order_line snapshot, UPDATE cart status ordered
      S-->>C: 201 created
    end
  end
```

## S3 — Readiness probe

```mermaid
sequenceDiagram
  participant U as Uptime worker or Railway healthcheck
  participant A as core readyz
  participant D as Database.ready
  participant S as CommerceStore.ready
  participant P as Postgres
  U->>A: GET /readyz (no auth)
  A->>D: SELECT 1
  D-->>A: true or false
  A->>S: readiness_checks commerce_schema
  S->>P: has_schema_privilege USAGE, migrations SELECT, 18 has_table_privilege checks
  S->>P: platform_schema_migrations versions and checksums for commerce
  S->>P: pg_class relrowsecurity and relforcerowsecurity for 6 tables
  S-->>A: bool
  A-->>U: 200 ready or 503 unavailable
```

Sources: `src/platform_commerce/app.py`, `src/platform_commerce/store.py`, `src/platform_commerce/_sentry.py`, `platform-backend-core@21d5f44` `http.py`, `auth.py`, `db.py`, `.railway/railway.ts`, ops record: book-platforms-status (2026-11-03)

## Open questions
- ไม่มี
