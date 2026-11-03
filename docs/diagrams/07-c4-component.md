# 07 — C4 Component (commerce-api)

```mermaid
C4Component
  title Components - commerce-api
  System_Ext(caller, "Caller", "Bearer JWT")
  System_Ext(jwks, "Identity JWKS", "HTTPS")
  ContainerDb(db, "Neon PostgreSQL", "RLS tables")
  System_Ext(sentry, "Sentry", "Errors")
  Container_Boundary(api, "commerce-api") {
    Component(boundary, "_Boundary middleware", "core http.py", "Body limit, 30 s timeout, redacted 500, x-request-id, route metrics")
    Component(capture, "CaptureErrors", "_sentry.py", "Innermost ASGI layer, reports then re-raises")
    Component(routes, "Routes", "app.py", "16 /v1 handlers, Strict pydantic models, fixed error strings")
    Component(scope, "require_scope", "core http.py", "401 or 403 per route scope")
    Component(verifier, "TokenVerifier and _JWKS", "core auth.py", "RS256, iss, aud, sub, ws, scope; JWKS refresh at most 60 s")
    Component(store, "CommerceStore", "store.py", "Catalog, promotion, cart, order SQL; locks; readiness")
    Component(pricing, "pricing.quote", "pricing.py", "Integer minor units, one promotion")
    Component(database, "Database", "core db.py", "Pool, sets app.workspace_id per transaction, refuses privileged role")
    Component(probes, "healthz, readyz, metrics", "core http.py", "Unauthenticated probes")
    Component(init, "init_sentry", "_sentry.py", "No-op without SENTRY_DSN")
  }
  Rel(caller, boundary, "HTTP")
  Rel(boundary, capture, "ASGI")
  Rel(capture, routes, "ASGI")
  Rel(routes, scope, "Depends")
  Rel(scope, verifier, "verify Authorization")
  Rel(verifier, jwks, "GET keys")
  Rel(routes, store, "calls with principal.workspace")
  Rel(store, pricing, "quote")
  Rel(store, database, "transaction(workspace)")
  Rel(database, db, "SQL")
  Rel(probes, store, "readiness_checks commerce_schema")
  Rel(capture, sentry, "capture_event")
  Rel(init, sentry, "sentry_sdk.init")
```

Sources: `src/platform_commerce/app.py`, `src/platform_commerce/store.py`, `src/platform_commerce/pricing.py`, `src/platform_commerce/_sentry.py`, `src/platform_commerce/__init__.py`, `platform-backend-core@21d5f44` `auth.py`, `http.py`, `db.py`

## Open questions
- ไม่มี
