# 06 — C4 Container

```mermaid
C4Container
  title Containers - platform-commerce
  System_Ext(hub, "Remote MCP hub", "Caller with bearer JWT")
  System_Ext(gw, "Edge API gateway", "Railway service gateway behind Cloudflare")
  System_Ext(identity, "platform-identity", "JWKS endpoint")
  System_Ext(sentry, "Sentry", "Error events")
  System_Ext(uptime, "Uptime worker", "Hourly /readyz")
  System_Boundary(rw, "Railway project platform-commerce, asia-southeast1-eqsg3a") {
    Container(api, "commerce-api", "Python 3.12, FastAPI, uvicorn, platform-backend-core 21d5f44", "python -m platform_commerce serve, PORT 8080, UID 65532")
    Container(mig, "migrate one-off", "Same image, command override", "python -m platform_commerce migrate with DDL DSN")
  }
  ContainerDb(db, "Neon PostgreSQL", "Postgres 16+ (CI tests 16)", "6 commerce tables + platform_schema_migrations, forced RLS")
  Rel(hub, gw, "HTTPS /v1/platform-commerce/v1/*")
  Rel(gw, api, "HTTPS JSON /v1/*, token passed through")
  Rel(uptime, api, "GET /readyz")
  Rel(api, identity, "GET JWKS, 5 s timeout, no redirects")
  Rel(api, db, "psycopg pool max 8, runtime role NOSUPERUSER NOBYPASSRLS")
  Rel(mig, db, "DDL role, advisory-locked migrations")
  Rel(api, sentry, "sentry-sdk errors only")
```

Container facts:
- Image: two-stage `Dockerfile` (`python:3.12-slim`), wheels for this service and `platform-backend-core` built from commit `21d5f44d…`, runtime stage no git, `USER 65532:65532`, `CMD python -m platform_commerce serve`.
- Runtime limits: concurrency 100 (uvicorn), pool 8, statement timeout 10 s, request timeout 30 s, body ≤ 16 KiB (`create_app(..., max_body_bytes=16384)`).
- `migrate` ไม่เคยรันตอน startup; ต้องรันแยกด้วย DDL DSN.

Sources: ops record: api-gateway-edge (2026-11-03); `bookchaowalit-backend/platform-api-gateway@51c4711` `routes.json`; `bookchaowalit/platform-mcp-remote-worker@7d127c2` `wrangler.toml` `CELLS` + `src/worker.ts` `PLATFORM_CELLS`, `Dockerfile`, `.railway/railway.ts`, `pyproject.toml`, `src/platform_commerce/__main__.py`, `src/platform_commerce/app.py`, `docs/runtime.md`, `platform-backend-core@21d5f44` `db.py` + `http.py`, ops record: book-platforms-status (2026-11-03)

## Open questions
- `migrate` รันอย่างไรบน Railway จริง (service แยก, `railway run`, หรือจากเครื่อง owner)? ops record recipe บอก "migrate with the owner role" แต่ไม่บอกวิธี.
- Postgres version ของ Neon project `platform-commerce` ไม่ได้บันทึก.
